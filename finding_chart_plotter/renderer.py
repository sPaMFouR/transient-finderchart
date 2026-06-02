from __future__ import annotations

import math
import sys
import contextlib
import io
import shutil
from pathlib import Path

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval
from astropy.wcs.utils import proj_plane_pixel_scales
from matplotlib.patches import Polygon

from .models import ChartSettings, ImageData, Target


def apply_project_style() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import plot_style  # noqa: F401
    except Exception:
        pass
    # plot_style.py enables LaTeX. Keep it when available, but do not let a
    # missing TeX install crash the interactive Qt canvas or PDF export.
    if shutil.which("latex") is None:
        plt.rcParams["text.usetex"] = False


apply_project_style()


def pixel_scale_arcsec(image: ImageData) -> float:
    scales = proj_plane_pixel_scales(image.wcs) * 3600.0
    return float(np.nanmean(np.abs(scales)))


def image_with_injected_psf(image: ImageData, target: Target, settings: ChartSettings) -> np.ndarray:
    data = np.array(image.data, dtype=float, copy=True)
    if not settings.show_injected_source:
        return data
    x0, y0 = image.wcs.world_to_pixel(SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))
    if not np.isfinite(x0) or not np.isfinite(y0):
        return data
    scale = pixel_scale_arcsec(image)
    beta = 2.5
    fwhm_pix = max(settings.psf_fwhm_arcsec / scale, 1.0)
    alpha_pix = fwhm_pix / (2.0 * math.sqrt(2.0 ** (1.0 / beta) - 1.0))
    radius = int(max(8, math.ceil(8 * alpha_pix)))
    ny, nx = data.shape[:2]
    y, x = np.mgrid[
        max(0, int(y0) - radius) : min(ny, int(y0) + radius + 1),
        max(0, int(x0) - radius) : min(nx, int(x0) + radius + 1),
    ]
    if x.size == 0:
        return data
    finite = data[np.isfinite(data)]
    noise = np.nanstd(finite) if finite.size else 1.0
    if data.ndim == 3:
        amplitude = 0.15 * 10 ** ((20.0 - settings.psf_magnitude) / 2.5)
    else:
        # Brightness is visual, not calibrated. Lower magnitude means brighter PSF.
        amplitude = max(noise, 1.0) * 10 ** ((22.0 - settings.psf_magnitude) / 2.5)
    rr = ((x - x0) / alpha_pix) ** 2 + ((y - y0) / alpha_pix) ** 2
    psf = amplitude * (1.0 + rr) ** (-beta)
    if data.ndim == 3:
        data[y, x, :] = np.clip(np.nan_to_num(data[y, x, :], nan=0.0) + psf[..., None], 0, 1)
    else:
        data[y, x] = np.nan_to_num(data[y, x], nan=np.nanmedian(finite) if finite.size else 0.0) + psf
    return data


def slit_polygon_pixels(image: ImageData, target: Target, settings: ChartSettings) -> list[tuple[float, float]]:
    center = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    pa = math.radians(settings.slit_pa_deg)
    half_l = settings.slit_length_arcsec / 2.0
    half_w = settings.slit_width_arcsec / 2.0
    along_e = half_l * math.sin(pa)
    along_n = half_l * math.cos(pa)
    perp_e = half_w * math.cos(pa)
    perp_n = -half_w * math.sin(pa)
    offsets = [
        (along_e + perp_e, along_n + perp_n),
        (along_e - perp_e, along_n - perp_n),
        (-along_e - perp_e, -along_n - perp_n),
        (-along_e + perp_e, -along_n + perp_n),
    ]
    coords = [center.spherical_offsets_by(east * u.arcsec, north * u.arcsec) for east, north in offsets]
    return [image.wcs.world_to_pixel(coord) for coord in coords]


def draw_chart(ax, image: ImageData, target: Target, settings: ChartSettings) -> None:
    data = image_with_injected_psf(image, target, settings)
    ny, nx = data.shape[:2]
    if data.ndim == 3:
        ax.imshow(np.clip(data, 0, 1), origin="lower")
    else:
        finite = data[np.isfinite(data)]
        if finite.size:
            interval = PercentileInterval(99.3)
            vmin, vmax = interval.get_limits(finite)
        else:
            vmin, vmax = 0.0, 1.0
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch())
        ax.imshow(data, origin="lower", cmap="gray", norm=norm)
    ax.set_xlim(-0.5, nx - 0.5)
    ax.set_ylim(-0.5, ny - 0.5)
    ax.set_aspect("equal", adjustable="box")
    ax.coords.grid(color="white", alpha=0.18, linestyle=":", linewidth=0.7)
    ax.coords[0].set_axislabel("RA")
    ax.coords[1].set_axislabel("Dec")

    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    x, y = image.wcs.world_to_pixel(target_coord)
    if settings.show_crosshair:
        draw_sn_marker(ax, image, x, y, target.label)
    if settings.show_slit:
        polygon = Polygon(
            slit_polygon_pixels(image, target, settings),
            closed=True,
            fill=False,
            edgecolor="tab:cyan",
            linewidth=1.8,
        )
        ax.add_patch(polygon)
        ax.text(
            0.02,
            0.98,
            f"Slit PA {settings.slit_pa_deg:.1f} deg  {settings.slit_width_arcsec:.1f}\" x {settings.slit_length_arcsec:.1f}\"",
            transform=ax.transAxes,
            ha="left",
            va="top",
            color="white",
            fontsize=9,
            bbox={"facecolor": "black", "alpha": 0.45, "edgecolor": "none", "pad": 3},
        )
    if settings.show_compass:
        draw_compass(ax, image)
    draw_scale_ruler(ax, image, 60.0)
    draw_catalog_sources(ax, image, target, settings)
    ax.set_title(chart_title(image, target), fontsize=plt.rcParams.get("axes.titlesize", 12))


def chart_title(image: ImageData, target: Target) -> str:
    coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    ra_text = coord.ra.to_string(unit=u.hour, sep=":", precision=2, pad=True)
    dec_text = coord.dec.to_string(unit=u.deg, sep=":", precision=1, alwayssign=True, pad=True)
    return f"{image.survey} {image.band} image | {target.label} | RA {ra_text}  Dec {dec_text}"


def draw_sn_marker(ax, image: ImageData, x: float, y: float, label: str) -> None:
    scale = pixel_scale_arcsec(image)
    inner = max(3.0, 1.0 / scale)
    outer = max(inner + 6.0, 3.5 / scale)
    color = "#ff3b30"
    kwargs = {"color": color, "lw": 1.8, "solid_capstyle": "butt"}
    ax.plot([x - outer, x - inner], [y, y], **kwargs)
    ax.plot([x + inner, x + outer], [y, y], **kwargs)
    ax.plot([x, x], [y - outer, y - inner], **kwargs)
    ax.plot([x, x], [y + inner, y + outer], **kwargs)
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(8, 10),
        textcoords="offset points",
        color=color,
        fontsize=10,
        weight="bold",
        path_effects=[],
    )


def draw_compass(ax, image: ImageData) -> None:
    ny, nx = image.data.shape[:2]
    base_x = 0.86 * nx
    base_y = 0.08 * ny
    center = image.wcs.pixel_to_world(base_x, base_y)
    length_arcsec = max(8.0, min(nx, ny) * pixel_scale_arcsec(image) * 0.085)
    north = center.spherical_offsets_by(0 * u.arcsec, length_arcsec * u.arcsec)
    east = center.spherical_offsets_by(length_arcsec * u.arcsec, 0 * u.arcsec)
    north_x, north_y = image.wcs.world_to_pixel(north)
    east_x, east_y = image.wcs.world_to_pixel(east)
    ax.annotate("", xy=(north_x, north_y), xytext=(base_x, base_y), arrowprops={"arrowstyle": "->", "color": "white", "lw": 1.5})
    ax.annotate("", xy=(east_x, east_y), xytext=(base_x, base_y), arrowprops={"arrowstyle": "->", "color": "white", "lw": 1.5})
    ax.text(north_x, north_y, "N", color="white", fontsize=10, weight="bold", ha="center", va="bottom")
    ax.text(east_x, east_y, "E", color="white", fontsize=10, weight="bold", ha="left", va="center")


def draw_scale_ruler(ax, image: ImageData, length_arcsec: float) -> None:
    ny, nx = image.data.shape[:2]
    center_x = 0.50 * nx
    center_y = 0.08 * ny
    center = image.wcs.pixel_to_world(center_x, center_y)
    left = center.spherical_offsets_by(-(length_arcsec / 2.0) * u.arcsec, 0 * u.arcsec)
    right = center.spherical_offsets_by((length_arcsec / 2.0) * u.arcsec, 0 * u.arcsec)
    left_x, left_y = image.wcs.world_to_pixel(left)
    right_x, right_y = image.wcs.world_to_pixel(right)
    ax.plot([left_x, right_x], [left_y, right_y], color="white", lw=2.0, solid_capstyle="butt")
    tick = max(3.0, 0.8 / pixel_scale_arcsec(image))
    ax.plot([left_x, left_x], [left_y - tick, left_y + tick], color="white", lw=1.6)
    ax.plot([right_x, right_x], [right_y - tick, right_y + tick], color="white", lw=1.6)
    ax.text(
        center_x,
        center_y + 2.5 * tick,
        "1 arcmin" if abs(length_arcsec - 60.0) < 1e-6 else f'{length_arcsec:.0f}"',
        color="white",
        fontsize=9,
        weight="bold",
        ha="center",
        va="bottom",
        bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none", "pad": 1.5},
    )


def draw_catalog_sources(ax, image: ImageData, target: Target, settings: ChartSettings) -> None:
    if not settings.catalog_sources:
        return
    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    for source in settings.catalog_sources:
        coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
        if coord.separation(target_coord).arcsec < 0.5:
            continue
        x, y = image.wcs.world_to_pixel(coord)
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        ax.plot(x, y, marker="o", ms=5, mec="#ffd166", mfc="none", mew=1.0, alpha=0.9)


def export_chart(path: Path, image: ImageData, target: Target, settings: ChartSettings, dpi: int = 180) -> None:
    apply_project_style()
    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111, projection=image.wcs)
    draw_chart(ax, image, target, settings)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
