"""Create a host-independent, reproducible v4 release-qualification receipt.

This verifies executable repository contracts only.  It deliberately does not
claim that a particular AI host loaded, interpreted, or executed the skill.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RUFF_COMMAND = ["uvx", "--offline", "--from", "ruff==0.17.5", "ruff"]


def load_module(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = load_module("v4_package_beta", ROOT / "eval" / "v4_package_beta.py")
runner = load_module("v4_beta_runner", ROOT / "eval" / "v4_beta_runner.py")


def run(name: str, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
    )
    return {
        "name": name,
        "command": command,
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "output_tail": (result.stdout + "\n" + result.stderr)[-5000:],
    }


def read_doctor() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "skills/skill-pilot/scripts/skill_scout.py", "doctor"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("skill_scout doctor failed")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise TypeError("skill_scout doctor did not produce an object")
    return payload


def package_check() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skill-pilot-v4-release-") as folder:
        root = pathlib.Path(folder)
        first, _ = package.build(root / "one")
        second, _ = package.build(root / "two")
        same = first.read_bytes() == second.read_bytes()
        return {
            "name": "reproducible_package",
            "passed": same,
            "version": package.VERSION,
            "archive_name": first.name,
        }


def qualification() -> dict[str, Any]:
    version = package.package_version()
    report = runner.create_report(strict_tools=False, include_simulated_hosts=False)
    runner_passed = report["all_required_checks_passed"]
    doctor = read_doctor()
    checks = [
        {
            "name": "stable_semver",
            "passed": bool(SEMVER.fullmatch(version)),
            "version": version,
        },
        {
            "name": "manifest_cli_parity",
            "passed": doctor["manifest_versions_consistent"]
            and doctor["cli_matches_manifests"],
            "cli_version": doctor["cli_version"],
            "manifest_versions": doctor["manifest_versions"],
        },
        {
            "name": "offline_regression_matrix",
            "passed": runner_passed,
            "checks": report["checks"],
        },
        run("ruff_format", [*RUFF_COMMAND, "format", "--check", "."]),
        run("ruff_lint", [*RUFF_COMMAND, "check", "."]),
        package_check(),
    ]
    return {
        "protocol": "skill_pilot_v4_executable_contract_release",
        "scope": "repository code, manifests, package and deterministic tests",
        "host_runtime_claim": "not evaluated and not required by this qualification",
        "version": version,
        "all_passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def write_create_only(path: pathlib.Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    report = qualification()
    write_create_only(args.output, report)
    print(
        json.dumps({"all_passed": report["all_passed"], "version": report["version"]})
    )
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
