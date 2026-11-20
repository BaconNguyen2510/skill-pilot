"""Deterministic adversarial evidence-scope fixtures (not human judgments)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner


class EvidenceScopeV4Tests(unittest.TestCase):
    def test_synthetic_en_vi_contradictions_and_positive_evidence(self) -> None:
        fixture = ROOT / "eval" / "v4_evidence_challenges.jsonl"
        cases = [
            json.loads(line)
            for line in fixture.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(cases), 32)
        with tempfile.TemporaryDirectory() as folder:
            for index, case in enumerate(cases):
                with self.subTest(case_id=case["id"]):
                    skill = pathlib.Path(folder) / str(index) / "SKILL.md"
                    skill.parent.mkdir()
                    skill.write_text(case["skill_md"], encoding="utf-8")
                    result = session_planner.verify_capability_evidence(
                        case["evidence_text"],
                        [{"id": "synthetic", "skill_md_path": str(skill)}],
                        step_text=case["step_text"],
                    )
                    self.assertEqual(result["verified"], case["expected_verified"])

    def test_relevant_denial_of_first_skill_does_not_poison_other_skills(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            denied = root / "negative.md"
            positive = root / "positive.md"
            denied.write_text(
                "# React UI\nBuild React UI components.\nNo support for React UI.\n",
                encoding="utf-8",
            )
            positive.write_text(
                "# React UI\nBuild React UI components.\n",
                encoding="utf-8",
            )
            result = session_planner.verify_capability_evidence(
                '"Build React UI components."',
                [
                    {"id": "negative", "skill_md_path": str(denied)},
                    {"id": "positive", "skill_md_path": str(positive)},
                ],
                step_text="Build React UI",
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["matched_skill_id"], "positive")

    def test_high_sentence_count_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            skill = pathlib.Path(folder) / "SKILL.md"
            skill.write_text("# React UI\n" + "React UI.\n" * 4100, encoding="utf-8")
            self.assertFalse(
                session_planner.extract_skill_capabilities(skill)["readable"]
            )


if __name__ == "__main__":
    unittest.main()
