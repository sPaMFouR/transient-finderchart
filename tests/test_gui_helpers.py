from pathlib import Path

from finding_chart_plotter.exporting import default_export_filename, ensure_export_suffix, safe_filename_part
from finding_chart_plotter.models import Target


def test_default_export_filename_prefers_alternate_name():
    target = Target(display_name="SN 2023ixf", ra_deg=210.0, dec_deg=54.0, aliases=["ZTF23abc"])

    assert default_export_filename(target) == "findingchart_ZTF23abc.jpg"


def test_default_export_filename_falls_back_to_target_label():
    target = Target(display_name="SN 2023ixf", ra_deg=210.0, dec_deg=54.0)

    assert default_export_filename(target) == "findingchart_SN_2023ixf.jpg"


def test_safe_filename_part_removes_path_punctuation():
    assert safe_filename_part("ATLAS / GOTO name") == "ATLAS_GOTO_name"


def test_ensure_export_suffix_defaults_to_jpeg_filter():
    assert ensure_export_suffix(Path("chart"), "JPEG (*.jpg *.jpeg)") == Path("chart.jpg")
