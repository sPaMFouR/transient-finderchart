# TransientFinderchart

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Qt GUI](https://img.shields.io/badge/GUI-PySide6%20%2F%20PyQt6-green.svg)](findingchart_guiplotter/qt_compat.py)
[![macOS SwiftUI](https://img.shields.io/badge/macOS%2014%2B-SwiftUI-black.svg)](findingchart_macapp)
[![Tests](https://img.shields.io/badge/tests-62%20passed-brightgreen.svg)](tests)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

TransientFinderchart creates observing charts for supernovae and other transients. It resolves TNS or manually entered targets, downloads archival survey cutouts, overlays slit and catalog geometry, adds an optional visual fake source, and exports publication-ready PNG, JPEG, or PDF charts.

The same Python science/rendering pipeline is exposed through three interfaces: the main Qt desktop application, a lightweight local web interface, and an experimental native macOS SwiftUI front-end. The chart presentation is inspired by Sean Brennan's [`Astro-Sean/finder_chart`](https://github.com/Astro-Sean/finder_chart).

![Template finding chart](docs/assets/findingchartGUI_2024ggi.jpg)

## Current capabilities

- Target input from TNS/IAU/ZTF names or custom decimal/sexagesimal RA and Dec.
- Pan-STARRS, Legacy Survey, DSS2, and 2MASS cutouts with survey-specific filters and supported color composites.
- WCS-aware chart, transient-centered inset, configurable zoom, compass, adaptive scale bar, crosshair, and fixed celestial slit PA measured east of north.
- Current parallactic-angle calculation for the included observatories, with an explicit action to copy it to the slit PA.
- Automatic field-star FWHM estimation and selectable fake-source kernels: `moffat`, `empirical core`, `empirical hybrid`, and `gaussian taper`.
- Automatic or manual contrast, `arcsinh`/linear/square-root/log stretches, selectable color maps, inversion, and annotation colors.
- Gaia DR3 and Pan-STARRS DR2 overlays, magnitude and target-distance cuts, source selection in the main chart or inset, and blind-offset details.
- Gaia parallax and proper-motion display when those fields are returned.
- PNG, JPEG, and PDF export. The native macOS interface additionally offers high-DPI PDF/JPEG presets.

The fake source is intended to make the expected transient position easy to recognize. It is **not a calibrated photometric simulation**; see [Scientific and operational limitations](#scientific-and-operational-limitations).

## Install

Python 3.9 or newer is required. A virtual environment is strongly recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e .
```

Installing from the duplicated runtime requirements file is also supported:

```bash
python3 -m pip install -r requirements.txt
```

`PySide6` is the declared Qt dependency. The compatibility layer can use an independently installed PyQt6 instead, which is useful in environments that already load PyQt6.

## Run

### Qt desktop application

```bash
python3 run_finding_chart.py
```

An editable install also provides:

```bash
findingchart-guiplotter
```

If PySide6 conflicts with a conda environment that already uses PyQt6:

```bash
FINDING_CHART_QT_API=pyqt6 python3 run_finding_chart.py
```

### Local development web interface

```bash
python3 -m findingchart_guiplotter.web --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. Generated images accumulate in `web_exports/`.

The web server has no authentication, authorization, rate limiting, or production hardening. Keep it bound to `127.0.0.1`; do not expose it directly to an untrusted network.

### Native macOS SwiftUI interface

The native shell requires macOS 14+, Swift 5.9+, and a Python environment containing this project's dependencies.

```bash
cd findingchart_macapp
swift run findingchart_macapp
```

Set both paths explicitly. The current Swift bridge default contains this developer checkout's absolute repository path, so these variables are required after moving or cloning the project elsewhere:

```bash
export FINDING_CHART_PYTHON="/absolute/path/to/.venv/bin/python"
export FINDING_CHART_REPO="/absolute/path/to/transient-finderchart"
swift run findingchart_macapp
```

The Swift application communicates with `findingchart_macapp/bridge/findingchart_bridge.py` through JSON subprocess calls and keeps rendered images, pickled image/catalog state, and plotting caches under `findingchart_macapp/rendered_charts/`. See the [native interface README](findingchart_macapp/README.md) for details.

## Typical workflow

1. Resolve a TNS/IAU/ZTF name, or enter a custom target name and coordinates.
2. Choose the survey, filter, field size, and pixel scale, then load the cutout.
3. Optionally query Gaia DR3, Pan-STARRS DR2, or both and apply magnitude/distance cuts.
4. Select a catalog marker to inspect its blind offset, PA, magnitude, and available astrometry.
5. Adjust contrast, color, inset zoom, fake-source PSF/FWHM/brightness, compass, crosshair, and slit.
6. Choose the observatory/time and copy the calculated parallactic angle if required.
7. Export the chart.

## Online data services

All target, image, and catalog lookups require network access and depend on third-party service availability.

| Data | Implementation | Important constraint |
| --- | --- | --- |
| TNS | Authenticated [TNS API](https://www.wis-tns.org/) when credentials exist; otherwise public CSV search | The public-search fallback is best-effort and may change independently of this project. |
| Pan-STARRS images | STScI [`ps1filenames.py` and `fitscut.cgi`](https://ps1images.stsci.edu/ps1image.html) | The public 3π stacked survey principally covers declinations north of −30° and filters `grizy`. |
| Legacy Survey images | [Legacy Survey viewer cutouts](https://www.legacysurvey.org/viewer/urls) using the `ls-dr10` layer | FITS server errors fall back to JPEG with an approximate centered TAN WCS; this loses the original calibrated pixel values and exact survey WCS. |
| DSS2 and 2MASS images | NASA [SkyView](https://skyview.gsfc.nasa.gov/current/cgi/titlepage.pl) | Responses are generated remotely and may depend on upstream STScI/JPL services. |
| Gaia catalog | ESA Gaia DR3 TAP, with CDS/VizieR fallback for request failures | Catalog positions are displayed at the catalog epoch; proper motion is reported but not propagated. |
| Pan-STARRS catalog | [MAST Pan-STARRS DR2 mean catalog API](https://catalogs.mast.stsci.edu/docs/panstarrs.html) | Queries use mean-object PSF magnitudes and require at least two detections. |

## TNS credentials

Credentials are read only from environment variables and are not stored by the application:

```bash
export TNS_API_KEY="..."
export TNS_BOT_ID="..."
export TNS_BOT_NAME="..."
export TNS_TYPE="bot"  # optional; this is the default
```

Authenticated API access is more reliable than the public-search fallback.

## Repository map

- `findingchart_guiplotter/models.py`: target, image-request, image, and chart-setting data models.
- `findingchart_guiplotter/image_fetchers.py`: archive adapters and Legacy JPEG fallback.
- `findingchart_guiplotter/catalog.py`: Gaia/MAST queries and catalog parsing/filtering.
- `findingchart_guiplotter/tns.py`: authenticated and public TNS resolution.
- `findingchart_guiplotter/empirical_psf.py`: source detection, FWHM measurement, PSF construction, and injection.
- `findingchart_guiplotter/renderer.py`: WCS plotting, overlays, inset, contrast, and export.
- `findingchart_guiplotter/gui.py`: Qt interface and background workers.
- `findingchart_guiplotter/web.py`: local HTTP interface.
- `findingchart_macapp/`: SwiftUI shell and Python JSON bridge.
- `tests/`: offline unit/regression tests plus optional PSF diagnostics.

## Test and verification status

The offline Python suite currently passes 62 tests:

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

On 2026-07-13, `python3 -m pytest -q` completed with `62 passed`; Python bytecode compilation also passed. The local `main` commit was verified against GitHub `main` at `5aa5e14`.

The repository does not yet declare `pytest` as a development dependency, run tests in CI, include Swift tests, or exercise live third-party endpoints automatically. A failed `swift test` inside a restricted sandbox may be caused by SwiftPM's nested sandbox/cache requirements rather than source compilation; run `swift build` or `swift test` in a normal macOS shell for release validation.

PSF diagnostic figures can be regenerated with:

```bash
python3 tests/psf_diagnostics.py
```

Outputs are written to `tests/figures/`.

## Scientific and operational limitations

These are the highest-value follow-up items identified by the full local/online audit.

### High priority

1. **Make fake-source calibration explicit and band-aware.** The renderer may estimate a visual zero point from Gaia G or Pan-STARRS magnitudes regardless of the loaded archive/filter. This is useful for display but is not a physical cross-band calibration. Record the chosen calibration path in chart metadata, match catalog band to image band where possible, and require a user-supplied magnitude/zero point for quantitative simulations.
2. **Propagate astrometry to the observing epoch.** Gaia proper motions are shown but are not applied to marker positions or blind offsets. High-proper-motion guide stars can therefore have materially incorrect offsets. Propagate Gaia coordinates with `SkyCoord.apply_space_motion` when a valid epoch is available and surface the reference/output epochs.
3. **Add reproducible CI and dependency management.** Declare a development extra containing `pytest`, add lint/type checks and Python-version CI, test both supported Qt bindings, and add a lock/constraints strategy. Replace the static test badge with CI status once available.
4. **Validate observing geometry with regression tests.** Add tests for slit PA under rotated/parity-flipped WCS, parallactic-angle reference cases, scale/compass orientation, target-near-edge behavior, and exported vector/raster parity.
5. **Harden remote-service behavior.** Add retry/backoff, structured error types, service-specific size/coverage validation, and broader Gaia fallback handling for non-2xx TAP responses. Prefer supported API contracts over parsing generated SkyView/TNS HTML/CSV pages where possible.

### Medium priority

6. Add survey coverage checks before download, including Pan-STARRS's main declination limit, and expose native pixel scales/maximum supported cutout sizes instead of allowing requests that remote services may reject or resample.
7. Split the large `renderer.py`, `gui.py`, and macOS bridge into smaller rendering, calibration, overlay, I/O, and presentation modules. Consolidate duplicated catalog-detail and payload conversion logic across Qt and Swift.
8. Make native bridge configuration portable by deriving the repository from the executable/package location instead of a developer-specific absolute default; validate configured paths at startup.
9. Replace unrestricted pickle state in the macOS bridge with a validated, versioned cache format; constrain cache paths to the application state directory.
10. Add bounded cleanup and reuse for `web_exports/` and `findingchart_macapp/rendered_charts/`; the current interfaces accumulate generated files and overwrite some target-derived native filenames.
11. Add contract tests for TNS, Gaia/VizieR, MAST, STScI cutouts, Legacy Survey, and SkyView using recorded responses, plus opt-in live smoke tests. Add Swift model/bridge decoding and UI-state tests.

### Lower priority

12. Add instrument presets, detector orientation/footprints, atmospheric-dispersion guidance, and user-defined observatories.
13. Add Legacy Tractor or other deeper catalogs, catalog de-duplication for combined Gaia+Pan-STARRS results, and catalog quality filters.
14. Add a sample gallery and release workflow, synchronize version strings across Python/HTTP/Swift metadata, and document data-service acknowledgement/citation requirements in exported charts.

See [docs/IMPLEMENTATION_LOG.md](docs/IMPLEMENTATION_LOG.md) for the chronological implementation history and the detailed 2026-07-13 audit record.
