import satquery.__main__ as cli


def test_connector_cli_exposes_passive_health_and_explicit_provider_operations(
    monkeypatch, capsys
):
    calls = []

    def request(method, path, *, payload=None, params=None):
        calls.append((method, path, payload, params))
        return {"ok": True}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    parser = cli.build_parser()
    list_args = parser.parse_args(["connectors"])
    health_args = parser.parse_args(["connectors", "health"])
    probe_args = parser.parse_args(["connectors", "probe", "provider/one"])
    discover_args = parser.parse_args(["platform", "discover", "provider-one"])
    stations_args = parser.parse_args([
        "connectors",
        "stations",
        "noaa-coops-water-level",
        "--bbox",
        "-123",
        "36",
        "-121",
        "38",
    ])

    for args in (list_args, health_args, probe_args, discover_args, stations_args):
        assert args.func(args) == 0

    assert calls == [
        ("GET", "/api/v1/platform/connectors", None, None),
        ("GET", "/api/v1/platform/connectors/health", None, None),
        (
            "POST",
            "/api/v1/platform/connectors/provider%2Fone/health-check",
            None,
            None,
        ),
        (
            "POST",
            "/api/v1/platform/connectors/provider-one/discover",
            None,
            None,
        ),
        (
            "POST",
            "/api/v1/platform/connectors/noaa-coops-water-level/stations/search",
            {"bbox": [-123.0, 36.0, -121.0, 38.0]},
            None,
        ),
    ]
    assert capsys.readouterr().out.count('"ok": true') == 5
