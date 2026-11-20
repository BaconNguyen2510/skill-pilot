"""Offline, stdlib-only Skill Pilot v4 beta verification runner.

This runs local tests and dev-only benchmarks. It cannot attest to real
Codex/Antigravity host-model behavior or independently review human labels.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON = sys.executable
REQUIRED_CHECKS: tuple[tuple[str, list[str]], ...] = (
    ("main_tests", [PYTHON, "-m", "unittest", "discover", "-s", "tests", "-q"]),
    (
        "blind_tests",
        [PYTHON, "-m", "unittest", "discover", "-s", "blind_eval/tests", "-q"],
    ),
    (
        "workflow_tests",
        [PYTHON, "-m", "unittest", "discover", "-s", ".github/tests", "-q"],
    ),
    ("release_verifier", [PYTHON, "eval/verify_rc.py"]),
    ("retrieval_dev", [PYTHON, "eval/v4_retrieval_ablation.py"]),
    ("evidence_dev", [PYTHON, "eval/v4_evidence_ablation.py"]),
    ("markdown_dev", [PYTHON, "eval/v4_markdown_evidence_ablation.py"]),
    ("indented_dev", [PYTHON, "eval/v4_indented_evidence_ablation.py"]),
    ("raw_html_dev", [PYTHON, "eval/v4_raw_html_evidence_ablation.py"]),
    ("composite_dev", [PYTHON, "eval/v4_composite_evidence_ablation.py"]),
    ("source_boundary_dev", [PYTHON, "eval/v4_source_boundary_ablation.py"]),
    ("simulated_hosts", [PYTHON, "eval/v4_host_smoke.py"]),
)
QUICK_CHECK_NAMES = frozenset(
    {"main_tests", "blind_tests", "workflow_tests", "simulated_hosts"}
)


def run_check(name: str, command: list[str], timeout: int = 300) -> dict[str, Any]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        )
        returncode = result.returncode
        text_output = result.stdout + "\n" + result.stderr
        failure = None
    except subprocess.TimeoutExpired:
        returncode = None
        text_output = ""
        failure = "timeout"
    except OSError as exc:
        returncode = None
        text_output = ""
        failure = type(exc).__name__
    return {
        "name": name,
        "command": command,
        "status": "passed" if returncode == 0 else "failed",
        "returncode": returncode,
        "error_class": failure,
        "duration_s": round(time.monotonic() - start, 3),
        "output_tail": text_output[-5000:],
    }


def repository_sha() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return value if len(value) == 40 else None


def create_report(
    *,
    quick: bool = False,
    strict_tools: bool = False,
    include_simulated_hosts: bool = True,
) -> dict[str, Any]:
    checks = list(REQUIRED_CHECKS)
    if not include_simulated_hosts:
        checks = [check for check in checks if check[0] != "simulated_hosts"]
    if quick:
        checks = [check for check in checks if check[0] in QUICK_CHECK_NAMES]
    ruff = shutil.which("ruff")
    if ruff is not None:
        checks.extend(
            (
                ("ruff_format", [ruff, "format", "--check", "."]),
                ("ruff_lint", [ruff, "check", "."]),
            )
        )
    runs = [run_check(name, cmd) for name, cmd in checks]
    if ruff is None:
        runs.append(
            {
                "name": "ruff",
                "status": "failed" if strict_tools else "not_run",
                "reason": "Ruff is not installed. CI runs it separately.",
            }
        )
    passed = all(item["status"] in {"passed", "not_run"} for item in runs)
    if strict_tools and ruff is None:
        passed = False
    return {
        "protocol": "skill_pilot_v4_beta_offline",
        "runtime_python": sys.version.split()[0],
        "os": os.name,
        "checkout_sha": repository_sha(),
        "quick": quick,
        "all_required_checks_passed": passed,
        "native_codex_verified": False,
        "native_antigravity_verified": False,
        "independent_human_evaluation_verified": False,
        "checks": runs,
    }


def write_report_create_only(path: pathlib.Path, report: dict[str, Any]) -> None:
    data = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--strict-tools", action="store_true")
    parser.add_argument(
        "--output", type=pathlib.Path, help="Create-only local JSON receipt"
    )
    args = parser.parse_args()

    report = create_report(quick=args.quick, strict_tools=args.strict_tools)
    for check in report["checks"]:
        print(f"{check['name']}: {check['status']}", file=sys.stderr)
    if args.output is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        try:
            write_report_create_only(args.output, report)
        except OSError as exc:
            print(
                f"Unable to save local receipt: {type(exc).__name__}", file=sys.stderr
            )
            return 1
        print(f"Report saved locally to {args.output}", file=sys.stderr)
    return 0 if report["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
