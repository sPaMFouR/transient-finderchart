from findingchart_guiplotter.catalog import DEFAULT_CATALOG_MAX_DISTANCE_ARCSEC
from findingchart_guiplotter.models import ImageData
from findingchart_guiplotter.web import payload_bool, render_from_payload


def test_payload_bool_accepts_browser_and_api_values():
    assert payload_bool({"x": True}, "x", False) is True
    assert payload_bool({"x": "on"}, "x", False) is True
    assert payload_bool({"x": "false"}, "x", True) is False
    assert payload_bool({}, "x", True) is True


def test_render_from_payload_defaults_catalog_distance_cut(monkeypatch, tmp_path):
    captured = {}

    def fake_query_catalog_sources(target, radius_arcmin, catalog, limit=200, max_magnitude=None, max_distance_arcsec=None):
        captured["catalog"] = catalog
        captured["max_distance_arcsec"] = max_distance_arcsec
        return []

    monkeypatch.setattr("findingchart_guiplotter.web.query_catalog_sources", fake_query_catalog_sources)
    monkeypatch.setattr("findingchart_guiplotter.web.fetch_image", lambda target, request: ImageData(data=[], wcs=None, survey=request.survey, band=request.band, mode=request.mode))  # type: ignore[arg-type]
    monkeypatch.setattr("findingchart_guiplotter.web.measured_image_fwhm_arcsec", lambda image, target: (None, None))
    monkeypatch.setattr("findingchart_guiplotter.web.export_chart", lambda path, image, target, settings: path.write_text("ok"))
    monkeypatch.setattr("findingchart_guiplotter.web.WEB_OUTPUT_DIR", tmp_path)

    image_url = render_from_payload({"ra_deg": 210.0, "dec_deg": 54.0, "catalog": "Gaia DR3"})

    assert image_url.startswith("/exports/finding_chart_")
    assert captured == {"catalog": "Gaia DR3", "max_distance_arcsec": DEFAULT_CATALOG_MAX_DISTANCE_ARCSEC}
