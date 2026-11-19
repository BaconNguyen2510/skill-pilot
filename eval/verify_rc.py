"""Independent RC verification harness (QA-11) running all local gates."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run_step(name: str, cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    return {
        "name": name,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout_tail": "\n".join(proc.stdout.strip().splitlines()[-25:]),
        "stderr_tail": "\n".join(proc.stderr.strip().splitlines()[-25:]),
    }


def main() -> int:
    py = sys.executable
    steps = [
        _run_step(
            "py_compile",
            [py, "-m", "py_compile", "skills/skill-pilot/scripts/skill_scout.py"],
        ),
        _run_step(
            "validate_self_skill",
            [
                py,
                "skills/skill-pilot/scripts/skill_scout.py",
                "validate",
                "skills/skill-pilot",
            ],
        ),
        _run_step(
            "unittest_suite",
            [py, "-m", "unittest", "discover", "-s", "tests", "-q"],
        ),
        _run_step("intake_benchmark", [py, "eval/intake_benchmark.py"]),
        _run_step("prompt_benchmark", [py, "-m", "eval.prompt_benchmark"]),
        _run_step(
            "validate_eval_queries",
            [py, "eval/validate_eval.py", "eval/queries.jsonl"],
        ),
        _run_step(
            "holdout_vs_v210_baseline",
            [
                py,
                "eval/run_eval.py",
                "--split",
                "holdout",
                "--compare-baseline",
                "docs/v3/v2_1_0_eval_baseline.json",
            ],
        ),
    ]
    all_passed = all(s["passed"] for s in steps)
    report = {
        "python": sys.version.split()[0],
        "all_passed": all_passed,
        "steps": steps,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
