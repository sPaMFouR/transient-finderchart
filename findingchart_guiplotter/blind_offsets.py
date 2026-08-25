from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

from .catalog import CatalogSource
from .models import Target


@dataclass(frozen=True)
class BlindOffsetDetails:
    delta_ra_arcsec: float
    delta_dec_arcsec: float
    separation_arcsec: float
    pa_east_of_north_deg: float


def blind_offset_from_target_to_source(source: CatalogSource, target: Target) -> BlindOffsetDetails:
    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    source_coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
    delta_ra, delta_dec = target_coord.spherical_offsets_to(source_coord)
    delta_ra_arcsec = float(delta_ra.to_value(u.arcsec))
    delta_dec_arcsec = float(delta_dec.to_value(u.arcsec))
    pa_east_of_north_deg = float((u.Quantity(np.degrees(np.arctan2(delta_ra_arcsec, delta_dec_arcsec)), u.deg).to_value(u.deg) + 360.0) % 360.0)
    separation_arcsec = float(source_coord.separation(target_coord).arcsec)
    return BlindOffsetDetails(
        delta_ra_arcsec=delta_ra_arcsec,
        delta_dec_arcsec=delta_dec_arcsec,
        separation_arcsec=separation_arcsec,
        pa_east_of_north_deg=pa_east_of_north_deg,
    )
