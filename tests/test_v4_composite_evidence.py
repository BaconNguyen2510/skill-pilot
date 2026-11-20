"""Synthetic composite-step source integrity regression tests."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_composite_evidence_ablation as ablation

sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner


class CompositeStepV4Tests(unittest.TestCase):
    def test_dev_only_fixture_integrity(self) -> None:
        cases = ablation.load_cases()
        self.assertEqual(len(cases), 16)
        self.assertEqual(sum(r["expected_verified"] for r in cases), 8)
        self.assertEqual({r["language"] for r in cases}, {"en", "vi"})

    def test_all_synthetic_composite_cases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for index, case in enumerate(ablation.load_cases()):
                with self.subTest(case=case["id"]):
                    path = pathlib.Path(folder) / f"case-{index}" / "SKILL.md"
                    path.parent.mkdir()
                    path.write_text(case["skill_md"], encoding="utf-8")
                    result = session_planner.verify_capability_evidence(
                        case["evidence_text"],
                        [{"id": "skill", "skill_md_path": str(path)}],
                        step_text=case["step_text"],
                    )
                    self.assertEqual(result["verified"], case["expected_verified"])

    def test_separate_skills_cannot_combine_independent_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            react = root / "react.md"
            db = root / "postgres.md"
            react.write_text(
                "# React UI\nBuild React UI components.\n", encoding="utf-8"
            )
            db.write_text(
                "# Postgres\nDesign PostgreSQL database schemas.\n", encoding="utf-8"
            )
            checked = session_planner.verify_capability_evidence(
                '"Build React UI components." "Design PostgreSQL database schemas."',
                [
                    {"id": "react", "skill_md_path": str(react)},
                    {"id": "db", "skill_md_path": str(db)},
                ],
                step_text="Build React UI and PostgreSQL database",
            )
            self.assertFalse(checked["verified"])

    def test_search_query_must_not_mask_missing_title_capability(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            skill = pathlib.Path(folder) / "SKILL.md"
            skill.write_text(
                "# React UI\nBuild React UI components.\n"
                "Design PostgreSQL database schemas.\n",
                encoding="utf-8",
            )

            def search(_query: str, _limit: int) -> int:
                print(
                    json.dumps(
                        {
                            "ranked_matches": [
                                {
                                    "id": "multi",
                                    "exists": True,
                                    "skill_md_path": str(skill),
                                    "score": 20,
                                }
                            ]
                        }
                    )
                )
                return 0

            plan = [
                {
                    "id": "app",
                    "title": "Build React UI and PostgreSQL database",
                    "query": "react ui",
                    "coverage_level": "direct",
                    "capability_evidence": '"Build React UI components."',
                    "depends_on": [],
                }
            ]
            result = session_planner.run_plan_search(plan, search)
            self.assertEqual(result["covered_steps"], 0)
            self.assertEqual(result["steps"][0]["coverage_level"], "unverified_fit")


if __name__ == "__main__":
    unittest.main()
