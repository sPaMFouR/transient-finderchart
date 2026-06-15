from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, tan

import astropy.units as u
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time


@dataclass(frozen=True)
class Observatory:
    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float

    @property
    def location(self) -> EarthLocation:
        return EarthLocation.from_geodetic(
            lon=self.longitude_deg * u.deg,
            lat=self.latitude_deg * u.deg,
            height=self.elevation_m * u.m,
        )


OBSERVATORIES: dict[str, Observatory] = {
    "La Palma": Observatory("La Palma", 28.7606, -17.8792, 2326.0),
    "Mauna Kea, Hawaii": Observatory("Mauna Kea, Hawaii", 19.8206, -155.4681, 4205.0),
    "Paranal, Chile": Observatory("Paranal, Chile", -24.6272, -70.4042, 2635.0),
    "Palomar Observatory": Observatory("Palomar Observatory", 33.3563, -116.8648, 1712.0),
    "La Silla, Chile": Observatory("La Silla, Chile", -29.2567, -70.7346, 2400.0),
    "HCT, IAO, India": Observatory("HCT, IAO, India", 32.7794, 78.9642, 4500.0),
    "Kanata, Hiroshima": Observatory("Kanata, Hiroshima", 34.3756, 132.7767, 511.0),
}


def parallactic_angle_deg(target: SkyCoord, observatory: Observatory, when: Time) -> float:
    """Return parallactic angle in degrees east of north."""
    lst = when.sidereal_time("apparent", longitude=observatory.location.lon)
    hour_angle = (lst - target.ra).wrap_at(180 * u.deg).rad
    dec = target.dec.rad
    lat = radians(observatory.latitude_deg)
    q = atan2(sin(hour_angle), tan(lat) * cos(dec) - sin(dec) * cos(hour_angle))
    return q * 180.0 / 3.141592653589793
