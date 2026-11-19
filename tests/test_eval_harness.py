"""Unit and contract tests for Skill Pilot v3 evaluation harness (EVAL-01..12, CORP-01..04)."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import corpus_builder
import metrics
import run_eval
import validate_eval


class EvalHarnessTests(unittest.TestCase):
    def test_hand_calculated_ranking_metrics_eval06(self):
        ranked = ["alt-1", "req-1", "forb-1", "req-2", "other"]
        required = {"req-1", "req-2"}
        alternates = {"alt-1"}
        relevant = required | alternates
        forbidden = {"forb-1"}

        self.assertAlmostEqual(metrics.hit_rate_at_k(ranked, relevant, 1), 1.0)
        self.assertAlmostEqual(metrics.recall_at_k(ranked, relevant, 1), 1 / 3)
        self.assertAlmostEqual(metrics.recall_at_k(ranked, relevant, 5), 1.0)
        self.assertAlmostEqual(metrics.mrr_at_k(["x", "req-1"], relevant, 5), 0.5)
        self.assertAlmostEqual(metrics.precision_at_k(ranked, relevant, 5), 3 / 5)
        self.assertAlmostEqual(metrics.forbidden_hit_rate(ranked, forbidden, 5), 1.0)
        self.assertAlmostEqual(metrics.forbidden_hit_rate(ranked, forbidden, 2), 0.0)

        # Ideal graded order: req-1(2), req-2(2), alt-1(1)
        # Actual grades at positions 1..5: [1, 2, 0, 2, 0]
        ndcg = metrics.ndcg_at_k(ranked, required, alternates, 5)
        self.assertGreater(ndcg, 0.7)
        self.assertLess(ndcg, 1.0)
        self.assertAlmostEqual(
            metrics.ndcg_at_k(["req-1", "req-2", "alt-1"], required, alternates, 5),
            1.0,
        )

    def test_abstention_and_bootstrap_ci_eval08(self):
        preds = [
            {"expected_abstain": True, "predicted_ids": []},
            {"expected_abstain": True, "predicted_ids": ["decoy"]},
            {"expected_abstain": False, "predicted_ids": ["a"]},
            {"expected_abstain": False, "predicted_ids": []},
        ]
        ab = metrics.abstention_metrics(preds)
        self.assertAlmostEqual(ab["precision"], 0.5)
        self.assertAlmostEqual(ab["recall"], 0.5)
        self.assertAlmostEqual(ab["f1"], 0.5)

        diff, lo, hi = metrics.paired_bootstrap_ci(
            [0.0, 0.5, 0.0, 0.5],
            [1.0, 1.0, 0.5, 1.0],
            n_resamples=200,
            seed=42,
        )
        self.assertGreater(diff, 0.0)
        self.assertLessEqual(lo, diff)
        self.assertGreaterEqual(hi, diff)

    def test_validator_rejects_contradictions_and_holdout_leakage_eval01_eval04(self):
        base_rec = {
            "id": "q-test-1",
            "query": "Build a DCF model",
            "language": "en",
            "domain": "finance",
            "split": "dev",
            "intent_family": "dcf",
            "required_skills": ["dcf-valuation"],
            "acceptable_alternates": [],
            "forbidden_skills": ["generic-helper"],
            "ambiguity_tags": [],
            "expected_abstain": False,
            "expected_skill_count": 1,
        }
        self.assertEqual(validate_eval.validate_record(base_rec), [])

        bad_overlap = dict(base_rec, forbidden_skills=["dcf-valuation"])
        self.assertTrue(validate_eval.validate_record(bad_overlap))

        leak_rec = dict(base_rec, id="q-test-2", split="holdout")
        errs = validate_eval.validate_records([base_rec, leak_rec])
        self.assertTrue(any("Split leakage detected" in e for e in errs))

    def test_gold_dataset_passes_validator_and_catalog_links_eval02(self):
        queries_path = EVAL_DIR / "queries.jsonl"
        self.assertEqual(validate_eval.validate_file(queries_path), [])
        records, parse_errors = validate_eval.load_jsonl(queries_path)
        self.assertEqual(parse_errors, [])
        self.assertGreaterEqual(len(records), 120)
        catalog_ids = {spec.skill_id for spec in corpus_builder.CANONICAL_CATALOG}
        for rec in records:
            for field in (
                "required_skills",
                "acceptable_alternates",
                "forbidden_skills",
            ):
                for sid in rec[field]:
                    self.assertIn(sid, catalog_ids)

    def test_synthetic_corpus_determinism_and_permission_fixtures_corp01_corp04(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            env_a = corpus_builder.build_eval_environment(root / "a", seed=42)
            env_b = corpus_builder.build_eval_environment(root / "b", seed=42)
            idx_a = (
                pathlib.Path(env_a["warehouses"][0]) / "skills_index.json"
            ).read_text(encoding="utf-8")
            idx_b = (
                pathlib.Path(env_b["warehouses"][0]) / "skills_index.json"
            ).read_text(encoding="utf-8")
            self.assertEqual(idx_a, idx_b)

            perm = corpus_builder.build_permission_fixtures(root / "perm")
            self.assertIn("created", perm)
            self.assertIn("skipped", perm)

    def test_baseline_gate_self_comparison_passes_eval12(self):
        dev_report = run_eval.evaluate_queries(EVAL_DIR / "queries.jsonl", split="dev")
        passed, diff_report = run_eval.compare_against_baseline(dev_report, dev_report)
        self.assertTrue(passed)
        self.assertEqual(diff_report["mrr@5_diff"], 0.0)
        self.assertEqual(diff_report["forbidden_hit_rate@5_delta"], 0.0)

    def test_cli_output_contract_invariants_eval11(self):
        scout = run_eval.load_scout_module()
        with tempfile.TemporaryDirectory() as tmp:
            env = corpus_builder.build_eval_environment(pathlib.Path(tmp), seed=42)
            code, payload = run_eval._run_scout_search(
                scout, env, "Build DCF valuation model", limit=5
            )
            self.assertEqual(code, 0)
            self.assertIsInstance(payload, dict)
            for key in (
                "query",
                "ranking_policy",
                "warehouses_scanned",
                "ranked_matches",
            ):
                self.assertIn(key, payload)
            # Negative-only query exits non-zero cleanly without crashing.
            neg_code, neg_payload = run_eval._run_scout_search(
                scout, env, "do not use docker", limit=5
            )
            self.assertEqual(neg_code, 1)
            self.assertIsNone(neg_payload)


if __name__ == "__main__":
    unittest.main()
