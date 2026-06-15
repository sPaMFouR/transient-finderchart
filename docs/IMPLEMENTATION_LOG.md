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
    - Gaia catalog sources are overlaid on the chart as small open circles.
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

14. Added finder-chart inset and improved source injection.
    - Added an in-plot metadata box and a transient-centered inset inspired by `Astro-Sean/finder_chart`.
    - Added README credit for `Astro-Sean/finder_chart`.
    - The first inset version showed a 10 arcsec cutout centered on the transient and included a 5 arcsec scalebar.
    - The injected Moffat profile is now normalized as a source-flux kernel instead of an arbitrary peak-only patch.
    - If Gaia catalog sources are loaded, field-star aperture fluxes and Gaia magnitudes are used to estimate the target flux scale.
    - Image display normalization is computed from the original image, not the injected image, so bright injected sources do not dim the host galaxy.

15. Improved archive loading and target entry.
    - Default image mode is now single-band.
    - Band choices are now survey-specific.
    - Added direct custom RA/Dec target entry.
    - Added 2MASS J/H/K image fetching through SkyView.
    - Legacy Survey FITS HTTP 500 errors now fall back to a JPEG cutout with an approximate centered TAN WCS when possible.
    - GUI worker errors now show compact user-facing messages while full tracebacks go to stderr.
    - The plotting canvas now catches render-time errors and displays them on the canvas instead of leaving a blank/unchanged display.
    - Verified live image loading for Pan-STARRS, DSS2, Legacy Survey, and 2MASS around `SN 2023ixf`.

16. Added contrast controls.
    - Added auto/manual contrast controls to the GUI.
    - Default rendering keeps the existing percentile/asinh auto stretch.
    - Manual vmin/vmax overrides are passed through to the chart renderer.

17. Added WCSAxes compatibility patch.
    - Added a runtime shim for environments where Astropy imports `AnchoredEllipse` but the installed Matplotlib no longer exposes it.
    - The shim is applied before WCS projections are created in both GUI and export rendering paths.
    - Suppressed repeated Matplotlib tight-layout warnings because the chart uses explicit WCSAxes margins and inset axes.

18. Improved custom coordinate entry.
    - Target name, RA, and Dec are now editable in the same Target panel that TNS search populates.
    - If a TNS name is unresolved, the searched name can still be used as the chart label with manually entered RA/Dec.
    - Verified sexagesimal manual coordinate entry through the offscreen GUI path.

19. Updated plotting defaults.
    - Default field of view is now 3 arcmin.
    - Default slit size was changed to 2 arcsec x 60 arcsec at this stage.
    - Slit outline color is `xkcd:red`.
    - Save button is shown at the top of the Chart/Catalog tab and explicitly advertises PNG/JPG/PDF output.
    - Axis and tick label sizes were reduced from the large SciencePlots defaults for GUI readability.
    - The host label was removed from the target panel until a real host-galaxy query is implemented.
    - The injected Moffat profile uses a tighter beta and smaller truncation radius, so changing injected magnitude changes flux more than apparent FWHM.

20. Enlarged the transient inset and slit default.
    - The default slit length was changed to 60 arcsec at this stage.
    - The transient inset was changed to use a 20 arcsec x 20 arcsec source box.
    - The source-box and inset borders are thinner, and connector lines link the SN box to the inset frame.

21. Refined chart styling controls.
    - The metadata box and title now use the same explicit serif/SciencePlots-style font family.
    - The save button is below the catalog query section and styled as a red primary action.
    - Compass arms are longer, thinner, and shifted farther right with the E label offset from the arrow tip.
    - Moffat injection keeps the requested FWHM but truncates the wings more tightly to reduce unrealistic visual broadening at high flux.

22. Adjusted inset and control placement.
    - Contrast controls moved to the Target / Archive tab directly below Image Cutout.
    - The inset now draws the slit at the same PA as the main chart.
    - The orange SN crosshair gap is larger in both the main chart and inset.

23. Matched the slit and inset geometry.
    - The default slit length is back to 30 arcsec.
    - The transient inset now uses a 30 arcsec x 30 arcsec source box.
    - The inset display area is scaled to 2.5 times the on-chart source-box area.
    - Inset connector lines use opposite diagonal vertices of the source box.
    - The orange SN crosshair line segments are twice as long.

24. Cleaned survey/filter title labels.
    - Chart titles now strip archive transport details such as `JPEG`.
    - DSS2 and 2MASS filter labels no longer repeat the survey name in the title.

25. Updated slit, crosshair, and inset ruler geometry.
    - Default slit length is now 20 arcsec.
    - SN crosshair segments are orange and remain aligned with sky north/south and east/west.
    - Inset connector lines now use the opposite diagonal vertices from the previous version.
    - The inset ruler now marks 10 arcsec and sits slightly higher in the inset.
    - The compass E label was moved slightly left to reduce arrow overlap.

26. Clarified slit PA handling.
    - Added a PA mode control for fixed sky PA versus parallactic angle.
    - The chart metadata states whether the slit PA is parallactic or fixed east of north.
    - The 10 arcsec inset ruler label and compass E label were shifted further from their arrows.

27. Adjusted target and overlay colors.
    - Target name is now drawn outside the metadata box in red.
    - The SN crosshair is red in the main chart and inset.
    - The slit overlay is orange in the main chart and inset.
    - The metadata box starts lower on the plot so the PA/slit text appears below the target label.

28. Adopted empirical fake-star PSF injection.
    - Added `finding_chart_plotter.empirical_psf` based on the supplied fake-star injection script.
    - Single-band images now try to build an empirical PSF from detected field stars, recenter and normalize PSF stamps, shift the kernel to the transient subpixel position, and inject the scaled fake source.
    - If empirical PSF construction is unavailable or too few suitable stars are found, injection falls back to the analytic Moffat kernel.
    - Added `photutils` as the preferred DAOStarFinder dependency, with a SciPy local-maximum fallback.

29. Fixed metadata placement and inset edge handling.
    - Restored the target name to the top metadata box.
    - Kept the SN name next to the crosshair/source-box indicator.
    - Added guards around inset sizing for clipped or off-edge targets to avoid invalid inset dimensions.

30. Simplified PA labels and hardened PSF/export paths.
    - Removed the separate PA offset control.
    - Parallactic mode now labels the chart as `PA = Parallactic Angle`; fixed mode labels the supplied angle as degrees east of north.
    - Empirical PSF flux now prefers a conservative fraction of the median PSF-star flux before falling back to Gaia/catalog or image-statistics scaling.
    - DAOStarFinder no-detection warnings are suppressed and fall back to the SciPy local-maximum detector.
    - Export now uses a backend-independent Matplotlib `Figure` to avoid Tk/Qt backend conflicts.

31. Updated catalog overlay color.
    - Catalog source markers use catalog-specific outlines.

32. Simplified slit PA and source brightness controls.
    - Removed the visible PA mode dropdown.
    - The Slit box had a single `PA offset (E of N)` control at this stage.
    - The injected source control is labeled `Brightness` instead of `Injected mag` because it is a relative display/injection scale, not a calibrated magnitude.

33. Added SN arrow label on the inset.
    - The SN name is now placed below the zoomed inset with an arrow pointing to the transient position inside the inset.
    - Removed the separate label drawn beside the source box on the main chart.

34. Converted injected-source brightness to a relative scale.
    - Brightness now ranges from 0 to 10 with a default of 5.
    - Removed the remaining pseudo-magnitude value from the GUI and model.
    - Injection flux scaling now uses the relative brightness value rather than pretending it is a calibrated magnitude.

35. Made slit PA a fixed celestial angle.
    - The app no longer auto-sets the slit to the parallactic angle when a target loads.
    - The PA field is now a fixed sky PA measured east of north.
    - The slit is off by default, with a `Draw slit` checkbox in the Slit box.
    - The parallactic button only copies the current parallactic angle into the fixed PA field when explicitly clicked.

36. Added catalog selection, blind-offset details, and web rendering.
    - The catalog query controls support Gaia DR3, Pan-STARRS DR2, or both, with an optional brightness cut.
    - Gaia sources include parallax, `pmRA`, and `pmDE` when the catalog returns those values.
    - Selected catalog stars report delta RA, delta Dec, and PA east of north for blind-offset use.
    - Selected stars are highlighted in royal blue; unselected Gaia stars are orange and unselected Pan-STARRS stars are light green.
    - Catalog markers are drawn in both the main chart and the zoomed inset.
    - Added a development web renderer that reuses the Python chart pipeline.

37. Hardened Gaia DR3 catalog queries.
    - Gaia queries try the ESA Gaia TAP service first.
    - If ESA TAP resets or times out, the query falls back to CDS/VizieR Gaia DR3 TSV output.
    - The VizieR fallback preserves magnitude, parallax, and proper-motion fields used by the blind-offset detail panel.
    - Verified a live Gaia DR3 fallback query around `SN 2023ixf` returned sources.

## Known next steps

1. Add archive coverage checks that enable/highlight survey tabs before image loading.
2. Add Legacy Tractor catalog overlays if deeper reference catalogs are needed.
3. Add instrument presets if specific telescope/instrument chart defaults are needed.
4. Add a sample gallery once preferred finding-chart visual style is chosen.
5. Add automated tests around WCS slit geometry and parallactic-angle calculations.
