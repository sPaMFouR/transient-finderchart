from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.wcs import WCS


@dataclass
class Target:
    display_name: str
    ra_deg: float
    dec_deg: float
    tns_name: str = ""
    prefix: str = ""
    objid: str = ""
    transient_type: str = ""
    redshift: str = ""
    host_name: str = ""
    aliases: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.display_name or self.tns_name or f"{self.ra_deg:.6f}, {self.dec_deg:.6f}"


@dataclass
class ImageRequest:
    survey: str
    mode: str
    band: str
    size_arcmin: float
    pixel_scale_arcsec: float

    @property
    def size_pixels(self) -> int:
        pixels = round((self.size_arcmin * 60.0) / self.pixel_scale_arcsec)
        return max(32, min(int(pixels), 3000))


@dataclass
class ImageData:
    data: np.ndarray
    wcs: WCS
    survey: str
    band: str
    mode: str
    source_url: str = ""
    local_path: Path | None = None


@dataclass
class ChartSettings:
    slit_width_arcsec: float = 2.0
    slit_length_arcsec: float = 10.0
    slit_pa_deg: float = 0.0
    psf_magnitude: float = 18.0
    psf_fwhm_arcsec: float = 1.0
    show_injected_source: bool = True
    show_crosshair: bool = True
    show_slit: bool = True
    show_compass: bool = True
    observation_time: datetime | None = None
    observatory_name: str = "La Palma"
    catalog_sources: list[object] = field(default_factory=list)
    auto_contrast: bool = True
    vmin: float | None = None
    vmax: float | None = None
