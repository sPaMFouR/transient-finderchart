# Implementation Log

## 2026-06-01

1. Reviewed the existing repository.
   - `_Codes/tns_dja_crossmatch.py` contains reusable TNS credential and lookup patterns.
   - `_Codes/01_download_images.py` contains useful archive cutout ideas, especially Legacy Survey handling.
   - The old scripts were left unchanged.

2. Created a new PySide6 app package.
   - Added `finding_chart_plotter/`.
   - Added `run_finding_chart.py` as a direct launcher.
   - Added `pyproject.toml` and `requirements.txt`.

3. Added data models.
   - `Target`
   - `ImageRequest`
   - `ImageData`
   - `ChartSettings`

4. Added observatory support.
   - La Palma
   - Mauna Kea, Hawaii
   - Paranal, Chile
   - Palomar Observatory
   - La Silla, Chile
   - HCT / IAO, India
   - Kanata, Hiroshima
   - Added parallactic-angle calculation in degrees east of north.

5. Added TNS lookup service.
   - Uses `TNS_API_KEY`, `TNS_BOT_ID`, and `TNS_BOT_NAME` when present.
   - Falls back to public TNS CSV search when credentials are unavailable.
   - Supports IAU/TNS names and ZTF-style internal-name searches.

6. Added archive image services.
   - Pan-STARRS through STScI PS1 cutout services.
   - Legacy Survey through the viewer FITS cutout endpoint.
   - DSS2 through NASA SkyView.
   - Single-band and color-composite requests are represented in the same app model.

7. Added chart rendering.
   - WCS-aware Matplotlib canvas.
   - 2D Gaussian visual SN injection.
   - SN crosshair and searched-name label.
   - North/east compass.
   - Slit overlay with configurable width, length, and PA.
   - PNG/JPG/PDF export.

8. Added the first GUI.
   - Target tab for TNS search.
   - Archive tab for image loading.
   - Chart tab for observatory, date/time, parallactic PA, slit, PSF, overlays, and export.
   - Catalog tab scaffold for future Gaia/PS1/Legacy Tractor overlays.

9. Added repository hygiene.
   - `.gitignore` excludes local venvs, caches, credentials, generated cutouts, and exports.
   - TNS credentials are not stored in code.

10. Verified locally.
    - Syntax check passed with `py_compile`.
    - Synthetic WCS chart exported successfully to PNG.
    - PySide6 offscreen GUI smoke test passed.
    - Live TNS lookup for `2023ixf` returned `SN 2023ixf`, RA `210.910675`, Dec `54.311651`, type `SN II`.
    - Live Pan-STARRS r-band cutout returned a WCS FITS image.
    - Live Legacy Survey r-band cutout returned a WCS FITS image.
    - Live DSS2 Red cutout returned a WCS FITS image.
    - Live Legacy Survey color cutout returned RGB image data with WCS.

11. Added Qt binding compatibility.
    - `finding_chart_plotter/qt_compat.py` prefers PySide6.
    - If `FINDING_CHART_QT_API=pyqt6` is set, the GUI imports PyQt6 instead.
    - This avoids Qt library collisions in conda environments that already load PyQt6, such as the observed `pypeit` environment.

12. Updated catalog, GUI layout, and chart annotations.
    - Replaced the catalog scaffold with a live Gaia DR3 TAP query.
    - Gaia catalog sources are overlaid on the chart as small yellow open circles.
    - Combined `Target` and `Archive` into one `Target / Archive` tab.
    - Combined `Chart` and `Catalog` into one `Chart / Catalog` tab.
    - Imported `plot_style.py` opportunistically for project plotting defaults while keeping GUI exports robust on systems without TeX.
    - Replaced the injected Gaussian with a visual Moffat PSF.
    - Changed the SN marker to separated horizontal and vertical line segments around the PSF center.
    - Moved the north/east compass to the bottom-right of the chart.
    - Added a scale ruler near the bottom-center of the chart.
    - Verified a live Gaia DR3 query around `SN 2023ixf` returned sources.

13. Updated finding-chart presentation defaults.
    - Default slit size is now 2 arcsec x 10 arcsec.
    - Scale ruler is now 1 arcmin instead of 2 arcsec.
    - Compass was moved further toward the bottom-right corner.
    - WCSAxes limits are explicitly fixed to image pixel edges for better RA/Dec alignment with the rectangular cutout.
    - Chart title now includes survey image name, target name, and sexagesimal RA/Dec.
    - SciencePlots styling from `plot_style.py` is preserved when available; LaTeX text is only disabled when no local `latex` executable is found.

## Known next steps

1. Add archive coverage checks that enable/highlight survey tabs before image loading.
2. Add Pan-STARRS and Legacy Tractor catalog overlays alongside the implemented Gaia DR3 overlay.
3. Add instrument presets if specific telescope/instrument chart defaults are needed.
4. Add a sample gallery once preferred finding-chart visual style is chosen.
5. Add automated tests around WCS slit geometry and parallactic-angle calculations.
