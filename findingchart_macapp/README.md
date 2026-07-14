# findingchart_macapp

Experimental native macOS 14+ SwiftUI front-end for the existing Python finding-chart pipeline. The Swift application owns the interface and live-render state; target resolution, archive/catalog access, PSF injection, WCS rendering, and export remain in `findingchart_guiplotter` and are invoked through a JSON subprocess bridge.

## Prerequisites

- macOS 14 or newer.
- Swift 5.9 or newer.
- Python 3.9+ with the repository's runtime dependencies installed.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cd findingchart_macapp
export FINDING_CHART_REPO="$(cd .. && pwd)"
export FINDING_CHART_PYTHON="$FINDING_CHART_REPO/.venv/bin/python"
swift run findingchart_macapp
```

The current `BridgeConfig.default` contains the original developer checkout as its fallback repository path. Set both variables after moving or cloning the repository elsewhere:

```bash
export FINDING_CHART_PYTHON="/absolute/path/to/.venv/bin/python"
export FINDING_CHART_REPO="/absolute/path/to/transient-finderchart"
swift run findingchart_macapp
```

The full image/catalog path requires network access. A bridge-only sanity check does not:

```bash
echo '{"action":"metadata"}' | python3 bridge/findingchart_bridge.py --repo-dir ..
```

## Workflow

1. Resolve a TNS target or enter manual RA/Dec.
2. Download and cache an archive cutout.
3. Adjust contrast, color, slit, inset, overlay, and fake-source controls; changes trigger a debounced render from the cached image.
4. Query Gaia DR3, Pan-STARRS DR2, or both. Catalog rows are sorted by target distance; selecting one highlights the marker and displays blind-offset details.
5. Save a 2000-DPI PDF or 400-DPI JPEG.

The interface can auto-fill a measured field-star FWHM and recommended visual fake-source brightness while preserving later user overrides. Available PSF models are Moffat, empirical core, empirical hybrid, and Gaussian taper.

## Bridge and local state

`bridge/findingchart_bridge.py` accepts one JSON request on standard input and emits one JSON result on standard output. It supports metadata, target loading, image loading, catalog queries, rendering, and export.

Generated charts, Matplotlib/font caches, and pickled image/catalog state are stored in `rendered_charts/`, which is ignored by Git. The cache is local trusted state: bridge payloads should not be accepted from untrusted clients because cache paths are read with Python pickle. There is currently no automatic cleanup policy.

## Validation status

The Swift package currently has no Swift test target. Validate release candidates with `swift build`/`swift test` in a normal macOS shell and run the root Python suite with `python3 -m pytest -q`. SwiftPM may fail inside a restricted outer sandbox because it invokes its own sandbox and writes compiler caches.

Scientific and operational limitations, including non-calibrated cross-band fake-source scaling and unpropagated Gaia proper motions, are documented in the [root README](../README.md#scientific-and-operational-limitations).
