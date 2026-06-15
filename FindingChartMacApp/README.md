# FindingChartMacApp

Native macOS SwiftUI front-end for the existing Python finding-chart pipeline.
The app keeps the science and rendering code in `finding_chart_plotter` and
talks to it through a JSON subprocess bridge.

## Run

```bash
cd FindingChartMacApp
swift run FindingChartMacApp
```

Override the Python environment when needed:

```bash
export FINDING_CHART_PYTHON="/path/to/.venv/bin/python"
export FINDING_CHART_REPO="/Users/avinash/Work/SupernovaeData/_ProjectG_FindingChart"
swift run FindingChartMacApp
```

Bridge sanity check:

```bash
echo '{"action":"metadata"}' | python3 FindingChartMacApp/bridge/finding_chart_bridge.py --repo-dir .
```

The full render path downloads archive cutouts, so it requires network access
and the same Python dependencies as the existing Qt/web apps.

## Workflow

1. Load Target resolves TNS or accepts manual RA/Dec.
2. Load Image downloads the selected Archive Image cutout and caches it locally.
3. Slit and SN/overlay sliders re-render from the cached image after a short debounce.
4. Load Catalog can query Gaia DR3, Pan-STARRS DR2, or both; selecting a row highlights it and shows offset/details.
5. Save PDF writes a 2000 dpi PDF; Save JPG writes a 300 dpi JPG.
