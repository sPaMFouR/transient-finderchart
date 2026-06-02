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
            )
        )
    return sources
