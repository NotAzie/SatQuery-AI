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
import sys
from typing import List, Optional

from .config import get_settings
from .errors import SatQueryError
from .schemas import Modality, ToolName


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

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    print(f"{settings.app_name} v{settings.app_version}  -  {settings.problem_statement}")
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

    return 0 if report["ready"] else 2


def command_warmup(args: argparse.Namespace) -> int:
    from .orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    result = engine.warmup()
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


def command_ask(args: argparse.Namespace) -> int:
    from .orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    try:
        response = engine.answer(
            args.query,
            image_paths=args.image,
            modality_hint=Modality(args.modality.upper()) if args.modality else None,
            force_tool=ToolName(args.tool) if args.tool else None,
        )
    except SatQueryError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        for line in exc.remediation:
            print(f"  - {line}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response.model_dump(mode="json"), indent=2))
        return 0

    print(response.answer)
    print()
    print(f"[{response.intent.value} via {response.plan.router} "
          f"-> {', '.join(tool.value for tool in response.tools_used)} "
          f"in {response.latency_ms:.0f} ms]")
    if args.trace:
        print()
        for step in response.trace:
            print(f"  {step.step:<32} {step.latency_ms:>9.1f} ms  {step.status.value}")
            if step.detail:
                print(f"      {step.detail}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="satquery", description="SatQuery AI")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the API and demo console.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=command_serve)

    doctor = sub.add_parser("doctor", help="Report what is installed and what is missing.")
    doctor.set_defaults(func=command_doctor)

    warm = sub.add_parser("warmup", help="Load every configured model now.")
    warm.set_defaults(func=command_warmup)

    ask = sub.add_parser("ask", help="Ask a question from the command line.")
    ask.add_argument("query")
    ask.add_argument("-i", "--image", action="append", default=[], help="Image path. Repeatable.")
    ask.add_argument("-m", "--modality", default=None, choices=["optical", "sar"])
    ask.add_argument("-t", "--tool", default=None, choices=[item.value for item in ToolName])
    ask.add_argument("--trace", action="store_true", help="Print the execution trace.")
    ask.add_argument("--json", action="store_true", help="Print the full JSON response.")
    ask.set_defaults(func=command_ask)

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
