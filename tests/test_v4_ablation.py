"""V4 dev ablation never consumes the holdout as an experiment input."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_retrieval_ablation as ablation


class V4AblationTests(unittest.TestCase):
    def test_rejects_non_registered_eval_datasets(self) -> None:
        with self.assertRaises(ValueError):
            ablation.run_variant(ROOT / "eval" / "holdout.jsonl", "baseline")

    def test_dev_snapshot_contains_no_holdout_records(self) -> None:
        import json

        path = ROOT / "eval" / "v4_dev_snapshot.jsonl"
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(rows), 80)
        self.assertTrue(all(row["split"] == "dev" for row in rows))

    def test_accepts_only_known_variants(self) -> None:
        scout = ablation.run_eval.load_scout_module()
        with self.assertRaises(ValueError):
            ablation.variant_scorer(scout, "unknown-v4")

    def test_gate_refuses_forbidden_regression(self) -> None:
        baseline = {
            "overall": {"mrr@5": 0.5, "recall@5": 0.5, "abstention_f1": 1.0},
            "by_language": {
                lang: {"mrr@5": 0.5, "recall@5": 0.5, "forbidden_hit_rate@5": 0}
                for lang in ablation.LANGUAGES
            },
        }
        candidate = {
            "overall": {"mrr@5": 0.6, "recall@5": 0.5, "abstention_f1": 1.0},
            "by_language": {
                lang: dict(values) for lang, values in baseline["by_language"].items()
            },
        }
        candidate["by_language"]["vi"]["forbidden_hit_rate@5"] = 0.1
        verdict = ablation.gate(candidate, baseline)
        self.assertFalse(verdict["forbidden_nonregression"])
        self.assertFalse(verdict["eligible_for_review"])


if __name__ == "__main__":
    unittest.main()
