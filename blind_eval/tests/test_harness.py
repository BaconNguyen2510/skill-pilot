"""Synthetic tests for the separate frozen-candidate harness."""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness


def jsonl(path, record):
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


class BlindHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        self.ledger.mkdir()
        self.queries = self.root / "queries.jsonl"
        self.labels = self.root / "labels.jsonl"
        provenance = {
            "author": "synthetic",
            "source": "test fixture",
            "independence": "not a final dataset",
        }
        jsonl(
            self.queries,
            {
                "id": "synthetic-only-001",
                "query": "zebra accordion nebulous synthetic fixture",
                "language": "en",
                "category": "single",
                "intent_family": "synthetic-only-family",
                "provenance": provenance,
            },
        )
        jsonl(
            self.labels,
            {
                "id": "synthetic-only-001",
                "relevant": ["dcf-valuation"],
                "forbidden": [],
                "expected_abstain": False,
                "annotation_provenance": provenance,
                "adjudication_status": "final",
            },
        )
        self.labels_hash = hashlib.sha256(self.labels.read_bytes()).hexdigest()
        self.readiness = mock.patch.object(harness, "query_readiness", return_value=[])
        self.readiness.start()
        self.addCleanup(self.readiness.stop)
        self.runtime = mock.patch.object(harness, "require_deterministic_runtime")
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def test_frozen_candidate_mismatch_fails_closed(self):
        fake = subprocess.CompletedProcess([], 0, stdout="0" * 40)
        with (
            mock.patch.object(harness.subprocess, "run", return_value=fake),
            self.assertRaisesRegex(ValueError, "candidate commit mismatch"),
        ):
            harness.materialize(self.root)

    def test_archive_hashes_are_independent_of_git_line_endings(self):
        canonical = hashlib.sha256(
            subprocess.check_output(
                [
                    "git",
                    "show",
                    "HEAD:skills/skill-pilot/scripts/skill_scout.py",
                ],
                cwd=harness.ROOT,
            )
        ).hexdigest()
        exported = []
        for setting in ("true", "false"):
            with self.subTest(core_autocrlf=setting):
                target = self.root / setting
                target.mkdir()
                with mock.patch.dict(
                    os.environ,
                    {
                        "GIT_CONFIG_COUNT": "1",
                        "GIT_CONFIG_KEY_0": "core.autocrlf",
                        "GIT_CONFIG_VALUE_0": setting,
                    },
                ):
                    hashes = harness.materialize(target)
                self.assertEqual(
                    hashes["skills/skill-pilot/scripts/skill_scout.py"], canonical
                )
                exported.append(hashes)
        self.assertEqual(exported[0], exported[1])

    def test_hash_seed_must_be_fixed_before_python_starts(self):
        script = "from harness import require_deterministic_runtime; require_deterministic_runtime()"
        for seed, expected in (("0", 0), ("1", 1)):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=Path(harness.__file__).parent,
                env=env,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, expected)

    def test_prediction_score_separation_and_single_use(self):
        out = harness.predict(self.queries, self.labels_hash, self.ledger)
        original = (out / "predictions.json").read_bytes()
        prediction = json.loads(original)
        self.assertNotIn("relevant", prediction["rows"][0])
        self.assertNotIn("expected_abstain", prediction["rows"][0])
        self.assertEqual(prediction["candidate"], harness.CANDIDATE)
        with self.assertRaises(FileExistsError):
            harness.predict(self.queries, self.labels_hash, self.ledger)
        report_path = harness.score(self.ledger, self.labels)
        self.assertEqual(
            json.loads(report_path.read_text(encoding="utf-8"))["verdict"],
            "INSUFFICIENT",
        )
        self.assertEqual(original, (out / "predictions.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "already attempted"):
            harness.score(self.ledger, self.labels)

    def test_tampered_prediction_and_labels_are_rejected(self):
        out = harness.predict(self.queries, self.labels_hash, self.ledger)
        prediction = out / "predictions.json"
        original = prediction.read_bytes()
        prediction.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
            harness.score(self.ledger, self.labels)
        prediction.write_bytes(original)
        self.labels.write_text(
            self.labels.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "commitment"):
            harness.score(self.ledger, self.labels)
        self.assertTrue((out / "scoring.started").exists())
        with self.assertRaisesRegex(ValueError, "already attempted"):
            harness.score(self.ledger, self.labels)

    def test_interrupted_prediction_remains_reserved(self):
        with (
            mock.patch.object(
                harness, "predict_one", side_effect=OSError("simulated interruption")
            ),
            self.assertRaises(OSError),
        ):
            harness.predict(self.queries, self.labels_hash, self.ledger)
        with self.assertRaises(FileExistsError):
            harness.predict(self.queries, self.labels_hash, self.ledger)

    def test_bootstrap_and_metric_summary_are_deterministic(self):
        rows = [
            {
                "intent_family": "fixture-a",
                "expected_abstain": False,
                "abstained": False,
                "mrr_at_5": 1.0,
                "recall_at_5": 0.5,
                "forbidden_at_5": 0.0,
            },
            {
                "intent_family": "fixture-b",
                "expected_abstain": True,
                "abstained": True,
                "mrr_at_5": 0.0,
                "recall_at_5": 0.0,
                "forbidden_at_5": 0.0,
            },
        ]
        result = harness.summary(rows)
        self.assertEqual(result["mrr_at_5"], 1.0)
        self.assertEqual(result["recall_at_5"], 0.5)
        self.assertEqual(result["abstention_precision"], 1.0)
        self.assertEqual(result["abstention_recall"], 1.0)
        self.assertEqual(result["abstention_support"], 1)
        self.assertEqual(result["abstention_f1"], 1.0)
        self.assertEqual(
            harness.confidence_intervals(rows), harness.confidence_intervals(rows)
        )

    def test_query_and_label_commitments_use_the_validated_snapshots(self):
        original_query = self.queries.read_bytes()
        validate_queries = harness.validate_queries

        def mutate_original_queries(snapshot, exposed):
            self.queries.write_text("changed after snapshot", encoding="utf-8")
            return validate_queries(snapshot, exposed)

        with mock.patch.object(
            harness, "validate_queries", side_effect=mutate_original_queries
        ):
            out = harness.predict(self.queries, self.labels_hash, self.ledger)
        receipt = json.loads(
            (out / "prediction.receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["query_sha256"], hashlib.sha256(original_query).hexdigest()
        )
        validate_labels = harness.validate_labels

        def mutate_original_labels(snapshot, queries, catalog):
            self.labels.write_text("changed after snapshot", encoding="utf-8")
            return validate_labels(snapshot, queries, catalog)

        with mock.patch.object(
            harness, "validate_labels", side_effect=mutate_original_labels
        ):
            report = json.loads(
                harness.score(self.ledger, self.labels).read_text(encoding="utf-8")
            )
        self.assertEqual(report["labels_sha256"], self.labels_hash)

    def test_candidate_nonzero_result_is_not_counted_as_abstention(self):
        load_runner = harness.load_runner

        def runner_with_error(root):
            runner = load_runner(root)
            runner._run_scout_search = lambda *args, **kwargs: (1, None)
            return runner

        with mock.patch.object(harness, "load_runner", side_effect=runner_with_error):
            out = harness.predict(self.queries, self.labels_hash, self.ledger)
        prediction = json.loads((out / "predictions.json").read_text(encoding="utf-8"))[
            "rows"
        ][0]
        self.assertFalse(prediction["abstained"])
        self.assertEqual(prediction["status"], "error_or_rejected")
        report = json.loads(
            harness.score(self.ledger, self.labels).read_text(encoding="utf-8")
        )
        self.assertEqual(report["failure_counts"]["candidate_errors_or_rejections"], 1)

    def test_intentional_invalid_query_is_an_abstention(self):
        class Scout:
            def cmd_search(self, _args):
                print(json.dumps({"error_code": "INVALID_QUERY"}))
                return 1

        class Runner:
            def _run_scout_search(self, scout, _env, _query, limit):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = scout.cmd_search(None)
                return code, None

        code, _, status = harness.predict_one(Runner(), Scout(), {}, "without widgets")
        self.assertEqual((code, status), (1, "invalid_query_abstention"))

    def test_frozen_candidate_invalid_query_is_an_abstention(self):
        root = self.root / "frozen"
        root.mkdir()
        harness.materialize(root)
        runner = harness.load_runner(root)
        scout = runner.load_scout_module()
        env = runner.build_eval_environment(self.root / "catalog", seed=42)
        code, _, status = harness.predict_one(runner, scout, env, "without docker")
        self.assertEqual((code, status), (1, "invalid_query_abstention"))

    def test_success_with_missing_payload_is_an_error(self):
        class Scout:
            def cmd_search(self, _args):
                return 0

        class Runner:
            def _run_scout_search(self, scout, _env, _query, limit):
                scout.cmd_search(None)
                return 0, None

        code, payload, status = harness.predict_one(Runner(), Scout(), {}, "synthetic")
        self.assertEqual((code, payload, status), (0, None, "invalid_response"))

    def test_insufficient_coverage_does_not_consume_ledger(self):
        self.readiness.stop()
        with self.assertRaisesRegex(ValueError, "coverage insufficient"):
            harness.predict(self.queries, self.labels_hash, self.ledger)
        self.assertFalse(harness.prediction_dir(self.ledger).exists())

    def test_cluster_normalizes_intent_family(self):
        rows = [
            {
                "intent_family": name,
                "expected_abstain": False,
                "abstained": False,
                "mrr_at_5": score,
                "recall_at_5": score,
                "forbidden_at_5": 0.0,
            }
            for name, score in (("Finance-Test", 0.0), ("finance_test", 1.0))
        ]
        intervals = harness.confidence_intervals(rows)
        self.assertEqual(intervals["mrr_at_5"], [0.5, 0.5])

    def test_full_coverage_gate_and_language_intervals_with_synthetic_labels(self):
        self.readiness.stop()
        provenance = {
            "author": "synthetic",
            "source": "test only",
            "independence": "not a final dataset",
        }
        languages = ("en", "vi", "vi_no_diacritic", "mixed")
        cases = [
            {
                "id": f"fixture-{n}",
                "query": f"fixture-{n}",
                "language": languages[n // 50],
                "category": "multi_intent" if n < 40 else "single",
                "intent_family": f"family-{n}",
                "provenance": provenance,
            }
            for n in range(200)
        ]
        labels = [
            {
                "id": row["id"],
                "relevant": [] if n < 40 else ["dcf-valuation"],
                "forbidden": [],
                "expected_abstain": n < 40,
                "annotation_provenance": provenance,
                "adjudication_status": "final",
            }
            for n, row in enumerate(cases)
        ]
        self.queries.write_text(
            "synthetic snapshot for scoring-only test\n", encoding="utf-8"
        )
        self.labels.write_text(
            "".join(json.dumps(item) + "\n" for item in labels), encoding="utf-8"
        )
        label_hash = hashlib.sha256(self.labels.read_bytes()).hexdigest()

        def simulate(_runner, _scout, _env, query):
            if int(query.split("-")[1]) < 40:
                return 1, None, "invalid_query_abstention"
            return 0, {"ranked_matches": [{"id": "dcf-valuation", "score": 1.0}]}, "ok"

        with (
            mock.patch.object(harness, "validate_queries", return_value=cases),
            mock.patch.object(harness, "predict_one", side_effect=simulate),
        ):
            harness.predict(self.queries, label_hash, self.ledger)
        report = json.loads(
            harness.score(self.ledger, self.labels).read_text(encoding="utf-8")
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["coverage"]["cases"], 200)
        self.assertEqual(report["overall"]["abstention_f1"], 1.0)
        self.assertEqual(report["failure_counts"]["invalid_query_abstentions"], 40)
        self.assertIsNotNone(report["by_language"]["en"]["ci95"])


if __name__ == "__main__":
    unittest.main()
