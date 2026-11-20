"""Deterministic beta tests for goal-persistent, read-only source recovery."""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "skills" / "skill-pilot" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import skill_scout
import source_recovery

SCENARIOS = ROOT / "eval" / "v4_blocked_source_scenarios.jsonl"


class SourceRecoveryBetaTests(unittest.TestCase):
    def test_frozen_en_vi_development_scenarios(self) -> None:
        cases = [
            json.loads(line)
            for line in SCENARIOS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(cases), 12)
        for case in cases:
            with self.subTest(case=case["id"]):
                calls: list[tuple[str, int]] = []

                def discover(query: str, limit: int):
                    calls.append((query, limit))
                    return "completed", [], "No local matches"

                result = source_recovery.make_recovery_plan(
                    goal=case["request"],
                    source_status=case["observed_access"],
                    kind="video",
                    goal_ambiguous=not case["goal_known"],
                    material_provided=case["user_supplied_material"],
                    skill_query=case["skill_query"],
                    discover=discover,
                )
                expected_decisions = {
                    "skill_lookup_then_one_source_input": (
                        "request_missing_source_material"
                    ),
                    "continue_from_supplied_material": "continue_from_user_material",
                    "one_goal_question": "ask_one_goal_question",
                }
                self.assertEqual(
                    result["decision"],
                    expected_decisions[case["expected_recovery_path"]],
                )
                self.assertFalse(result["source_content_fetched"])
                self.assertFalse(result["access_control_bypassed"])
                self.assertEqual(result["external_retries"], 0)
                self.assertNotIn("watched the reel", json.dumps(result).lower())
                if (
                    case["expected_recovery_path"]
                    == "skill_lookup_then_one_source_input"
                ):
                    self.assertEqual(calls, [(case["skill_query"], 5)])
                    self.assertEqual(result["skill_discovery"]["status"], "completed")
                else:
                    self.assertEqual(calls, [])

    def test_private_url_removed_from_goal_and_never_used_as_skill_query(self) -> None:
        calls = []

        def discover(query: str, limit: int):
            calls.append((query, limit))
            return "completed", [], ""

        result = source_recovery.make_recovery_plan(
            goal="Evaluate https://private.example/video?t=SECRET idea",
            source_status="403",
            kind="video",
            discover=discover,
        )
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("private.example", json.dumps(result))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("private.example", calls[0][0])
        with self.assertRaisesRegex(ValueError, "capability"):
            source_recovery.make_recovery_plan(
                goal="Evaluate this video",
                source_status="403",
                kind="video",
                skill_query="https://private.example/secret",
                discover=discover,
            )

    def test_no_provider_reports_unavailable_but_preserves_goal(self) -> None:
        result = source_recovery.make_recovery_plan(
            goal="Evaluate the video idea",
            source_status="login_wall",
            kind="video",
        )
        self.assertTrue(result["goal_preserved"])
        self.assertEqual(result["skill_discovery"]["status"], "unavailable")
        self.assertEqual(result["decision"], "request_missing_source_material")

    def test_discovery_error_is_reported_not_passed(self) -> None:
        def fail(_query: str, _limit: int):
            raise OSError("Disallowed read")

        result = source_recovery.make_recovery_plan(
            goal="Analyze this campaign",
            source_status="timeout",
            kind="video",
            discover=fail,
        )
        self.assertEqual(result["skill_discovery"]["status"], "unavailable")
        self.assertNotIn("Disallowed read", json.dumps(result))

    def test_source_kind_and_size_guards(self) -> None:
        with self.assertRaises(ValueError):
            source_recovery.make_recovery_plan(
                goal="x" * 2001, source_status="403", kind="video"
            )
        with self.assertRaises(ValueError):
            source_recovery.make_recovery_plan(
                goal="Analyze video", source_status="success", kind="video"
            )
        with self.assertRaises(ValueError):
            source_recovery.make_recovery_plan(
                goal="Analyze video", source_status="403", kind="video", limit=100
            )

    def _invoke_cli(self, args: list[str], warehouse: pathlib.Path) -> tuple[int, dict]:
        stdout = io.StringIO()
        with (
            mock.patch.object(
                skill_scout, "resolve_warehouses", return_value=[warehouse]
            ),
            mock.patch.object(skill_scout, "collect_active_skills", return_value=[]),
            mock.patch.object(skill_scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(sys, "argv", ["skill_scout.py", *args]),
            contextlib.redirect_stdout(stdout),
        ):
            code = skill_scout.main()
        return code, json.loads(stdout.getvalue())

    def test_cli_discovers_real_warehouse_skill_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wh = pathlib.Path(root)
            skill = wh / "skills" / "video-idea"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: video-idea\n"
                "description: Video content analysis for marketing ideas.\n---\n"
                "# Video idea\nEvaluate video campaigns and marketing ideas.\n",
                encoding="utf-8",
            )
            (wh / "skills_index.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "video-idea",
                            "name": "video-idea",
                            "path": "skills/video-idea",
                            "description": (
                                "Video content analysis for marketing ideas."
                            ),
                            "tags": ["video", "marketing", "analysis"],
                            "risk": "low",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            rc, out = self._invoke_cli(
                [
                    "recover-source",
                    "--goal",
                    "Evaluate this Facebook video business idea",
                    "--source-status",
                    "403",
                    "--kind",
                    "video",
                    "--harness",
                    "all",
                    "--skill-query",
                    "video marketing analysis",
                ],
                wh,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(out["skill_discovery"]["status"], "completed")
            skills = out["skill_discovery"]["candidates"]
            self.assertTrue(skills)
            self.assertEqual(skills[0]["id"], "video-idea")
            self.assertTrue(skills[0]["requires_inspection"])
            self.assertFalse(out["source_content_fetched"])

    def test_repo_compatibility_wrapper_supports_recovery(self) -> None:
        wrapper = ROOT / "scripts" / "skill_scout.py"
        result = subprocess.run(
            [
                sys.executable,
                str(wrapper),
                "recover-source",
                "--goal",
                "Evaluate this reel",
                "--source-status",
                "blocked",
                "--kind",
                "video",
                "--material-provided",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["decision"], "continue_from_user_material")
        self.assertFalse(data["source_content_fetched"])

    def test_cli_no_match_remains_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            wh = pathlib.Path(root)
            (wh / "skills_index.json").write_text("[]", encoding="utf-8")
            rc, out = self._invoke_cli(
                [
                    "recover-source",
                    "--goal",
                    "Analyze the idea behind the video",
                    "--source-status",
                    "404",
                    "--kind",
                    "video",
                ],
                wh,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(out["skill_discovery"]["status"], "completed")
            self.assertEqual(out["skill_discovery"]["candidates"], [])
            self.assertEqual(out["decision"], "request_missing_source_material")


if __name__ == "__main__":
    unittest.main()
