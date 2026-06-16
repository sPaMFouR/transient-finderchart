#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scienceplots
from astropy.coordinates import SkyCoord
from astropy.stats import sigma_clipped_stats
from pypalettes import load_cmap
from scipy.ndimage import center_of_mass, gaussian_filter
from scipy.ndimage import shift as ndi_shift

from findingchart_guiplotter.empirical_psf import (
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
from findingchart_guiplotter.renderer import (
    inject_psf,
    injected_reference_mag,
    pixel_scale_arcsec,
    world_to_scalar_pixel,
)

plt.style.use("science")

HIROSHIGE = load_cmap("Hiroshige", cmap_type="continuous", reverse=True)
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
        shifted = ndi_shift(
            psf,
            shift=(half - cy, half - cx),
            order=3,
            mode="constant",
            cval=0.0,
            prefilter=True,
        )
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


def kernel_center(kernel: np.ndarray) -> tuple[int, int]:
    finite_kernel = np.where(np.isfinite(kernel), kernel, -np.inf)
    return np.unravel_index(np.argmax(finite_kernel), kernel.shape)


def image_limits(values: np.ndarray) -> tuple[float, float]:
    positive = values[np.isfinite(values) & (values > 0)]
    if positive.size == 0:
        return 0.0, 1.0
    vmin = float(np.nanpercentile(positive, 5))
    vmax = float(np.nanpercentile(positive, 99.8))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
        return float(np.nanmin(positive)), float(np.nanmax(positive))
    return vmin, vmax


def contour_levels(values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    positive = values[np.isfinite(values) & (values > 0)]
    if positive.size == 0:
        return np.array([])
    low = max(vmin, float(np.nanmin(positive)))
    high = max(vmax, low * 1.0001)
    levels = np.geomspace(low, high, 7)
    return np.unique(levels[np.isfinite(levels)])


def symmetric_enclosed_flux_radius(profile: np.ndarray, fractions: tuple[float, ...] = (0.68, 0.95)) -> dict[float, float]:
    values = np.asarray(profile, dtype=float)
    values = np.where(np.isfinite(values) & (values > 0), values, 0.0)
    center = values.size // 2
    total = values[center] + 2.0 * np.sum(values[center + 1 :])
    if total <= 0:
        return {fraction: 0.0 for fraction in fractions}

    enclosed = values[center]
    radii: dict[float, float] = {}
    for radius in range(1, center + 1):
        enclosed += values[center - radius] + values[center + radius]
        fraction = enclosed / total
        for target in fractions:
            if target not in radii and fraction >= target:
                radii[target] = float(radius)
    for target in fractions:
        radii.setdefault(target, float(center))
    return radii


def plot_kernel_diagnostics(kernels: dict[str, np.ndarray], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(kernels) > 8:
        raise ValueError("The 2 x 4 layout supports at most eight kernels.")

    fig = plt.figure(figsize=(22, 11))
    outer = fig.add_gridspec(
        2,
        4,
        left=0.03,
        right=0.985,
        bottom=0.06,
        top=0.95,
        wspace=0.28,
        hspace=0.32,
    )

    for index, (name, kernel) in enumerate(kernels.items()):
        row, col = divmod(index, 4)
        inner = outer[row, col].subgridspec(
            2,
            4,
            height_ratios=(1.0, 3.2),
            width_ratios=(0.45, 3.2, 1.0, 0.18),
            hspace=0.06,
            wspace=0.06,
        )

        ax_blank = fig.add_subplot(inner[0, 0])
        ax_top = fig.add_subplot(inner[0, 1])
        ax_img = fig.add_subplot(inner[1, 1])
        ax_right = fig.add_subplot(inner[1, 2])
        ax_cbar = fig.add_subplot(inner[1, 3])

        ax_blank.axis("off")

        y0, x0 = kernel_center(kernel)
        ny, nx = kernel.shape
        x = np.arange(nx) - x0
        y = np.arange(ny) - y0

        x_profile = np.ma.masked_less_equal(kernel[y0, :], 0.0)
        y_profile = np.ma.masked_less_equal(kernel[:, x0], 0.0)
        x_radii = symmetric_enclosed_flux_radius(kernel[y0, :])
        y_radii = symmetric_enclosed_flux_radius(kernel[:, x0])
        vmin, vmax = image_limits(kernel)

        image = ax_img.imshow(
            kernel,
            origin="lower",
            cmap=HIROSHIGE,
            vmin=vmin,
            vmax=vmax,
            interpolation="nearest",
            extent=(x[0] - 0.5, x[-1] + 0.5, y[0] - 0.5, y[-1] + 0.5),
            aspect="equal",
        )

        levels = contour_levels(kernel, vmin, vmax)
        if levels.size:
            ax_img.contour(x, y, kernel, levels=levels, colors="white", linewidths=0.45, alpha=0.8)
        ax_img.axhline(0.0, color="white", ls="--", lw=0.45, alpha=0.5)
        ax_img.axvline(0.0, color="white", ls="--", lw=0.45, alpha=0.5)
        ax_img.set_xlabel(r"$x-x_0$ [pix]", fontsize=11)
        ax_img.set_ylabel(r"$y-y_0$ [pix]", fontsize=11)
        ax_img.tick_params(labelsize=10)

        colorbar = fig.colorbar(image, cax=ax_cbar)
        colorbar.ax.tick_params(labelsize=9)

        ax_top.grid(alpha=0.20)
        ax_top.tick_params(axis="x", labelbottom=False)
        ax_top.tick_params(labelsize=9)
        ax_top.set_title(name, fontsize=12)
        ax_top.plot(x, x_profile, color=HIROSHIGE(0.8), lw=2.0, alpha=0.5)
        for fraction, color, linestyle, label in (
            (0.68, "xkcd:dodger blue", "--", r"$1\sigma$"),
            (0.95, "xkcd:bright red", "-", r"$2\sigma$"),
        ):
            radius = x_radii[fraction]
            ax_top.axvline(-radius, color=color, ls=linestyle, lw=1.0, alpha=0.5)
            ax_top.axvline(radius, color=color, ls=linestyle, lw=1.0, alpha=0.5, label=label)
        ax_top.legend(loc="upper right", fontsize=7, frameon=False)

        ax_right.plot(y_profile, y, color=HIROSHIGE(0.8), lw=2.0, alpha=0.5)
        ax_right.grid(alpha=0.20)
        ax_right.tick_params(axis="y", labelleft=False, labelright=True, right=True)
        ax_right.tick_params(labelsize=9)
        ax_right.yaxis.set_label_position("right")
        for fraction, color, linestyle in (
            (0.68, "xkcd:dodger blue", "--"),
            (0.95, "xkcd:bright red", "-"),
        ):
            radius = y_radii[fraction]
            ax_right.axhline(-radius, color=color, ls=linestyle, lw=1.0, alpha=0.5)
            ax_right.axhline(radius, color=color, ls=linestyle, lw=1.0, alpha=0.5)

    for index in range(len(kernels), 8):
        row, col = divmod(index, 4)
        ax = fig.add_subplot(outer[row, col])
        ax.axis("off")

    fig.savefig(output, dpi=300)
    plt.close(fig)


def plot_injection_comparison(data: np.ndarray, kernels: dict[str, np.ndarray], x: float, y: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(kernels) > 7:
        raise ValueError("The 2 x 4 survey-overlap layout supports at most seven PSF variants.")

    finite = data[np.isfinite(data)]
    median = float(np.nanmedian(finite))
    _, _, std = sigma_clipped_stats(finite, sigma=3.0, maxiters=5)
    flux = 35.0 * max(float(std), 1.0) * max(kernel.size for kernel in kernels.values())

    half = 32
    xi = int(round(x))
    yi = int(round(y))
    survey_crop = data[yi - half : yi + half + 1, xi - half : xi + half + 1]
    vmin, vmax = np.nanpercentile(survey_crop[np.isfinite(survey_crop)], [5, 99.7])

    fig, axes = plt.subplots(2, 4, figsize=(18, 9), constrained_layout=True)
    flat_axes = list(np.ravel(axes))

    flat_axes[0].imshow(survey_crop, origin="lower", cmap=HIROSHIGE, vmin=vmin, vmax=vmax)
    flat_axes[0].set_title("survey image")
    flat_axes[0].set_xticks([])
    flat_axes[0].set_yticks([])

    contour_span = np.linspace(vmin, vmax, 8)[2:]
    for ax, (name, kernel) in zip(flat_axes[1:], kernels.items()):
        injected = inject_psf(np.nan_to_num(data, nan=median), kernel, x, y, flux=flux)
        stamp = injected[yi - half : yi + half + 1, xi - half : xi + half + 1]
        ax.imshow(stamp, origin="lower", cmap=HIROSHIGE, vmin=vmin, vmax=vmax)
        ax.contour(stamp, levels=contour_span, colors="white", linewidths=0.45, alpha=0.8)
        ax.set_title(name)
        ax.set_xticks([])
        ax.set_yticks([])

    for ax in flat_axes[1 + len(kernels) :]:
        ax.axis("off")

    fig.savefig(output, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PSF diagnostic plots for SN 2023ixf.")
    parser.add_argument("--output-dir", type=Path, default=Path("tests/figures"))
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
    circular = normalize_kernel(
        smooth_psf_wings(circularize_psf(gaussian_filter(raw, sigma=0.55)), taper_start_fraction=0.42)
    )
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

    for magnitude in (20.0, 18.0, 16.0):
        mag = injected_reference_mag(ChartSettings(psf_magnitude=magnitude))
        print(f"Injected source magnitude setting {magnitude:.1f} maps to reference magnitude {mag:.1f}")
    print(f"Wrote diagnostics to {args.output_dir}")


if __name__ == "__main__":
    main()
