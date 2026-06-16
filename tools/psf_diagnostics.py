#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
from pypalettes import load_cmap

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.stats import sigma_clipped_stats
from scipy.ndimage import center_of_mass, gaussian_filter
from scipy.ndimage import shift as ndi_shift

from findingchart_guiplotter.empirical_psf import (
    build_empirical_psf,
    circularize_psf,
    cut_stamp,
    detect_field_stars,
    edge_mask,
    moffat_kernel,
    odd_stamp_size,
    radial_edge_taper,
    smooth_psf_wings,
)
from findingchart_guiplotter.image_fetchers import fetch_image
from findingchart_guiplotter.models import ChartSettings, ImageRequest, Target
from findingchart_guiplotter.renderer import brightness_reference_mag, inject_psf, pixel_scale_arcsec, world_to_scalar_pixel

import scienceplots
plt.style.use('science')

# Blue background and warm high-intensity core.
HIROSHIGE = load_cmap(
    "Hiroshige",
    cmap_type="continuous",
    reverse=True,
)

SN2023IXF = Target(display_name="SN 2023ixf", ra_deg=210.910674, dec_deg=54.311651)


def build_raw_empirical_stack(data: np.ndarray, coords: list[tuple[float, float]], stamp_size: int) -> np.ndarray:
    half = stamp_size // 2
    background_mask = edge_mask((stamp_size, stamp_size), 5)
    stamps = []
    for x, y in coords:
        try:
            stamp = cut_stamp(data, x, y, stamp_size)
        except ValueError:
            continue
        psf = stamp - np.nanmedian(stamp[background_mask])
        psf[~np.isfinite(psf)] = 0.0
        psf[psf < 0] = 0.0
        if np.sum(psf) <= 0:
            continue
        cy, cx = center_of_mass(psf)
        if not np.isfinite(cx) or not np.isfinite(cy):
            continue
        shifted = ndi_shift(psf, shift=(half - cy, half - cx), order=3, mode="constant", cval=0.0, prefilter=True)
        shifted[shifted < 0] = 0.0
        total = np.sum(shifted)
        if total > 0:
            stamps.append(shifted / total)
    if not stamps:
        raise RuntimeError("no usable empirical PSF stamps")
    stack = np.nanmedian(np.stack(stamps, axis=0), axis=0)
    stack[~np.isfinite(stack)] = 0.0
    stack[stack < 0] = 0.0
    return stack / np.sum(stack)


def normalize_kernel(kernel: np.ndarray) -> np.ndarray:
    kernel = np.array(kernel, dtype=float, copy=True)
    kernel[~np.isfinite(kernel)] = 0.0
    kernel[kernel < 0] = 0.0
    total = float(np.sum(kernel))
    if total <= 0:
        raise RuntimeError("kernel has no positive flux")
    return kernel / total


def radial_profile(kernel: np.ndarray, bins: int = 32) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.indices(kernel.shape)
    cy = 0.5 * (kernel.shape[0] - 1)
    cx = 0.5 * (kernel.shape[1] - 1)
    radius = np.hypot(x - cx, y - cy)
    edges = np.linspace(0, radius.max(), bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    profile = np.full(bins, np.nan)
    for idx in range(bins):
        mask = (radius >= edges[idx]) & (radius < edges[idx + 1])
        if np.any(mask):
            profile[idx] = np.nanmean(kernel[mask])
    return centers, profile


def plot_kernel_diagnostics(kernels: dict[str, np.ndarray], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    nrows, ncols = 2, 4

    if len(kernels) > nrows * ncols:
        raise ValueError("The 2 x 4 layout supports at most eight kernels.")

    fig = plt.figure(figsize=(20, 10))

    outer = fig.add_gridspec(
        nrows,
        ncols,
        left=0.04,
        right=0.98,
        bottom=0.06,
        top=0.96,
        wspace=0.25,
        hspace=0.30,
    )

    if len(kernels) == 1:
        axes = np.asarray([axes])
        for index, (name, kernel) in enumerate(kernels.items()):
            row, col = divmod(index, ncols)

            inner = outer[row, col].subgridspec(
                2,
                3,
                height_ratios=(1, 3),
                width_ratios=(1, 3, 0.12),
                hspace=0.05,
                wspace=0.05,
            )

            ax_corner = fig.add_subplot(inner[0, 0])
            ax_img = fig.add_subplot(inner[1, 1])
            ax_top = fig.add_subplot(inner[0, 1], sharex=ax_img)
            ax_left = fig.add_subplot(inner[1, 0], sharey=ax_img)
            ax_cbar = fig.add_subplot(inner[1, 2])

            ax_corner.axis("off")
#    for row, (name, kernel) in enumerate(kernels.items()):
#         ax_img, ax_profile = axes[row]
            positive = kernel[kernel > 0]
            vmin = np.nanpercentile(positive, 5) if positive.size else 0.0
            vmax = np.nanpercentile(positive, 99.8) if positive.size else 1.0

            finite_kernel = np.where(np.isfinite(kernel), kernel, -np.inf)
            y0, x0 = np.unravel_index(np.argmax(finite_kernel), kernel.shape)

            ny, nx = kernel.shape

            x = np.arange(nx) - x0
            y = np.arange(ny) - y0

            x_profile = np.ma.masked_less_equal(kernel[y0, :], 0.0)
            y_profile = np.ma.masked_less_equal(kernel[:, x0], 0.0)

            extent = (
                x[0] - 0.5,
                x[-1] + 0.5,
                y[0] - 0.5,
                y[-1] + 0.5,
            )

            image = ax_img.imshow(kernel, origin="lower", cmap=HIROSHIGE, vmin=vmin, vmax=vmax, 
                                  interpolation="nearest", aspect='equal')
            levels = np.geomspace(max(vmin, positive.min() if positive.size else 1.0e-8), max(vmax, 1.0e-8), 7)
            ax_img.contour(x, y, kernel, levels=np.unique(levels), colors="white", linewidths=0.45, alpha=0.75,)
            # ax_img.contour(kernel, levels=np.unique(levels), colors="white", linewidths=0.45, alpha=0.75)
            ax_img.axhline(0, color="white", ls="--", lw=0.45, alpha=0.45)
            ax_img.axvline(0, color="white", ls="--", lw=0.45, alpha=0.45)
            # ax_img.set_title(name)
            # ax_img.set_xticks([])
            # ax_img.set_yticks([])
            # fig.colorbar(image, ax=ax_img, fraction=0.045, pad=0.02,)
            colorbar = fig.colorbar(image, fraction=0.045, pad=0.02, cax=ax_cbar)
            colorbar.ax.tick_params(labelsize=10)

            # Top horizontal profile: I(x, y0)
            ax_top.plot(
                x,
                x_profile,
                color="black",
                lw=1.1,
            )
            ax_top.set_yscale("log")
            ax_top.grid(alpha=0.20)
            ax_top.set_title(name)
            ax_top.tick_params(axis="x", labelbottom=False)
            ax_top.tick_params(labelsize=12)

            # Left vertical profile: I(x0, y)
            ax_left.plot(
                y_profile,
                y,
                color="black",
                lw=1.1,
            )
            ax_left.set_xscale("log")
            ax_left.invert_xaxis()
            ax_left.grid(alpha=0.20)
            ax_left.tick_params(axis="y", labelleft=False)
            ax_left.tick_params(labelsize=7)

            ax_img.set_xlabel(r"$x-x_0$ [pix]", fontsize=12)
            ax_img.set_ylabel(r"$y-y_0$ [pix]", fontsize=12)
            ax_img.tick_params(labelsize=12)

        fig.savefig(output, dpi=300)
        plt.close(fig)


def plot_injection_comparison(data: np.ndarray, kernels: dict[str, np.ndarray], x: float, y: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    finite = data[np.isfinite(data)]
    median = float(np.nanmedian(finite))
    _, _, std = sigma_clipped_stats(finite, sigma=3.0, maxiters=5)
    flux = 35.0 * max(float(std), 1.0) * max(kernel.size for kernel in kernels.values())
    half = 32
    xi = int(round(x))
    yi = int(round(y))
    crop = data[yi - half : yi + half + 1, xi - half : xi + half + 1]
    vmin, vmax = np.nanpercentile(crop, [5, 99.7])

    fig, axes = plt.subplots(2, np.ceil(len(kernels) / 2), figsize=(5 * len(kernels), 5), constrained_layout=True)
    if len(kernels) == 1:
        axes = [axes]
    for ax, (name, kernel) in zip(axes, kernels.items()):
        injected = inject_psf(np.nan_to_num(data, nan=median), kernel, x, y, flux=flux)
        stamp = injected[yi - half : yi + half + 1, xi - half : xi + half + 1]
        ax.imshow(stamp, origin="lower", cmap="gray_r", vmin=vmin, vmax=vmax)
        ax.contour(stamp, levels=np.linspace(vmin, vmax, 8)[2:], colors="tomato", linewidths=0.45, alpha=0.8)
        ax.set_title(name)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.savefig(output, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PSF diagnostic plots for SN 2023ixf.")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/assets/psf_diagnostics"))
    parser.add_argument("--survey", default="Pan-STARRS")
    parser.add_argument("--band", default="r")
    parser.add_argument("--size-arcmin", type=float, default=3.0)
    parser.add_argument("--pixel-scale", type=float, default=0.262)
    args = parser.parse_args()

    image = fetch_image(
        SN2023IXF,
        ImageRequest(
            survey=args.survey,
            mode="Single band",
            band=args.band,
            size_arcmin=args.size_arcmin,
            pixel_scale_arcsec=args.pixel_scale,
        ),
    )
    data = np.asarray(image.data, dtype=float)
    target_x, target_y = world_to_scalar_pixel(image, SkyCoord(SN2023IXF.ra_deg, SN2023IXF.dec_deg, unit="deg"))
    scale = pixel_scale_arcsec(image)
    fwhm_pix = max(1.0 / scale, 1.0)
    stamp_size = odd_stamp_size(fwhm_pix)
    coords, _, _ = detect_field_stars(data, fwhm_pix=fwhm_pix, stamp_size=stamp_size, exclude_xy=(target_x, target_y))

    raw = build_raw_empirical_stack(data, coords, stamp_size)
    smoothed = normalize_kernel(smooth_psf_wings(raw))
    gaussian = normalize_kernel(smooth_psf_wings(gaussian_filter(raw, sigma=0.75)))
    compact = normalize_kernel(smooth_psf_wings(gaussian_filter(raw, sigma=0.65), taper_start_fraction=0.42))
    circular = normalize_kernel(smooth_psf_wings(circularize_psf(gaussian_filter(raw, sigma=0.55)), taper_start_fraction=0.42))
    taper_only = normalize_kernel(raw * radial_edge_taper(raw.shape, start_fraction=0.55, boundary_width=4.0))
    moffat = moffat_kernel(fwhm_pix)
    kernels = {
        "raw empirical": raw,
        "smooth taper": smoothed,
        "gaussian + taper": gaussian,
        "compact empirical": compact,
        "radial empirical": circular,
        "wide taper": taper_only,
        "moffat fallback": moffat,
    }
    plot_kernel_diagnostics(kernels, args.output_dir / "sn2023ixf_psf_kernel_diagnostics.png")
    plot_injection_comparison(data, kernels, target_x, target_y, args.output_dir / "sn2023ixf_bright_injection_comparison.png")
    for brightness in (5.0, 7.0, 10.0):
        mag = brightness_reference_mag(ChartSettings(psf_brightness=brightness))
        print(f"Brightness {brightness:.1f} maps to approximate injected reference magnitude {mag:.1f}")
    print(f"Wrote diagnostics to {args.output_dir}")


if __name__ == "__main__":
    main()
