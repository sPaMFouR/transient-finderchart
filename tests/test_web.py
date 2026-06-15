from findingchart_guiplotter.web import payload_bool


def test_payload_bool_accepts_browser_and_api_values():
    assert payload_bool({"x": True}, "x", False) is True
    assert payload_bool({"x": "on"}, "x", False) is True
    assert payload_bool({"x": "false"}, "x", True) is False
    assert payload_bool({}, "x", True) is True
