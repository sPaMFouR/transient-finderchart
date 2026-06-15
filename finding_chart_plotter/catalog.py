from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

import requests

from .models import Target

GAIA_TAP_SYNC_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_VIZIER_TSV_URL = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
REQUEST_HEADERS = {"User-Agent": "transient-finderchart/0.1"}


@dataclass
class CatalogSource:
    ra_deg: float
    dec_deg: float
    label: str
    magnitude: float | None = None
    magnitude_band: str = ""
    catalog: str = "Gaia DR3"
    source_id: str = ""
    parallax_mas: float | None = None
    pmra_mas_per_year: float | None = None
    pmdec_mas_per_year: float | None = None


def query_gaia_dr3(target: Target, radius_arcmin: float, limit: int = 200, max_magnitude: float | None = None) -> list[CatalogSource]:
    try:
        return query_gaia_dr3_tap(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)
    except requests.RequestException:
        return query_gaia_dr3_vizier(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)


def query_gaia_dr3_tap(target: Target, radius_arcmin: float, limit: int = 200, max_magnitude: float | None = None) -> list[CatalogSource]:
    radius_deg = radius_arcmin / 60.0
    magnitude_filter = ""
    if max_magnitude is not None:
        magnitude_filter = f"AND phot_g_mean_mag <= {float(max_magnitude):.3f}"
    adql = f"""
    SELECT TOP {int(limit)}
        source_id, ra, dec, phot_g_mean_mag, parallax, pmra, pmdec
    FROM gaiadr3.gaia_source
    WHERE 1 = CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {target.ra_deg:.9f}, {target.dec_deg:.9f}, {radius_deg:.9f})
    )
    {magnitude_filter}
    ORDER BY phot_g_mean_mag ASC
    """
    response = requests.post(
        GAIA_TAP_SYNC_URL,
        data={
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "QUERY": adql,
        },
        timeout=60,
        headers=REQUEST_HEADERS,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text.replace("\n", " ")[:500])
    return parse_gaia_tap_csv(response.text)


def query_gaia_dr3_vizier(target: Target, radius_arcmin: float, limit: int = 200, max_magnitude: float | None = None) -> list[CatalogSource]:
    params = {
        "-source": "I/355/gaiadr3",
        "-c": f"{target.ra_deg:.9f} {target.dec_deg:.9f}",
        "-c.r": f"{float(radius_arcmin):.6f}",
        "-c.u": "arcmin",
        "-out": "Source,RA_ICRS,DE_ICRS,Gmag,Plx,pmRA,pmDE",
        "-out.max": str(max(int(limit) * 5, int(limit))),
        "-sort": "Gmag",
    }
    response = requests.get(GAIA_VIZIER_TSV_URL, params=params, timeout=60, headers=REQUEST_HEADERS)
    if response.status_code >= 400:
        raise RuntimeError(response.text.replace("\n", " ")[:500])
    sources = parse_gaia_vizier_tsv(response.text)
    if max_magnitude is not None:
        sources = [source for source in sources if source.magnitude is not None and source.magnitude <= float(max_magnitude)]
    sources.sort(key=lambda source: source.magnitude if source.magnitude is not None else float("inf"))
    return sources[:limit]


def parse_gaia_tap_csv(text: str) -> list[CatalogSource]:
    sources: list[CatalogSource] = []
    for row in csv.DictReader(StringIO(text)):
        mag_text = (row.get("phot_g_mean_mag") or "").strip()
        mag = float(mag_text) if mag_text else None
        label = f"Gaia {row['source_id']}"
        sources.append(
            CatalogSource(
                ra_deg=float(row["ra"]),
                dec_deg=float(row["dec"]),
                label=label,
                magnitude=mag,
                magnitude_band="G",
                catalog="Gaia DR3",
                source_id=row["source_id"],
                parallax_mas=parse_optional_float(row.get("parallax")),
                pmra_mas_per_year=parse_optional_float(row.get("pmra")),
                pmdec_mas_per_year=parse_optional_float(row.get("pmdec")),
            )
        )
    return sources


def parse_gaia_vizier_tsv(text: str) -> list[CatalogSource]:
    data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(data_lines) < 3:
        return []
    rows = [line for line in data_lines if not line.startswith("-") and not line.startswith(" ")]
    if not rows:
        return []
    reader = csv.DictReader(StringIO("\n".join(rows)), delimiter="\t")
    sources: list[CatalogSource] = []
    for row in reader:
        source_id = (row.get("Source") or "").strip()
        ra_text = (row.get("RA_ICRS") or "").strip()
        dec_text = (row.get("DE_ICRS") or "").strip()
        if not source_id or not ra_text or not dec_text:
            continue
        mag = parse_optional_float(row.get("Gmag"))
        sources.append(
            CatalogSource(
                ra_deg=float(ra_text),
                dec_deg=float(dec_text),
                label=f"Gaia {source_id}",
                magnitude=mag,
                magnitude_band="G" if mag is not None else "",
                catalog="Gaia DR3",
                source_id=source_id,
                parallax_mas=parse_optional_float(row.get("Plx")),
                pmra_mas_per_year=parse_optional_float(row.get("pmRA")),
                pmdec_mas_per_year=parse_optional_float(row.get("pmDE")),
            )
        )
    return sources


def query_panstarrs_dr2(target: Target, radius_arcmin: float, limit: int = 200, max_magnitude: float | None = None) -> list[CatalogSource]:
    radius_deg = radius_arcmin / 60.0
    max_r_mag = 40.0 if max_magnitude is None else float(max_magnitude)
    params = {
        "ra": f"{target.ra_deg:.9f}",
        "dec": f"{target.dec_deg:.9f}",
        "radius": f"{radius_deg:.9f}",
        "nDetections.gte": "2",
        "rMeanPSFMag.gt": "0",
        "rMeanPSFMag.lt": f"{max_r_mag:.3f}",
        "pagesize": str(max(int(limit) * 5, int(limit))),
        "sort_by": "rMeanPSFMag",
        "columns": "[objID,raMean,decMean,gMeanPSFMag,rMeanPSFMag,iMeanPSFMag,zMeanPSFMag,yMeanPSFMag]",
    }
    response = requests.get(
        "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv",
        params=params,
        timeout=60,
        headers=REQUEST_HEADERS,
    )
    if response.status_code >= 400:
        params.pop("columns", None)
        response = requests.get(
            "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv",
            params=params,
            timeout=60,
            headers=REQUEST_HEADERS,
        )
    if response.status_code >= 400:
        raise RuntimeError(response.text.replace("\n", " ")[:500])
    sources = parse_panstarrs_dr2_csv(response.text)
    sources.sort(key=lambda source: source.magnitude if source.magnitude is not None else float("inf"))
    return sources[:limit]


def parse_panstarrs_dr2_csv(text: str) -> list[CatalogSource]:
    sources: list[CatalogSource] = []
    for row in csv.DictReader(StringIO(text)):
        ra_text = _first_present(row, "raMean", "ra")
        dec_text = _first_present(row, "decMean", "dec")
        if not ra_text or not dec_text:
            continue
        mag, band = _best_ps1_magnitude(row)
        obj_id = _first_present(row, "objID", "objid", "id") or ""
        label = f"PS1 {obj_id}" if obj_id else "PS1 source"
        sources.append(
            CatalogSource(
                ra_deg=float(ra_text),
                dec_deg=float(dec_text),
                label=label,
                magnitude=mag,
                magnitude_band=band if mag is not None else "",
                catalog="Pan-STARRS DR2",
                source_id=obj_id,
            )
        )
    return sources


def query_catalog_sources(
    target: Target,
    radius_arcmin: float,
    catalog: str,
    limit: int = 200,
    max_magnitude: float | None = None,
) -> list[CatalogSource]:
    if catalog == "Gaia DR3":
        return query_gaia_dr3(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)
    if catalog == "Pan-STARRS DR2":
        return query_panstarrs_dr2(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)
    if catalog == "Gaia DR3 + Pan-STARRS DR2":
        gaia_sources = query_gaia_dr3(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)
        ps1_sources = query_panstarrs_dr2(target, radius_arcmin, limit=limit, max_magnitude=max_magnitude)
        return (gaia_sources + ps1_sources)[: 2 * limit]
    raise ValueError(f"Unsupported catalog: {catalog}")


def parse_optional_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _best_ps1_magnitude(row: dict[str, str]) -> tuple[float | None, str]:
    for band, column in (
        ("r", "rMeanPSFMag"),
        ("i", "iMeanPSFMag"),
        ("g", "gMeanPSFMag"),
        ("z", "zMeanPSFMag"),
        ("y", "yMeanPSFMag"),
    ):
        value = _first_present(row, column)
        if value:
            try:
                magnitude = float(value)
                if -90.0 < magnitude < 90.0:
                    return magnitude, band
            except ValueError:
                pass
    return None, "mag"


def _first_present(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""
