#!/usr/bin/env python
"""
01_download_images.py
=====================
Step 1 of the FrankenBLAST pipeline for 1987A-like SN host galaxies.

Downloads multi-survey FITS image cutouts for each host galaxy in the
1987A-like sample.  Uses host coordinates directly from the master sample
CSV — no PROST host-association step needed.

22 survey bands (FrankenBLAST / Nugent+2025 + DES_i added):
  GALEX:     FUV, NUV
  PanSTARRS: g, r, i, z, y
  DES/LS:    g, r, i, z   ← downloaded from LS DR10 brickfiles (NERSC)
  SDSS:      u, g, r, i, z
  2MASS:     J, H, K
  WISE:      W1, W2, W3, W4

Output
------
  cutouts/<sn_name>/<survey>/<filter>.fits   — per-band FITS cutouts
  logs/download_manifest.csv                 — per-object × band status log

Usage
-----
  # Test on one object:
  python 01_download_images.py --sn 2018hna

  # Full sample:
  python 01_download_images.py --all

  # Resume (skip already-downloaded files):
  python 01_download_images.py --all --skip-done

  # Wider field of view (default 120 arcsec):
  python 01_download_images.py --all --fov 180

Prerequisites
-------------
  conda activate frankenblast
  (FrankenBLAST environment with astroquery, photutils, pyvo, requests)

Notes
-----
  - GALEX FUV/NUV may not cover all targets (AIS is ~26% of sky).
    Missing data is flagged `no_coverage` in the manifest, NOT an error.
  - PanSTARRS covers dec > -30 deg only.
  - "DES" bands are downloaded from Legacy Survey DR10 (ls-dr10 layer):
      South (dec < ~+25°): DECam/DECaLS data (same as DES footprint)
      North (dec > ~+30°): BASS (g, r) + MzLS (z) — same LS viewer endpoint,
        no code change needed.  Targets ~+25°–+84° get BASS/MzLS automatically.
      Gap (~+25° to +30°): mixed; LS server returns best available data.
      Completely outside LS: HTTP 400 → flagged no_coverage.
  - 2MASS covers full sky; WISE covers full sky.
  - Download rate is limited to ~1 request/sec per survey to avoid blocks.
  - All FITS files are validated after download (WCS present, data not all NaN).
"""

import argparse
import csv
import logging
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.io import fits
import astropy.units as u_unit
from astropy.units import Quantity
from astropy.wcs import WCS

# tqdm progress bar — graceful fallback if not installed
try:
    from tqdm import tqdm as _tqdm
    _TQDM_AVAILABLE = True
except ImportError:
    _TQDM_AVAILABLE = False

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Progress-bar helpers
# ---------------------------------------------------------------------------

def _stream_to_file_with_progress(response, fits_path: Path, band: str) -> int:
    """
    Write a streaming requests.Response to disk with a tqdm progress bar.

    Displays:
        Downloading <url>
        |████████████| 2.4M/2.4M [00:03<00:00, 780kB/s]

    Falls back to a silent write if tqdm is not installed.
    Returns the number of bytes written.
    """
    # Content-Length is not always present (chunked transfer)
    total = int(response.headers.get("Content-Length", 0)) or None

    print(f"Downloading {response.url}")

    chunk_size = 65536
    bytes_written = 0
    fits_path.parent.mkdir(parents=True, exist_ok=True)

    if _TQDM_AVAILABLE:
        with _tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=band,
            leave=False,
            bar_format="|{bar:40}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        ) as pbar:
            with open(fits_path, "wb") as fh:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    fh.write(chunk)
                    pbar.update(len(chunk))
                    bytes_written += len(chunk)
    else:
        with open(fits_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=chunk_size):
                fh.write(chunk)
                bytes_written += len(chunk)

    return bytes_written


def _log_download_size(fits_path: Path, band: str, dt: float, logger: logging.Logger):
    """Log file size and elapsed time after any download completes."""
    size_bytes = fits_path.stat().st_size if fits_path.exists() else 0
    if size_bytes >= 1_048_576:
        size_str = f"{size_bytes / 1_048_576:.1f} MB"
    elif size_bytes >= 1024:
        size_str = f"{size_bytes / 1024:.0f} KB"
    else:
        size_str = f"{size_bytes} B"
    logger.info(f"  {band}: {size_str} in {dt:.1f}s → {fits_path.name}")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_DIR  = SCRIPT_DIR.parent
SAMPLE_CSV   = PROJECT_DIR / "01_sample_revision" / "revised_1987A_like_sample.csv"
CUTOUT_DIR   = SCRIPT_DIR / "cutouts"
LOG_DIR      = SCRIPT_DIR / "logs"
MANIFEST_CSV = LOG_DIR / "download_manifest.csv"

# Upstream FrankenBLAST repo (symlinked at frankenblast-host/)
UPSTREAM_DIR = SCRIPT_DIR / "frankenblast-host"
SURVEY_YAML  = UPSTREAM_DIR / "data" / "survey_frankenblast_metadata.yml"

# Add upstream to path so we can import its modules
sys.path.insert(0, str(UPSTREAM_DIR))

# ---------------------------------------------------------------------------
# Import upstream FrankenBLAST modules
# ---------------------------------------------------------------------------
try:
    import settings as fb_settings
    from classes import Filter, Survey, Transient, Host
    from get_host_images import (
        cutout,
        survey_list,
        download_and_save_cutouts,
        download_function_dict,
    )
except ImportError as e:
    print(f"\nERROR: Cannot import FrankenBLAST modules from {UPSTREAM_DIR}.")
    print(f"  {e}")
    print("\nMake sure:")
    print("  1. The frankenblast-host symlink exists in this folder.")
    print("  2. You are in the 'frankenblast' conda environment.")
    print("     conda activate frankenblast")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Monkey-patch broken upstream IRSA download functions
# (must be done AFTER the import block above)
#
#   WISE   WISE_cutout()    → KeyError: 't_exptime'
#          The IRSA SIA 2.0 CSV column schema changed; that column is gone.
#          _patched_WISE_cutout keeps the URL extraction logic and makes the
#          exptime access safe with a try/except + fallback to 1.0.
#
#   2MASS  TWOMASS_cutout() → silent None return ("download failed — unknown")
#          The legacy nph-im_sia CGI no longer returns VOTABLE/CDATA blocks;
#          the regex finds nothing.  _patched_TWOMASS_cutout tries IRSA SIA 2.0
#          first, then falls back to the old CGI.
# ---------------------------------------------------------------------------
# (function definitions appear below — forward reference is fine in Python
#  because download_function_dict is patched inside main() after all defs load)

# ---------------------------------------------------------------------------
# Default field-of-view (arcsec).
# When --fov-mode catalog is used, each object's FoV is set to 2× its
# HyperLEDA D25 isophotal diameter (minimum DEFAULT_FOV_ARCSEC).
# ---------------------------------------------------------------------------
DEFAULT_FOV_ARCSEC     = 600.0    # 10 arcmin — fallback / manual override
MIN_FOV_ARCSEC         = 600.0    # never go below 10 arcmin even for small D25
FOV_D25_MULTIPLIER     = 2.0      # cutout = FOV_D25_MULTIPLIER × D25

# ---------------------------------------------------------------------------
# SDSS configuration
# ---------------------------------------------------------------------------
SDSS_BANDS   = ["u", "g", "r", "i", "z"]
SDSS_SURVEY  = "SDSS"
SDSS_PIXSCALE_ARCSEC = 0.396   # SDSS native pixel scale

# ---------------------------------------------------------------------------
# Quality flag definitions
# ---------------------------------------------------------------------------
FLAG_OK             = "ok"             # downloaded and validated
FLAG_NO_COVERAGE    = "no_coverage"    # survey does not cover this position
FLAG_DOWNLOAD_FAIL  = "download_fail"  # download attempt failed
FLAG_FITS_INVALID   = "fits_invalid"   # downloaded file failed FITS checks
FLAG_SKIPPED        = "skipped"        # file already exists and --skip-done set
FLAG_ALL_NAN        = "all_nan"        # FITS data is entirely NaN
FLAG_NO_WCS         = "no_wcs"         # FITS header has no valid WCS

# Bands that have limited sky coverage — missing data expected for many objects
PARTIAL_COVERAGE_BANDS = {
    "GALEX_FUV",
    "GALEX_NUV",
    "DES_g",
    "DES_r",
    "DES_i",
    "DES_z",
    "SDSS_u",    # not all sky, especially at high |b|
    "SDSS_g",
    "SDSS_r",
    "SDSS_i",
    "SDSS_z",
}

# ---------------------------------------------------------------------------
# Session-level logging (Tee stdout → terminal + timestamped log file)
# ---------------------------------------------------------------------------

class _TeeStream:
    """Write every print() / logging StreamHandler line to both the terminal
    and an open log file, so that the full terminal session is preserved."""
    def __init__(self, file_obj):
        self._file   = file_obj
        self._stdout = sys.__stdout__
    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)
    def flush(self):
        self._stdout.flush()
        self._file.flush()
    def fileno(self):        # allows subprocess / os.dup2 if needed
        return self._stdout.fileno()
    def isatty(self):
        return False


def setup_session_log(log_dir: Path, script_name: str = "run") -> Path:
    """
    Redirect stdout to a Tee that writes simultaneously to the terminal and a
    timestamped session log file inside log_dir.

    All print() calls and logging StreamHandler messages are captured.
    The per-object log files (frankenblast_<sn>.log) are unaffected.

    Returns the path to the session log file.
    """
    import datetime
    log_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_log = log_dir / f"run_{script_name}_{ts}.log"
    fh  = open(session_log, "w", buffering=1, encoding="utf-8")
    sys.stdout = _TeeStream(fh)
    return session_log


# ---------------------------------------------------------------------------
# Per-object loggers
# ---------------------------------------------------------------------------

def setup_logger(sn_name: str) -> logging.Logger:
    """Create a per-object logger writing to logs/frankenblast_<sn>.log."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"frankenblast_{sn_name}.log"
    logger   = logging.getLogger(f"fb.{sn_name}")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh  = logging.FileHandler(log_file, mode="w")
        fh.setLevel(logging.DEBUG)
        ch  = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Sample loading
# ---------------------------------------------------------------------------

def load_sample(csv_path: Path) -> pd.DataFrame:
    """
    Load the revised 1987A-like sample.  Keeps objects with valid host
    coordinates and positive redshift.
    """
    df = pd.read_csv(csv_path)
    n_raw = len(df)

    missing_coords = df[["host_ra", "host_dec"]].isna().any(axis=1)
    missing_z      = df["redshift"].isna() | (df["redshift"] <= 0)
    bad = missing_coords | missing_z

    if bad.any():
        print(f"  WARNING: {bad.sum()} objects dropped (missing host coords or z):")
        for name in df.loc[bad, "sn_name"]:
            print(f"    {name}")

    df = df[~bad].reset_index(drop=True)
    print(f"  Loaded {len(df)} / {n_raw} objects with valid host coords.")
    return df


# ---------------------------------------------------------------------------
# FITS validation
# ---------------------------------------------------------------------------

def validate_fits(fits_path: Path, logger: logging.Logger) -> str:
    """
    Open the FITS file and run basic quality checks.

    Returns one of FLAG_OK, FLAG_FITS_INVALID, FLAG_ALL_NAN, FLAG_NO_WCS.
    """
    try:
        with fits.open(fits_path) as hdul:
            data   = hdul[0].data
            header = hdul[0].header
    except Exception as exc:
        logger.warning(f"    FITS open failed: {exc}")
        return FLAG_FITS_INVALID

    # Check data exists
    if data is None or data.size == 0:
        logger.warning("    FITS data is empty")
        return FLAG_FITS_INVALID

    # Check not all NaN
    arr = np.asarray(data, dtype=float)
    if not np.any(np.isfinite(arr)):
        logger.warning("    FITS data is all NaN/Inf")
        return FLAG_ALL_NAN

    # Check WCS is present and has RA/Dec axes
    try:
        wcs = WCS(header)
        if wcs.naxis < 2:
            raise ValueError("fewer than 2 WCS axes")
        # Try a round-trip to confirm WCS is usable
        cx, cy = arr.shape[-1] / 2.0, arr.shape[-2] / 2.0
        sky = wcs.pixel_to_world(cx, cy)
    except Exception as exc:
        logger.warning(f"    WCS invalid: {exc}")
        return FLAG_NO_WCS

    return FLAG_OK


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    """
    Load existing manifest into a dict keyed by (sn_name, band).
    Returns {} if manifest does not exist.
    """
    if not MANIFEST_CSV.exists():
        return {}
    rows = {}
    with open(MANIFEST_CSV, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows[(row["sn_name"], row["band"])] = row
    return rows


def save_manifest_row(row: dict):
    """
    Append one row to the manifest CSV.  Creates the file with header if needed.
    """
    LOG_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "sn_name", "band", "status", "fits_path",
        "file_size_kb", "download_time_s", "timestamp",
    ]
    write_header = not MANIFEST_CSV.exists()
    with open(MANIFEST_CSV, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fieldnames})


def update_manifest_row(manifest: dict, sn_name: str, band: str,
                         status: str, fits_path: Path = None,
                         file_size_kb: float = 0.0, dt: float = 0.0):
    """Update in-memory manifest and flush the row to disk."""
    import datetime
    row = {
        "sn_name":        sn_name,
        "band":           band,
        "status":         status,
        "fits_path":      str(fits_path) if fits_path else "",
        "file_size_kb":   f"{file_size_kb:.1f}",
        "download_time_s": f"{dt:.1f}",
        "timestamp":      datetime.datetime.now().isoformat(timespec="seconds"),
    }
    manifest[(sn_name, band)] = row
    save_manifest_row(row)


# ---------------------------------------------------------------------------
# Per-band download
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Legacy Survey DR10 unified download
# ---------------------------------------------------------------------------
#
# Architecture note
# -----------------
# The NAT/NATICA SIA at astroarchive.noirlab.edu returns *individual DECam
# exposures* (single nights, per-chip, sky-subtracted).  For host-galaxy SED
# fitting we need the *co-added* science images, which live in the LS DR10
# brickfiles at NERSC — not in the NOIRLab archive.  The NOAO/nat-nb repo was
# archived in July 2024 and its API is no longer the recommended path.
#
# Approach used here
# ------------------
# 1. Compute the LS DR10 brickname for the target position.
# 2. Determine region: north (BASS+MzLS, Dec > +32.375°) or south (DECam).
# 3. Download the full .fits.fz brick from the NERSC public portal.
#    Bricks are cached under  cutouts/ls_brick_cache/  so the same brick
#    is not downloaded twice even for different SNe in the same brick.
# 4. Cut out the FoV using astropy.nddata.Cutout2D and save as the pipeline
#    FITS file.
#
# Supported bands: g, r, i, z  (DES_g, DES_r, DES_i, DES_z)
#
# Brick URLs
#   south: https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/dr10/south/
#            coadd/{brickpre}/{brickname}/legacysurvey-{brickname}-image-{band}.fits.fz
#   north: https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/dr10/north/
#            coadd/{brickpre}/{brickname}/legacysurvey-{brickname}-image-{band}.fits.fz
#
# Fallback
# --------
# If the brick download fails (NERSC outage, 404, network timeout), the
# function falls back to the LS viewer cutout API which produces an identical
# but smaller file.  The fallback is logged at WARNING level.
# ---------------------------------------------------------------------------

# NERSC LS DR10 base URL
_LS_NERSC_BASE = "https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/dr10"
# LS viewer cutout API (fallback)
_LS_VIEWER_URL = "https://www.legacysurvey.org/viewer/fits-cutout"
_LS_PIXSCALE   = 0.262    # arcsec/pixel (native LS scale, both north+south)
# North/south boundary (brick-centre Dec that puts us in the north region)
_LS_NORTH_DEC_THRESHOLD = 32.375   # degrees

# Map pipeline band names to LS single-letter filter codes
_LS_BAND_MAP = {"DES_g": "g", "DES_r": "r", "DES_i": "i", "DES_z": "z"}


def _ls_brickname(ra: float, dec: float) -> str:
    """
    Compute the LS DR10 brick name for a sky position.

    LS bricks are 0.25° × 0.25° tiles.  The brick containing (ra, dec) has its
    centre at:
        brick_ra  = (floor(ra  / 0.25) + 0.5) × 0.25   [degrees]
        brick_dec = (floor(|dec| / 0.25) + 0.5) × 0.25 × sign(dec)

    Brick name format: {ra_int:04d}{sign}{dec_int:03d}
        ra_int  = round(brick_ra  × 10)
        dec_int = round(|brick_dec| × 10)
        sign    = 'p' if brick_dec >= 0 else 'm'

    Examples
    --------
    >>> _ls_brickname(186.55, 58.31)  → '1866p584'   (2018hna, north)
    >>> _ls_brickname(150.0,  2.5)    → '1501p025'   (south, DECam)
    >>> _ls_brickname(30.0,  -35.0)   → '0301m348'   (south, DECam)
    """
    import math
    brick_ra  = (math.floor(ra   / 0.25) + 0.5) * 0.25
    brick_dec = (math.floor(abs(dec) / 0.25) + 0.5) * 0.25 * (1 if dec >= 0 else -1)
    ra_int    = int(round(brick_ra  * 10))
    dec_int   = int(round(abs(brick_dec) * 10))
    sign      = "p" if brick_dec >= 0 else "m"
    return f"{ra_int:04d}{sign}{dec_int:03d}"


def _ls_region(dec: float) -> str:
    """Return 'north' (BASS+MzLS) or 'south' (DECam) for a given declination."""
    return "north" if dec >= _LS_NORTH_DEC_THRESHOLD else "south"


def _ls_brick_url(brickname: str, region: str, ls_band: str) -> str:
    """Construct the NERSC portal URL for one LS DR10 co-add brick."""
    brickpre = brickname[:3]
    return (
        f"{_LS_NERSC_BASE}/{region}/coadd/{brickpre}/{brickname}/"
        f"legacysurvey-{brickname}-image-{ls_band}.fits.fz"
    )


def _download_ls_brick_file(
    url: str,
    brick_path: Path,
    band: str,
    logger: logging.Logger,
) -> bool:
    """
    Download an LS DR10 brickfile (.fits.fz) to brick_path.

    Returns True on success, False on any failure.
    Shows a tqdm progress bar.  The file is streamed directly to disk.
    """
    import requests

    MAX_RETRIES = 3
    RETRY_WAITS = [5, 15, 30]

    print(f"Downloading {url}")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=300, stream=True)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                logger.warning(
                    f"  {band}: brick fetch attempt {attempt}/{MAX_RETRIES} "
                    f"failed ({type(exc).__name__}: {exc}) — retry in {RETRY_WAITS[attempt-1]}s"
                )
                time.sleep(RETRY_WAITS[attempt - 1])
                continue
            logger.warning(f"  {band}: brick fetch failed after {MAX_RETRIES} attempts: {exc}")
            return False

        if resp.status_code == 404:
            logger.info(f"  {band}: brick not found at NERSC (HTTP 404) — {url}")
            return False
        if resp.status_code == 400:
            logger.info(f"  {band}: no LS DR10 coverage — HTTP 400")
            return False
        if resp.status_code >= 500:
            if attempt < MAX_RETRIES:
                logger.warning(
                    f"  {band}: NERSC HTTP {resp.status_code} on attempt "
                    f"{attempt}/{MAX_RETRIES} — retry in {RETRY_WAITS[attempt-1]}s"
                )
                time.sleep(RETRY_WAITS[attempt - 1])
                continue
            logger.warning(f"  {band}: NERSC HTTP {resp.status_code} — giving up")
            return False
        if resp.status_code != 200:
            logger.warning(f"  {band}: NERSC HTTP {resp.status_code} — not retrying")
            return False

        # 200 OK — stream to disk with progress bar
        brick_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _stream_to_file_with_progress(resp, brick_path, band)
        except Exception as exc:
            logger.warning(f"  {band}: write error during brick download: {exc}")
            brick_path.unlink(missing_ok=True)
            return False
        return True

    return False


def _cutout_from_brick(
    brick_path: Path,
    coord: SkyCoord,
    fov_arcsec: float,
    out_path: Path,
    band: str,
    logger: logging.Logger,
) -> bool:
    """
    Cut out a FoV-sized sub-image centred on coord from an LS DR10 brick.

    The full brick is opened, a Cutout2D is extracted, and saved to out_path
    as a plain (uncompressed) FITS file with a valid WCS.  Returns True on
    success.
    """
    from astropy.nddata import Cutout2D
    from astropy.wcs import WCS as _WCS

    size_px = max(int(fov_arcsec / _LS_PIXSCALE) + 1, 64)

    try:
        with fits.open(str(brick_path)) as hdul:
            # LS .fits.fz uses RICE tile compression; image is in extension 1
            sci_idx = 1 if len(hdul) > 1 and hdul[1].data is not None else 0
            hdr  = hdul[sci_idx].header
            data = hdul[sci_idx].data

            if data is None or data.size == 0:
                logger.warning(f"  {band}: brick {brick_path.name} has no data array")
                return False

            wcs = _WCS(hdr)

            # Check target falls inside the brick
            try:
                px, py = wcs.world_to_pixel(coord)
                ny, nx = data.shape
                if not (0 <= px < nx and 0 <= py < ny):
                    logger.warning(
                        f"  {band}: target position is outside brick {brick_path.name} "
                        f"(px={px:.0f}, py={py:.0f}, brick={nx}×{ny})"
                    )
                    return False
            except Exception as exc:
                logger.warning(f"  {band}: WCS check failed: {exc}")
                return False

            cutout = Cutout2D(
                data, coord, (size_px, size_px),
                wcs=wcs, mode="partial", fill_value=np.nan,
            )

        # Save cutout as a plain FITS
        out_hdr = cutout.wcs.to_header()
        out_hdr["BUNIT"]   = hdr.get("BUNIT", "nanomaggies")
        out_hdr["MAGZERO"] = hdr.get("MAGZERO", 22.5)
        out_hdr["FILTER"]  = hdr.get("FILTER", band)
        out_hdr["INSTRUME"] = hdr.get("INSTRUME", "")
        out_hdr["SURVEY"]  = "Legacy Survey DR10"
        out_hdr["BRICKNAM"] = brick_path.stem.split("-")[1] if "-" in brick_path.stem else ""
        out_hdr["LS_REGIO"] = "north" if "north" in str(brick_path) else "south"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        fits.writeto(str(out_path), cutout.data, header=out_hdr, overwrite=True)
        return True

    except Exception as exc:
        logger.warning(f"  {band}: Cutout2D failed for brick {brick_path.name}: {exc}")
        return False


def _download_legacysurvey_band(
    coord: SkyCoord,
    band: str,
    filter_obj,
    fov_arcsec: float,
    fits_path: Path,
    manifest: dict,
    sn_name: str,
    logger: logging.Logger,
    t0: float,
) -> str:
    """
    Download a Legacy Survey DR10 co-add cutout for one band.

    Bands supported: DES_g, DES_r, DES_i, DES_z

    Strategy
    --------
    Primary:  Download the LS DR10 brickfile (.fits.fz) from the NERSC public
              portal and cut out the requested FoV using astropy Cutout2D.
              Bricks are cached under cutouts/ls_brick_cache/ so the same
              ~50 MB brick is not re-downloaded for multiple objects that fall
              within the same brick.

    Fallback: If the brick download fails (NERSC outage, 404, network issue),
              fall back to the LS viewer cutout API which serves from the same
              data but as a pre-cropped image.  Fallback is logged at WARNING.

    Region selection (automatic — no separate code paths needed)
    -----------------------------------------------------------
    Dec >= +32.375°  →  north brick  (BASS g/r + MzLS z/i)
    Dec <  +32.375°  →  south brick  (DECam g/r/i/z)
    """
    import requests

    ls_band = _LS_BAND_MAP.get(band)
    if ls_band is None:
        logger.warning(f"  {band}: not a recognised LS band — skipping")
        update_manifest_row(manifest, sn_name, band, FLAG_DOWNLOAD_FAIL,
                            dt=time.time() - t0)
        return FLAG_DOWNLOAD_FAIL

    ra  = coord.ra.deg
    dec = coord.dec.deg
    region    = _ls_region(dec)
    brickname = _ls_brickname(ra, dec)
    brick_url = _ls_brick_url(brickname, region, ls_band)

    logger.info(
        f"  {band}: brick={brickname}  region={region}  "
        f"filter={ls_band}  source=LS-DR10-{region.upper()}"
    )

    # ------------------------------------------------------------------
    # Brick cache: skip download if we already have this brick
    # ------------------------------------------------------------------
    brick_cache_dir = CUTOUT_DIR / "ls_brick_cache" / region
    brick_path      = brick_cache_dir / f"legacysurvey-{brickname}-image-{ls_band}.fits.fz"

    if brick_path.exists() and brick_path.stat().st_size > 10_000:
        logger.info(f"  {band}: brick already cached → {brick_path.name}")
    else:
        ok = _download_ls_brick_file(brick_url, brick_path, band, logger)
        if not ok:
            # ------------------------------------------------------------------
            # Fallback: LS viewer cutout API
            # ------------------------------------------------------------------
            logger.warning(
                f"  {band}: NERSC brick download failed — falling back to LS viewer cutout API"
            )
            size_px = max(int(fov_arcsec / _LS_PIXSCALE) + 1, 64)
            params  = {
                "ra": f"{ra:.6f}", "dec": f"{dec:.6f}",
                "width": size_px, "height": size_px,
                "pixscale": _LS_PIXSCALE,
                "bands": ls_band, "layer": "ls-dr10",
            }
            try:
                resp = requests.get(_LS_VIEWER_URL, params=params, timeout=120, stream=True)
            except Exception as exc:
                logger.warning(f"  {band}: viewer fallback also failed: {exc}")
                update_manifest_row(manifest, sn_name, band, FLAG_DOWNLOAD_FAIL,
                                    dt=time.time() - t0)
                return FLAG_DOWNLOAD_FAIL

            if resp.status_code == 400:
                update_manifest_row(manifest, sn_name, band, FLAG_NO_COVERAGE,
                                    dt=time.time() - t0)
                return FLAG_NO_COVERAGE
            if resp.status_code != 200:
                logger.warning(f"  {band}: viewer fallback HTTP {resp.status_code}")
                update_manifest_row(manifest, sn_name, band, FLAG_DOWNLOAD_FAIL,
                                    dt=time.time() - t0)
                return FLAG_DOWNLOAD_FAIL

            try:
                _stream_to_file_with_progress(resp, fits_path, band)
            except Exception as exc:
                logger.warning(f"  {band}: viewer fallback write error: {exc}")
                update_manifest_row(manifest, sn_name, band, FLAG_FITS_INVALID,
                                    dt=time.time() - t0)
                return FLAG_FITS_INVALID

            dt = time.time() - t0
            flag = validate_fits(fits_path, logger)
            if flag != FLAG_OK:
                update_manifest_row(manifest, sn_name, band, flag,
                                    fits_path=fits_path, dt=dt)
                return flag
            size_kb = fits_path.stat().st_size / 1024
            _log_download_size(fits_path, band, dt, logger)
            logger.info(f"  {band}: OK [LS viewer fallback]")
            update_manifest_row(manifest, sn_name, band, FLAG_OK,
                                fits_path=fits_path, file_size_kb=size_kb, dt=dt)
            return FLAG_OK

    # ------------------------------------------------------------------
    # Primary path: cut out from downloaded brick
    # ------------------------------------------------------------------
    ok = _cutout_from_brick(brick_path, coord, fov_arcsec, fits_path, band, logger)
    dt = time.time() - t0

    if not ok:
        # Brick exists but position is outside or cutout failed — may be a gap
        logger.info(
            f"  {band}: position not covered by brick {brickname} "
            f"(outside footprint or gap)"
        )
        update_manifest_row(manifest, sn_name, band, FLAG_NO_COVERAGE, dt=dt)
        return FLAG_NO_COVERAGE

    flag = validate_fits(fits_path, logger)
    if flag != FLAG_OK:
        logger.warning(f"  {band}: FITS validation failed after cutout ({flag})")
        update_manifest_row(manifest, sn_name, band, flag, fits_path=fits_path, dt=dt)
        return flag

    size_kb = fits_path.stat().st_size / 1024
    _log_download_size(fits_path, band, dt, logger)
    logger.info(
        f"  {band}: OK [LS DR10 {region.upper()} brick={brickname}]"
    )
    update_manifest_row(manifest, sn_name, band, FLAG_OK,
                        fits_path=fits_path, file_size_kb=size_kb, dt=dt)
    return FLAG_OK


def _patched_WISE_cutout(position, image_size=None, filter=None):
    """
    Fixed replacement for the upstream WISE_cutout().

    Root cause: WISE_cutout() calls data["t_exptime"][0] after parsing the
    IRSA SIA 2.0 CSV response.  The IRSA API changed its column schema and
    't_exptime' is no longer present → KeyError on every call.

    Fix: the image URL extraction logic (scan CSV fields for the first HTTPS
    URL) still works fine.  We make the exptime access safe by trying several
    plausible column names and falling back to 1.0 if none are found.
    exptime is written only to the FITS header EXPTIME keyword; it does not
    affect the flux measurements downstream.

    Monkey-patched into download_function_dict["WISE"] at import time so the
    normal retry/fallback flow in download_one_band() still applies.
    """
    import requests
    import astropy.table as at
    from astropy.io import fits as _afits
    from astropy.nddata import Cutout2D
    from astropy.wcs import WCS

    band_to_wavelength = {
        "W1": "3.4e-6", "W2": "4.6e-6",
        "W3": "1.2e-5", "W4": "2.2e-5",
    }
    sia_url = (
        f"https://irsa.ipac.caltech.edu/SIA?COLLECTION=wise_allwise"
        f"&POS=circle+{position.ra.deg}+{position.dec.deg}+0.002777"
        f"&RESPONSEFORMAT=CSV&BAND={band_to_wavelength[filter]}&FORMAT=image/fits"
    )
    r = requests.get(sia_url, timeout=30)

    # Extract image URL — scan all comma-separated tokens for first https URL
    img_url = None
    for tok in r.text.split(","):
        tok = tok.strip()
        if tok.startswith("https"):
            img_url = tok
            break

    # Strip embedded JSON objects that break astropy CSV parsing
    line_out = ""
    for line in r.text.split("\n"):
        try:
            i1 = line.index("{")
            i2 = line.index("}")
            line_out += line[:i1 + 1] + line[i2:] + "\n"
        except ValueError:
            line_out += line + "\n"

    # Safely extract exposure time — try current and historical column names
    exptime = 1.0
    try:
        data = at.Table.read(line_out, format="ascii.csv")
        for col in ("t_exptime", "exptime", "EXPTIME", "t_exp"):
            if col in data.colnames and len(data) > 0:
                exptime = float(data[col][0])
                break
    except Exception:
        pass   # exptime stays 1.0 — not critical for photometry

    if img_url is None:
        return None

    fits_image = _afits.open(img_url, cache=None)
    wcs = WCS(fits_image[0].header)
    co = Cutout2D(fits_image[0].data, position, image_size, wcs=wcs)
    fits_image[0].data = co.data
    fits_image[0].header.update(co.wcs.to_header())
    fits_image[0].header["EXPTIME"] = exptime
    return fits_image


def _patched_TWOMASS_cutout(position, image_size=None, filter=None):
    """
    Fixed replacement for the upstream TWOMASS_cutout().

    Root cause: TWOMASS_cutout() queries the legacy nph-im_sia CGI endpoint
    and parses the response by splitting on '<TD><![CDATA[', then applies a
    regex to find FITS URLs.  The VOTABLE/CDATA format was retired; the regex
    matches nothing → function returns None silently (no exception raised) →
    log shows "download failed — unknown" (err is None).

    Fix (two-tier):
      1. Primary  — IRSA SIA 2.0 (COLLECTION=twomass_allsky): returns a CSV
                    table with access_url column containing the image URLs.
                    Scan for the URL containing the filter letter (j/h/k).
      2. Fallback — old nph-im_sia CGI, in case the SIA 2.0 endpoint changes.

    Monkey-patched into download_function_dict["2MASS"] at import time.
    """
    import re
    import requests
    import astropy.table as at
    from astropy.io import fits as _afits
    from astropy.nddata import Cutout2D
    from astropy.wcs import WCS

    fl = filter.lower()   # 'j', 'h', or 'k'
    img_url = None

    # ---- Primary: IRSA SIA 2.0 ----------------------------------------
    try:
        sia_url = (
            f"https://irsa.ipac.caltech.edu/SIA?COLLECTION=twomass_allsky"
            f"&POS=circle+{position.ra.deg}+{position.dec.deg}+0.01"
            f"&RESPONSEFORMAT=CSV&FORMAT=image/fits"
        )
        r = requests.get(sia_url, timeout=30)
        if r.status_code == 200 and r.text.strip():
            # Strip embedded JSON then parse table
            line_out = ""
            for line in r.text.split("\n"):
                try:
                    i1 = line.index("{")
                    i2 = line.index("}")
                    line_out += line[:i1 + 1] + line[i2:] + "\n"
                except ValueError:
                    line_out += line + "\n"
            try:
                data = at.Table.read(line_out, format="ascii.csv")
                # Identify URL column(s): any column whose first non-blank value starts https
                url_cols = [c for c in data.colnames
                            if any(str(v).strip().startswith("https")
                                   for v in data[c])]
                for row in data:
                    for col in url_cols:
                        val = str(row[col]).strip()
                        if (val.startswith("https") and "fits" in val.lower()
                                and fl in val.lower()):
                            img_url = val
                            break
                    if img_url:
                        break
            except Exception:
                pass
            # Naive scan if table parsing yielded nothing
            if img_url is None:
                for tok in r.text.split(","):
                    tok = tok.strip()
                    if (tok.startswith("https") and "fits" in tok.lower()
                            and fl in tok.lower()):
                        img_url = tok
                        break
    except Exception:
        pass

    # ---- Fallback: legacy nph-im_sia CGI --------------------------------
    if img_url is None:
        try:
            cgi = (
                f"https://irsa.ipac.caltech.edu/cgi-bin/2MASS/IM/nph-im_sia"
                f"?POS={position.ra.deg},{position.dec.deg}&SIZE=0.01"
            )
            r2 = requests.get(cgi, timeout=30)
            for line in r2.content.decode("utf-8").split("<TD><![CDATA["):
                candidate = line.split("]]>")[0]
                if re.match(rf"https://irsa.*{fl}i.*fits", candidate):
                    img_url = candidate
                    break
        except Exception:
            pass

    if img_url is None:
        return None

    fits_image = _afits.open(img_url, cache=None)
    wcs = WCS(fits_image[0].header)
    if not position.contained_by(wcs):
        return None
    co = Cutout2D(fits_image[0].data, position, image_size, wcs=wcs)
    fits_image[0].data = co.data
    fits_image[0].header.update(co.wcs.to_header())
    return fits_image


def download_one_band(
    transient: "Transient",
    filter_obj: "Filter",
    fov_arcsec: float,
    skip_done: bool,
    manifest: dict,
    logger: logging.Logger,
) -> str:
    """
    Download one band for one transient.

    Returns the quality flag (FLAG_OK, FLAG_SKIPPED, FLAG_DOWNLOAD_FAIL, etc.)
    """
    band      = filter_obj.name                             # e.g. "PanSTARRS_r"
    sn_name   = transient.name
    survey_nm = filter_obj.survey if filter_obj.survey else band.split("_")[0]

    # Output path: cutouts/<sn_name>/<survey_name>/<filter_name>.fits
    save_dir   = CUTOUT_DIR / sn_name / survey_nm
    save_dir.mkdir(parents=True, exist_ok=True)
    fits_path  = save_dir / f"{band}.fits"

    # Skip if already done
    if skip_done and fits_path.exists():
        prev_flag = manifest.get((sn_name, band), {}).get("status", FLAG_SKIPPED)
        if prev_flag == FLAG_OK:
            logger.debug(f"  {band}: already downloaded ({fits_path.name}) — skipping")
            return FLAG_SKIPPED
        # If previously failed, retry
        logger.info(f"  {band}: previous status was '{prev_flag}', retrying")

    logger.info(f"  {band}: downloading (survey={survey_nm}) ...")
    t0 = time.time()

    # ---- DES bands: use Legacy Survey FITS cutout API directly ----
    # (progress bar is shown inside _download_legacysurvey_band via tqdm)
    # The upstream DES_cutout() queries noirlab.edu/sia/ls_dr9 which returns
    # 502 errors unreliably. We override with the stable LS viewer cutout API.
    #
    # The FrankenBLAST "DES" bands are actually Legacy Survey (LS DR10) images:
    #   South (dec < ~+25°) : DECam (DECaLS / DES)  — g, r, z
    #   North (dec > ~+30°) : BASS (g, r) + MzLS (z) via the same ls-dr10 layer
    #
    # The LS viewer API with layer=ls-dr10 automatically serves BASS+MzLS for
    # ---- DES bands (g, r, i, z): LS DR10 brickfile from NERSC ----
    # Primary: download full brick → Cutout2D.  Fallback: LS viewer cutout API.
    # Region auto-detected: north (BASS+MzLS, Dec > +32.375°) or south (DECam).
    # DES_i is now included — it exists in both north and south DR10 co-adds.
    if survey_nm == "DES":
        flag = _download_legacysurvey_band(
            transient.coordinates, band, filter_obj, fov_arcsec,
            fits_path, manifest, sn_name, logger, t0
        )
        return flag

    # Retry loop: up to MAX_RETRIES attempts with exponential backoff.
    # Handles transient server failures for all surveys.
    # 2MASS uses _patched_TWOMASS_cutout, WISE uses _patched_WISE_cutout —
    # both are monkey-patched into download_function_dict at import time and
    # flow through the normal cutout() → download_function_dict path here.
    # A None hdulist that looks like a "no coverage" response is not retried.
    MAX_RETRIES   = 3
    RETRY_WAITS   = [1, 2, 4]   # seconds between attempts
    hdulist = status = err = None
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            fov_qty = Quantity(fov_arcsec, unit="arcsec")
            hdulist, status, err = cutout(
                transient.coordinates,
                filter_obj,
                fov=fov_qty,
            )
            last_exc = None
            break   # success — exit retry loop

        except Exception as exc:
            last_exc = exc
            err_msg = f"{type(exc).__name__}: {exc}"

            # Detect permanent "no coverage" exceptions by message
            # (some backends raise instead of returning status != 0)
            no_cov_keywords = ("no data", "no image", "not found", "outside",
                               "outside footprint", "404", "no coverage")
            if any(kw in str(exc).lower() for kw in no_cov_keywords):
                logger.info(
                    f"  {band}: no coverage (exception on attempt {attempt}): {err_msg}"
                )
                update_manifest_row(manifest, sn_name, band, FLAG_NO_COVERAGE,
                                    dt=time.time() - t0)
                return FLAG_NO_COVERAGE

            if attempt < MAX_RETRIES:
                wait = RETRY_WAITS[attempt - 1]
                logger.warning(
                    f"  {band}: cutout() attempt {attempt}/{MAX_RETRIES} failed "
                    f"({err_msg}) — retrying in {wait}s"
                )
                time.sleep(wait)
            else:
                logger.warning(
                    f"  {band}: cutout() failed after {MAX_RETRIES} attempts "
                    f"— last error: {err_msg}"
                )

    if last_exc is not None:
        update_manifest_row(manifest, sn_name, band, FLAG_DOWNLOAD_FAIL, dt=time.time()-t0)
        return FLAG_DOWNLOAD_FAIL

    dt = time.time() - t0

    # Handle no coverage / download failure
    if hdulist is None or status != 0:
        if band in PARTIAL_COVERAGE_BANDS:
            logger.info(f"  {band}: no coverage at this position (expected for {band})")
            update_manifest_row(manifest, sn_name, band, FLAG_NO_COVERAGE, dt=dt)
            return FLAG_NO_COVERAGE
        else:
            err_str = str(err) if err else "unknown"
            logger.warning(f"  {band}: download failed — {err_str}")
            update_manifest_row(manifest, sn_name, band, FLAG_DOWNLOAD_FAIL, dt=dt)
            return FLAG_DOWNLOAD_FAIL

    # Save FITS to disk
    try:
        hdulist.writeto(str(fits_path), overwrite=True)
        hdulist.close()
    except Exception as exc:
        logger.warning(f"  {band}: could not write FITS — {exc}")
        update_manifest_row(manifest, sn_name, band, FLAG_FITS_INVALID, dt=dt)
        return FLAG_FITS_INVALID

    # Validate the saved file
    flag = validate_fits(fits_path, logger)
    if flag != FLAG_OK:
        # Keep the file for inspection but record the bad flag
        logger.warning(f"  {band}: FITS validation failed ({flag}), file kept for inspection")
        update_manifest_row(manifest, sn_name, band, flag, fits_path=fits_path, dt=dt)
        return flag

    # Success
    size_kb = fits_path.stat().st_size / 1024.0
    _log_download_size(fits_path, band, dt, logger)
    logger.info(f"  {band}: OK")
    update_manifest_row(manifest, sn_name, band, FLAG_OK,
                         fits_path=fits_path, file_size_kb=size_kb, dt=dt)
    return FLAG_OK


# ---------------------------------------------------------------------------
# HyperLEDA D25 query — used to set per-object field-of-view
# ---------------------------------------------------------------------------

def _query_hyperleda_sql(coord: SkyCoord, search_arcmin: float = 5.0):
    """
    Query the live HyperLEDA SQL API at leda.univ-lyon1.fr for galaxy
    parameters near `coord`.

    HyperLEDA column conventions
    -----------------------------
      al2000  RA  in decimal hours  (divide by 15 → degrees)
      de2000  Dec in decimal degrees
      logd25  log10(D25 / 0.1 arcmin)  → D25 = 10^logd25 × 6 arcsec
      logr25  log10(a/b)
      pa      position angle (deg, N through E)

    Returns a dict with the closest matching row plus key '_sep_arcsec',
    or None if no galaxy found within search_arcmin.

    Two-strategy parser: tries CSV first (format=C), then looks for a
    pipe-delimited <pre> block in the HTML response (the fallback format
    the server sometimes returns).
    """
    import urllib.request, urllib.parse, re, io, csv as _csv
    from astropy.coordinates import SkyCoord as _SC

    ra_h    = coord.ra.deg / 15.0
    dec_d   = coord.dec.deg
    cos_dec = max(np.cos(np.deg2rad(abs(dec_d))), 0.017)   # never < 1°
    dr_h    = (search_arcmin / 60.0) / cos_dec / 15.0
    dd      = search_arcmin / 60.0

    sql = (
        "SELECT pgc,objname,al2000,de2000,logd25,logr25,pa FROM meandata "
        f"WHERE al2000 BETWEEN {ra_h - dr_h:.6f} AND {ra_h + dr_h:.6f} "
        f"AND de2000 BETWEEN {dec_d - dd:.6f} AND {dec_d + dd:.6f}"
    )
    # NOTE: the old /leda/sql.html endpoint was retired; current endpoint is /fullsql.html (HTTPS only)
    url = ("https://leda.univ-lyon1.fr/fullsql.html?"
           + urllib.parse.urlencode({"sql": sql, "format": "C"}))
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FrankenBLAST/1.0 (avinash.singh@astro.su.se)"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", errors="replace")

    # ---- Strategy 1: CSV (format=C honoured by server) ----
    rows = []
    try:
        clean = [l for l in raw.splitlines()
                 if l.strip() and not l.startswith("#") and "<" not in l]
        if len(clean) >= 2 and "," in clean[0]:
            reader = _csv.DictReader(io.StringIO("\n".join(clean)))
            rows = list(reader)
    except Exception:
        pass

    # ---- Strategy 2: pipe-delimited <pre> block in HTML response ----
    if not rows:
        try:
            pre_m = re.search(r'<pre[^>]*>(.*?)</pre>', raw,
                              re.DOTALL | re.IGNORECASE)
            if pre_m:
                pre_text = re.sub(r'<[^>]+>', '', pre_m.group(1))
                lines = [l.strip() for l in pre_text.splitlines()
                         if l.strip() and not l.startswith("#")]
                if len(lines) >= 2 and "|" in lines[0]:
                    header = [h.strip() for h in lines[0].split("|")]
                    for line in lines[1:]:
                        cols = [c.strip() for c in line.split("|")]
                        if len(cols) >= len(header):
                            rows.append(dict(zip(header, cols)))
        except Exception:
            pass

    if not rows:
        return None

    best, best_sep = None, np.inf
    for row in rows:
        try:
            al = row.get("al2000", "").strip()
            de = row.get("de2000", "").strip()
            if not al or not de:
                continue
            ra_row_deg = float(al) * 15.0
            dec_row    = float(de)
        except (ValueError, TypeError):
            continue
        if not (np.isfinite(ra_row_deg) and np.isfinite(dec_row)):
            continue
        sep = coord.separation(
            _SC(ra=ra_row_deg, dec=dec_row, unit="deg")
        ).arcsec
        if sep < best_sep:
            best_sep = sep
            best = row

    if best is None or best_sep > search_arcmin * 60.0:
        return None

    best["_sep_arcsec"] = best_sep
    return best


def query_d25_arcsec(coord: SkyCoord, sn_name: str) -> float:
    """
    Query HyperLEDA for the host galaxy D25 diameter.

    Primary:  live HyperLEDA SQL API at leda.univ-lyon1.fr
    Fallback: VizieR VII/237 (Paturel et al. 2003 mirror — incomplete)

    Returns D25 in arcsec, or None if not found / no valid logd25.
    D25 = 10^logd25 × 6 arcsec  (logd25 in 0.1-arcmin units).
    """
    # ------------------------------------------------------------------
    # 1. Live HyperLEDA SQL API
    # ------------------------------------------------------------------
    try:
        row = _query_hyperleda_sql(coord, search_arcmin=5.0)
        if row is not None:
            logd25_str = row.get("logd25", "").strip()
            if logd25_str:
                logd25 = float(logd25_str)
                if np.isfinite(logd25):
                    return float(10.0 ** logd25 * 6.0)
            else:
                logging.getLogger("fb").debug(
                    f"[D25] HyperLEDA row found for {sn_name} but logd25 is empty/null: {row}"
                )
        else:
            logging.getLogger("fb").debug(
                f"[D25] HyperLEDA SQL returned no rows within 5' of {sn_name}"
            )
    except Exception as _e:
        logging.getLogger("fb").warning(
            f"[D25] HyperLEDA SQL query failed for {sn_name}: {type(_e).__name__}: {_e}"
        )

    # ------------------------------------------------------------------
    # 2. VizieR VII/237 fallback (Paturel et al. 2003 — may be incomplete)
    # ------------------------------------------------------------------
    try:
        from astroquery.vizier import Vizier
        import numpy.ma as nma
    except ImportError:
        return None

    result = None
    for radius_arcmin in (0.5, 2.0, 5.0):
        try:
            v = Vizier(columns=["RAJ2000", "DEJ2000", "logd25"], row_limit=10)
            result = v.query_region(coord, radius=radius_arcmin * u_unit.arcmin,
                                    catalog="VII/237")
            if result and len(result) > 0 and len(result[0]) > 0:
                break
        except Exception as _e:
            logging.getLogger("fb").warning(
                f"[D25] VizieR VII/237 query at {radius_arcmin}' failed for {sn_name}: "
                f"{type(_e).__name__}: {_e}"
            )
            result = None
    if not result:
        return None

    table = result[0]

    def _ra_f(val):
        if nma.is_masked(val): return np.nan
        try: return float(val)
        except Exception:
            try:
                from astropy.coordinates import Angle
                return Angle(str(val).strip(), unit="hourangle").deg
            except Exception: return np.nan

    def _dec_f(val):
        if nma.is_masked(val): return np.nan
        try: return float(val)
        except Exception:
            try:
                from astropy.coordinates import Angle
                return Angle(str(val).strip(), unit="deg").deg
            except Exception: return np.nan

    ras  = np.array([_ra_f(r["RAJ2000"])  for r in table])
    decs = np.array([_dec_f(r["DEJ2000"]) for r in table])
    valid = np.isfinite(ras) & np.isfinite(decs)
    if not valid.any():
        return None

    from astropy.coordinates import SkyCoord as _SC
    cat_c  = _SC(ra=ras[valid], dec=decs[valid], unit="deg")
    sep    = coord.separation(cat_c)
    best   = int(sep.argmin())
    if sep[best].to(u_unit.arcsec).value > 5.0 * 60.0:
        return None   # no match within 5'

    best_row = table[np.where(valid)[0][best]]
    try:
        raw = best_row["logd25"]
        if nma.is_masked(raw): return None
        logd25 = float(raw)
        if not np.isfinite(logd25): return None
        return float(10.0 ** logd25 * 6.0)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SDSS image cutout download
# ---------------------------------------------------------------------------

def download_sdss_band(
    coord: SkyCoord,
    band: str,
    fov_arcsec: float,
    out_path: Path,
    logger: logging.Logger,
) -> str:
    """
    Download a single SDSS DR17 FITS cutout for one band using astroquery.

    Uses astroquery.sdss.SDSS.get_images() which queries the SDSS SkyServer
    and returns the first field image covering the position.

    Returns one of FLAG_OK / FLAG_NO_COVERAGE / FLAG_DOWNLOAD_FAIL / FLAG_FITS_INVALID.
    """
    try:
        from astroquery.sdss import SDSS
    except ImportError:
        logger.warning(f"  SDSS_{band}: astroquery.sdss not available — skipping")
        return FLAG_DOWNLOAD_FAIL

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and out_path.stat().st_size > 0:
        return FLAG_SKIPPED

    try:
        imgs = SDSS.get_images(
            coordinates=coord,
            radius=fov_arcsec / 2.0 * u_unit.arcsec,
            band=band,
            data_release=17,
            timeout=120,
        )
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("no sources", "no images", "404", "no data")):
            logger.info(f"  SDSS_{band}: no coverage at this position")
            return FLAG_NO_COVERAGE
        logger.warning(f"  SDSS_{band}: download error: {exc}")
        return FLAG_DOWNLOAD_FAIL

    if imgs is None or len(imgs) == 0:
        logger.info(f"  SDSS_{band}: no coverage at this position")
        return FLAG_NO_COVERAGE

    # Use the first HDUList returned (closest field)
    hdulist = imgs[0]
    try:
        hdulist.writeto(str(out_path), overwrite=True)
    except Exception as exc:
        logger.warning(f"  SDSS_{band}: write error: {exc}")
        return FLAG_FITS_INVALID

    # Validate
    try:
        with fits.open(out_path) as h:
            data = h[0].data
            if data is None or data.size == 0:
                raise ValueError("empty data")
            if not np.any(np.isfinite(data)):
                out_path.unlink(missing_ok=True)
                return FLAG_ALL_NAN
            wcs_tmp = WCS(h[0].header)
            sky_test = SkyCoord(ra=0.0, dec=0.0, unit="deg")
            wcs_tmp.world_to_pixel(sky_test)
    except Exception as exc:
        logger.warning(f"  SDSS_{band}: FITS validation failed: {exc}")
        out_path.unlink(missing_ok=True)
        return FLAG_FITS_INVALID

    size_kb = out_path.stat().st_size / 1024
    logger.info(f"  SDSS_{band}: OK ({size_kb:.0f} KB) → {out_path.name}")
    return FLAG_OK


# ---------------------------------------------------------------------------
# Host-name resolution
# ---------------------------------------------------------------------------

def resolve_host_name(
    coord: SkyCoord,
    sn_name: str,
    csv_host_name: str = "",
    search_arcmin: float = 5.0,
    logger: logging.Logger = None,
) -> str:
    """
    Return the best available NED-resolvable name for the host galaxy.

    Priority
    --------
    1. ``csv_host_name`` from the sample CSV — used as-is if non-empty.
    2. NED cone search within ``search_arcmin`` arcmin of ``coord``:
       returns the name of the nearest catalogued extragalactic object.
    3. Empty string — caller falls back to coordinate-only mode (no D25 lookup).

    The resolved name is logged at INFO level so it is always visible in the
    session log.
    """
    _log = logger or logging.getLogger("fb")

    # 1. CSV value takes priority
    name = (csv_host_name or "").strip()
    if name:
        _log.info(f"  {sn_name}: host name from CSV → '{name}'")
        return name

    # 2. NED cone search fallback
    _log.info(
        f"  {sn_name}: no host_name in CSV — querying NED within {search_arcmin}' ..."
    )
    try:
        from astroquery.ned import Ned
        import astropy.units as _u
        result = Ned.query_region(coord, radius=search_arcmin * _u.arcmin)
        if result is None or len(result) == 0:
            _log.warning(f"  {sn_name}: NED cone search returned no objects within {search_arcmin}'")
            return ""

        # Filter to extragalactic objects (exclude stars, HII regions, etc.)
        GALAXY_TYPES = {"G", "GCluster", "GGroup", "GPair", "GTrpl", "QSO",
                        "AbsLineSys", "EmLS"}
        gal_mask = [
            str(row["Type"]).strip() in GALAXY_TYPES
            for row in result
        ]
        candidates = result[gal_mask] if any(gal_mask) else result

        # Pick closest by angular separation
        from astropy.coordinates import SkyCoord as _SC
        ned_coords = _SC(
            ra=candidates["RA(deg)"],
            dec=candidates["DEC(deg)"],
            unit="deg",
        )
        seps = coord.separation(ned_coords).arcmin
        best_idx = int(seps.argmin())
        best_name = str(candidates["Object Name"][best_idx]).strip()
        best_sep  = float(seps[best_idx])

        _log.info(
            f"  {sn_name}: NED cone search → '{best_name}' "
            f"({best_sep:.2f}' from host coords)"
        )
        return best_name

    except ImportError:
        _log.warning(
            f"  {sn_name}: astroquery not available — cannot do NED fallback"
        )
        return ""
    except Exception as _e:
        _log.warning(
            f"  {sn_name}: NED cone search failed: {type(_e).__name__}: {_e}"
        )
        return ""


# ---------------------------------------------------------------------------
# Per-object orchestration
# ---------------------------------------------------------------------------

def download_one_object(
    row: pd.Series,
    filter_objects: list,
    fov_arcsec: float,
    skip_done: bool,
    manifest: dict,
    logger: logging.Logger,
) -> dict:
    """
    Download all 17 bands for one host galaxy.

    Uses host_ra / host_dec (not SN coordinates) as the pointing centre.

    Returns a summary dict: {band: flag, ...}
    """
    sn_name  = row["sn_name"]
    redshift = float(row["redshift"])

    # Parse coordinates robustly: accept decimal degrees OR sexagesimal strings
    # (e.g. "12:26:12.08" / "+47:30:04.5" from the sample CSV)
    ra_raw  = str(row["host_ra"]).strip()
    dec_raw = str(row["host_dec"]).strip()
    try:
        # Fast path: plain floats (decimal degrees)
        host_ra  = float(ra_raw)
        host_dec = float(dec_raw)
        coord = SkyCoord(ra=host_ra, dec=host_dec, unit="deg")
    except ValueError:
        # Sexagesimal: RA in hours (H:M:S), Dec in degrees (D:M:S)
        coord = SkyCoord(ra=ra_raw, dec=dec_raw, unit=("hourangle", "deg"))
        host_ra  = coord.ra.deg
        host_dec = coord.dec.deg

    # ---- Resolve host galaxy name (CSV → NED fallback) ----
    coord = SkyCoord(ra=host_ra, dec=host_dec, unit="deg")
    csv_host = str(row.get("host_name", "") or "").strip()
    host_name = resolve_host_name(coord, sn_name, csv_host_name=csv_host, logger=logger)

    # ---- Per-object FoV: use 2×D25 from HyperLEDA if available ----
    d25 = query_d25_arcsec(coord, sn_name)
    if d25 is not None:
        fov_catalog = max(FOV_D25_MULTIPLIER * d25, MIN_FOV_ARCSEC)
        if abs(fov_catalog - fov_arcsec) > 5:
            logger.info(
                f"  Catalog FoV: {fov_catalog:.0f}\" "
                f"(2×D25={d25:.0f}\")  [overrides --fov {fov_arcsec:.0f}\"]"
            )
        fov_used = fov_catalog
    else:
        fov_used = fov_arcsec
        logger.info(f"  FoV: {fov_used:.0f}\" (no HyperLEDA D25 found — using default)")

    host_label = f"  host={host_name}" if host_name else ""
    logger.info(
        f"=== {sn_name} | RA={host_ra:.5f}  Dec={host_dec:.5f}  z={redshift:.4f}"
        f"{host_label} | FoV={fov_used:.0f}\" ==="
    )

    transient = Transient(
        name=sn_name,
        coordinates=coord,
        transient_redshift=redshift,
    )

    band_results = {}
    n_ok = 0

    # ---- All survey bands (includes SDSS now that it's in the YAML) ----
    for filter_obj in filter_objects:
        band   = filter_obj.name
        flag   = download_one_band(
            transient, filter_obj, fov_used, skip_done, manifest, logger
        )
        band_results[band] = flag
        if flag == FLAG_OK:
            n_ok += 1
        time.sleep(0.5)

    n_total = len(filter_objects)
    logger.info(
        f"=== {sn_name}: {n_ok}/{n_total} bands downloaded successfully ==="
    )

    if n_ok == 0:
        logger.error(
            f"  WARNING: No bands downloaded for {sn_name}. "
            "Check network, coordinates, and survey coverage."
        )

    return band_results


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(manifest: dict, sample: pd.DataFrame, filter_names: list):
    """Print a tabular per-object summary after all downloads."""
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)

    counts = {"ok": 0, "skipped": 0, "no_coverage": 0,
              "download_fail": 0, "fits_invalid": 0, "all_nan": 0, "no_wcs": 0}

    for _, row in sample.iterrows():
        sn   = row["sn_name"]
        ok   = sum(1 for b in filter_names
                   if manifest.get((sn, b), {}).get("status") in (FLAG_OK, FLAG_SKIPPED))
        fail = sum(1 for b in filter_names
                   if manifest.get((sn, b), {}).get("status") == FLAG_DOWNLOAD_FAIL)
        nc   = sum(1 for b in filter_names
                   if manifest.get((sn, b), {}).get("status") == FLAG_NO_COVERAGE)
        print(f"  {sn:<20s}  ok/skip={ok:2d}  no_cov={nc:2d}  fail={fail:2d}")

    # Aggregate totals
    for row_data in manifest.values():
        st = row_data.get("status", "")
        if st in counts:
            counts[st] += 1

    print()
    print(f"  Total bands attempted : {len(manifest)}")
    print(f"  OK (fresh download)   : {counts['ok']}")
    print(f"  Skipped (existing)    : {counts['skipped']}")
    print(f"  No coverage           : {counts['no_coverage']}")
    print(f"  Download failed       : {counts['download_fail']}")
    print(f"  FITS invalid          : {counts['fits_invalid'] + counts['all_nan'] + counts['no_wcs']}")
    print(f"\n  Manifest: {MANIFEST_CSV}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Step 1: Download multi-survey FITS cutouts for 1987A-like host galaxies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python 01_download_images.py --sn 2018hna
  python 01_download_images.py --all --skip-done
  python 01_download_images.py --all --fov 300   # 5 arcmin

Output: cutouts/<sn_name>/<survey>/<filter>.fits
        logs/download_manifest.csv
        """,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--sn",  type=str,
                       help="Process a single SN by name (e.g. 2018hna)")
    group.add_argument("--all", action="store_true",
                       help="Process all objects in the sample CSV")

    p.add_argument("--skip-done", action="store_true", default=False,
                   help="Skip bands where a valid FITS file already exists")
    p.add_argument("--fov", type=float, default=DEFAULT_FOV_ARCSEC,
                   help=f"Cutout field of view in arcsec (default: {DEFAULT_FOV_ARCSEC})")
    p.add_argument("--sample-csv", type=str, default=str(SAMPLE_CSV),
                   help=f"Path to master sample CSV (default: {SAMPLE_CSV})")
    p.add_argument("--surveys-yaml", type=str, default=str(SURVEY_YAML),
                   help=f"Path to survey metadata YAML (default: {SURVEY_YAML})")
    p.add_argument("--verbose", "-v", action="store_true", default=False,
                   help="Enable verbose (DEBUG-level) logging to stdout")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # ---- Session log: tee all terminal output to a timestamped file ----
    LOG_DIR.mkdir(exist_ok=True)
    session_log = setup_session_log(LOG_DIR, script_name="01_download_images")

    print("\n" + "=" * 70)
    print("01_download_images.py — FrankenBLAST image download")
    print("=" * 70)
    print(f"  Session log: {session_log}")

    # ---- Load survey filter definitions ----
    survey_yaml_path = Path(args.surveys_yaml)
    if not survey_yaml_path.exists():
        print(f"\nERROR: Survey YAML not found: {survey_yaml_path}")
        print("Expected location: frankenblast-host/data/survey_frankenblast_metadata.yml")
        sys.exit(1)

    Filter._filters = []   # Reset global filter list in case of re-import
    filter_names = survey_list(str(survey_yaml_path))
    filter_objects = Filter.all()

    # Patch broken IRSA download functions with fixed versions defined above
    download_function_dict["WISE"]   = _patched_WISE_cutout
    download_function_dict["2MASS"]  = _patched_TWOMASS_cutout

    print(f"\nLoaded {len(filter_names)} survey bands from {survey_yaml_path.name}:")
    for fn in filter_names:
        print(f"  {fn}")

    # ---- Load sample ----
    sample_path = Path(args.sample_csv)
    if not sample_path.exists():
        print(f"\nERROR: Sample CSV not found: {sample_path}")
        sys.exit(1)

    print(f"\nLoading sample from {sample_path.name} ...")
    sample = load_sample(sample_path)

    # ---- Select targets ----
    if args.sn:
        hits = sample[sample["sn_name"] == args.sn]
        if len(hits) == 0:
            # Try case-insensitive match
            hits = sample[sample["sn_name"].str.lower() == args.sn.lower()]
        if len(hits) == 0:
            print(f"\nERROR: '{args.sn}' not found in sample.")
            print(f"Available names: {list(sample['sn_name'])}")
            sys.exit(1)
        targets = hits
    else:
        targets = sample

    print(f"Processing {len(targets)} object(s), FoV = {args.fov} arcsec\n")

    # ---- Create output directories ----
    CUTOUT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    # ---- Load existing manifest ----
    manifest = load_manifest()
    if manifest:
        n_prev = len(manifest)
        n_ok   = sum(1 for r in manifest.values() if r.get("status") == FLAG_OK)
        print(f"  Found existing manifest: {n_prev} entries, {n_ok} OK.\n")

    # ---- Main download loop ----
    all_results = {}
    for i, (_, row) in enumerate(targets.iterrows(), 1):
        sn = row["sn_name"]
        print(f"\n[{i}/{len(targets)}] {sn}")

        logger = setup_logger(sn)
        if args.verbose:
            for h in logger.handlers:
                if isinstance(h, logging.StreamHandler):
                    h.setLevel(logging.DEBUG)

        try:
            results = download_one_object(
                row,
                filter_objects=filter_objects,
                fov_arcsec=args.fov,
                skip_done=args.skip_done,
                manifest=manifest,
                logger=logger,
            )
            all_results[sn] = results
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.  Manifest saved to:", MANIFEST_CSV)
            sys.exit(0)
        except Exception as exc:
            logger = logging.getLogger(f"fb.{sn}")
            logger.exception(f"Unhandled exception for {sn}: {exc}")
            print(f"  ERROR on {sn}: {exc} (see log for traceback)")

    # ---- Summary ----
    print_summary(manifest, targets, filter_names)

    # ---- Sanity check: count bands with ≥1 good optical image per object ----
    optical_bands = ["PanSTARRS_r", "PanSTARRS_i", "DES_r", "PanSTARRS_g"]
    n_no_optical = 0
    for _, row in targets.iterrows():
        sn = row["sn_name"]
        has_opt = any(
            manifest.get((sn, b), {}).get("status") in (FLAG_OK, FLAG_SKIPPED)
            for b in optical_bands
        )
        if not has_opt:
            print(
                f"  *** WARNING: {sn} has no valid optical reference image! "
                "Step 2 (aperture definition) will fail for this object."
            )
            n_no_optical += 1

    if n_no_optical:
        print(
            f"\n  {n_no_optical} object(s) lack a valid optical reference. "
            "Check network connectivity and sky coverage at those positions."
        )

    print(f"\nNext step:  python 02_create_apertures.py --all\n")


if __name__ == "__main__":
    main()
