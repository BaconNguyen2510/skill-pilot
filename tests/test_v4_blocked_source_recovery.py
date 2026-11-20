"""V4 release-blocker tests: blocked-source goal persistence and skill discovery.

These deterministic tests check instructions, synthetic scenarios and CLI
discovery plumbing. They do NOT simulate native Codex/Antigravity LLM behavior
and do not satisfy the release's external host-evaluation gate.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "skill-pilot" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import skill_scout

SKILL = ROOT / "skills" / "skill-pilot" / "SKILL.md"
REFERENCE = ROOT / "skills" / "skill-pilot" / "references" / "source-recovery.md"
SCENARIOS = ROOT / "eval" / "v4_blocked_source_scenarios.jsonl"


class BlockedSourceV4Tests(unittest.TestCase):
    def test_release_policy_requires_goal_and_recovery_before_dead_end(self) -> None:
        instructions = SKILL.read_text(encoding="utf-8")
        guide = REFERENCE.read_text(encoding="utf-8")
        self.assertIn(
            "Source-access recovery gate (v4.0 release blocker)", instructions
        )
        self.assertIn("Preserve the goal", instructions)
        self.assertIn(
            "run one bounded, read-only relevant skill discovery", instructions
        )
        self.assertIn("not merely the failed URL", instructions)
        self.assertIn("No access bypass or fabrication", instructions)
        self.assertIn("one concrete source-input question", instructions)
        self.assertIn("does not authorize a full `plan-search` session", instructions)
        self.assertIn("Fast, Guided, and Deep", instructions)
        self.assertIn("--harness all --format json --limit 5", guide)
        self.assertIn("Host lacks video tool", guide)
        self.assertIn("No login bypass", guide)

    def test_synthetic_scenarios_are_complete_and_not_human_labels(self) -> None:
        rows = [
            json.loads(line)
            for line in SCENARIOS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 28)
        self.assertEqual(len({item["id"] for item in rows}), 28)
        self.assertEqual(
            {r["language"] for r in rows}, {"en", "vi", "vi_no_diacritic", "mixed"}
        )
        self.assertEqual(
            {r["platform"] for r in rows},
            {"facebook", "instagram", "tiktok", "youtube", "other"},
        )
        self.assertTrue(
            all(
                r["split"] == "dev"
                and r["fixture_origin"] == "synthetic_blocked_source_release_cases"
                and r["actual_host_result"] is None
                for r in rows
            )
        )
        self.assertEqual(
            {
                r["expected_recovery_path"]
                for r in rows
                if r["goal_known"] and not r["user_supplied_material"]
            },
            {"skill_lookup_then_one_source_input"},
        )
        self.assertEqual(
            {r["expected_recovery_path"] for r in rows if not r["goal_known"]},
            {"one_goal_question"},
        )
        self.assertTrue(all(r["goal_summary"] and r["skill_query"] for r in rows))
        self.assertTrue(
            {"unsupported", "unknown", "timeout", "rate_limit", "deleted", "404", "403"}
            <= {r["observed_access"] for r in rows}
        )

    def _search_warehouse(self, records: list[dict]) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as temp:
            warehouse = pathlib.Path(temp)
            for record in records:
                folder = warehouse / record["path"]
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "SKILL.md").write_text(
                    "---\nname: video-idea-review\n"
                    "description: Analyze video concept and marketing ideas.\n"
                    "---\n# Video idea review\nEvaluate video marketing ideas.\n",
                    encoding="utf-8",
                )
            (warehouse / "skills_index.json").write_text(
                json.dumps(records), encoding="utf-8"
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    skill_scout, "resolve_warehouses", return_value=[warehouse]
                ),
                mock.patch.object(
                    skill_scout, "collect_active_skills", return_value=[]
                ),
                mock.patch.object(skill_scout, "collect_codex_skills", return_value=[]),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "skill_scout.py",
                        "search",
                        "video",
                        "content",
                        "analysis",
                        "marketing",
                        "idea",
                        "--harness",
                        "all",
                        "--format",
                        "json",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                rc = skill_scout.main()
            return rc, json.loads(stdout.getvalue())

    def test_recovery_skill_can_be_discovered_read_only(self) -> None:
        record = {
            "id": "video-idea-review",
            "name": "video-idea-review",
            "path": "skills/video-idea-review",
            "description": "Analyze short-form video content and marketing ideas.",
            "tags": ["video", "analysis", "marketing", "idea"],
            "risk": "low",
        }
        rc, result = self._search_warehouse([record])
        self.assertEqual(rc, 0)
        matched = [item["id"] for item in result["ranked_matches"]]
        self.assertIn("video-idea-review", matched)
        self.assertTrue(result["ranked_matches"][0]["exists"])

    def test_no_available_skill_is_not_invented(self) -> None:
        rc, result = self._search_warehouse([])
        self.assertEqual(rc, 0)
        self.assertEqual(result["ranked_matches"], [])


if __name__ == "__main__":
    unittest.main()
