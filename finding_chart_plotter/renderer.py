from __future__ import annotations

import math
import sys
import contextlib
import io
import shutil
import warnings
from pathlib import Path

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval
from astropy.wcs.utils import proj_plane_pixel_scales
from matplotlib.figure import Figure
from matplotlib.patches import ConnectionPatch, Polygon, Rectangle
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

from .empirical_psf import EmpiricalPSFError, empirical_psf_from_field, inject_psf, moffat_kernel
from .mpl_compat import ensure_astropy_wcsaxes_compat
from .models import ChartSettings, ImageData, Target

try:
    import scienceplots  # noqa: F401
    plt.style.use("science")
except Exception:
    pass

ensure_astropy_wcsaxes_compat()
warnings.filterwarnings("ignore", message="Tight layout not applied.*", category=UserWarning)

SCIENCE_FONT_FAMILY = "sans-serif"
# SCIENCE_FONT_FAMILY = "DejaVu Sans"
# SCIENCE_FONT_FAMILY = "cursive"
TEXT_COLOR = 'xkcd:dark'
CROSSHAIR_COLOR = 'xkcd:dark red'
SLIT_COLOR = 'xkcd:tomato'
INSET_SOURCE_BOX_FOV_FRACTION = 1.0 / 6.0
INSET_DISPLAY_LINEAR_SCALE = 2.0


def apply_project_style() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import plot_style  # noqa: F401
    except Exception:
        pass

    # Force the Matplotlib-like figure font used in the reference paper plots.
    # Do this after importing plot_style, because plot_style may override rcParams.
    plt.rcParams.update(
        {
            # "text.usetex": False,
            # "font.sans-serif": [SCIENCE_FONT_FAMILY],
            # "mathtext.fontset": "sans-serif",
            
#             "font.family": "serif",
#             "text.usetex": True,
#             "mathtext.fontset": "dejavuserif",
#             "text.latex.preamble": r"\usepackage{amsmath} \usepackage{amssymb}",
            
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.labelsize": 10,
            "axes.titlesize": 11,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
        }
    )

apply_project_style()


def pixel_scale_arcsec(image: ImageData) -> float:
    scales = proj_plane_pixel_scales(image.wcs) * 3600.0
    return float(np.nanmean(np.abs(scales)))


def image_fov_arcsec(image: ImageData) -> float:
    ny, nx = image.data.shape[:2]
    return min(nx, ny) * pixel_scale_arcsec(image)


def inset_source_box_arcsec(image: ImageData) -> float:
    return image_fov_arcsec(image) * INSET_SOURCE_BOX_FOV_FRACTION


def scalar_pixel(value) -> float:
    return float(np.asarray(value).reshape(-1)[0])


def world_to_scalar_pixel(image: ImageData, coord: SkyCoord) -> tuple[float, float]:
    x, y = image.wcs.world_to_pixel(coord)
    return scalar_pixel(x), scalar_pixel(y)


def image_display_extent(nx: int, ny: int) -> tuple[float, float, float, float]:
    return -0.5, nx - 0.5, -0.5, ny - 0.5


def image_with_injected_psf(image: ImageData, target: Target, settings: ChartSettings) -> np.ndarray:
    data = np.array(image.data, dtype=float, copy=True)
    if not settings.show_injected_source:
        return data
    x0, y0 = world_to_scalar_pixel(image, SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))
    if not np.isfinite(x0) or not np.isfinite(y0):
        return data
    scale = pixel_scale_arcsec(image)
    fwhm_pix = max(settings.psf_fwhm_arcsec / scale, 1.0)
    if data.ndim == 3:
        total_flux = rgb_visual_flux(settings)
        kernel = moffat_kernel(fwhm_pix)
        for channel in range(data.shape[2]):
            data[..., channel] = np.clip(inject_psf(data[..., channel], kernel, x0, y0, total_flux), 0, 1)
        return data
    try:
        kernel, _, psf_star_fluxes = empirical_psf_from_field(data, x0, y0, fwhm_pix=fwhm_pix)
        total_flux = estimate_target_flux_from_field(data, image, target, settings, fwhm_pix, psf_star_fluxes)
    except (EmpiricalPSFError, ValueError, RuntimeError):
        kernel = moffat_kernel(fwhm_pix)
        total_flux = estimate_target_flux_from_field(data, image, target, settings, fwhm_pix)
    finite = data[np.isfinite(data)]
    fill = np.nanmedian(finite) if finite.size else 0.0
    return inject_psf(np.nan_to_num(data, nan=fill), kernel, x0, y0, total_flux)


def rgb_visual_flux(settings: ChartSettings) -> float:
    return 0.08 * brightness_flux_scale(settings)


def brightness_flux_scale(settings: ChartSettings) -> float:
    return 10 ** ((settings.psf_brightness - 5.0) / 2.5)


def estimate_target_flux_from_field(
    data: np.ndarray,
    image: ImageData,
    target: Target,
    settings: ChartSettings,
    fwhm_pix: float,
    psf_star_fluxes: np.ndarray | None = None,
) -> float:
    if psf_star_fluxes is not None and psf_star_fluxes.size:
        median_star_flux = float(np.nanmedian(psf_star_fluxes))
        if np.isfinite(median_star_flux) and median_star_flux > 0:
            relative_flux = 0.25 * brightness_flux_scale(settings)
            return max(relative_flux * median_star_flux, 1.0)
    empirical_flux = estimate_catalog_flux_scale(data, image, target, settings, fwhm_pix)
    if empirical_flux is not None:
        return empirical_flux
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 1.0
    p50, p99 = np.nanpercentile(finite, [50, 99])
    peak = max(p99 - p50, np.nanstd(finite), 1.0)
    return max(peak * brightness_flux_scale(settings), 1.0)


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
    reference_mag = 18.0 - (settings.psf_brightness - 5.0)
    return max(10 ** (zero_point - 0.4 * reference_mag), 1.0)


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
    extent = image_display_extent(nx, ny)
    if data.ndim == 3:
        if not settings.auto_contrast and settings.vmax is not None and settings.vmin is not None and settings.vmax > settings.vmin:
            data = np.clip((data - settings.vmin) / (settings.vmax - settings.vmin), 0, 1)
        norm = None
        ax.imshow(np.clip(data, 0, 1), origin="lower", extent=extent)
    else:
        vmin, vmax = contrast_limits(original, settings)
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch())
        ax.imshow(data, origin="lower", cmap="gray_r", norm=norm, extent=extent)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.coords.grid(color="white", alpha=0.18, linestyle=":", linewidth=0.7)
    ax.coords[0].set_axislabel("RA", fontsize=12)
    ax.coords[1].set_axislabel("Dec", fontsize=12)
    ax.coords[0].set_ticklabel(size=9)
    ax.coords[1].set_ticklabel(size=9)
    ax._finding_chart_pixel_offset = (0.0, 0.0)

    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    x, y = world_to_scalar_pixel(image, target_coord)
    draw_metadata_box(ax, image, target, settings)
    draw_inset(ax, image, data, target, settings, norm)
    if settings.show_crosshair:
        draw_sn_marker(ax, image, target, settings, x, y)
    if settings.show_slit:
        polygon = Polygon(
            slit_polygon_pixels(image, target, settings),
            closed=True,
            fill=False,
            edgecolor=SLIT_COLOR,
            linewidth=0.7,
        )
        ax.add_patch(polygon)
    if settings.show_compass:
        draw_compass(ax, image)
    draw_scale_ruler(ax, image, 60.0)
    draw_catalog_sources(ax, image, target, settings)
    ax.set_title(chart_title(image, target), fontsize=12, fontfamily=SCIENCE_FONT_FAMILY, pad=12)


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
    return f"{survey_filter_label(image)}: {target.label} ({ra_text}, {dec_text})"


def survey_filter_label(image: ImageData) -> str:
    band = image.band.replace(" JPEG", "").strip()
    survey_prefixes = {
        "DSS2": "DSS2 ",
        "2MASS": "2MASS-",
        "Legacy Survey": "Legacy Survey-",
        "Pan-STARRS": "Pan-STARRS-",
    }
    prefix = survey_prefixes.get(image.survey, f"{image.survey}-")
    if band.startswith(prefix):
        band = band[len(prefix) :].strip()
    return f"{image.survey}-{band}" if band else image.survey


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
            # f"{target.label}",
            # f"RA  {ra_text}",
            # f"Dec {dec_text}",
            slit_instruction_text(settings),
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
        fontsize=10,
        fontfamily=SCIENCE_FONT_FAMILY,
        linespacing=1.2,
        bbox={"facecolor": "black", "alpha": 0.55, "edgecolor": "white", "linewidth": 0.8, "pad": 5},
    )


def slit_instruction_text(settings: ChartSettings) -> str:
    slit_size = f"Slit {settings.slit_width_arcsec:.1f}\" x {settings.slit_length_arcsec:.1f}\""
    if not settings.show_slit:
        return "Slit PA: Parallactic Angle"
    return f"{slit_size}\n PA = {settings.slit_pa_deg:.1f} deg E of N"


def draw_inset(ax, image: ImageData, data: np.ndarray, target: Target, settings: ChartSettings, norm) -> None:
    scale = pixel_scale_arcsec(image)
    if not np.isfinite(scale) or scale <= 0:
        return
    source_box_arcsec = inset_source_box_arcsec(image)
    if not np.isfinite(source_box_arcsec) or source_box_arcsec <= 0:
        return
    half_size_pix = max(5, int(round((source_box_arcsec / 2.0) / scale)))
    x0, y0 = world_to_scalar_pixel(image, SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))
    if not np.isfinite(x0) or not np.isfinite(y0):
        return
    ny, nx = data.shape[:2]
    if nx <= 0 or ny <= 0:
        return
    x1 = max(0, int(round(x0)) - half_size_pix)
    x2 = min(nx, int(round(x0)) + half_size_pix + 1)
    y1 = max(0, int(round(y0)) - half_size_pix)
    y2 = min(ny, int(round(y0)) + half_size_pix + 1)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return
    ax.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False, edgecolor="black", linewidth=0.5, alpha=0.85))
    
    nominal_box_size = 2 * half_size_pix + 1
    inset_width, inset_height = inset_axes_size_percent(nx, ny, nominal_box_size, nominal_box_size)
    inset = inset_axes(ax, width=f"{inset_width:.2f}%", height=f"{inset_height:.2f}%", loc="upper right", borderpad=1.1)
    stamp = data[y1:y2, x1:x2]
    stamp_ny, stamp_nx = stamp.shape[:2]
    stamp_extent = image_display_extent(stamp_nx, stamp_ny)
    if data.ndim == 3:
        inset.imshow(np.clip(stamp, 0, 1), origin="lower", extent=stamp_extent)
    else:
        inset.imshow(stamp, origin="lower", cmap="gray_r", norm=norm, extent=stamp_extent)
    inset.set_xlim(stamp_extent[0], stamp_extent[1])
    inset.set_ylim(stamp_extent[2], stamp_extent[3])
    inset.set_aspect("equal", adjustable="box")
    inset.set_xticks([])
    inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_edgecolor("black")
        spine.set_linewidth(0.6)
    inset._finding_chart_pixel_offset = (float(x1), float(y1))
    connect_inset_to_source_box(ax, inset, x1, x2, y1, y2)
    if settings.show_slit:
        draw_inset_slit(inset, image, target, settings, x1, y1)
    draw_catalog_sources_inset(inset, image, target, settings, x1, y1, stamp.shape[:2])
    local_x = x0 - x1
    local_y = y0 - y1
    draw_inset_marker(inset, image, target, settings, scale, local_x, local_y)
    draw_inset_scalebar(inset, scale, stamp.shape[:2])
    draw_inset_sn_label(inset, target.label, local_x, local_y)


def connect_inset_to_source_box(ax, inset, x1: int, x2: int, y1: int, y2: int) -> None:
    pairs = [
        ((0.0, 1.0), (x1, y2)),
        ((1.0, 0.0), (x2, y1)),
    ]
    for inset_xy, data_xy in pairs:
        connection = ConnectionPatch(
            xyA=inset_xy,
            coordsA=inset.transAxes,
            xyB=data_xy,
            coordsB=ax.transData,
            axesA=inset,
            axesB=ax,
            color="black",
            lw=0.5,
            alpha=0.75,
            clip_on=False,
        )
        ax.add_artist(connection)


def inset_axes_size_percent(nx: int, ny: int, box_width: int, box_height: int) -> tuple[float, float]:
    width_percent = 100.0 * INSET_DISPLAY_LINEAR_SCALE * max(box_width, 1) / max(nx, 1)
    height_percent = 100.0 * INSET_DISPLAY_LINEAR_SCALE * max(box_height, 1) / max(ny, 1)
    width_percent = min(max(width_percent, 5.0), 55.0)
    height_percent = min(max(height_percent, 5.0), 55.0)
    return width_percent, height_percent


def draw_inset_slit(inset, image: ImageData, target: Target, settings: ChartSettings, x_offset: int, y_offset: int) -> None:
    polygon = [(x - x_offset, y - y_offset) for x, y in slit_polygon_pixels(image, target, settings)]
    inset.add_patch(
        Polygon(
            polygon,
            closed=True,
            fill=False,
            edgecolor=SLIT_COLOR,
            linewidth=0.6,
            clip_on=True,
        )
    )


def draw_inset_marker(
    inset,
    image: ImageData,
    target: Target,
    settings: ChartSettings,
    scale: float,
    x: float,
    y: float,
) -> None:
    inner = max(6.0, 0.9 / scale)
    outer = max(inner + 8.0, 4.1 / scale)
    draw_crosshair_segments(inset, x, y, marker_unit_vectors(image, target), inner, outer, color=CROSSHAIR_COLOR, linewidth=0.6)


def draw_inset_scalebar(inset, scale: float, shape: tuple[int, int]) -> None:
    ny, nx = shape
    length_pix = 10.0 / scale
    x0 = 0.62 * nx
    y0 = 0.08 * ny
    tick = 1
    inset.plot([x0, x0 + length_pix], [y0, y0], color=SLIT_COLOR, lw=1.2)
    inset.plot([x0, x0], [y0 - tick, y0 + tick], color=SLIT_COLOR, lw=0.8)
    inset.plot([x0 + length_pix, x0 + length_pix], [y0 - tick, y0 + tick], color=SLIT_COLOR, lw=0.8)
    
    inset.text(
        x0 + 0.5 * length_pix,
        y0 + 3,
        '10"',
        color=SLIT_COLOR,
        ha="center",
        va="bottom",
        fontsize=7,
        # bbox={"facecolor": "black", "alpha": 0.4, "edgecolor": "none", "pad": 1.0},
    )


def draw_inset_sn_label(inset, label: str, x: float, y: float) -> None:
    inset.annotate(
        label,
        xy=(x, y),
        xycoords="data",
        xytext=(0.5, -0.12),
        textcoords="axes fraction",
        ha="center",
        va="top",
        color=SLIT_COLOR,
        fontsize=9,
        fontfamily=SCIENCE_FONT_FAMILY,
        weight="bold",
        arrowprops={
            "arrowstyle": "->",
            "linewidth": 1.0,
            "color": CROSSHAIR_COLOR,
            "shrinkA": 0,
            "shrinkB": 4,
        },
        bbox={"facecolor": "white", "alpha": 0.5, "edgecolor": "none", "pad": 1.5},
        annotation_clip=False,
        zorder=20,
        clip_on=False,
    )
    
    
def draw_sn_marker(ax, image: ImageData, target: Target, settings: ChartSettings, x: float, y: float) -> None:
    scale = pixel_scale_arcsec(image)
    inner = max(5.0, 1.8 / scale)
    outer = max(inner + 11.0, 5.6 / scale)
    draw_crosshair_segments(ax, x, y, marker_unit_vectors(image, target), inner, outer, color=CROSSHAIR_COLOR, linewidth=0.7)
    
    # ax.annotate(
#         target.label,
#         xy=(x, y),
#         xytext=(12, 12),
#         textcoords="offset points",
#         color=color,
#         fontsize=10,
#         weight="bold",
#         path_effects=[],
#)


def marker_unit_vectors(image: ImageData, target: Target) -> tuple[tuple[float, float], tuple[float, float]]:
    center = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    north = center.spherical_offsets_by(0 * u.arcsec, 1 * u.arcsec)
    east = center.spherical_offsets_by(1 * u.arcsec, 0 * u.arcsec)
    x0, y0 = world_to_scalar_pixel(image, center)
    nx, ny = world_to_scalar_pixel(image, north)
    ex, ey = world_to_scalar_pixel(image, east)
    return normalize_vector(nx - x0, ny - y0), normalize_vector(ex - x0, ey - y0)


def normalize_vector(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if not np.isfinite(length) or length <= 0:
        return 1.0, 0.0
    return dx / length, dy / length


def draw_crosshair_segments(ax, x: float, y: float, vectors, inner: float, outer: float, color: str, linewidth: float) -> None:
    kwargs = {"color": color, "lw": linewidth, "solid_capstyle": "butt"}
    for ux, uy in vectors:
        ax.plot([x + ux * inner, x + ux * outer], [y + uy * inner, y + uy * outer], **kwargs)
        ax.plot([x - ux * inner, x - ux * outer], [y - uy * inner, y - uy * outer], **kwargs)


def draw_compass(ax, image: ImageData) -> None:
    ny, nx = image.data.shape[:2]
    base_x = 0.94 * nx
    base_y = 0.04 * ny
    center = image.wcs.pixel_to_world(base_x, base_y)
    length_arcsec = max(16.0, min(nx, ny) * pixel_scale_arcsec(image) * 0.12)
    north = center.spherical_offsets_by(0 * u.arcsec, length_arcsec * u.arcsec)
    east = center.spherical_offsets_by(length_arcsec * u.arcsec, 0 * u.arcsec)
    north_x, north_y = world_to_scalar_pixel(image, north)
    east_x, east_y = world_to_scalar_pixel(image, east)
    ax.plot(base_x, base_y, color=SLIT_COLOR, marker='o', ms=5)
    ax.annotate("", xy=(north_x, north_y), xytext=(base_x, base_y), arrowprops={"arrowstyle": "->", "color": SLIT_COLOR, "lw": 0.9})
    ax.annotate("", xy=(east_x, east_y), xytext=(base_x, base_y), arrowprops={"arrowstyle": "->", "color": SLIT_COLOR, "lw": 0.9})
    ax.text(north_x, north_y, "N", color=SLIT_COLOR, fontsize=10, weight="bold", ha="center", va="bottom")
    ax.annotate(
        "E",
        xy=(east_x, east_y),
        xytext=(-2, 0),
        textcoords="offset points",
        color=SLIT_COLOR,
        fontsize=10,
        weight="bold",
        ha="right",
        va="center",
    )


def draw_scale_ruler(ax, image: ImageData, length_arcsec: float) -> None:
    ny, nx = image.data.shape[:2]
    center_x = 0.50 * nx
    center_y = 0.03 * ny
    center = image.wcs.pixel_to_world(center_x, center_y)
    left = center.spherical_offsets_by(-(length_arcsec / 2.0) * u.arcsec, 0 * u.arcsec)
    right = center.spherical_offsets_by((length_arcsec / 2.0) * u.arcsec, 0 * u.arcsec)
    left_x, left_y = world_to_scalar_pixel(image, left)
    right_x, right_y = world_to_scalar_pixel(image, right)
    ax.plot([left_x, right_x], [left_y, right_y], color=SLIT_COLOR, lw=2.0, solid_capstyle="butt")
    tick = max(2.0, 0.8 / pixel_scale_arcsec(image))
    ax.plot([left_x, left_x], [left_y - tick, left_y + tick], color=SLIT_COLOR, lw=1.2)
    ax.plot([right_x, right_x], [right_y - tick, right_y + tick], color=SLIT_COLOR, lw=1.2)
    ax.text(
        center_x,
        center_y + 2.5 * tick,
        '1"' if abs(length_arcsec - 60.0) < 1e-6 else f'{length_arcsec:.0f}"',
        color=SLIT_COLOR,
        fontsize=9,
        weight="bold",
        ha="center",
        va="bottom",
        # bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none", "pad": 1.5},
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
        draw_catalog_marker(ax, x, y, source, settings)


def draw_catalog_sources_inset(
    inset,
    image: ImageData,
    target: Target,
    settings: ChartSettings,
    x_offset: int,
    y_offset: int,
    shape: tuple[int, int],
) -> None:
    if not settings.catalog_sources:
        return
    ny, nx = shape
    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    for source in settings.catalog_sources:
        coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
        if coord.separation(target_coord).arcsec < 0.5:
            continue
        x, y = world_to_scalar_pixel(image, coord)
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        local_x = x - x_offset
        local_y = y - y_offset
        if local_x < -0.5 or local_x > nx - 0.5 or local_y < -0.5 or local_y > ny - 0.5:
            continue
        draw_catalog_marker(inset, local_x, local_y, source, settings, markersize=5.5, linewidth=0.9)


def draw_catalog_marker(ax, x: float, y: float, source, settings: ChartSettings, markersize: float = 5.0, linewidth: float = 1.0) -> None:
    selected = getattr(source, "label", "") == settings.selected_catalog_source_label
    edge_color = catalog_source_color(source)
    ax.plot(
        x,
        y,
        marker="o",
        ms=markersize + (3.0 if selected else 0.0),
        mec="royalblue" if selected else edge_color,
        mfc="none",
        mew=linewidth + (0.6 if selected else 0.0),
        alpha=1.0 if selected else 0.9,
        zorder=30 if selected else 8,
        clip_on=True,
    )
    if selected:
        ax.annotate(
            catalog_short_label(source),
            xy=(x, y),
            xytext=(5, 5),
            textcoords="offset points",
            color="royalblue",
            fontsize=7,
            ha="left",
            va="bottom",
            zorder=31,
            clip_on=True,
            bbox={"facecolor": "white", "alpha": 0.5, "edgecolor": "none", "pad": 1.5},
        )


def catalog_source_color(source) -> str:
    catalog = getattr(source, "catalog", "")
    if "Pan-STARRS" in catalog:
        return "dimgray"
    return "white"


def catalog_short_label(source) -> str:
    catalog = getattr(source, "catalog", "")
    source_id = getattr(source, "source_id", "")
    if "Pan-STARRS" in catalog:
        return f"PS1 {source_id}" if source_id else "PS1"
    if source_id:
        return f"Gaia {source_id}"
    return getattr(source, "label", "catalog source")


def export_chart(path: Path, image: ImageData, target: Target, settings: ChartSettings, dpi: int = 180) -> None:
    apply_project_style()
    fig = Figure(figsize=(7, 7))
    ax = fig.add_subplot(111, projection=image.wcs)
    draw_chart(ax, image, target, settings)
    fig.subplots_adjust(left=0.12, right=0.96, bottom=0.14, top=0.90)
    fig.savefig(path, dpi=dpi)
