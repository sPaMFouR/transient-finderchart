from __future__ import annotations

import sys
import traceback
import warnings
from datetime import datetime
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from .qt_compat import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QObject,
    QThread,
    Signal,
    qdatetime_to_datetime,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .catalog import CatalogSource, query_catalog_sources
from .exporting import default_export_filename, ensure_export_suffix
from .image_fetchers import available_bands, available_surveys, fetch_image
from .mpl_compat import ensure_astropy_wcsaxes_compat
from .models import ChartSettings, ImageData, ImageRequest, Target
from .observatories import OBSERVATORIES, parallactic_angle_deg
from .renderer import draw_chart, export_chart, pixel_scale_arcsec, world_to_scalar_pixel
from .tns import TNSClient, TNSLookupError


ensure_astropy_wcsaxes_compat()
warnings.filterwarnings("ignore", message="Tight layout not applied.*", category=UserWarning)


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, function, *args) -> None:
        super().__init__()
        self.function = function
        self.args = args

    def run(self) -> None:
        try:
            self.finished.emit(self.function(*self.args))
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr)
            self.failed.emit(compact_error_message(exc))


class ChartCanvas(FigureCanvas):
    def __init__(self) -> None:
        self.figure = Figure(figsize=(10, 10), tight_layout=False)
        super().__init__(self.figure)
        self.image: ImageData | None = None
        self.target: Target | None = None
        self.settings = ChartSettings()
        self.source_selected_callback = None
        self.mpl_connect("button_press_event", self._handle_catalog_click)

    def set_chart(self, image: ImageData, target: Target, settings: ChartSettings) -> None:
        self.image = image
        self.target = target
        self.settings = settings
        self.redraw()

    def redraw(self) -> None:
        self.figure.clear()
        if self.image is None or self.target is None:
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "Search a target and load an image", ha="center", va="center")
            ax.set_axis_off()
        else:
            try:
                ax = self.figure.add_subplot(111, projection=self.image.wcs)
                draw_chart(ax, self.image, self.target, self.settings)
                self.figure.subplots_adjust(left=0.12, right=0.96, bottom=0.10, top=0.90)
            except Exception as exc:
                print(traceback.format_exc(), file=sys.stderr)
                ax = self.figure.add_subplot(111)
                ax.text(0.5, 0.5, compact_error_message(exc), ha="center", va="center", wrap=True)
                ax.set_axis_off()
        self.draw_idle()

    def _handle_catalog_click(self, event) -> None:
        if event.button != 1 or self.image is None or self.target is None or event.inaxes is None:
            return
        source = self.nearest_catalog_source(event)
        if source is not None and self.source_selected_callback is not None:
            self.source_selected_callback(source)

    def nearest_catalog_source(self, event) -> CatalogSource | None:
        if event.xdata is None or event.ydata is None or self.image is None:
            return None
        sources = list(self.settings.catalog_sources)
        if not sources:
            return None
        x_offset, y_offset = getattr(event.inaxes, "_finding_chart_pixel_offset", (0.0, 0.0))
        click_x = float(event.xdata) + float(x_offset)
        click_y = float(event.ydata) + float(y_offset)
        try:
            scale = pixel_scale_arcsec(self.image)
        except Exception:
            scale = 1.0
        tolerance_pix = max(6.0, 2.5 / scale) if scale > 0 else 8.0
        nearest: tuple[float, CatalogSource] | None = None
        for source in sources:
            coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
            x, y = world_to_scalar_pixel(self.image, coord)
            if not all(value == value for value in (x, y)):
                continue
            distance = ((x - click_x) ** 2 + (y - click_y) ** 2) ** 0.5
            if distance <= tolerance_pix and (nearest is None or distance < nearest[0]):
                nearest = (distance, source)
        return nearest[1] if nearest is not None else None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Transient Finding Chart Plotter")
        self.resize(1280, 860)
        self.tns_client = TNSClient()
        self.target: Target | None = None
        self.image: ImageData | None = None
        self.catalog_sources: list[CatalogSource] = []
        self.selected_catalog_source: CatalogSource | None = None
        self._thread: QThread | None = None
        self._worker: Worker | None = None

        self.canvas = ChartCanvas()
        self.canvas.source_selected_callback = self.select_catalog_source
        self.status_label = QLabel("Ready")
        self._build_ui()
        self._sync_settings_from_controls()
        self.canvas.redraw()

    def _build_ui(self) -> None:
        root = QWidget()
        main_layout = QHBoxLayout(root)
        main_layout.addWidget(self._build_sidebar(), 0)
        main_layout.addWidget(self.canvas, 1)
        self.setCentralWidget(root)
        self.statusBar().addWidget(self.status_label, 1)

    def _build_sidebar(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setMaximumWidth(410)
        tabs.addTab(self._build_target_archive_tab(), "Target / Archive")
        tabs.addTab(self._build_chart_catalog_tab(), "Chart / Catalog")
        return tabs

    def _build_target_archive_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        search_box = QGroupBox("TNS Search")
        form = QFormLayout(search_box)
        self.name_edit = QLineEdit("2023ixf")
        self.search_button = QPushButton("Search TNS")
        self.search_button.clicked.connect(self.search_target)
        form.addRow("IAU/ZTF name", self.name_edit)
        form.addRow(self.search_button)
        layout.addWidget(search_box)

        info_box = QGroupBox("Target")
        info_layout = QFormLayout(info_box)
        self.target_name_edit = QLineEdit()
        self.target_name_edit.setPlaceholderText("Target label used on chart")
        self.alternate_name_edit = QLineEdit()
        self.alternate_name_edit.setPlaceholderText("ZTF / ATLAS / GOTO name")
        self.ra_edit = QLineEdit()
        self.ra_edit.setPlaceholderText("RA, e.g. 14:03:38.56 or 210.9107")
        self.dec_edit = QLineEdit()
        self.dec_edit.setPlaceholderText("Dec, e.g. +54:18:41.9")
        self.type_label = QLabel("-")
        self.use_coordinates_button = QPushButton("Use Coordinates")
        self.use_coordinates_button.clicked.connect(self.use_custom_coordinates)
        self.target_name_edit.textChanged.connect(self.update_target_name_tag)
        self.alternate_name_edit.textChanged.connect(self.update_target_name_tag)
        info_layout.addRow("Name", self.target_name_edit)
        info_layout.addRow("Alternate name", self.alternate_name_edit)
        info_layout.addRow("RA", self.ra_edit)
        info_layout.addRow("Dec", self.dec_edit)
        info_layout.addRow(self.use_coordinates_button)
        layout.addWidget(info_box)

        box = QGroupBox("Image Cutout")
        form = QFormLayout(box)
        self.survey_combo = QComboBox()
        self.survey_combo.addItems(available_surveys())
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Single band", "Color composite"])
        self.band_combo = QComboBox()
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.2, 60.0)
        self.size_spin.setSuffix(" arcmin")
        self.size_spin.setValue(3.0)
        self.size_spin.setDecimals(2)
        self.pixscale_spin = QDoubleSpinBox()
        self.pixscale_spin.setRange(0.05, 5.0)
        self.pixscale_spin.setSuffix(" arcsec/pix")
        self.pixscale_spin.setValue(0.262)
        self.pixscale_spin.setDecimals(3)
        self.load_button = QPushButton("Load Image")
        self.load_button.clicked.connect(self.load_image)
        self.survey_combo.currentTextChanged.connect(self.update_band_choices)
        self.mode_combo.currentTextChanged.connect(self.update_band_choices)
        self.update_band_choices()
        form.addRow("Survey", self.survey_combo)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Band", self.band_combo)
        form.addRow("Field", self.size_spin)
        form.addRow("Pixel scale", self.pixscale_spin)
        form.addRow(self.load_button)
        layout.addWidget(box)

        contrast_box = QGroupBox("Contrast")
        contrast_form = QFormLayout(contrast_box)
        self.auto_contrast_check = QCheckBox("Auto")
        self.auto_contrast_check.setChecked(True)
        self.stretch_combo = QComboBox()
        self.stretch_combo.addItems(["arcsinh", "linear", "sqrt", "log"])
        self.stretch_combo.setCurrentText("arcsinh")
        self.vmin_spin = QDoubleSpinBox()
        self.vmin_spin.setRange(-1.0e12, 1.0e12)
        self.vmin_spin.setDecimals(4)
        self.vmin_spin.setEnabled(False)
        self.vmax_spin = QDoubleSpinBox()
        self.vmax_spin.setRange(-1.0e12, 1.0e12)
        self.vmax_spin.setDecimals(4)
        self.vmax_spin.setEnabled(False)
        self.reset_contrast_button = QPushButton("Use image range")
        self.reset_contrast_button.clicked.connect(self.reset_contrast_from_image)
        self.auto_contrast_check.stateChanged.connect(self.toggle_contrast_controls)
        contrast_form.addRow(self.auto_contrast_check)
        contrast_form.addRow("Stretch", self.stretch_combo)
        contrast_form.addRow("vmin", self.vmin_spin)
        contrast_form.addRow("vmax", self.vmax_spin)
        contrast_form.addRow(self.reset_contrast_button)
        layout.addWidget(contrast_box)

        layout.addWidget(self._build_injected_source_box())
        layout.addStretch(1)
        return page

    def _build_injected_source_box(self) -> QGroupBox:
        source_box = QGroupBox("Injected SN")
        source_form = QFormLayout(source_box)
        self.inject_check = QCheckBox("Show empirical PSF")
        self.inject_check.setChecked(True)
        self.magnitude_spin = QDoubleSpinBox()
        self.magnitude_spin.setRange(10.0, 22.0)
        self.magnitude_spin.setValue(18.0)
        self.magnitude_spin.setDecimals(1)
        self.magnitude_spin.setSuffix(" mag")
        self.fwhm_spin = QDoubleSpinBox()
        self.fwhm_spin.setRange(0.1, 10.0)
        self.fwhm_spin.setValue(1.0)
        self.fwhm_spin.setSuffix(" arcsec")
        source_form.addRow(self.inject_check)
        source_form.addRow("Brightness / mag", self.magnitude_spin)
        source_form.addRow("FWHM", self.fwhm_spin)
        return source_box

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Image Cutout")
        form = QFormLayout(box)
        self.survey_combo = QComboBox()
        self.survey_combo.addItems(["Pan-STARRS", "Legacy Survey", "DSS2"])
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Color composite", "Single band"])
        self.band_combo = QComboBox()
        self.band_combo.addItems(["g", "r", "i", "z", "y", "red", "blue", "ir"])
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.2, 60.0)
        self.size_spin.setSuffix(" arcmin")
        self.size_spin.setValue(3.0)
        self.size_spin.setDecimals(2)
        self.pixscale_spin = QDoubleSpinBox()
        self.pixscale_spin.setRange(0.05, 5.0)
        self.pixscale_spin.setSuffix(" arcsec/pix")
        self.pixscale_spin.setValue(0.262)
        self.pixscale_spin.setDecimals(3)
        self.load_button = QPushButton("Load Image")
        self.load_button.clicked.connect(self.load_image)
        form.addRow("Survey", self.survey_combo)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Band", self.band_combo)
        form.addRow("Field", self.size_spin)
        form.addRow("Pixel scale", self.pixscale_spin)
        form.addRow(self.load_button)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _build_chart_catalog_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        obs_box = QGroupBox("Observation")
        obs_form = QFormLayout(obs_box)
        self.observatory_combo = QComboBox()
        self.observatory_combo.addItems(list(OBSERVATORIES.keys()))
        self.datetime_edit = QDateTimeEdit(datetime.now())
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.parallactic_button = QPushButton("Set PA to parallactic now")
        self.parallactic_button.clicked.connect(self.set_pa_to_parallactic)
        obs_form.addRow("Observatory", self.observatory_combo)
        obs_form.addRow("Date/time", self.datetime_edit)
        obs_form.addRow(self.parallactic_button)
        layout.addWidget(obs_box)

        slit_box = QGroupBox("Slit")
        slit_form = QFormLayout(slit_box)
        self.slit_check = QCheckBox("Draw slit")
        self.slit_check.setChecked(False)
        self.pa_spin = QDoubleSpinBox()
        self.pa_spin.setRange(-360.0, 360.0)
        self.pa_spin.setSuffix(" deg")
        self.pa_spin.setDecimals(2)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.1, 30.0)
        self.width_spin.setSuffix(" arcsec")
        self.width_spin.setValue(2.0)
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(1.0, 600.0)
        self.length_spin.setSuffix(" arcsec")
        self.length_spin.setValue(20.0)
        rotate_layout = QHBoxLayout()
        self.rotate_left_button = QPushButton("-5 deg")
        self.rotate_right_button = QPushButton("+5 deg")
        self.rotate_left_button.clicked.connect(lambda: self.rotate_pa(-5.0))
        self.rotate_right_button.clicked.connect(lambda: self.rotate_pa(5.0))
        rotate_layout.addWidget(self.rotate_left_button)
        rotate_layout.addWidget(self.rotate_right_button)
        slit_form.addRow(self.slit_check)
        slit_form.addRow("PA (E of N)", self.pa_spin)
        slit_form.addRow("Width", self.width_spin)
        slit_form.addRow("Length", self.length_spin)
        slit_form.addRow(rotate_layout)
        layout.addWidget(slit_box)

        overlay_box = QGroupBox("Overlays")
        grid = QGridLayout(overlay_box)
        self.crosshair_check = QCheckBox("Crosshair/label")
        self.crosshair_check.setChecked(True)
        self.compass_check = QCheckBox("North/east")
        self.compass_check.setChecked(True)
        grid.addWidget(self.crosshair_check, 0, 0)
        grid.addWidget(self.compass_check, 0, 1)
        layout.addWidget(overlay_box)

        catalog_box = QGroupBox("Catalog")
        catalog_layout = QVBoxLayout(catalog_box)
        self.catalog_combo = QComboBox()
        self.catalog_combo.addItems(["Gaia DR3", "Pan-STARRS DR2", "Gaia DR3 + Pan-STARRS DR2"])
        catalog_cut_form = QFormLayout()
        self.catalog_mag_cut_check = QCheckBox("Apply brightness cut")
        self.catalog_mag_cut_check.setChecked(True)
        self.catalog_mag_cut_spin = QDoubleSpinBox()
        self.catalog_mag_cut_spin.setRange(5.0, 25.0)
        self.catalog_mag_cut_spin.setDecimals(2)
        self.catalog_mag_cut_spin.setValue(21.0)
        self.catalog_mag_cut_spin.setSuffix(" mag")
        self.catalog_mag_cut_spin.setEnabled(self.catalog_mag_cut_check.isChecked())
        self.catalog_mag_cut_check.stateChanged.connect(
            lambda: self.catalog_mag_cut_spin.setEnabled(self.catalog_mag_cut_check.isChecked())
        )
        catalog_cut_form.addRow(self.catalog_mag_cut_check)
        catalog_cut_form.addRow("Max magnitude", self.catalog_mag_cut_spin)
        catalog_controls = QHBoxLayout()
        self.catalog_button = QPushButton("Query Catalog")
        self.catalog_button.clicked.connect(self.query_catalog)
        self.catalog_clear_button = QPushButton("Clear")
        self.catalog_clear_button.clicked.connect(self.clear_catalog)
        catalog_controls.addWidget(self.catalog_button)
        catalog_controls.addWidget(self.catalog_clear_button)
        self.catalog_text = QTextEdit()
        self.catalog_text.setReadOnly(True)
        self.catalog_text.setMaximumHeight(100)
        self.catalog_text.setPlainText("Query a catalog to overlay field sources. Click an overlaid source to identify it.")
        catalog_layout.addWidget(self.catalog_combo)
        catalog_layout.addLayout(catalog_cut_form)
        catalog_layout.addLayout(catalog_controls)
        catalog_layout.addWidget(self.catalog_text)
        layout.addWidget(catalog_box)

        self.export_button = QPushButton("Save FC as PNG / JPG / PDF")
        self.export_button.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; padding: 8px; }"
            "QPushButton:hover { background-color: #a93226; }"
            "QPushButton:pressed { background-color: #922b21; }"
        )
        self.export_button.clicked.connect(self.export_current_chart)
        layout.addWidget(self.export_button)

        layout.addStretch(1)

        for widget in (
            self.pa_spin,
            self.width_spin,
            self.length_spin,
            self.magnitude_spin,
            self.fwhm_spin,
            self.vmin_spin,
            self.vmax_spin,
            self.inject_check,
            self.auto_contrast_check,
            self.crosshair_check,
            self.slit_check,
            self.compass_check,
        ):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.update_chart_from_controls)
            else:
                widget.stateChanged.connect(self.update_chart_from_controls)
        self.stretch_combo.currentTextChanged.connect(self.update_chart_from_controls)
        self.observatory_combo.currentTextChanged.connect(self.update_pa_from_mode)
        self.datetime_edit.dateTimeChanged.connect(self.update_pa_from_mode)
        return page

    def _run_worker(self, label: str, function, success_callback, *args) -> None:
        self.status_label.setText(label)
        self._thread = QThread()
        self._worker = Worker(function, *args)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(success_callback)
        self._worker.failed.connect(self._worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def search_target(self) -> None:
        self.search_button.setEnabled(False)
        searched_name = self.name_edit.text().strip()
        if searched_name:
            self.target_name_edit.setText(searched_name)
        self._run_worker("Searching TNS...", self.tns_client.lookup, self._target_loaded, self.name_edit.text())

    def use_custom_coordinates(self) -> None:
        ra_text = self.ra_edit.text().strip()
        dec_text = self.dec_edit.text().strip()
        try:
            coord = SkyCoord(ra_text, dec_text, unit=(u.hourangle, u.deg))
        except Exception:
            try:
                coord = SkyCoord(float(ra_text) * u.deg, float(dec_text) * u.deg)
            except Exception as exc:
                self.show_error(f"Could not parse custom RA/Dec. Use sexagesimal RA/Dec or decimal degrees.\n{exc}")
                return
        name = self.target_name_edit.text().strip() or self.name_edit.text().strip() or "Custom transient"
        alternate = self.alternate_name_edit.text().strip()
        self._target_loaded(Target(display_name=name, ra_deg=coord.ra.deg, dec_deg=coord.dec.deg, aliases=[alternate] if alternate else []))

    def _target_loaded(self, target: Target) -> None:
        self.search_button.setEnabled(True)
        self.target = target
        self.catalog_sources = []
        self.target_name_edit.setText(target.display_name or target.tns_name or target.label)
        self.alternate_name_edit.setText(target.aliases[0] if target.aliases else "")
        self.ra_edit.setText(target_coord_strings(target)[0])
        self.dec_edit.setText(target_coord_strings(target)[1])
        self.type_label.setText(target.transient_type or "-")
        self.status_label.setText(f"Loaded target {target.label}")
        self.update_chart_from_controls()

    def update_target_name_tag(self) -> None:
        if self.target is None:
            return
        name = self.target_name_edit.text().strip()
        alternate = self.alternate_name_edit.text().strip()
        if name:
            self.target.display_name = name
        self.target.aliases = [alternate] if alternate else []
        self.update_chart_from_controls()

    def update_band_choices(self) -> None:
        current = self.band_combo.currentText() if hasattr(self, "band_combo") else ""
        bands = available_bands(self.survey_combo.currentText(), self.mode_combo.currentText())
        self.band_combo.blockSignals(True)
        self.band_combo.clear()
        self.band_combo.addItems(bands)
        if current in bands:
            self.band_combo.setCurrentText(current)
        self.band_combo.blockSignals(False)

    def load_image(self) -> None:
        if self.target is None:
            self.show_error("Search or load a target before loading an image.")
            return
        self.load_button.setEnabled(False)
        request = ImageRequest(
            survey=self.survey_combo.currentText(),
            mode=self.mode_combo.currentText(),
            band=self.band_combo.currentText(),
            size_arcmin=self.size_spin.value(),
            pixel_scale_arcsec=self.pixscale_spin.value(),
        )
        self._run_worker("Loading image cutout...", fetch_image, self._image_loaded, self.target, request)

    def _image_loaded(self, image: ImageData) -> None:
        self.load_button.setEnabled(True)
        self.image = image
        self.reset_contrast_from_image()
        self.status_label.setText(f"Loaded {image.survey} {image.band}")
        self.update_chart_from_controls()

    def _worker_failed(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self.load_button.setEnabled(True)
        if hasattr(self, "catalog_button"):
            self.catalog_button.setEnabled(True)
        self.status_label.setText("Operation failed")
        self.show_error(message)

    def _sync_settings_from_controls(self) -> ChartSettings:
        requested_pa = self.pa_spin.value()
        return ChartSettings(
            slit_width_arcsec=self.width_spin.value(),
            slit_length_arcsec=self.length_spin.value(),
            slit_pa_deg=requested_pa,
            slit_pa_mode="Fixed sky PA",
            psf_magnitude=self.magnitude_spin.value(),
            psf_fwhm_arcsec=self.fwhm_spin.value(),
            show_injected_source=self.inject_check.isChecked(),
            show_crosshair=self.crosshair_check.isChecked(),
            show_slit=self.slit_check.isChecked(),
            show_compass=self.compass_check.isChecked(),
            observation_time=qdatetime_to_datetime(self.datetime_edit.dateTime()),
            observatory_name=self.observatory_combo.currentText(),
            catalog_sources=list(self.catalog_sources),
            selected_catalog_source_label=self.selected_catalog_source.label if self.selected_catalog_source else "",
            auto_contrast=self.auto_contrast_check.isChecked(),
            vmin=self.vmin_spin.value(),
            vmax=self.vmax_spin.value(),
            contrast_stretch=self.stretch_combo.currentText(),
        )

    def update_chart_from_controls(self) -> None:
        if self.image is None or self.target is None:
            return
        settings = self._sync_settings_from_controls()
        self.canvas.set_chart(self.image, self.target, settings)

    def set_pa_to_parallactic(self) -> None:
        if self.target is None:
            return
        q = self.parallactic_pa_deg()
        self.pa_spin.setValue(q)
        self.slit_check.setChecked(True)
        self.status_label.setText(f"Fixed slit PA set to current parallactic angle {q:.2f} deg")

    def update_pa_from_mode(self) -> None:
        self.update_chart_from_controls()

    def rotate_pa(self, delta: float) -> None:
        self.pa_spin.setValue(self.pa_spin.value() + delta)
        self.slit_check.setChecked(True)

    def parallactic_pa_deg(self) -> float:
        if self.target is None:
            return 0.0
        coord = SkyCoord(self.target.ra_deg * u.deg, self.target.dec_deg * u.deg)
        obs = OBSERVATORIES[self.observatory_combo.currentText()]
        return parallactic_angle_deg(coord, obs, Time(qdatetime_to_datetime(self.datetime_edit.dateTime())))

    def export_current_chart(self) -> None:
        if self.image is None or self.target is None:
            self.show_error("Load an image before exporting.")
            return
        default_name = default_export_filename(self.target)
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export finding chart",
            str(Path.cwd() / default_name),
            "JPEG (*.jpg *.jpeg);;PNG (*.png);;PDF (*.pdf)",
        )
        if not path:
            return
        output_path = ensure_export_suffix(Path(path), selected_filter)
        export_chart(output_path, self.image, self.target, self._sync_settings_from_controls())
        self.status_label.setText(f"Exported {output_path}")

    def query_catalog(self) -> None:
        if self.target is None:
            self.show_error("Search a target before querying catalogs.")
            return
        self.catalog_button.setEnabled(False)
        catalog = self.catalog_combo.currentText()
        max_magnitude = self.catalog_mag_cut_spin.value() if self.catalog_mag_cut_check.isChecked() else None
        self._run_worker(
            f"Querying {catalog}...",
            query_catalog_sources,
            self._catalog_loaded,
            self.target,
            self.size_spin.value() / 2.0,
            catalog,
            200,
            max_magnitude,
        )

    def _catalog_loaded(self, sources: list[CatalogSource]) -> None:
        self.catalog_button.setEnabled(True)
        self.catalog_sources = sources
        self.selected_catalog_source = None
        preview = "\n".join(source.label for source in sources[:8])
        suffix = "" if len(sources) <= 8 else f"\n... {len(sources) - 8} more"
        catalog = self.catalog_combo.currentText()
        self.catalog_text.setPlainText(f"{len(sources)} {catalog} sources returned.\n{preview}{suffix}")
        self.status_label.setText(f"Loaded {len(sources)} {catalog} sources")
        self.update_chart_from_controls()

    def clear_catalog(self) -> None:
        self.catalog_sources = []
        self.selected_catalog_source = None
        self.catalog_text.setPlainText("Catalog overlay cleared.")
        self.update_chart_from_controls()

    def select_catalog_source(self, source: CatalogSource) -> None:
        self.selected_catalog_source = source
        self.catalog_text.setPlainText(source_detail_text(source, self.target))
        self.status_label.setText(f"Selected {source.label}")
        self.update_chart_from_controls()

    def toggle_contrast_controls(self) -> None:
        manual = not self.auto_contrast_check.isChecked()
        self.vmin_spin.setEnabled(manual)
        self.vmax_spin.setEnabled(manual)
        self.update_chart_from_controls()

    def reset_contrast_from_image(self) -> None:
        if self.image is None:
            return
        import numpy as np

        data = np.asarray(self.image.data, dtype=float)
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            return
        lo, hi = np.nanpercentile(finite, [1, 99.3])
        self.vmin_spin.blockSignals(True)
        self.vmax_spin.blockSignals(True)
        self.vmin_spin.setValue(float(lo))
        self.vmax_spin.setValue(float(hi))
        self.vmin_spin.blockSignals(False)
        self.vmax_spin.blockSignals(False)
        self.update_chart_from_controls()

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Finding Chart Plotter", message)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def compact_error_message(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lower = text.lower()
    if "archive server error" in lower or "server error 5" in lower:
        return text
    if "no pan-starrs coverage" in lower:
        return text
    if "skyview returned html" in lower:
        return text
    if "no image data" in lower or "no celestial wcs" in lower:
        return f"Image download did not return a usable WCS image. {text}"
    if len(text) > 420:
        return text[:417].rstrip() + "..."
    return text


def target_coord_strings(target: Target) -> tuple[str, str]:
    coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    return (
        coord.ra.to_string(unit=u.hour, sep=":", precision=2, pad=True),
        coord.dec.to_string(unit=u.deg, sep=":", precision=1, alwayssign=True, pad=True),
    )


def source_detail_text(source: CatalogSource, target: Target | None = None) -> str:
    coord = SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg)
    ra = coord.ra.to_string(unit=u.hour, sep=":", precision=3, pad=True)
    dec = coord.dec.to_string(unit=u.deg, sep=":", precision=2, alwayssign=True, pad=True)
    lines = [
        source.label,
        f"Catalog: {source.catalog}",
        f"RA: {ra}",
        f"Dec: {dec}",
    ]
    if source.magnitude is not None:
        band = f" {source.magnitude_band}" if source.magnitude_band else ""
        lines.append(f"Magnitude{band}: {source.magnitude:.3f}")
    lines.append(f"Parallax: {format_optional(source.parallax_mas, ' mas')}")
    lines.append(f"PM RA: {format_optional(source.pmra_mas_per_year, ' mas/yr')}")
    lines.append(f"PM Dec: {format_optional(source.pmdec_mas_per_year, ' mas/yr')}")
    if target is not None:
        target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
        delta_ra, delta_dec = target_coord.spherical_offsets_to(coord)
        delta_ra_arcsec = delta_ra.to_value(u.arcsec)
        delta_dec_arcsec = delta_dec.to_value(u.arcsec)
        pa_e_of_n = (u.Quantity(np.degrees(np.arctan2(delta_ra_arcsec, delta_dec_arcsec)), u.deg).to_value(u.deg) + 360.0) % 360.0
        lines.append(f"Delta_RA: {delta_ra_arcsec:+.2f} arcsec")
        lines.append(f"Delta_Dec: {delta_dec_arcsec:+.2f} arcsec")
        lines.append(f"PA E of N: {pa_e_of_n:.2f} deg")
        lines.append(f"Offset from target: {coord.separation(target_coord).arcsec:.2f} arcsec")
    return "\n".join(lines)


def format_optional(value: float | None, suffix: str) -> str:
    if value is None:
        return "not available"
    return f"{value:.3f}{suffix}"
