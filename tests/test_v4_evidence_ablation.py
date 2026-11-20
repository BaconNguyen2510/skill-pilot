"""Synthetic development benchmark contract; no hidden or human evaluation."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_evidence_ablation as evidence_ablation  # noqa: E402


class EvidenceAblationTests(unittest.TestCase):
    def test_registered_fixture_has_only_synthetic_dev_cases(self) -> None:
        cases = evidence_ablation.load_dev_cases()
        self.assertEqual(len(cases), 32)
        self.assertEqual(len({row["id"] for row in cases}), len(cases))
        self.assertEqual({row["language"] for row in cases}, {"en", "vi"})
        self.assertTrue(all(row["split"] == "dev" for row in cases))
        self.assertTrue(
            all(row["fixture_origin"] == "synthetic_engineering_case" for row in cases)
        )

    def test_refuses_unregistered_corpus(self) -> None:
        with self.assertRaises(ValueError):
            evidence_ablation.load_dev_cases(ROOT / "eval" / "queries.jsonl")

    def test_confusion_matrix_on_synthetic_predictions(self) -> None:
        data = [
            {
                "expected": expected,
                "actual": actual,
                "id": f"item-{index}",
                "language": "en",
                "category": "synthetic",
                "latency_ms": 0.1,
            }
            for index, (expected, actual) in enumerate(
                ((True, True), (True, False), (False, True), (False, False))
            )
        ]
        result = evidence_ablation.aggregate(data)["overall"]
        self.assertEqual(
            (result["tp"], result["tn"], result["fp"], result["fn"]),
            (1, 1, 1, 1),
        )
        self.assertEqual(result["false_positive_rate"], 0.5)
        self.assertEqual(result["false_negative_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
