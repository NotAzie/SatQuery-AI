import satquery.__main__ as cli


def test_monitor_event_filters_are_passed_as_structured_query_parameters(
    monkeypatch, capsys
):
    captured = {}

    def request(method, path, *, payload=None, params=None):
        captured.update(method=method, path=path, payload=payload, params=params)
        return {"events": [], "next_cursor": None}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        [
            "monitor",
            "events",
            "--schedule-id",
            "schedule&/one",
            "--run-id",
            "run?two",
            "--cursor",
            "token + next",
            "--limit",
            "17",
        ]
    )

    assert cli.command_platform_monitor(args) == 0
    assert captured == {
        "method": "GET",
        "path": "/api/v1/platform/monitoring/events/page",
        "payload": None,
        "params": {
            "limit": 17,
            "schedule_id": "schedule&/one",
            "run_id": "run?two",
            "cursor": "token + next",
        },
    }
    capsys.readouterr()


def test_monitor_listing_keeps_mission_id_as_a_parameter(monkeypatch, capsys):
    captured = {}

    def request(method, path, *, payload=None, params=None):
        captured.update(method=method, path=path, payload=payload, params=params)
        return {"schedules": []}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        ["monitor", "list", "--mission-id", "mission/with spaces"]
    )

    assert cli.command_platform_monitor(args) == 0
    assert captured == {
        "method": "GET",
        "path": "/api/v1/platform/monitoring/schedules",
        "payload": None,
        "params": {"mission_id": "mission/with spaces"},
    }
    capsys.readouterr()
