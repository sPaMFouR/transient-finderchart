from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

import requests

from .models import Target


@dataclass
class CatalogSource:
    ra_deg: float
    dec_deg: float
    label: str
    magnitude: float | None = None
    catalog: str = "Gaia DR3"
    source_id: str = ""


def query_gaia_dr3(target: Target, radius_arcmin: float, limit: int = 200) -> list[CatalogSource]:
    radius_deg = radius_arcmin / 60.0
    adql = f"""
    SELECT TOP {int(limit)}
        source_id, ra, dec, phot_g_mean_mag
    FROM gaiadr3.gaia_source
    WHERE 1 = CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {target.ra_deg:.9f}, {target.dec_deg:.9f}, {radius_deg:.9f})
    )
    ORDER BY phot_g_mean_mag ASC
    """
    response = requests.post(
        "https://gea.esac.esa.int/tap-server/tap/sync",
        data={
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "QUERY": adql,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text.replace("\n", " ")[:500])
    sources: list[CatalogSource] = []
    for row in csv.DictReader(StringIO(response.text)):
        mag_text = (row.get("phot_g_mean_mag") or "").strip()
        mag = float(mag_text) if mag_text else None
        label = f"Gaia {row['source_id']}"
        if mag is not None:
            label += f"  G={mag:.2f}"
        sources.append(
            CatalogSource(
                ra_deg=float(row["ra"]),
                dec_deg=float(row["dec"]),
                label=label,
                magnitude=mag,
                catalog="Gaia DR3",
                source_id=row["source_id"],
            )
        )
    return sources


def query_panstarrs_dr2(target: Target, radius_arcmin: float, limit: int = 200) -> list[CatalogSource]:
    radius_deg = radius_arcmin / 60.0
    params = {
        "ra": f"{target.ra_deg:.9f}",
        "dec": f"{target.dec_deg:.9f}",
        "radius": f"{radius_deg:.9f}",
        "nDetections.gte": "2",
        "rMeanPSFMag.gt": "0",
        "rMeanPSFMag.lt": "40",
        "pagesize": str(max(int(limit) * 5, int(limit))),
        "sort_by": "rMeanPSFMag",
        "columns": "[objID,raMean,decMean,gMeanPSFMag,rMeanPSFMag,iMeanPSFMag,zMeanPSFMag,yMeanPSFMag]",
    }
    response = requests.get(
        "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv",
        params=params,
        timeout=60,
    )
    if response.status_code >= 400:
        params.pop("columns", None)
        response = requests.get(
            "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv",
            params=params,
            timeout=60,
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
        if mag is not None:
            label += f"  {band}={mag:.2f}"
        sources.append(
            CatalogSource(
                ra_deg=float(ra_text),
                dec_deg=float(dec_text),
                label=label,
                magnitude=mag,
                catalog="Pan-STARRS DR2",
                source_id=obj_id,
            )
        )
    return sources


def query_catalog_sources(target: Target, radius_arcmin: float, catalog: str, limit: int = 200) -> list[CatalogSource]:
    if catalog == "Gaia DR3":
        return query_gaia_dr3(target, radius_arcmin, limit=limit)
    if catalog == "Pan-STARRS DR2":
        return query_panstarrs_dr2(target, radius_arcmin, limit=limit)
    if catalog == "Gaia DR3 + Pan-STARRS DR2":
        gaia_sources = query_gaia_dr3(target, radius_arcmin, limit=limit)
        ps1_sources = query_panstarrs_dr2(target, radius_arcmin, limit=limit)
        return (gaia_sources + ps1_sources)[: 2 * limit]
    raise ValueError(f"Unsupported catalog: {catalog}")


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
