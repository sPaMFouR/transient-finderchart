#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pickle
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_repo(repo_dir: Path) -> None:
    repo = repo_dir.resolve()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _state_dir(repo_dir: Path) -> Path:
    path = repo_dir / "findingchart_macapp" / "rendered_charts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configure_runtime_cache(repo_dir: Path) -> None:
    cache_root = _state_dir(repo_dir) / "cache"
    mpl_cache = cache_root / "matplotlib"
    xdg_cache = cache_root / "xdg"
    mpl_cache.mkdir(parents=True, exist_ok=True)
    xdg_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache))


def _safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text).strip("_") or "target"


def _parse_target(payload: dict[str, Any]):
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    from findingchart_guiplotter.models import Target
    from findingchart_guiplotter.tns import TNSClient

    if payload.get("resolveTNS", False):
        return TNSClient().lookup(str(payload.get("queryName", "")).strip())

    name = str(payload.get("targetName") or payload.get("queryName") or "Custom transient").strip()
    ra_text = str(payload.get("raText", "")).strip()
    dec_text = str(payload.get("decText", "")).strip()
    try:
        coord = SkyCoord(ra_text, dec_text, unit=(u.hourangle, u.deg))
    except Exception:
        coord = SkyCoord(float(ra_text) * u.deg, float(dec_text) * u.deg)
    return Target(display_name=name, ra_deg=float(coord.ra.deg), dec_deg=float(coord.dec.deg))


def _target_payload(target) -> dict[str, Any]:
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    return {
        "name": target.label,
        "raDeg": float(target.ra_deg),
        "decDeg": float(target.dec_deg),
        "raText": coord.ra.to_string(unit=u.hour, sep=":", precision=2, pad=True),
        "decText": coord.dec.to_string(unit=u.deg, sep=":", precision=1, alwayssign=True, pad=True),
        "transientType": target.transient_type,
        "redshift": target.redshift,
        "hostName": target.host_name,
    }


def _source_payload(source, target=None) -> dict[str, Any]:
    detail = source.label
    if source.magnitude is not None:
        detail += f"\nMagnitude {source.magnitude:.3f} {source.magnitude_band}".rstrip()
    if getattr(source, "parallax_mas", None) is not None:
        detail += f"\nParallax {source.parallax_mas:.3f} mas"
    if getattr(source, "pmra_mas_per_year", None) is not None and getattr(source, "pmdec_mas_per_year", None) is not None:
        detail += f"\nPM RA {source.pmra_mas_per_year:.3f} mas/yr, Dec {source.pmdec_mas_per_year:.3f} mas/yr"
    if target is not None:
        import astropy.units as u
        from astropy.coordinates import SkyCoord

        t = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
        s = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
        sep = t.separation(s).arcsec
        pa = t.position_angle(s).deg
        detail += f"\nOffset {sep:.2f}\" at PA {pa:.2f} deg E of N"
    return {
        "id": source.label,
        "label": source.label,
        "catalog": source.catalog,
        "raDeg": float(source.ra_deg),
        "decDeg": float(source.dec_deg),
        "magnitude": source.magnitude,
        "magnitudeBand": source.magnitude_band,
        "sourceID": source.source_id,
        "detail": detail,
    }


def _source_payloads_with_markers(sources: list[Any], target, image, ax, figure_width: float, figure_height: float) -> list[dict[str, Any]]:
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    from findingchart_guiplotter.renderer import world_to_scalar_pixel

    payloads = []
    for source in sources:
        payload = _source_payload(source, target)
        try:
            x_data, y_data = world_to_scalar_pixel(image, SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg))
            x_display, y_display = ax.transData.transform((x_data, y_data))
            if 0 <= x_display <= figure_width and 0 <= y_display <= figure_height:
                payload["markerX"] = float(x_display / figure_width)
                payload["markerY"] = float(1.0 - (y_display / figure_height))
        except Exception:
            pass
        payloads.append(payload)
    return payloads


def _save_chart_with_marker_payload(output_path: Path, image, target, settings, catalog_sources: list[Any], dpi: int) -> tuple[list[dict[str, Any]], int, int]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from findingchart_guiplotter.renderer import apply_project_style, draw_chart

    apply_project_style()
    fig = Figure(figsize=(7, 7), dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, projection=image.wcs)
    draw_chart(ax, image, target, settings)
    fig.subplots_adjust(left=0.12, right=0.96, bottom=0.14, top=0.90)
    fig.canvas.draw()
    width, height = fig.canvas.get_width_height()
    payloads = _source_payloads_with_markers(catalog_sources, target, image, ax, float(width), float(height))
    fig.savefig(output_path, dpi=dpi)
    return payloads, int(width), int(height)


def _metadata() -> dict[str, Any]:
    from findingchart_guiplotter.image_fetchers import SURVEY_BANDS, available_surveys
    from findingchart_guiplotter.observatories import OBSERVATORIES

    return {
        "ok": True,
        "action": "metadata",
        "surveys": available_surveys(),
        "bands": SURVEY_BANDS,
        "observatories": list(OBSERVATORIES.keys()),
    }


def _load_target(payload: dict[str, Any]) -> dict[str, Any]:
    target = _parse_target(payload)
    return {"ok": True, "action": "loadTarget", "target": _target_payload(target), "message": f"Loaded target {target.label}"}


def _image_request(payload: dict[str, Any]):
    from findingchart_guiplotter.image_fetchers import available_bands
    from findingchart_guiplotter.models import ImageRequest

    survey = str(payload.get("survey") or "Pan-STARRS")
    mode = str(payload.get("mode") or "Single band")
    bands = available_bands(survey, mode)
    requested_band = str(payload.get("band") or (bands[0] if bands else ""))
    band = requested_band if requested_band in bands else (bands[0] if bands else requested_band)
    return ImageRequest(
        survey=survey,
        mode=mode,
        band=band,
        size_arcmin=float(payload.get("sizeArcmin", 3.0)),
        pixel_scale_arcsec=float(payload.get("pixelScaleArcsec", 0.262)),
    )


def _load_image(payload: dict[str, Any], repo_dir: Path) -> dict[str, Any]:
    from findingchart_guiplotter.image_fetchers import fetch_image
    from findingchart_guiplotter.renderer import pixel_scale_arcsec

    target = _parse_target(payload)
    request = _image_request(payload)
    image = fetch_image(target, request)
    cache_path = _state_dir(repo_dir) / f"{_safe_name(target.label)}_{_safe_name(image.survey)}_{_safe_name(image.band)}.pkl"
    with cache_path.open("wb") as handle:
        pickle.dump({"target": target, "request": request, "image": image}, handle)
    return {
        "ok": True,
        "action": "loadImage",
        "target": _target_payload(target),
        "imageCachePath": str(cache_path.resolve()),
        "survey": image.survey,
        "band": image.band,
        "mode": image.mode,
        "sourceURL": image.source_url,
        "pixelScaleArcsec": pixel_scale_arcsec(image),
        "message": f"Loaded {image.survey} {image.band}",
    }


def _load_image_cache(payload: dict[str, Any]) -> dict[str, Any]:
    cache = str(payload.get("imageCachePath") or "").strip()
    if not cache:
        raise RuntimeError("Load an archive image before rendering.")
    with Path(cache).open("rb") as handle:
        return pickle.load(handle)


def _load_catalog_cache(payload: dict[str, Any]) -> list[Any]:
    cache = str(payload.get("catalogCachePath") or "").strip()
    if not cache:
        return []
    with Path(cache).open("rb") as handle:
        return pickle.load(handle)


def _settings(payload: dict[str, Any], target, catalog_sources: list[Any]):
    from findingchart_guiplotter.models import ChartSettings
    from findingchart_guiplotter.observatories import OBSERVATORIES, parallactic_angle_deg

    import astropy.units as u
    from astropy.coordinates import SkyCoord
    from astropy.time import Time

    observation_time = None
    raw_time = str(payload.get("observationTimeISO") or "").strip()
    if raw_time:
        observation_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))

    slit_pa = float(payload.get("slitPaDeg", 0.0))
    if payload.get("useParallacticPA", False) and observation_time is not None:
        observatory = OBSERVATORIES.get(str(payload.get("observatoryName") or "La Palma"))
        if observatory is not None:
            coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
            slit_pa = float(parallactic_angle_deg(coord, observatory, Time(observation_time)))

    selected = str(payload.get("selectedCatalogSourceID") or "")
    return ChartSettings(
        slit_width_arcsec=float(payload.get("slitWidthArcsec", 2.0)),
        slit_length_arcsec=float(payload.get("slitLengthArcsec", 20.0)),
        slit_pa_deg=slit_pa,
        slit_pa_mode="Parallactic Angle" if payload.get("useParallacticPA", False) else "Fixed sky PA",
        psf_brightness=float(payload.get("psfBrightness", 5.0)),
        psf_fwhm_arcsec=float(payload.get("psfFwhmArcsec", 1.0)),
        show_injected_source=bool(payload.get("showInjectedSource", True)),
        show_crosshair=bool(payload.get("showCrosshair", True)),
        show_slit=bool(payload.get("showSlit", False)),
        show_compass=bool(payload.get("showCompass", True)),
        observation_time=observation_time,
        observatory_name=str(payload.get("observatoryName") or "La Palma"),
        catalog_sources=catalog_sources,
        selected_catalog_source_label=selected,
        auto_contrast=bool(payload.get("autoContrast", True)),
        vmin=float(payload["vmin"]) if payload.get("vmin") not in (None, "") else None,
        vmax=float(payload["vmax"]) if payload.get("vmax") not in (None, "") else None,
    )


def _render(payload: dict[str, Any], repo_dir: Path, output_dir: Path | None, export_format: str = "png", dpi: int = 180) -> dict[str, Any]:
    from findingchart_guiplotter.renderer import pixel_scale_arcsec

    cached = _load_image_cache(payload)
    target = cached["target"]
    image = cached["image"]
    catalog_sources = _load_catalog_cache(payload)
    settings = _settings(payload, target, catalog_sources)

    destination = output_dir or _state_dir(repo_dir)
    destination.mkdir(parents=True, exist_ok=True)
    suffix = export_format.lower().lstrip(".")
    output_path = destination / f"{_safe_name(target.label)}_finding_chart.{suffix}"
    sources, image_width, image_height = _save_chart_with_marker_payload(output_path, image, target, settings, catalog_sources, dpi=dpi)

    selected_id = str(payload.get("selectedCatalogSourceID") or "")
    selected_detail = next((source["detail"] for source in sources if source["id"] == selected_id), "")
    return {
        "ok": True,
        "action": "render",
        "target": _target_payload(target),
        "imagePath": str(output_path.resolve()),
        "imageCachePath": payload.get("imageCachePath"),
        "imageWidth": image_width,
        "imageHeight": image_height,
        "catalogCachePath": payload.get("catalogCachePath"),
        "catalogSources": sources,
        "selectedCatalogDetail": selected_detail,
        "survey": image.survey,
        "band": image.band,
        "mode": image.mode,
        "sourceURL": image.source_url,
        "pixelScaleArcsec": pixel_scale_arcsec(image),
        "catalogCount": len(catalog_sources),
        "slitPaDeg": settings.slit_pa_deg,
        "message": f"Rendered {image.survey} {image.band} chart for {target.label}",
    }


def _query_catalog(payload: dict[str, Any], repo_dir: Path) -> dict[str, Any]:
    from findingchart_guiplotter.catalog import query_catalog_sources

    cached = _load_image_cache(payload)
    target = cached["target"]
    request = cached["request"]
    max_mag = payload.get("catalogMaxMagnitude")
    sources = query_catalog_sources(
        target,
        request.size_arcmin / 2.0,
        str(payload.get("catalogName") or "Gaia DR3"),
        200,
        float(max_mag) if max_mag not in (None, "") else None,
    )
    cache_path = _state_dir(repo_dir) / f"{_safe_name(target.label)}_{_safe_name(str(payload.get('catalogName') or 'catalog'))}_catalog.pkl"
    with cache_path.open("wb") as handle:
        pickle.dump(sources, handle)
    return {
        "ok": True,
        "action": "queryCatalog",
        "target": _target_payload(target),
        "imageCachePath": payload.get("imageCachePath"),
        "catalogCachePath": str(cache_path.resolve()),
        "catalogSources": [_source_payload(source, target) for source in sources],
        "catalogCount": len(sources),
        "message": f"Loaded {len(sources)} catalog sources",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    try:
        repo_dir = Path(args.repo_dir)
        _configure_runtime_cache(repo_dir)
        _load_repo(repo_dir)
        payload = json.loads(sys.stdin.read() or "{}")
        action = str(payload.get("action") or "render")
        output_dir = Path(args.output_dir) if args.output_dir else None
        with contextlib.redirect_stdout(sys.stderr):
            if action == "metadata":
                result = _metadata()
            elif action == "loadTarget":
                result = _load_target(payload)
            elif action == "loadImage":
                result = _load_image(payload, repo_dir)
            elif action == "queryCatalog":
                result = _query_catalog(payload, repo_dir)
            elif action == "exportPDF":
                result = _render(payload, repo_dir, output_dir, export_format="pdf", dpi=2000)
                result["message"] = f"Saved PDF at {result['imagePath']}"
            elif action == "exportJPG":
                result = _render(payload, repo_dir, output_dir, export_format="jpg", dpi=300)
                result["message"] = f"Saved JPG at {result['imagePath']}"
            else:
                result = _render(payload, repo_dir, output_dir)
        print(json.dumps(result), flush=True)
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc()}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
