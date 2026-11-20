"""Synthetic raw HTML source integrity regression tests."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_raw_html_evidence_ablation as ablation

sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner


class RawHtmlV4Tests(unittest.TestCase):
    def test_dev_only_fixture_integrity(self) -> None:
        cases = ablation.load_cases()
        self.assertEqual(len(cases), 16)
        self.assertEqual(sum(r["expected_verified"] for r in cases), 8)
        self.assertEqual({r["language"] for r in cases}, {"en", "vi"})

    def test_all_synthetic_indented_cases(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
