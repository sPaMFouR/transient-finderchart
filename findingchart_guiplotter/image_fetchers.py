from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from .models import ImageData, ImageRequest, Target


CACHE_DIR = Path("data") / "cutouts"


class ImageFetchError(RuntimeError):
    pass


SURVEY_BANDS: dict[str, dict[str, list[str]]] = {
    "Pan-STARRS": {
        "Single band": ["g", "r", "i", "z", "y"],
        "Color composite": ["gri"],
    },
    "Legacy Survey": {
        "Single band": ["g", "r", "i", "z"],
        "Color composite": ["grz"],
    },
    "DSS2": {
        "Single band": ["red", "blue", "ir"],
        "Color composite": ["red"],
    },
    "2MASS": {
        "Single band": ["J", "H", "K"],
        "Color composite": ["JHK"],
    },
}


def available_surveys() -> list[str]:
    return list(SURVEY_BANDS)


def available_bands(survey: str, mode: str) -> list[str]:
    return SURVEY_BANDS.get(survey, {}).get(mode, [])


def available_filter_choices(survey: str) -> list[str]:
    options: list[str] = []
    if available_bands(survey, "Color composite"):
        options.append("Color composite")
    options.extend(available_bands(survey, "Single band"))
    return options


def preferred_filter_choice(survey: str) -> str:
    preferred = {
        "Pan-STARRS": "r",
        "Legacy Survey": "r",
        "DSS2": "red",
        "2MASS": "J",
    }.get(survey, "")
    options = available_filter_choices(survey)
    if preferred in options:
        return preferred
    return options[0] if options else ""


def mode_and_band_from_filter_choice(survey: str, choice: str) -> tuple[str, str]:
    if choice == "Color composite" and available_bands(survey, "Color composite"):
        return "Color composite", available_bands(survey, "Color composite")[0]
    single_band_options = available_bands(survey, "Single band")
    if choice in single_band_options:
        return "Single band", choice
    if single_band_options:
        return "Single band", single_band_options[0]
    color_options = available_bands(survey, "Color composite")
    if color_options:
        return "Color composite", color_options[0]
    return "Single band", choice


def _normalize_channel(data: np.ndarray) -> np.ndarray:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros_like(data, dtype=float)
    lo, hi = np.nanpercentile(finite, [1, 99.5])
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((np.nan_to_num(data, nan=np.nanmedian(finite)) - lo) / (hi - lo), 0, 1)


def _coerce_image_data(arrays: list[np.ndarray], mode: str) -> np.ndarray:
    if mode == "Color composite" and len(arrays) >= 3:
        channels = [_normalize_channel(np.asarray(arr, dtype=float).squeeze()) for arr in arrays[:3]]
        return np.dstack(channels)
    data = np.asarray(arrays[0], dtype=float)
    data = np.squeeze(data)
    if data.ndim == 3 and mode == "Color composite":
        if data.shape[0] in (3, 4):
            data = np.moveaxis(data[:3], 0, -1)
        return np.dstack([_normalize_channel(data[..., idx]) for idx in range(min(3, data.shape[-1]))])
    while data.ndim > 2:
        data = data[0]
    return data


def _read_fits_from_bytes(payload: bytes, survey: str, band: str, mode: str, url: str) -> ImageData:
    with fits.open(io.BytesIO(payload)) as hdul:
        image_hdus = [item for item in hdul if getattr(item, "data", None) is not None]
        if not image_hdus:
            raise ImageFetchError("No image data found in FITS response.")
        hdu = image_hdus[0]
        data = _coerce_image_data([item.data for item in image_hdus], mode)
        wcs = WCS(hdu.header)
    if not wcs.has_celestial:
        raise ImageFetchError("Downloaded FITS image has no celestial WCS.")
    return ImageData(data=data, wcs=wcs.celestial, survey=survey, band=band, mode=mode, source_url=url)


def _legacy_placeholder_tile(rgb_data: np.ndarray) -> bool:
    data = np.asarray(rgb_data, dtype=float)
    if data.ndim != 3 or data.shape[-1] < 3:
        return False
    flattened = data.reshape(-1, data.shape[-1])
    channel_spread = np.nanstd(flattened[:, :3], axis=0)
    return bool(np.nanmax(channel_spread) <= (0.5 / 255.0))


def _legacy_jpeg_array(image: Image.Image, mode: str) -> np.ndarray:
    rgb_data = np.asarray(image.convert("RGB"), dtype=float) / 255.0
    if _legacy_placeholder_tile(rgb_data):
        raise ImageFetchError(
            "Legacy Survey JPEG fallback returned a flat placeholder tile. "
            "This usually means the selected Legacy Survey layer has no usable image coverage at this coordinate."
        )
    if mode == "Single band":
        return np.asarray(image.convert("L"), dtype=float) / 255.0
    return rgb_data


def _request_bytes(url: str, timeout: float = 120.0) -> bytes:
    response = requests.get(url, timeout=timeout)
    if response.status_code >= 400:
        body = response.text.replace("\n", " ").strip()
        if response.status_code >= 500:
            raise ImageFetchError(
                f"Archive server error {response.status_code}. "
                f"The remote image service failed for this field; try another survey, band, or smaller cutout. "
                f"{body[:180]}"
            )
        raise ImageFetchError(f"Archive request failed with HTTP {response.status_code}. {body[:240]}")
    return response.content


def fetch_image(target: Target, request: ImageRequest) -> ImageData:
    if request.survey == "Pan-STARRS":
        return fetch_ps1(target, request)
    if request.survey == "Legacy Survey":
        return fetch_legacy(target, request)
    if request.survey == "DSS2":
        return fetch_dss2(target, request)
    if request.survey == "2MASS":
        return fetch_2mass(target, request)
    raise ImageFetchError(f"Unsupported survey: {request.survey}")


def fetch_ps1(target: Target, request: ImageRequest) -> ImageData:
    filters = "grizy" if request.mode == "Color composite" else request.band
    list_url = "https://ps1images.stsci.edu/cgi-bin/ps1filenames.py?" + urlencode(
        {"ra": target.ra_deg, "dec": target.dec_deg, "filters": filters}
    )
    rows = _parse_ps1_filename_table(_request_bytes(list_url).decode("utf-8"))
    rows = [row for row in rows if row.get("filename")]
    if not rows:
        raise ImageFetchError("No Pan-STARRS coverage found at this coordinate.")
    by_filter = {row.get("filter", ""): row["filename"] for row in rows}
    size = request.size_pixels
    if request.mode == "Color composite":
        params = {
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "size": size,
            "format": "fits",
            "red": by_filter.get("i") or by_filter.get("z") or rows[0]["filename"],
            "green": by_filter.get("r") or rows[0]["filename"],
            "blue": by_filter.get("g") or rows[0]["filename"],
        }
        band = "gri"
    else:
        filename = by_filter.get(request.band)
        if not filename:
            raise ImageFetchError(f"Pan-STARRS has no {request.band} image at this coordinate.")
        params = {
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "size": size,
            "format": "fits",
            "red": filename,
        }
        band = request.band
    url = "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi?" + urlencode(params)
    return _read_fits_from_bytes(_request_bytes(url), "Pan-STARRS", band, request.mode, url)


def _parse_ps1_filename_table(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        return []
    header = re.split(r"\s+", lines[0])
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = re.split(r"\s+", line)
        if len(values) < len(header):
            continue
        rows.append(dict(zip(header, values)))
    return rows


def fetch_legacy(target: Target, request: ImageRequest) -> ImageData:
    band = "grz" if request.mode == "Color composite" else request.band
    params = {
        "ra": target.ra_deg,
        "dec": target.dec_deg,
        "size": min(request.size_pixels, 3000),
        "layer": "ls-dr10",
        "pixscale": request.pixel_scale_arcsec,
        "bands": band,
    }
    url = "https://www.legacysurvey.org/viewer/fits-cutout?" + urlencode(params)
    try:
        return _read_fits_from_bytes(_request_bytes(url), "Legacy Survey", band, request.mode, url)
    except ImageFetchError as exc:
        if "server error 5" not in str(exc).lower():
            raise
        return fetch_legacy_jpeg_fallback(target, request, band, str(exc))


def fetch_legacy_jpeg_fallback(target: Target, request: ImageRequest, band: str, reason: str) -> ImageData:
    params = {
        "ra": target.ra_deg,
        "dec": target.dec_deg,
        "size": min(request.size_pixels, 3000),
        "layer": "ls-dr10",
        "pixscale": request.pixel_scale_arcsec,
        "bands": band,
    }
    url = "https://www.legacysurvey.org/viewer/jpeg-cutout?" + urlencode(params)
    payload = _request_bytes(url)
    try:
        image = Image.open(io.BytesIO(payload))
        data = _legacy_jpeg_array(image, request.mode)
    except ImageFetchError as exc:
        raise ImageFetchError(f"{exc} Original FITS error: {reason}") from exc
    except Exception as exc:
        raise ImageFetchError(
            "Legacy Survey FITS cutout failed, and the JPEG fallback could not be decoded. "
            f"Original FITS error: {reason}"
        ) from exc
    wcs = centered_tan_wcs(target, data.shape[1], data.shape[0], request.pixel_scale_arcsec)
    return ImageData(data=data, wcs=wcs, survey="Legacy Survey", band=band, mode=request.mode, source_url=url)


def centered_tan_wcs(target: Target, nx: int, ny: int, pixscale_arcsec: float) -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [(nx + 1) / 2.0, (ny + 1) / 2.0]
    wcs.wcs.cdelt = np.array([-pixscale_arcsec / 3600.0, pixscale_arcsec / 3600.0])
    wcs.wcs.crval = [target.ra_deg, target.dec_deg]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def fetch_dss2(target: Target, request: ImageRequest) -> ImageData:
    survey_map = {
        "red": ("DSS2 Red", "Red"),
        "blue": ("DSS2 Blue", "Blue"),
        "ir": ("DSS2 IR", "IR"),
        "r": ("DSS2 Red", "Red"),
        "b": ("DSS2 Blue", "Blue"),
    }
    survey_name, band_label = survey_map.get(request.band.lower(), ("DSS2 Red", "Red"))
    params = {
        "Position": f"{target.ra_deg},{target.dec_deg}",
        "Survey": survey_name,
        "Return": "FITS",
        "Pixels": request.size_pixels,
        "Size": request.size_arcmin / 60.0,
    }
    url = "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?" + urlencode(params)
    payload = _request_bytes(url, timeout=180.0)
    if payload[:6].lower().startswith(b"<html"):
        text = payload.decode("utf-8", errors="ignore")
        match = re.search(r'href="([^"]+\.fits[^"]*)"', text, flags=re.IGNORECASE)
        if not match:
            raise ImageFetchError("SkyView returned HTML instead of FITS; try a smaller cutout or another DSS2 band.")
        fits_url = match.group(1)
        if fits_url.startswith("/"):
            fits_url = "https://skyview.gsfc.nasa.gov" + fits_url
        payload = _request_bytes(fits_url, timeout=180.0)
        url = fits_url
    return _read_fits_from_bytes(payload, "DSS2", band_label, request.mode, url)


def fetch_2mass(target: Target, request: ImageRequest) -> ImageData:
    band_map = {
        "j": ("2MASS-J", "J"),
        "h": ("2MASS-H", "H"),
        "k": ("2MASS-K", "K"),
    }
    band = request.band if request.mode == "Single band" else "J"
    survey_name, band_label = band_map.get(band.lower(), ("2MASS-J", "J"))
    params = {
        "Position": f"{target.ra_deg},{target.dec_deg}",
        "Survey": survey_name,
        "Return": "FITS",
        "Pixels": request.size_pixels,
        "Size": request.size_arcmin / 60.0,
    }
    url = "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?" + urlencode(params)
    payload = _request_bytes(url, timeout=180.0)
    if payload[:6].lower().startswith(b"<html"):
        text = payload.decode("utf-8", errors="ignore")
        match = re.search(r'href="([^"]+\.fits[^"]*)"', text, flags=re.IGNORECASE)
        if not match:
            raise ImageFetchError("SkyView returned HTML instead of a 2MASS FITS image.")
        fits_url = match.group(1)
        if fits_url.startswith("/"):
            fits_url = "https://skyview.gsfc.nasa.gov" + fits_url
        payload = _request_bytes(fits_url, timeout=180.0)
        url = fits_url
    return _read_fits_from_bytes(payload, "2MASS", band_label, "Single band", url)


def save_preview_png(image: ImageData, path: Path) -> None:
    data = np.nan_to_num(image.data, nan=np.nanmedian(image.data))
    lo, hi = np.nanpercentile(data, [1, 99])
    scaled = np.clip((data - lo) / (hi - lo if hi > lo else 1.0), 0, 1)
    Image.fromarray(np.uint8(scaled * 255)).save(path)
