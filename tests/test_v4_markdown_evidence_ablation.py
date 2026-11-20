"""Synthetic Markdown source integrity fixture contract."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_markdown_evidence_ablation as ablation


class MarkdownEvidenceAblationTests(unittest.TestCase):
    def test_only_dev_synthetic_cases(self) -> None:
        rows = ablation.load_cases()
        self.assertEqual(len(rows), 16)
        self.assertEqual({r["split"] for r in rows}, {"dev"})
        self.assertEqual(
            {r["fixture_origin"] for r in rows}, {"synthetic_markdown_source"}
        )
        self.assertEqual(sum(r["expected_verified"] for r in rows), 8)

    def test_baseline_is_pinned_to_distinct_commit(self) -> None:
        self.assertEqual(len(ablation.MARKDOWN_BASELINE_SHA), 40)
        self.assertNotEqual(
            ablation.MARKDOWN_BASELINE_SHA,
            ablation.current.__name__,
        )


if __name__ == "__main__":
    unittest.main()
