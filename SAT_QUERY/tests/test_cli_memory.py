import json
from pathlib import Path
from uuid import uuid4

import satquery.__main__ as cli


def test_earth_memory_cli_forwards_structured_filters(monkeypatch, capsys):
    captured = {}

    def request(method, path, *, payload=None, params=None):
        captured.update(method=method, path=path, payload=payload, params=params)
        return {"artifacts": [], "total": 0}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        [
            "memory",
            "search",
            "flood evidence",
            "--artifact-type",
            "observation",
            "--variable",
            "precipitation_amount",
            "--mission-id",
            "mission-1",
            "--investigation-id",
            "investigation-1",
            "--method-id",
            "method-1",
            "--source-artifact-id",
            "observation:source-1",
            "--cursor",
            "page-token",
            "--limit",
            "12",
        ]
    )

    assert cli.command_platform_earth_memory(args) == 0
    assert captured == {
        "method": "POST",
        "path": "/api/v1/platform/earth-memory/search",
        "payload": {
            "text": "flood evidence",
            "artifact_types": ["observation"],
            "canonical_variable": "precipitation_amount",
            "mission_id": "mission-1",
            "investigation_id": "investigation-1",
            "method_id": "method-1",
            "source_artifact_id": "observation:source-1",
            "cursor": "page-token",
            "limit": 12,
        },
        "params": None,
    }
    assert json.loads(capsys.readouterr().out)["total"] == 0


def test_earth_object_transition_cli_posts_explicit_revision(monkeypatch, capsys):
    captured = {}
    transition = {
        "prior_object_id": "object:r1",
        "transition_type": "lifecycle",
        "actor": "reviewer-1",
        "rationale": "Source owner confirmed the station is inactive.",
        "observation_ids": ["observation-1"],
        "evidence_ids": [],
        "prior_lifecycle": "active",
        "new_lifecycle": "inactive",
    }
    transition_path = Path.cwd() / f".object-transition-{uuid4().hex}.json"
    transition_path.write_text(json.dumps(transition), encoding="utf-8")

    def request(method, path, *, payload=None, params=None):
        captured.update(method=method, path=path, payload=payload, params=params)
        return {"object_id": "object:r2", "lifecycle": "inactive"}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    args = cli.build_parser().parse_args(
        ["objects", "transition", "object:r1", "--transition-file", str(transition_path)]
    )

    try:
        assert cli.command_platform_earth_objects(args) == 0
        assert captured == {
            "method": "POST",
            "path": "/api/v1/platform/earth-objects/id/object%3Ar1/transitions",
            "payload": transition,
            "params": None,
        }
        assert json.loads(capsys.readouterr().out)["lifecycle"] == "inactive"
    finally:
        transition_path.unlink(missing_ok=True)


def test_earth_object_cli_encodes_ids_and_keeps_filters_as_parameters(monkeypatch, capsys):
    calls = []

    def request(method, path, *, payload=None, params=None):
        calls.append((method, path, payload, params))
        return {"earth_objects": []}

    monkeypatch.setattr(cli, "_platform_api_request", request)
    show_args = cli.build_parser().parse_args(["objects", "show", "object:group/1"])
    list_args = cli.build_parser().parse_args(
        ["objects", "list", "--investigation-id", "case/with spaces"]
    )

    assert cli.command_platform_earth_objects(show_args) == 0
    assert cli.command_platform_earth_objects(list_args) == 0
    assert calls == [
        (
            "GET",
            "/api/v1/platform/earth-objects/id/object%3Agroup%2F1",
            None,
            None,
        ),
        (
            "GET",
            "/api/v1/platform/earth-objects",
            None,
            {"investigation_id": "case/with spaces"},
        ),
    ]
    capsys.readouterr()
