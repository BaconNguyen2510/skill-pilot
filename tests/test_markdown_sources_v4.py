"""Adversarial Markdown provenance regressions; synthetic engineering cases only."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner


class MarkdownEvidenceSourceTests(unittest.TestCase):
    def test_fenced_and_hidden_capability_claims_are_inert(self) -> None:
        file = ROOT / "eval" / "v4_markdown_evidence_challenges.jsonl"
        cases = [
            json.loads(line)
            for line in file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(cases), 16)
        with tempfile.TemporaryDirectory() as folder:
            for index, row in enumerate(cases):
                with self.subTest(case_id=row["id"]):
                    skill = pathlib.Path(folder) / str(index) / "SKILL.md"
                    skill.parent.mkdir()
                    skill.write_text(row["skill_md"], encoding="utf-8")
                    result = session_planner.verify_capability_evidence(
                        row["evidence_text"],
                        [{"id": "synthetic", "skill_md_path": str(skill)}],
                        step_text=row["step_text"],
                    )
                    self.assertEqual(result["verified"], row["expected_verified"])

    def test_unclosed_html_comment_cannot_ground_heading(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            skill = pathlib.Path(folder) / "SKILL.md"
            skill.write_text(
                "# Notes\n<!--\n# React UI\nBuild React UI components.\n",
                encoding="utf-8",
            )
            caps = session_planner.extract_skill_capabilities(skill)
            self.assertTrue(caps["readable"])
            self.assertEqual(caps["headings"], ["Notes"])
            self.assertFalse(
                session_planner.verify_capability_evidence(
                    '"Build React UI components."',
                    [{"id": "sample", "skill_md_path": str(skill)}],
                    step_text="Build React UI",
                )["verified"]
            )

    def test_excessive_markdown_source_lines_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            skill = pathlib.Path(folder) / "SKILL.md"
            skill.write_text("# Notes\n" + "line\n" * 8200, encoding="utf-8")
            self.assertFalse(
                session_planner.extract_skill_capabilities(skill)["readable"]
            )


if __name__ == "__main__":
    unittest.main()
