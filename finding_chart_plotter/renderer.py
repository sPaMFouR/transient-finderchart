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
from matplotlib.patches import Polygon, Rectangle
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

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


def scalar_pixel(value) -> float:
    return float(np.asarray(value).reshape(-1)[0])


def world_to_scalar_pixel(image: ImageData, coord: SkyCoord) -> tuple[float, float]:
    x, y = image.wcs.world_to_pixel(coord)
    return scalar_pixel(x), scalar_pixel(y)


def image_with_injected_psf(image: ImageData, target: Target, settings: ChartSettings) -> np.ndarray:
    data = np.array(image.data, dtype=float, copy=True)
    if not settings.show_injected_source:
        return data
    x0, y0 = world_to_scalar_pixel(image, SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))
    if not np.isfinite(x0) or not np.isfinite(y0):
        return data
    scale = pixel_scale_arcsec(image)
    beta = 2.5
    fwhm_pix = max(settings.psf_fwhm_arcsec / scale, 1.0)
    alpha_pix = moffat_alpha_from_fwhm(fwhm_pix, beta)
    radius = int(max(8, math.ceil(8 * alpha_pix)))
    ny, nx = data.shape[:2]
    y, x = np.mgrid[
        max(0, int(y0) - radius) : min(ny, int(y0) + radius + 1),
        max(0, int(x0) - radius) : min(nx, int(x0) + radius + 1),
    ]
    if x.size == 0:
        return data
    if data.ndim == 3:
        total_flux = rgb_visual_flux(settings)
    else:
        total_flux = estimate_target_flux_from_field(data, image, target, settings, fwhm_pix)
    rr = ((x - x0) / alpha_pix) ** 2 + ((y - y0) / alpha_pix) ** 2
    kernel = (1.0 + rr) ** (-beta)
    kernel_sum = np.nansum(kernel)
    if kernel_sum <= 0:
        return data
    psf = total_flux * kernel / kernel_sum
    if data.ndim == 3:
        data[y, x, :] = np.clip(np.nan_to_num(data[y, x, :], nan=0.0) + psf[..., None], 0, 1)
    else:
        finite = data[np.isfinite(data)]
        fill = np.nanmedian(finite) if finite.size else 0.0
        data[y, x] = np.nan_to_num(data[y, x], nan=fill) + psf
    return data


def moffat_alpha_from_fwhm(fwhm_pix: float, beta: float) -> float:
    return fwhm_pix / (2.0 * math.sqrt(2.0 ** (1.0 / beta) - 1.0))


def rgb_visual_flux(settings: ChartSettings) -> float:
    return 0.40 * 10 ** ((20.0 - settings.psf_magnitude) / 2.5)


def estimate_target_flux_from_field(
    data: np.ndarray,
    image: ImageData,
    target: Target,
    settings: ChartSettings,
    fwhm_pix: float,
) -> float:
    empirical_flux = estimate_catalog_flux_scale(data, image, target, settings, fwhm_pix)
    if empirical_flux is not None:
        return empirical_flux
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 1.0
    p50, p99 = np.nanpercentile(finite, [50, 99])
    peak = max(p99 - p50, np.nanstd(finite), 1.0)
    beta = 2.5
    alpha_pix = moffat_alpha_from_fwhm(fwhm_pix, beta)
    kernel_peak_fraction = 1.0 / max(np.sum((1.0 + (np.hypot(*np.mgrid[-8:9, -8:9]) / alpha_pix) ** 2) ** (-beta)), 1.0)
    target_peak = peak * 10 ** ((20.0 - settings.psf_magnitude) / 2.5)
    return max(target_peak / kernel_peak_fraction, 1.0)


def estimate_catalog_flux_scale(
    data: np.ndarray,
    image: ImageData,
    target: Target,
    settings: ChartSettings,
    fwhm_pix: float,
) -> float | None:
    usable = []
    if not settings.catalog_sources:
        return None
    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    aperture_radius = max(2.0, 1.3 * fwhm_pix)
    annulus_inner = max(aperture_radius + 2.0, 2.2 * fwhm_pix)
    annulus_outer = max(annulus_inner + 2.0, 3.5 * fwhm_pix)
    ny, nx = data.shape[:2]
    for source in settings.catalog_sources:
        mag = getattr(source, "magnitude", None)
        if mag is None or not np.isfinite(mag):
            continue
        coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
        if coord.separation(target_coord).arcsec < 3.0:
            continue
        x0, y0 = world_to_scalar_pixel(image, coord)
        if not np.isfinite(x0) or not np.isfinite(y0):
            continue
        margin = int(math.ceil(annulus_outer + 1))
        if x0 < margin or x0 >= nx - margin or y0 < margin or y0 >= ny - margin:
            continue
        x1, x2 = int(x0) - margin, int(x0) + margin + 1
        y1, y2 = int(y0) - margin, int(y0) + margin + 1
        yy, xx = np.mgrid[y1:y2, x1:x2]
        rr = np.hypot(xx - x0, yy - y0)
        aperture = rr <= aperture_radius
        annulus = (rr >= annulus_inner) & (rr <= annulus_outer)
        stamp = data[y1:y2, x1:x2]
        if not np.any(aperture) or not np.any(annulus):
            continue
        background_values = stamp[annulus & np.isfinite(stamp)]
        if background_values.size < 8:
            continue
        background = np.nanmedian(background_values)
        flux = np.nansum(stamp[aperture] - background)
        if np.isfinite(flux) and flux > 0:
            usable.append((float(mag), float(flux)))
    if len(usable) < 2:
        return None
    zero_points = [math.log10(flux) + 0.4 * mag for mag, flux in usable]
    zero_point = float(np.nanmedian(zero_points))
    return max(10 ** (zero_point - 0.4 * settings.psf_magnitude), 1.0)


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
    return [world_to_scalar_pixel(image, coord) for coord in coords]


def draw_chart(ax, image: ImageData, target: Target, settings: ChartSettings) -> None:
    original = np.asarray(image.data, dtype=float)
    data = image_with_injected_psf(image, target, settings)
    ny, nx = data.shape[:2]
    if data.ndim == 3:
        if not settings.auto_contrast and settings.vmax is not None and settings.vmin is not None and settings.vmax > settings.vmin:
            data = np.clip((data - settings.vmin) / (settings.vmax - settings.vmin), 0, 1)
        norm = None
        ax.imshow(np.clip(data, 0, 1), origin="lower")
    else:
        vmin, vmax = contrast_limits(original, settings)
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch())
        ax.imshow(data, origin="lower", cmap="gray", norm=norm)
    ax.set_xlim(-0.5, nx - 0.5)
    ax.set_ylim(-0.5, ny - 0.5)
    ax.set_aspect("equal", adjustable="box")
    ax.coords.grid(color="white", alpha=0.18, linestyle=":", linewidth=0.7)
    ax.coords[0].set_axislabel("RA", fontsize=22)
    ax.coords[1].set_axislabel("Dec", fontsize=22)
    ax.coords[0].set_ticklabel(size=18)
    ax.coords[1].set_ticklabel(size=18)

    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    x, y = world_to_scalar_pixel(image, target_coord)
    draw_metadata_box(ax, image, target, settings)
    draw_inset(ax, image, data, target, norm)
    if settings.show_crosshair:
        draw_sn_marker(ax, image, x, y, target.label)
    if settings.show_slit:
        polygon = Polygon(
            slit_polygon_pixels(image, target, settings),
            closed=True,
            fill=False,
            edgecolor="tab:cyan",
            linewidth=0.5,
        )
        ax.add_patch(polygon)
    if settings.show_compass:
        draw_compass(ax, image)
    draw_scale_ruler(ax, image, 60.0)
    draw_catalog_sources(ax, image, target, settings)
    ax.set_title(chart_title(image, target), fontsize=16, pad=12)


def contrast_limits(data: np.ndarray, settings: ChartSettings) -> tuple[float, float]:
    if not settings.auto_contrast and settings.vmin is not None and settings.vmax is not None and settings.vmax > settings.vmin:
        return float(settings.vmin), float(settings.vmax)
    finite = data[np.isfinite(data)]
    if finite.size:
        interval = PercentileInterval(99.3)
        return tuple(float(value) for value in interval.get_limits(finite))
    return 0.0, 1.0


def chart_title(image: ImageData, target: Target) -> str:
    coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    ra_text = coord.ra.to_string(unit=u.hour, sep=":", precision=2, pad=True)
    dec_text = coord.dec.to_string(unit=u.deg, sep=":", precision=1, alwayssign=True, pad=True)
    return f"{image.survey}-{image.band}: {target.label} ({ra_text}, {dec_text})"


def target_sexagesimal(target: Target) -> tuple[str, str]:
    coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    return (
        coord.ra.to_string(unit=u.hour, sep=":", precision=2, pad=True),
        coord.dec.to_string(unit=u.deg, sep=":", precision=1, alwayssign=True, pad=True),
    )


def draw_metadata_box(ax, image: ImageData, target: Target, settings: ChartSettings) -> None:
    ra_text, dec_text = target_sexagesimal(target)
    text = "\n".join(
        [
            f"{target.label}",
            f"RA  {ra_text}",
            f"Dec {dec_text}",
            f"Slit {settings.slit_width_arcsec:.1f}\" x {settings.slit_length_arcsec:.1f}\"  PA {settings.slit_pa_deg:.1f} deg",
        ]
    )
    ax.text(
        0.02,
        0.98,
        text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color="white",
        fontsize=9,
        linespacing=1.2,
        bbox={"facecolor": "black", "alpha": 0.55, "edgecolor": "white", "linewidth": 0.8, "pad": 5},
    )


def draw_inset(ax, image: ImageData, data: np.ndarray, target: Target, norm) -> None:
    scale = pixel_scale_arcsec(image)
    total_arcsec = 10.0
    half_size_pix = max(5, int(round((total_arcsec / 2.0) / scale)))
    x0, y0 = world_to_scalar_pixel(image, SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))
    if not np.isfinite(x0) or not np.isfinite(y0):
        return
    ny, nx = data.shape[:2]
    x1 = max(0, int(round(x0)) - half_size_pix)
    x2 = min(nx, int(round(x0)) + half_size_pix + 1)
    y1 = max(0, int(round(y0)) - half_size_pix)
    y2 = min(ny, int(round(y0)) + half_size_pix + 1)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return
    ax.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False, edgecolor="white", linewidth=1.0, alpha=0.85))
    inset = inset_axes(ax, width="30%", height="30%", loc="upper right", borderpad=1.1)
    stamp = data[y1:y2, x1:x2]
    if data.ndim == 3:
        inset.imshow(np.clip(stamp, 0, 1), origin="lower")
    else:
        inset.imshow(stamp, origin="lower", cmap="gray", norm=norm)
    inset.set_xticks([])
    inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_edgecolor("white")
        spine.set_linewidth(1.2)
    local_x = x0 - x1
    local_y = y0 - y1
    draw_inset_marker(inset, scale, local_x, local_y)
    draw_inset_scalebar(inset, scale, stamp.shape[:2])


def draw_inset_marker(inset, scale: float, x: float, y: float) -> None:
    inner = max(2.0, 0.5 / scale)
    outer = max(inner + 3.0, 1.8 / scale)
    kwargs = {"color": "#ff9500", "lw": 0.6, "solid_capstyle": "butt"}
    inset.plot([x - outer, x - inner], [y, y], **kwargs)
    inset.plot([x + inner, x + outer], [y, y], **kwargs)
    inset.plot([x, x], [y - outer, y - inner], **kwargs)
    inset.plot([x, x], [y + inner, y + outer], **kwargs)


def draw_inset_scalebar(inset, scale: float, shape: tuple[int, int]) -> None:
    ny, nx = shape
    length_pix = 5.0 / scale
    x0 = 0.12 * nx
    y0 = 0.12 * ny
    inset.plot([x0, x0 + length_pix], [y0, y0], color="white", lw=1.5)
    inset.text(
        x0 + 0.5 * length_pix,
        y0 + 0.7,
        '5"',
        color="white",
        ha="center",
        va="bottom",
        fontsize=7,
        bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none", "pad": 1.0},
    )


def draw_sn_marker(ax, image: ImageData, x: float, y: float, label: str) -> None:
    scale = pixel_scale_arcsec(image)
    inner = max(3.0, 1.0 / scale)
    outer = max(inner + 4.5, 2.8 / scale)
    color = "#ff9500"
    kwargs = {"color": color, "lw": 0.7, "solid_capstyle": "butt"}
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
    north_x, north_y = world_to_scalar_pixel(image, north)
    east_x, east_y = world_to_scalar_pixel(image, east)
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
    left_x, left_y = world_to_scalar_pixel(image, left)
    right_x, right_y = world_to_scalar_pixel(image, right)
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
        x, y = world_to_scalar_pixel(image, coord)
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        ax.plot(x, y, marker="o", ms=5, mec="#ffd166", mfc="none", mew=1.0, alpha=0.9)


def export_chart(path: Path, image: ImageData, target: Target, settings: ChartSettings, dpi: int = 180) -> None:
    apply_project_style()
    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111, projection=image.wcs)
    draw_chart(ax, image, target, settings)
    fig.subplots_adjust(left=0.12, right=0.96, bottom=0.10, top=0.90)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
