from __future__ import annotations

import math
import warnings

import numpy as np
from astropy.stats import sigma_clipped_stats
from scipy.ndimage import center_of_mass, maximum_filter
from scipy.ndimage import shift as ndi_shift
from scipy.spatial import cKDTree

try:
    from photutils.detection import DAOStarFinder
except Exception:  # pragma: no cover - optional dependency fallback
    DAOStarFinder = None


class EmpiricalPSFError(RuntimeError):
    pass


def odd_stamp_size(fwhm_pix: float) -> int:
    size = int(math.ceil(max(25.0, 10.0 * fwhm_pix)))
    if size % 2 == 0:
        size += 1
    return min(size, 61)


def cut_stamp(image: np.ndarray, x: float, y: float, size: int) -> np.ndarray:
    if size % 2 == 0:
        raise ValueError("stamp size must be odd")
    half = size // 2
    xi = int(np.rint(x))
    yi = int(np.rint(y))
    y0 = yi - half
    y1 = yi + half + 1
    x0 = xi - half
    x1 = xi + half + 1
    if y0 < 0 or x0 < 0 or y1 > image.shape[0] or x1 > image.shape[1]:
        raise ValueError("stamp would hit image boundary")
    return image[y0:y1, x0:x1].copy()


def edge_mask(shape: tuple[int, int], width: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    mask[:width, :] = True
    mask[-width:, :] = True
    mask[:, :width] = True
    mask[:, -width:] = True
    return mask


def nearest_neighbor_distances(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    coords = np.column_stack([x, y])
    if len(coords) <= 1:
        return np.full(len(coords), np.inf)
    distances, _ = cKDTree(coords).query(coords, k=2)
    return distances[:, 1]


def detect_field_stars(
    data: np.ndarray,
    *,
    fwhm_pix: float,
    threshold_sigma: float = 5.0,
    stamp_size: int | None = None,
    max_stars: int = 30,
    min_separation: float | None = None,
    exclude_xy: tuple[float, float] | None = None,
    exclude_radius: float = 10.0,
) -> tuple[list[tuple[float, float]], np.ndarray, tuple[float, float, float]]:
    finite = np.isfinite(data)
    if finite.sum() == 0:
        raise EmpiricalPSFError("image contains no finite pixels")
    mean, median, std = sigma_clipped_stats(data[finite], sigma=3.0, maxiters=5)
    if not np.isfinite(std) or std <= 0:
        raise EmpiricalPSFError("image background scatter is not usable for PSF-star detection")
    clean = np.array(data, dtype=float, copy=True)
    clean[~np.isfinite(clean)] = median
    stamp_size = stamp_size or odd_stamp_size(fwhm_pix)
    if DAOStarFinder is not None:
        try:
            x, y, flux = _detect_with_daofind(clean, median, std, fwhm_pix, threshold_sigma)
        except EmpiricalPSFError:
            x, y, flux = _detect_with_local_max(clean, median, std, fwhm_pix, threshold_sigma)
    else:
        x, y, flux = _detect_with_local_max(clean, median, std, fwhm_pix, threshold_sigma)
    keep = star_selection_mask(data, x, y, flux, fwhm_pix, stamp_size, min_separation, exclude_xy, exclude_radius)
    idx = np.where(keep)[0]
    if len(idx) == 0:
        raise EmpiricalPSFError("no detected stars passed the empirical PSF cuts")
    idx = idx[np.argsort(flux[idx])[::-1]][:max_stars]
    return [(float(x[i]), float(y[i])) for i in idx], flux[idx], (float(mean), float(median), float(std))


def _detect_with_daofind(
    clean: np.ndarray,
    median: float,
    std: float,
    fwhm_pix: float,
    threshold_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sources = DAOStarFinder(fwhm=fwhm_pix, threshold=threshold_sigma * std)(clean - median)
    if sources is None or len(sources) == 0:
        raise EmpiricalPSFError("no PSF stars detected with DAOStarFinder")
    return (
        np.asarray(sources["xcentroid"], dtype=float),
        np.asarray(sources["ycentroid"], dtype=float),
        np.asarray(sources["flux"], dtype=float),
    )


def _detect_with_local_max(
    clean: np.ndarray,
    median: float,
    std: float,
    fwhm_pix: float,
    threshold_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    footprint = max(3, int(math.ceil(2.5 * fwhm_pix)))
    if footprint % 2 == 0:
        footprint += 1
    threshold = median + threshold_sigma * std
    peaks = (clean == maximum_filter(clean, size=footprint)) & (clean > threshold)
    y, x = np.nonzero(peaks)
    if len(x) == 0:
        raise EmpiricalPSFError("no PSF stars detected with local-maximum fallback")
    radius = max(2.0, 1.5 * fwhm_pix)
    flux = aperture_fluxes(clean, x.astype(float), y.astype(float), radius, median)
    return x.astype(float), y.astype(float), flux


def aperture_fluxes(data: np.ndarray, x: np.ndarray, y: np.ndarray, radius: float, background: float) -> np.ndarray:
    values = np.full(len(x), np.nan, dtype=float)
    margin = int(math.ceil(radius))
    for idx, (xx, yy) in enumerate(zip(x, y)):
        xi = int(np.rint(xx))
        yi = int(np.rint(yy))
        y0 = max(0, yi - margin)
        y1 = min(data.shape[0], yi + margin + 1)
        x0 = max(0, xi - margin)
        x1 = min(data.shape[1], xi + margin + 1)
        grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
        aperture = np.hypot(grid_x - xx, grid_y - yy) <= radius
        values[idx] = np.nansum(data[y0:y1, x0:x1][aperture] - background)
    return values


def star_selection_mask(
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    flux: np.ndarray,
    fwhm_pix: float,
    stamp_size: int,
    min_separation: float | None,
    exclude_xy: tuple[float, float] | None,
    exclude_radius: float,
) -> np.ndarray:
    half_margin = stamp_size // 2 + 2
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(flux) & (flux > 0)
    keep &= x > half_margin
    keep &= y > half_margin
    keep &= x < data.shape[1] - half_margin
    keep &= y < data.shape[0] - half_margin
    if min_separation is None:
        min_separation = max(4.0 * fwhm_pix, 0.7 * stamp_size)
    keep &= nearest_neighbor_distances(x, y) > min_separation
    if exclude_xy is not None:
        keep &= np.hypot(x - exclude_xy[0], y - exclude_xy[1]) > exclude_radius
    return keep


def build_empirical_psf(
    data: np.ndarray,
    coords: list[tuple[float, float]],
    *,
    stamp_size: int,
    edge_width: int = 5,
    min_stars: int = 3,
    max_recentering: float = 5.0,
) -> tuple[np.ndarray, list[tuple[float, float]], np.ndarray]:
    half = stamp_size // 2
    background_mask = edge_mask((stamp_size, stamp_size), edge_width)
    normalized_stamps: list[np.ndarray] = []
    used_coords: list[tuple[float, float]] = []
    raw_fluxes: list[float] = []
    for x, y in coords:
        try:
            stamp = cut_stamp(data, x, y, stamp_size)
        except ValueError:
            continue
        psf = stamp - np.nanmedian(stamp[background_mask])
        psf[~np.isfinite(psf)] = 0.0
        psf[psf < 0] = 0.0
        raw_flux = float(np.sum(psf))
        if raw_flux <= 0 or not np.isfinite(raw_flux):
            continue
        cy, cx = center_of_mass(psf)
        if not np.isfinite(cx) or not np.isfinite(cy):
            continue
        if abs(cx - half) > max_recentering or abs(cy - half) > max_recentering:
            continue
        shifted = ndi_shift(psf, shift=(half - cy, half - cx), order=3, mode="constant", cval=0.0, prefilter=True)
        shifted[shifted < 0] = 0.0
        shifted_flux = float(np.sum(shifted))
        if shifted_flux <= 0 or not np.isfinite(shifted_flux):
            continue
        normalized_stamps.append(shifted / shifted_flux)
        raw_fluxes.append(raw_flux)
        used_coords.append((x, y))
    if len(normalized_stamps) < min_stars:
        raise EmpiricalPSFError(f"only {len(normalized_stamps)} usable PSF stars survived")
    stack = np.nanmedian(np.stack(normalized_stamps, axis=0), axis=0)
    stack[~np.isfinite(stack)] = 0.0
    stack[stack < 0] = 0.0
    stack = smooth_psf_wings(stack, background_mask=background_mask)
    total = float(np.sum(stack))
    if total <= 0:
        raise EmpiricalPSFError("built empirical PSF has non-positive total flux")
    return stack / total, used_coords, np.asarray(raw_fluxes)


def smooth_psf_wings(
    psf: np.ndarray,
    *,
    background_mask: np.ndarray | None = None,
    edge_width: int = 5,
    taper_start_fraction: float = 0.68,
) -> np.ndarray:
    cleaned = np.array(psf, dtype=float, copy=True)
    cleaned[~np.isfinite(cleaned)] = 0.0
    cleaned[cleaned < 0] = 0.0
    if background_mask is None:
        width = max(1, min(edge_width, min(cleaned.shape) // 2))
        background_mask = edge_mask(cleaned.shape, width)
    background_values = cleaned[background_mask & np.isfinite(cleaned)]
    background_level = 0.0
    if background_values.size:
        _, background_level, _ = sigma_clipped_stats(background_values, sigma=3.0, maxiters=5)
    if np.isfinite(background_level) and background_level > 0:
        cleaned -= background_level
    cleaned[cleaned < 0] = 0.0
    return cleaned * radial_edge_taper(cleaned.shape, start_fraction=taper_start_fraction)


def radial_edge_taper(shape: tuple[int, int], start_fraction: float = 0.68, boundary_width: float = 3.0) -> np.ndarray:
    ny, nx = shape
    y, x = np.mgrid[:ny, :nx]
    cy = 0.5 * (ny - 1)
    cx = 0.5 * (nx - 1)
    radius = np.hypot(x - cx, y - cy)
    max_radius = float(np.max(radius))
    if max_radius <= 0:
        return np.ones(shape, dtype=float)
    start = max(0.0, min(float(start_fraction), 0.98)) * max_radius
    taper = np.ones(shape, dtype=float)
    edge = radius >= start
    if np.any(edge):
        phase = np.clip((radius[edge] - start) / max(max_radius - start, 1.0e-12), 0.0, 1.0)
        taper[edge] = 0.5 * (1.0 + np.cos(np.pi * phase))
    taper[radius >= max_radius] = 0.0
    distance_to_boundary = np.minimum.reduce([x, y, nx - 1 - x, ny - 1 - y]).astype(float)
    boundary_phase = np.clip(distance_to_boundary / max(float(boundary_width), 1.0e-12), 0.0, 1.0)
    boundary_taper = boundary_phase * boundary_phase * (3.0 - 2.0 * boundary_phase)
    return taper * boundary_taper


def empirical_psf_from_field(
    data: np.ndarray,
    x: float,
    y: float,
    *,
    fwhm_pix: float,
    threshold_sigma: float = 5.0,
) -> tuple[np.ndarray, list[tuple[float, float]], np.ndarray]:
    stamp_size = odd_stamp_size(fwhm_pix)
    coords, _, _ = detect_field_stars(
        data,
        fwhm_pix=fwhm_pix,
        threshold_sigma=threshold_sigma,
        stamp_size=stamp_size,
        exclude_xy=(x, y),
        exclude_radius=max(10.0, 3.0 * fwhm_pix),
    )
    return build_empirical_psf(data, coords, stamp_size=stamp_size, min_stars=3)


def shift_psf_to_subpixel(psf: np.ndarray, dx: float, dy: float) -> np.ndarray:
    shifted = ndi_shift(psf, shift=(dy, dx), order=3, mode="constant", cval=0.0, prefilter=True)
    shifted[shifted < 0] = 0.0
    shifted = smooth_psf_wings(shifted)
    total = float(np.sum(shifted))
    if total <= 0:
        raise EmpiricalPSFError("subpixel-shifted PSF has non-positive flux")
    return shifted / total


def inject_psf(data: np.ndarray, psf: np.ndarray, x: float, y: float, flux: float) -> np.ndarray:
    if flux <= 0:
        raise ValueError("Source flux must be positive")
    out = np.array(data, dtype=float, copy=True)
    size = psf.shape[0]
    half = size // 2
    xi = int(np.rint(x))
    yi = int(np.rint(y))
    kernel = shift_psf_to_subpixel(psf, dx=x - xi, dy=y - yi)
    y0 = yi - half
    y1 = yi + half + 1
    x0 = xi - half
    x1 = xi + half + 1
    img_y0 = max(y0, 0)
    img_y1 = min(y1, out.shape[0])
    img_x0 = max(x0, 0)
    img_x1 = min(x1, out.shape[1])
    if img_y0 >= img_y1 or img_x0 >= img_x1:
        raise ValueError("Source position lies outside the image")
    ker_y0 = img_y0 - y0
    ker_y1 = ker_y0 + (img_y1 - img_y0)
    ker_x0 = img_x0 - x0
    ker_x1 = ker_x0 + (img_x1 - img_x0)
    out[img_y0:img_y1, img_x0:img_x1] += flux * kernel[ker_y0:ker_y1, ker_x0:ker_x1]
    return out


def moffat_kernel(fwhm_pix: float, beta: float = 4.5) -> np.ndarray:
    alpha = fwhm_pix / (2.0 * math.sqrt(2.0 ** (1.0 / beta) - 1.0))
    radius = int(max(6, math.ceil(3.0 * fwhm_pix)))
    y, x = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    kernel = (1.0 + ((x / alpha) ** 2 + (y / alpha) ** 2)) ** (-beta)
    kernel[~np.isfinite(kernel)] = 0.0
    total = float(np.sum(kernel))
    if total <= 0:
        raise EmpiricalPSFError("analytic fallback PSF has non-positive total flux")
    return kernel / total
