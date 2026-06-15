from findingchart_guiplotter.models import Target


def test_target_label_includes_first_distinct_alias():
    target = Target(display_name="SN 2023ixf", ra_deg=210.0, dec_deg=54.0, aliases=["ZTF23abc"])

    assert target.label == "SN 2023ixf (ZTF23abc)"


def test_target_label_omits_duplicate_alias():
    target = Target(display_name="SN 2023ixf", ra_deg=210.0, dec_deg=54.0, aliases=["SN 2023ixf"])

    assert target.label == "SN 2023ixf"
