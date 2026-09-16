r"""Run and archive the Phase 1 acceptance checks.

Examples from satquery-ai/:

    ..\.venv\Scripts\python.exe scripts\run_phase1.py
    ..\.venv\Scripts\python.exe scripts\run_phase1.py --real
    ..\.venv\Scripts\python.exe scripts\run_phase1.py --real --profile fast
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent
RESULTS_ROOT = PACKAGE_ROOT / "test_runs" / "phase1"
DURATION_PATTERN = re.compile(r"PHASE1_LATENCY query=.*? seconds=(?P<seconds>\d+(?:\.\d+)?)")


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    duration_s: float
    output_file: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    key_durations_s: list[float] | None = None


@dataclass
class RunSummary:
    timestamp_utc: str
    run_directory: str
    package_root: str
    python_executable: str
    profile: str
    real_acceptance_enabled: bool
    commands: list[CommandResult]
    environment_notes: list[str]
    final_verdict: str


def _parse_counts(output: str) -> tuple[int, int, int]:
    def last_count(label: str) -> int:
        matches = re.findall(rf"(\d+) {label}\b", output)
        return int(matches[-1]) if matches else 0

    return last_count("passed"), last_count("failed"), last_count("skipped")


def _parse_durations(output: str) -> list[float]:
    return [float(match.group("seconds")) for match in DURATION_PATTERN.finditer(output)]


def _run(command: Sequence[str], env: dict[str, str], output_path: Path) -> CommandResult:
    started = __import__("time").perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=PACKAGE_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = __import__("time").perf_counter() - started
    output_path.write_text(completed.stdout, encoding="utf-8")
    passed, failed, skipped = _parse_counts(completed.stdout)
    return CommandResult(
        command=list(command),
        returncode=completed.returncode,
        duration_s=round(duration, 3),
        output_file=str(output_path.relative_to(PROJECT_ROOT)),
        passed=passed,
        failed=failed,
        skipped=skipped,
        key_durations_s=_parse_durations(completed.stdout),
    )


def _markdown(summary: RunSummary) -> str:
    lines = [
        "# Phase 1 Test Run",
        "",
        f"- Timestamp (UTC): `{summary.timestamp_utc}`",
        f"- Profile: `{summary.profile}`",
        f"- Real acceptance enabled: `{summary.real_acceptance_enabled}`",
        f"- Python: `{summary.python_executable}`",
        f"- Final verdict: **{summary.final_verdict}**",
        "",
        "## Commands",
        "",
    ]
    for index, result in enumerate(summary.commands, 1):
        lines.extend(
            [
                f"### {index}. `{' '.join(result.command)}`",
                "",
                f"- Exit code: `{result.returncode}`",
                f"- Duration: `{result.duration_s:.3f}s`",
                f"- Passed: `{result.passed}`",
                f"- Failed: `{result.failed}`",
                f"- Skipped: `{result.skipped}`",
                f"- Raw output: `{result.output_file}`",
            ]
        )
        if result.key_durations_s:
            lines.append(
                "- Key measured query latencies (seconds): "
                + ", ".join(f"{value:.3f}" for value in result.key_durations_s)
            )
        lines.append("")
    lines.extend(["## Environment notes", ""])
    lines.extend(f"- {note}" for note in summary.environment_notes)
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `PASS` means every selected command exited with code 0.",
            "- A skipped real acceptance command means real-model verification was not enabled or prerequisites were unavailable; it is not evidence that real inference passed.",
            "- Inspect the per-command `.txt` files for model loading errors, trace failures, and latency details.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and archive SatQuery Phase 1 acceptance checks.")
    parser.add_argument("--real", action="store_true", help="Also run opt-in real-model acceptance tests.")
    parser.add_argument(
        "--profile",
        choices=("quality", "fast"),
        default=None,
        help="Profile to expose to tests; default preserves the current environment/default.",
    )
    parser.add_argument(
        "--timeout",
        default=None,
        help="Post-warmup real-query timeout passed as SATQUERY_ACCEPTANCE_QUERY_TIMEOUT.",
    )
    args = parser.parse_args(argv)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_directory = RESULTS_ROOT / timestamp
    run_directory.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    if args.profile:
        env["SATQUERY_PROFILE"] = args.profile
    if args.real:
        env["SATQUERY_RUN_REAL_ACCEPTANCE"] = "1"
    if args.timeout:
        env["SATQUERY_ACCEPTANCE_QUERY_TIMEOUT"] = args.timeout

    commands: list[CommandResult] = []
    base = [sys.executable, "-m", "pytest", "tests/test_phase1_acceptance.py", "-s", "-rA"]
    deterministic_env = env.copy()
    deterministic_env.pop("SATQUERY_RUN_REAL_ACCEPTANCE", None)
    deterministic_env.pop("SATQUERY_PROFILE", None)
    commands.append(_run(base, deterministic_env, run_directory / "deterministic.txt"))
    if args.real:
        commands.append(
            _run(
                base + ["-m", "real_acceptance"],
                env,
                run_directory / "real_acceptance.txt",
            )
        )

    environment_notes = [
        f"Working directory: {PACKAGE_ROOT}",
        f"Python version: {sys.version.split()[0]}",
        f"Configured SATQUERY_PROFILE: {env.get('SATQUERY_PROFILE', 'quality (default)')}",
        "Real acceptance uses existing fetched images under data/fetched_images when available.",
        "The runner does not alter source modules or change model defaults.",
    ]
    verdict = "PASS" if all(result.returncode == 0 for result in commands) else "FAIL"
    summary = RunSummary(
        timestamp_utc=timestamp,
        run_directory=str(run_directory.relative_to(PROJECT_ROOT)),
        package_root=str(PACKAGE_ROOT),
        python_executable=sys.executable,
        profile=env.get("SATQUERY_PROFILE", "quality (default)"),
        real_acceptance_enabled=args.real,
        commands=commands,
        environment_notes=environment_notes,
        final_verdict=verdict,
    )
    (run_directory / "summary.json").write_text(
        json.dumps(asdict(summary), indent=2), encoding="utf-8"
    )
    (run_directory / "REPORT.md").write_text(_markdown(summary), encoding="utf-8")
    print(f"Phase 1 verdict: {verdict}")
    print(f"Saved report: {run_directory / 'REPORT.md'}")
    print(f"Saved summary: {run_directory / 'summary.json'}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
