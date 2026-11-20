"""Clean git-archive CLI smoke test across simulated Antigravity and Codex layouts.

This validates CLI + packaging on a fresh temp HOME, not native LLM host behavior.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def write_skill(path: pathlib.Path, name: str, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n"
        f"# {name}\n{description}\n",
        encoding="utf-8",
    )


def invoke(script: pathlib.Path, home: pathlib.Path, *args: str) -> dict:
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=script.parents[1] if script.parent.name == "scripts" else script.parent,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=40,
    )
    if result.returncode:
        raise AssertionError(
            f"CLI failure ({' '.join(args)}): code={result.returncode} "
            f"stdout={result.stdout[-800:]} stderr={result.stderr[-800:]}"
        )
    return json.loads(result.stdout)


def archive_checkout(destination: pathlib.Path) -> pathlib.Path:
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        timeout=40,
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(path=destination, filter="data")
    checkout = destination
    if not (checkout / "skills/skill-pilot/scripts/skill_scout.py").is_file():
        raise AssertionError("git archive missing canonical skill runner")
    return checkout


def run_smoke(checkout: pathlib.Path, home: pathlib.Path) -> dict:
    canonical = checkout / "skills/skill-pilot/scripts/skill_scout.py"
    wrapper = checkout / "scripts/skill_scout.py"
    write_skill(
        home / ".gemini/config/skills/ag-demo",
        "ag-demo",
        "Build React web user interfaces.",
    )
    write_skill(
        home / ".codex/skills/cx-demo",
        "cx-demo",
        "Create backend API endpoints.",
    )

    warehouse = home / "warehouse"
    write_skill(
        warehouse / "skills/react-warehouse",
        "react-warehouse",
        "Build React web user interfaces.",
    )
    (warehouse / "skills_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "react-warehouse",
                    "name": "react-warehouse",
                    "path": "skills/react-warehouse",
                    "risk": "low",
                    "tags": ["react"],
                    "description": "Build React web user interfaces.",
                }
            ]
        ),
        encoding="utf-8",
    )

    workspace = home / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text(
        "Project tests: python -m unittest discover -s tests\n",
        encoding="utf-8",
    )

    doctor = invoke(canonical, home, "doctor", "--harness", "all")
    if not doctor.get("manifest_versions_consistent"):
        raise AssertionError("Doctor reported inconsistent plugin manifests")
    inventory = invoke(canonical, home, "inventory", "--harness", "all")
    if not isinstance(inventory, dict):
        raise TypeError("Inventory did not emit JSON")
    intake = invoke(
        canonical, home, "intake", "--workspace", str(workspace), "--format", "json"
    )
    if not isinstance(intake, dict):
        raise TypeError("Intake did not emit JSON")
    inspected = invoke(
        canonical,
        home,
        "inspect",
        str(warehouse / "skills/react-warehouse"),
        "--format",
        "json",
    )
    if inspected.get("name") != "react-warehouse":
        raise AssertionError("Inspect did not resolve warehouse skill")
    dryrun = invoke(
        canonical,
        home,
        "promote",
        "react-warehouse",
        "--warehouse",
        str(warehouse),
        "--dest",
        str(home / ".codex/skills"),
        "--target",
        "codex",
        "--dry-run",
    )
    if not dryrun.get("dry_run"):
        raise AssertionError("Promotion dry run incorrectly modified environment")

    session = home / "session.json"
    patch = home / "confirmed.json"
    invoke(
        canonical,
        home,
        "session",
        "init",
        "--session",
        str(session),
        "--request",
        "Build React UI",
    )
    patch.write_text(
        json.dumps(
            {
                "intent_confirmed": True,
                "confirmed_requirements": [
                    {
                        "id": "r1",
                        "text": "Build a React app",
                        "source": "user_confirmed",
                    }
                ],
                "success_criteria": [{"id": "a1", "text": "UI is accessible"}],
                "plan_steps": [
                    {
                        "id": "ui",
                        "title": "Build React UI",
                        "query": "react",
                        "depends_on": [],
                        "coverage_level": "direct",
                        "capability_evidence": '"Build React web user interfaces."',
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    updated = invoke(
        canonical,
        home,
        "session",
        "update",
        "--session",
        str(session),
        "--patch",
        str(patch),
    )
    if not updated["readiness"]["ready_for_discovery"]:
        raise AssertionError("Confirmed fixture should be discovery-ready")
    search = invoke(
        canonical,
        home,
        "plan-search",
        "--session",
        str(session),
        "--harness",
        "all",
        "--warehouse",
        str(warehouse),
    )
    if search["dependency_validation"]["execution_order"] != ["ui"]:
        raise AssertionError("Plan-search lost dependency order")
    version = subprocess.run(
        [sys.executable, str(wrapper), "--version"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )
    expected_version = json.loads(
        (checkout / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    if version.returncode or expected_version not in version.stdout:
        raise AssertionError("Repository CLI wrapper did not delegate correctly")

    # Human-host UI testing remains out of scope.
    return {
        "doctor": "ok",
        "inventory": "ok",
        "intake": "ok",
        "inspect": "ok",
        "promote_dry_run": "ok",
        "session": "ok",
        "plan_search": "ok",
        "wrapper": "ok",
        "candidate_count": len(search["steps"][0]["matches"]),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        checkout = archive_checkout(root / "checkout")
        home = root / "fake_home"
        home.mkdir()
        summary = run_smoke(checkout, home)
    print(
        json.dumps(
            {
                "status": "passed",
                "mode": "simulated-host-clean-archive",
                "checks": summary,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
