# Supernova Finding Chart Plotter

PySide6 desktop app for building finding charts for core-collapse supernovae.

## Current scope

- Search a target by TNS/IAU name or ZTF/internal name.
- Fetch coordinates from TNS using environment credentials when available.
- Download image cutouts from Pan-STARRS, Legacy Survey, or DSS2.
- Choose color composite or single-band cutouts where the archive supports it.
- Default field size is 2 arcmin x 2 arcmin.
- Inject the SN as a visual Moffat PSF at the WCS target position.
- Draw a crosshair and target label.
- Draw a north/east compass.
- Draw a 1 arcmin ruler.
- Draw a configurable slit.
- Query Gaia DR3 catalog sources and overlay them on the finding chart.
- Default slit width is 2 arcsec and default slit length is 10 arcsec.
- Compute parallactic angle from target, observatory, and date/time.
- Export finding charts as PNG, JPG, or PDF.

## Install

```bash
python3 -m pip install -r requirements.txt
```

For development:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e .
```

TNS credentials should be kept out of git:

```bash
export TNS_API_KEY="..."
export TNS_BOT_ID="..."
export TNS_BOT_NAME="..."
```

## Run

```bash
python3 run_finding_chart.py
```

or:

```bash
python3 -m finding_chart_plotter
```

If you are inside a conda environment that already has PyQt6 installed and
PySide6 fails with a Qt symbol error, run with the PyQt6 compatibility path:

```bash
FINDING_CHART_QT_API=pyqt6 python run_finding_chart.py
```

The project-local virtual environment created during development can be run
directly with:

```bash
.venv/bin/python run_finding_chart.py
```

## First test targets

- `2023ixf`
- `2024ggi`
- `2025wny`

## Notes

- The date/time control defaults to the current date and time at launch.
- The PA convention is degrees east of north.
- The injected magnitude is currently a visual brightness control, not a calibrated photometric injection.
- The sidebar has two tabs: `Target / Archive` and `Chart / Catalog`.
- Gaia DR3 catalog overlays are implemented. Pan-STARRS/Legacy Tractor catalog overlays are still future work.

## Implementation log

See `docs/IMPLEMENTATION_LOG.md`.
