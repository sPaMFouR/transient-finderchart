import requests

from finding_chart_plotter.catalog import parse_gaia_vizier_tsv, parse_panstarrs_dr2_csv, query_catalog_sources, query_gaia_dr3
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


def test_parse_gaia_vizier_tsv_includes_astrometry():
    text = "\n".join(
        [
            "# comment",
            "Source\tRA_ICRS\tDE_ICRS\tGmag\tPlx\tpmRA\tpmDE",
            " \tdeg\tdeg\tmag\tmas\tmas/yr\tmas/yr",
            "-------------------\t---------------\t---------------\t---------\t---------\t---------\t---------",
            "1609227596164002432\t210.94040711660\t+54.32197630174\t16.840706\t0.2689\t-1.416\t-4.283",
            "1609227561802708096\t210.92248585293\t+54.31792212891\t18.462927\t\t\t",
        ]
    )

    sources = parse_gaia_vizier_tsv(text)

    assert len(sources) == 2
    assert sources[0].catalog == "Gaia DR3"
    assert sources[0].source_id == "1609227596164002432"
    assert sources[0].magnitude == 16.840706
    assert sources[0].magnitude_band == "G"
    assert sources[0].parallax_mas == 0.2689
    assert sources[0].pmra_mas_per_year == -1.416
    assert sources[0].pmdec_mas_per_year == -4.283
    assert sources[1].parallax_mas is None
    assert sources[1].pmra_mas_per_year is None


def test_query_gaia_dr3_falls_back_to_vizier_on_connection_error(monkeypatch):
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)

    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("reset")

    class FakeResponse:
        status_code = 200
        text = "\n".join(
            [
                "Source\tRA_ICRS\tDE_ICRS\tGmag\tPlx\tpmRA\tpmDE",
                " \tdeg\tdeg\tmag\tmas\tmas/yr\tmas/yr",
                "-------------------\t---------------\t---------------\t---------\t---------\t---------\t---------",
                "1\t210.1\t54.1\t17.5\t0.1\t1.2\t-0.3",
                "2\t210.2\t54.2\t21.5\t0.2\t1.3\t-0.4",
            ]
        )

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("finding_chart_plotter.catalog.requests.post", fake_post)
    monkeypatch.setattr("finding_chart_plotter.catalog.requests.get", fake_get)

    sources = query_gaia_dr3(target, 1.5, limit=10, max_magnitude=20.0)

    assert len(sources) == 1
    assert sources[0].source_id == "1"
    assert sources[0].magnitude == 17.5


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
