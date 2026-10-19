"""Command line entry point.

python -m satquery serve          # API + demo console
python -m satquery doctor         # what is installed, what is missing
python -m satquery warmup         # load models now
python -m satquery ask "..." -i scene.png
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
from pathlib import Path
from typing import List, Optional

from .config import get_settings
from .errors import SatQueryError
from .platform.contracts import EarthQuery
from .schemas import ToolName


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def command_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run: pip install uvicorn", file=sys.stderr)
        return 1

    platform_config = getattr(args, "platform_config", None)
    if platform_config:
        os.environ["SATQUERY_PLATFORM_CONFIG"] = str(Path(platform_config).expanduser().resolve())

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    print(
        f"{settings.app_name} v{settings.app_version}  -  {settings.problem_statement}"
    )
    print(f"Console  http://{host}:{port}/")
    print(f"API docs http://{host}:{port}/docs")
    print("Models load on first use; run `python -m satquery warmup` to preload.\n")

    uvicorn.run(
        "satquery.api:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
    )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    from .orchestrator import SatQueryEngine

    settings = get_settings()
    engine = SatQueryEngine(settings)
    report = engine.health()

    print(f"{settings.app_name} v{settings.app_version}")
    print(f"Status        {report['status']}")
    print(f"Device        {report['device']}")
    print()

    print("Dependencies")
    for name, info in report["dependencies"].items():
        mark = "ok     " if info["installed"] else "MISSING"
        print(f"  {mark} {name:<16} {info.get('version') or ''}")
    print()

    print("Backends")
    for name, info in report["backends"].items():
        if not isinstance(info, dict) or "available" not in info:
            continue
        mark = "ok     " if info["available"] else "not set"
        reason = f"  ({info['reason']})" if info.get("reason") else ""
        print(f"  {mark} {name}{reason}")
    print()

    if report["setup_actions"]:
        print("Next steps")
        for action in report["setup_actions"]:
            print(f"  - {action}")
    else:
        print("Everything needed is configured.")

    try:
        platform = _platform_api_request("GET", "/api/v1/platform/runtime")
    except SatQueryError:
        print(
            "Platform runtime  not reachable (start `satquery serve` for live status)"
        )
    else:
        print(
            "Platform runtime  "
            f"{platform['state']} · {platform['connector_count']} implementations · "
            f"{platform['dataset_count']} datasets · {platform['mission_count']} missions"
        )

    return 0 if report["ready"] else 2


def command_warmup(args: argparse.Namespace) -> int:
    result = _platform_api_request("POST", "/api/v1/warmup")
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


def command_ask(args: argparse.Namespace) -> int:
    import httpx

    upload_files = []
    try:
        for image_path in args.image:
            path = Path(image_path)
            handle = path.open("rb")
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            upload_files.append(("files", (path.name, handle, content_type)))
        form = {"query": args.query, "include_trace": "true"}
        if args.modality:
            form["modality_hint"] = args.modality.upper()
        if args.tool:
            form["force_tool"] = args.tool
        response = httpx.post(
            f"{_platform_api_url()}/api/v1/query",
            data=form,
            files=upload_files,
            timeout=300,
        )
    except (OSError, httpx.HTTPError):
        from .errors import QueryError

        error = QueryError(
            "The image query could not be submitted to the SatQuery platform.",
            remediation=["Start `python -m satquery serve` and check the image paths."],
        )
        print(f"{error.code}: {error.message}", file=sys.stderr)
        for line in error.remediation:
            print(f"  - {line}", file=sys.stderr)
        return 1
    finally:
        for _, (_, handle, _) in upload_files:
            handle.close()

    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    if not response.is_success:
        detail = body.get("detail") or body.get("error") or response.reason_phrase
        print(f"SatQuery request failed: {detail}", file=sys.stderr)
        for line in body.get("remediation", []):
            print(f"  - {line}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(body, indent=2))
        return 0

    print(body["answer"])
    print()
    print(
        f"[{body['intent']} via {body['plan']['router']} "
        f"-> {', '.join(body['tools_used'])} "
        f"in {body['latency_ms']:.0f} ms]"
    )
    if body.get("platform_investigation_id"):
        print(
            "[platform] "
            f"mission={body['platform_mission_id']} "
            f"investigation={body['platform_investigation_id']} "
            f"execution={body['platform_execution_id']}"
        )
    if args.trace:
        print()
        for step in body["trace"]:
            print(
                f"  {step['step']:<32} {step['latency_ms']:>9.1f} ms  {step['status']}"
            )
            if step.get("detail"):
                print(f"      {step['detail']}")
    return 0


def command_platform_inspect(_args: argparse.Namespace) -> int:
    payload = _platform_api_request("GET", "/api/v1/platform/inspect")
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_capabilities(_args: argparse.Namespace) -> int:
    payload = _platform_api_request("GET", "/api/v1/platform/earth/capabilities")
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_discover(args: argparse.Namespace) -> int:
    references = _platform_api_request(
        "POST", f"/api/v1/platform/connectors/{args.connector_id}/discover"
    )
    print(json.dumps(references, indent=2))
    return 0


def _load_earth_query(path: str) -> EarthQuery:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return EarthQuery.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        from .errors import QueryError

        raise QueryError(
            f"Could not load a valid EarthQuery from {path!r}: {exc}",
            remediation=["Provide a JSON file matching the EarthQuery contract."],
        ) from exc


def command_earth_plan(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file)
    plan = _platform_api_request(
        "POST", "/api/v1/platform/earth/plan", payload=query.model_dump(mode="json")
    )
    print(json.dumps(plan, indent=2))
    return 0


def command_earth_observe(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file)
    result = _platform_api_request(
        "POST", "/api/v1/platform/earth/observe", payload=query.model_dump(mode="json")
    )
    print(json.dumps(result, indent=2))
    return 0


def _platform_api_url() -> str:
    settings = get_settings()
    return os.environ.get(
        "SATQUERY_API_URL", f"http://127.0.0.1:{settings.port}"
    ).rstrip("/")


def _platform_api_request(method: str, path: str, *, payload=None, params=None):
    import httpx

    from .errors import QueryError

    try:
        response = httpx.request(
            method,
            f"{_platform_api_url()}{path}",
            json=payload,
            params=params,
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise QueryError(
            "The SatQuery platform API could not be reached.",
            remediation=[
                "Start the platform with `python -m satquery serve`.",
                "Set SATQUERY_API_URL if the server is not at the local default.",
            ],
        ) from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    if not response.is_success:
        detail = body.get("detail") or body.get("error") or response.reason_phrase
        remediation = body.get("remediation", [])
        raise QueryError(str(detail), remediation=remediation)
    return body


def command_platform_plan(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file)
    endpoint = (
        "/api/v1/platform/earth/plan/explain"
        if args.explain
        else "/api/v1/platform/earth/plan"
    )
    payload = _platform_api_request(
        "POST", endpoint, payload=query.model_dump(mode="json")
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_observe(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file)
    payload = _platform_api_request(
        "POST", "/api/v1/platform/earth/observe", payload=query.model_dump(mode="json")
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_investigate(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file) if args.query_file else None
    payload = {
        "question": args.question,
        "mission_name": args.name,
        "mission_id": args.mission_id,
        "earth_query": query.model_dump(mode="json") if query is not None else None,
    }
    created = _platform_api_request(
        "POST", "/api/v1/platform/investigate", payload=payload
    )
    print(json.dumps(created, indent=2))
    return 0


def command_platform_intelligence_design(args: argparse.Namespace) -> int:
    query = _load_earth_query(args.query_file) if args.query_file else None
    payload = {
        "question": args.question,
        "earth_query": query.model_dump(mode="json") if query is not None else None,
    }
    result = _platform_api_request(
        "POST", "/api/v1/platform/intelligence/design", payload=payload
    )
    print(json.dumps(result, indent=2))
    return 0


def command_platform_list(args: argparse.Namespace) -> int:
    path = (
        "/api/v1/platform/datasets"
        if args.kind == "datasets"
        else "/api/v1/platform/connectors"
    )
    params = {"q": args.query} if args.kind == "datasets" and args.query else None
    if params:
        path += "/search"
    print(json.dumps(_platform_api_request("GET", path, params=params), indent=2))
    return 0


def command_platform_mission(args: argparse.Namespace) -> int:
    if args.mission_command == "show":
        payload = {
            "mission": _platform_api_request(
                "GET", f"/api/v1/platform/missions/{args.mission_id}"
            ),
            "investigations": _platform_api_request(
                "GET", f"/api/v1/platform/missions/{args.mission_id}/investigations"
            ),
        }
    else:
        payload = _platform_api_request("GET", "/api/v1/platform/missions")
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_investigation(args: argparse.Namespace) -> int:
    investigation = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{args.investigation_id}"
    )
    executions = [
        _platform_api_request("GET", f"/api/v1/platform/executions/{result_id}")
        for result_id in investigation.get("result_ids", [])
    ]
    intelligence = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{args.investigation_id}/intelligence"
    )
    temporal_differences = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{args.investigation_id}/temporal-differences"
    )
    observation_stacks = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{args.investigation_id}/observation-stacks"
    )
    payload = {
        "investigation": investigation,
        "intelligence": intelligence,
        "executions": executions,
        "observation_stacks": observation_stacks,
        "temporal_differences": temporal_differences,
    }
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_investigation_execute(args: argparse.Namespace) -> int:
    investigation_id = args.investigation_id
    execution = _platform_api_request(
        "POST", f"/api/v1/platform/investigations/{investigation_id}/execute"
    )
    observations = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{investigation_id}/observations"
    )
    provenance = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{investigation_id}/provenance"
    )
    intelligence = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{investigation_id}/intelligence"
    )
    temporal_differences = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{investigation_id}/temporal-differences"
    )
    observation_stacks = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{investigation_id}/observation-stacks"
    )
    print(
        json.dumps(
            {
                "execution": execution,
                "observations": observations,
                "provenance": provenance,
                "intelligence": intelligence,
                "observation_stacks": observation_stacks,
                "temporal_differences": temporal_differences,
            },
            indent=2,
        )
    )
    return 0 if execution["status"] == "succeeded" else 1


def command_platform_investigation_cancel(args: argparse.Namespace) -> int:
    result = _platform_api_request(
        "POST", f"/api/v1/platform/investigations/{args.investigation_id}/cancel"
    )
    print(json.dumps(result, indent=2))
    return 0


def command_platform_investigation_resume(args: argparse.Namespace) -> int:
    result = _platform_api_request(
        "POST", f"/api/v1/platform/investigations/{args.investigation_id}/resume"
    )
    events = _platform_api_request(
        "GET", f"/api/v1/platform/executions/{result['plan_id']}/events"
    )
    print(json.dumps({"execution": result, "events": events}, indent=2))
    return 0 if result["status"] == "succeeded" else 1


def command_platform_reasoning(args: argparse.Namespace) -> int:
    report = _platform_api_request(
        "GET", f"/api/v1/platform/investigations/{args.investigation_id}/reasoning"
    )
    print(json.dumps(report, indent=2))
    return 0


def command_platform_hypotheses(args: argparse.Namespace) -> int:
    payload = _platform_api_request(
        "GET",
        f"/api/v1/platform/investigations/{args.investigation_id}/hypotheses",
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_investigation_artifact(args: argparse.Namespace) -> int:
    payload = _platform_api_request(
        "GET",
        f"/api/v1/platform/investigations/{args.investigation_id}/{args.artifact}",
    )
    if args.artifact == "report":
        print(payload["markdown"])
    else:
        print(json.dumps(payload, indent=2))
    return 0


def command_platform_investigation_compare(args: argparse.Namespace) -> int:
    payload = _platform_api_request(
        "POST",
        "/api/v1/platform/investigation-comparisons",
        payload={"investigation_ids": args.investigation_ids},
    )
    print(payload["markdown"])
    return 0


def command_platform_scientific_methods(_args: argparse.Namespace) -> int:
    payload = _platform_api_request("GET", "/api/v1/platform/scientific-methods")
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_scientific_workflows(_args: argparse.Namespace) -> int:
    payload = _platform_api_request("GET", "/api/v1/platform/scientific-workflows")
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_scientific_knowledge(args: argparse.Namespace) -> int:
    params = {"domain": args.domain} if args.domain else None
    payload = _platform_api_request(
        "GET", "/api/v1/platform/scientific-knowledge/methods", params=params
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_earth_memory(args: argparse.Namespace) -> int:
    payload_body = {
        "text": args.query or None,
        "artifact_types": args.artifact_type or (),
        "canonical_variable": args.variable or None,
        "limit": args.limit,
    }
    if args.bbox is not None:
        payload_body["spatial_bbox"] = args.bbox
        payload_body["spatial_crs"] = args.crs
    if args.start is not None or args.end is not None:
        payload_body["temporal_start"] = args.start
        payload_body["temporal_end"] = args.end
    payload = _platform_api_request(
        "POST", "/api/v1/platform/earth-memory/search",
        payload=payload_body,
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_platform_earth_objects(args: argparse.Namespace) -> int:
    if args.object_command == "show":
        path = f"/api/v1/platform/earth-objects/id/{args.object_id}"
    elif args.object_command == "graph":
        path = "/api/v1/platform/earth-objects/graph"
        if args.investigation_id:
            path += f"?investigation_id={args.investigation_id}"
    else:
        path = "/api/v1/platform/earth-objects"
        if args.investigation_id:
            path += f"?investigation_id={args.investigation_id}"
    print(json.dumps(_platform_api_request("GET", path), indent=2))
    return 0


def command_platform_runtime(_args: argparse.Namespace) -> int:
    print(
        json.dumps(_platform_api_request("GET", "/api/v1/platform/runtime"), indent=2)
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="satquery", description="SatQuery Earth Intelligence Operating System"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the API and demo console.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument(
        "--platform-config",
        help="JSON platform configuration (for example, to enable durable local history).",
    )
    serve.set_defaults(func=command_serve)

    doctor = sub.add_parser(
        "doctor", help="Report what is installed and what is missing."
    )
    doctor.set_defaults(func=command_doctor)

    warm = sub.add_parser(
        "warmup", help="Load configured models into the running platform."
    )
    warm.set_defaults(func=command_warmup)

    ask = sub.add_parser(
        "ask", help="Run the image-perception capability through the platform API."
    )
    ask.add_argument("query")
    ask.add_argument(
        "-i", "--image", action="append", default=[], help="Image path. Repeatable."
    )
    ask.add_argument("-m", "--modality", default=None, choices=["optical", "sar"])
    ask.add_argument(
        "-t", "--tool", default=None, choices=[item.value for item in ToolName]
    )
    ask.add_argument("--trace", action="store_true", help="Print the execution trace.")
    ask.add_argument(
        "--json", action="store_true", help="Print the full JSON response."
    )
    ask.set_defaults(func=command_ask)

    platform = sub.add_parser(
        "platform", help="Inspect the Earth Intelligence runtime."
    )
    platform_sub = platform.add_subparsers(dest="platform_command", required=True)
    inspect = platform_sub.add_parser(
        "inspect", help="List registered platform capabilities."
    )
    inspect.set_defaults(func=command_platform_inspect)
    capabilities = platform_sub.add_parser(
        "capabilities", help="Print the Earth capability matrix."
    )
    capabilities.set_defaults(func=command_platform_capabilities)
    discover = platform_sub.add_parser(
        "discover", help="Discover datasets from one connector."
    )
    discover.add_argument("connector_id")
    discover.set_defaults(func=command_platform_discover)

    earth = sub.add_parser("earth", help="Plan or run a canonical EarthQuery.")
    earth_sub = earth.add_subparsers(dest="earth_command", required=True)
    plan = earth_sub.add_parser("plan", help="Show modality and dataset coverage.")
    plan.add_argument("query_file", help="Path to a JSON EarthQuery document.")
    plan.set_defaults(func=command_earth_plan)
    observe = earth_sub.add_parser(
        "observe", help="Acquire registered Earth observations."
    )
    observe.add_argument("query_file", help="Path to a JSON EarthQuery document.")
    observe.set_defaults(func=command_earth_observe)

    investigate = sub.add_parser(
        "investigate",
        help="Start an Earth investigation from a natural-language objective.",
    )
    investigate.add_argument("question")
    investigate.add_argument(
        "--query-file", help="Explicit EarthQuery JSON for acquisition."
    )
    investigate.add_argument("--name", help="Mission name; defaults to the objective.")
    investigate.add_argument(
        "--mission-id", help="Add this investigation to an existing mission."
    )
    investigate.set_defaults(func=command_platform_investigate)

    intelligence = sub.add_parser(
        "intelligence", help="Design and inspect evidence strategies."
    )
    intelligence_sub = intelligence.add_subparsers(
        dest="intelligence_command", required=True
    )
    design = intelligence_sub.add_parser(
        "design", help="Design evidence strategies from a scientific question."
    )
    design.add_argument("question")
    design.add_argument("--query-file", help="Explicit EarthQuery JSON criteria.")
    design.set_defaults(func=command_platform_intelligence_design)

    plan = sub.add_parser(
        "plan", help="Plan Earth observation coverage from EarthQuery JSON."
    )
    plan.add_argument("query_file")
    plan.add_argument(
        "--explain", action="store_true", help="Include query and selection basis."
    )
    plan.set_defaults(func=command_platform_plan)

    explain = sub.add_parser(
        "explain", help="Explain registered coverage for an EarthQuery."
    )
    explain.add_argument("query_file")
    explain.set_defaults(func=command_platform_plan, explain=True)

    observe = sub.add_parser(
        "observe", help="Acquire Earth observations from EarthQuery JSON."
    )
    observe.add_argument("query_file")
    observe.set_defaults(func=command_platform_observe)

    capabilities_cmd = sub.add_parser(
        "capabilities", help="Print the Earth capability matrix."
    )
    capabilities_cmd.set_defaults(func=command_platform_capabilities)

    datasets_cmd = sub.add_parser("datasets", help="List registered Earth datasets.")
    datasets_cmd.add_argument("--query", help="Search registered dataset metadata.")
    datasets_cmd.set_defaults(func=command_platform_list, kind="datasets")

    connectors_cmd = sub.add_parser(
        "connectors", help="List registered sensing implementations."
    )
    connectors_cmd.set_defaults(func=command_platform_list, kind="connectors")

    mission_cmd = sub.add_parser("mission", help="Inspect local Earth missions.")
    mission_sub = mission_cmd.add_subparsers(dest="mission_command", required=True)
    mission_sub.add_parser("list", help="List missions.").set_defaults(
        func=command_platform_mission
    )
    mission_show = mission_sub.add_parser(
        "show", help="Show a mission and its investigations."
    )
    mission_show.add_argument("mission_id")
    mission_show.set_defaults(func=command_platform_mission)

    investigation_cmd = sub.add_parser(
        "investigation", help="Inspect an investigation and executions."
    )
    investigation_sub = investigation_cmd.add_subparsers(
        dest="investigation_command", required=True
    )
    investigation_show = investigation_sub.add_parser("show")
    investigation_show.add_argument("investigation_id")
    investigation_show.set_defaults(func=command_platform_investigation)
    investigation_execute = investigation_sub.add_parser(
        "execute", help="Execute a ready investigation plan."
    )
    investigation_execute.add_argument("investigation_id")
    investigation_execute.set_defaults(func=command_platform_investigation_execute)
    investigation_cancel = investigation_sub.add_parser(
        "cancel", help="Request cooperative cancellation of an investigation."
    )
    investigation_cancel.add_argument("investigation_id")
    investigation_cancel.set_defaults(func=command_platform_investigation_cancel)
    investigation_resume = investigation_sub.add_parser(
        "resume", help="Resume an interrupted workflow from safe task checkpoints."
    )
    investigation_resume.add_argument("investigation_id")
    investigation_resume.set_defaults(func=command_platform_investigation_resume)
    for artifact in ("audit", "reproducibility", "report"):
        artifact_command = investigation_sub.add_parser(
            artifact, help=f"Export the investigation {artifact} record."
        )
        artifact_command.add_argument("investigation_id")
        artifact_command.set_defaults(
            func=command_platform_investigation_artifact, artifact=artifact
        )
    compare = investigation_sub.add_parser(
        "compare", help="Align recorded canonical measurements across investigations."
    )
    compare.add_argument("investigation_ids", nargs="+", help="At least two investigation IDs.")
    compare.set_defaults(func=command_platform_investigation_compare)

    reasoning_cmd = sub.add_parser(
        "reasoning", help="Inspect scientific evaluation traces."
    )
    reasoning_sub = reasoning_cmd.add_subparsers(
        dest="reasoning_command", required=True
    )
    reasoning_show = reasoning_sub.add_parser(
        "show", help="Show a stored reasoning report."
    )
    reasoning_show.add_argument("investigation_id")
    reasoning_show.set_defaults(func=command_platform_reasoning)
    reasoning_sub.add_parser(
        "methods",
        help="Inspect registered scientific methods and their validation state.",
    ).set_defaults(func=command_platform_scientific_methods)

    science_cmd = sub.add_parser(
        "science", help="Inspect scientific method and investigation scaffolds."
    )
    science_sub = science_cmd.add_subparsers(dest="science_command", required=True)
    science_sub.add_parser(
        "methods", help="Inspect versioned methods and domain catalog status."
    ).set_defaults(func=command_platform_scientific_methods)
    science_sub.add_parser(
        "workflows", help="List configuration-only investigation templates."
    ).set_defaults(func=command_platform_scientific_workflows)
    science_methods = science_sub.add_parser(
        "library", help="List independently documented domain method records."
    )
    science_methods.add_argument("--domain", help="Filter by Earth-science domain.")
    science_methods.set_defaults(func=command_platform_scientific_knowledge)

    memory_cmd = sub.add_parser(
        "memory", help="Search indexed Earth investigation artifacts."
    )
    memory_sub = memory_cmd.add_subparsers(dest="memory_command", required=True)
    memory_search = memory_sub.add_parser("search", help="Search Earth Memory by text, time, and space.")
    memory_search.add_argument("query", nargs="?", default="")
    memory_search.add_argument("--artifact-type", action="append", choices=(
        "investigation", "plan", "observation", "evidence", "hypothesis",
        "scientific_method", "reproducibility_artifact", "provenance_node",
        "earth_object", "object_relationship", "observation_stack",
        "temporal_difference",
    ))
    memory_search.add_argument(
        "--variable",
        help="Filter by an exact canonical Earth variable identifier, such as ndvi or precipitation_amount.",
    )
    memory_search.add_argument("--limit", type=int, default=100)
    memory_search.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_X", "MIN_Y", "MAX_X", "MAX_Y"))
    memory_search.add_argument("--crs", help="CRS identifier required with --bbox.")
    memory_search.add_argument("--start", help="Timezone-aware ISO-8601 interval start; requires --end.")
    memory_search.add_argument("--end", help="Timezone-aware ISO-8601 interval end; requires --start.")
    memory_search.set_defaults(func=command_platform_earth_memory)

    objects_cmd = sub.add_parser(
        "objects", help="Inspect evidence-backed canonical Earth Objects."
    )
    objects_sub = objects_cmd.add_subparsers(dest="object_command", required=True)
    objects_list = objects_sub.add_parser("list", help="List materialized Earth Objects.")
    objects_list.add_argument("--investigation-id")
    objects_list.set_defaults(func=command_platform_earth_objects)
    objects_show = objects_sub.add_parser("show", help="Inspect an object and its traceability.")
    objects_show.add_argument("object_id")
    objects_show.set_defaults(func=command_platform_earth_objects)
    objects_graph = objects_sub.add_parser("graph", help="Inspect object relationships.")
    objects_graph.add_argument("--investigation-id")
    objects_graph.set_defaults(func=command_platform_earth_objects)

    hypotheses_cmd = sub.add_parser(
        "hypotheses", help="Inspect hypothesis lifecycle and transition history."
    )
    hypotheses_sub = hypotheses_cmd.add_subparsers(
        dest="hypotheses_command", required=True
    )
    hypotheses_show = hypotheses_sub.add_parser("show")
    hypotheses_show.add_argument("investigation_id")
    hypotheses_show.set_defaults(func=command_platform_hypotheses)

    runtime_cmd = sub.add_parser(
        "runtime", help="Inspect local runtime and connector health."
    )
    runtime_cmd.set_defaults(func=command_platform_runtime)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    if not getattr(args, "command", None):
        args = parser.parse_args((argv or []) + ["serve"])

    try:
        return int(args.func(args))
    except SatQueryError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        for line in exc.remediation:
            print(f"  - {line}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
