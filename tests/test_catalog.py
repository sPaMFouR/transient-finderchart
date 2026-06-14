from finding_chart_plotter.catalog import parse_panstarrs_dr2_csv, query_catalog_sources
from finding_chart_plotter.models import Target


def test_parse_panstarrs_dr2_csv_uses_best_available_psf_magnitude():
    text = "\n".join(
        [
            "objID,raMean,decMean,gMeanPSFMag,rMeanPSFMag,iMeanPSFMag",
            "123,210.1,54.2,18.7,17.9,17.8",
            "456,210.2,54.3,19.1,-999,18.2",
        ]
    )

    sources = parse_panstarrs_dr2_csv(text)

    assert len(sources) == 2
    assert sources[0].catalog == "Pan-STARRS DR2"
    assert sources[0].source_id == "123"
    assert sources[0].magnitude == 17.9
    assert sources[0].magnitude_band == "r"
    assert sources[0].label == "PS1 123"
    assert sources[1].magnitude == 18.2
    assert sources[1].magnitude_band == "i"
    assert sources[1].label == "PS1 456"


def test_query_catalog_sources_dispatches_combined_catalog(monkeypatch):
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    calls = []

    def fake_gaia(query_target, radius_arcmin, limit=200, max_magnitude=None):
        calls.append(("gaia", query_target, radius_arcmin, limit, max_magnitude))
        return ["gaia"]

    def fake_ps1(query_target, radius_arcmin, limit=200, max_magnitude=None):
        calls.append(("ps1", query_target, radius_arcmin, limit, max_magnitude))
        return ["ps1"]

    monkeypatch.setattr("finding_chart_plotter.catalog.query_gaia_dr3", fake_gaia)
    monkeypatch.setattr("finding_chart_plotter.catalog.query_panstarrs_dr2", fake_ps1)

    sources = query_catalog_sources(target, 1.5, "Gaia DR3 + Pan-STARRS DR2", limit=50, max_magnitude=20.5)

    assert sources == ["gaia", "ps1"]
    assert calls == [("gaia", target, 1.5, 50, 20.5), ("ps1", target, 1.5, 50, 20.5)]
