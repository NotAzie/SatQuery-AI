import json

import satquery.__main__ as cli


def test_investigate_execute_runs_only_ready_plan_and_includes_report(monkeypatch, capsys):
    calls = []
    creation = {
        "state": "ready",
        "next_step": "Review the plan, then execute the investigation explicitly.",
        "mission": {"mission_id": "mission-1"},
        "investigation": {
            "investigation_id": "investigation-1",
            "tasks": [{"handler": "earth.observe"}],
        },
    }
    responses = {
        ("POST", "/api/v1/platform/investigate"): creation,
        ("POST", "/api/v1/platform/investigations/investigation-1/execute"):
            {"status": "succeeded", "plan_id": "execution-1"},
        ("GET", "/api/v1/platform/investigations/investigation-1/observations"):
            {"observations": []},
        ("GET", "/api/v1/platform/investigations/investigation-1/provenance"):
            {"sources": []},
        ("GET", "/api/v1/platform/investigations/investigation-1/intelligence"):
            {"assessment": None},
        ("GET", "/api/v1/platform/investigations/investigation-1/temporal-differences"):
            {"differences": []},
        ("GET", "/api/v1/platform/investigations/investigation-1/observation-stacks"):
            {"stacks": []},
        ("GET", "/api/v1/platform/earth-objects"):
            {"earth_objects": []},
        ("GET", "/api/v1/platform/investigations/investigation-1/reasoning"):
            {"findings": []},
        ("GET", "/api/v1/platform/investigations/investigation-1/report"):
            {"report_id": "report-1", "markdown": "Evidence-bound report."},
        ("GET", "/api/v1/platform/investigations/investigation-1/audit"):
            {"chains": {}},
        ("GET", "/api/v1/platform/investigations/investigation-1/reproducibility"):
            {"manifest": {}},
        ("GET", "/api/v1/platform/executions/execution-1/events"):
            {"events": []},
    }

    def request(method, path, *, payload=None, params=None):
        calls.append((method, path, payload, params))
        return responses[(method, path)]

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        ["investigate", "Review rainfall near this site", "--execute"]
    )

    assert cli.command_platform_investigate(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["creation"] == creation
    assert result["execution"]["status"] == "succeeded"
    assert result["report"]["markdown"] == "Evidence-bound report."
    assert result["events"] == {"events": []}
    assert result["earth_objects"] == {"earth_objects": []}
    assert result["reasoning"] == {"findings": []}
    assert result["audit"] == {"chains": {}}
    assert result["reproducibility"] == {"manifest": {}}
    assert calls[0][:2] == ("POST", "/api/v1/platform/investigate")
    assert calls[1][:2] == (
        "POST",
        "/api/v1/platform/investigations/investigation-1/execute",
    )
    assert (
        "GET",
        "/api/v1/platform/investigations/investigation-1/report",
        None,
        None,
    ) in calls
    assert calls[-1][:2] == (
        "GET",
        "/api/v1/platform/executions/execution-1/events",
    )
    assert (
        "GET",
        "/api/v1/platform/earth-objects",
        None,
        {"investigation_id": "investigation-1"},
    ) in calls


def test_investigate_execute_does_not_acquire_when_plan_needs_review(
    monkeypatch, capsys
):
    calls = []
    creation = {
        "state": "needs_clarification",
        "next_step": "Resolve the missing location.",
        "investigation": {
            "investigation_id": "investigation-2",
            "tasks": [{"handler": "earth.observe"}],
        },
    }

    def request(method, path, *, payload=None, params=None):
        calls.append((method, path, payload, params))
        return creation

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        ["investigate", "Review rainfall", "--execute"]
    )

    assert cli.command_platform_investigate(args) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["execution"] is None
    assert result["execution_skipped"]["reason"] == "investigation_not_ready"
    assert result["execution_skipped"]["next_step"] == creation["next_step"]
    assert len(calls) == 1
    assert calls[0][:2] == ("POST", "/api/v1/platform/investigate")


def test_investigate_remains_plan_only_without_explicit_execute(monkeypatch, capsys):
    creation = {
        "state": "ready",
        "investigation": {
            "investigation_id": "investigation-3",
            "tasks": [{"handler": "earth.observe"}],
        },
    }
    calls = []

    def request(method, path, *, payload=None, params=None):
        calls.append((method, path, payload, params))
        return creation

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        ["investigate", "Review rainfall"]
    )

    assert cli.command_platform_investigate(args) == 0
    assert json.loads(capsys.readouterr().out) == creation
    assert calls[0][:2] == ("POST", "/api/v1/platform/investigate")
