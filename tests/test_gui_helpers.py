from pathlib import Path

import pytest

from findingchart_macapp.bridge.findingchart_bridge import _source_payload
from findingchart_guiplotter.blind_offsets import blind_offset_from_target_to_source
from findingchart_guiplotter.catalog import CatalogSource
from findingchart_guiplotter.exporting import default_export_filename, ensure_export_suffix, safe_filename_part
from findingchart_guiplotter.models import Target


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


def test_source_detail_offsets_are_from_target_to_blind_offset_star():
    target = Target(display_name="SN", ra_deg=0.0, dec_deg=0.0)
    star = CatalogSource(ra_deg=1.0 / 3600.0, dec_deg=-2.0 / 3600.0, label="Offset star")

    offset = blind_offset_from_target_to_source(star, target)

    assert offset.delta_ra_arcsec == pytest.approx(1.0)
    assert offset.delta_dec_arcsec == pytest.approx(-2.0)
    assert offset.pa_east_of_north_deg == pytest.approx(153.434948822922)

    payload = _source_payload(star, target)
    assert 'Delta_RA : 1.00"' in payload["detail"]
    assert 'Delta_Dec: -2.00"' in payload["detail"]
