"""Contract tests for offline beta receipts and unscored host packets."""

from __future__ import annotations

import csv
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_beta_runner
import v4_host_trial_packet


class BetaRunnerTests(unittest.TestCase):
    def test_failed_check_never_claims_success(self) -> None:
        fake = {
            "name": "test",
            "status": "failed",
            "returncode": 1,
            "duration_s": 0.01,
        }
        with (
            mock.patch.object(v4_beta_runner, "run_check", return_value=fake),
            mock.patch.object(v4_beta_runner.shutil, "which", return_value=None),
        ):
            report = v4_beta_runner.create_report(quick=True)
        self.assertFalse(report["all_required_checks_passed"])
        self.assertFalse(report["native_codex_verified"])
        self.assertFalse(report["native_antigravity_verified"])
        self.assertFalse(report["independent_human_evaluation_verified"])

    def test_receipts_are_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder) / "receipt.json"
            v4_beta_runner.write_report_create_only(output, {"all_passed": False})
            saved = output.read_bytes()
            with self.assertRaises(FileExistsError):
                v4_beta_runner.write_report_create_only(output, {"all_passed": True})
            self.assertEqual(output.read_bytes(), saved)

    def test_ruff_unavailable_not_misreported_as_passed(self) -> None:
        fake = {
            "name": "test",
            "status": "passed",
            "returncode": 0,
            "duration_s": 0.01,
        }
        with (
            mock.patch.object(v4_beta_runner, "run_check", return_value=fake),
            mock.patch.object(v4_beta_runner.shutil, "which", return_value=None),
        ):
            report = v4_beta_runner.create_report(quick=True, strict_tools=True)
        self.assertFalse(report["all_required_checks_passed"])
        self.assertEqual(report["checks"][-1]["status"], "failed")

    def test_native_packet_has_no_claimed_results(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder) / "codex_trials"
            data, reviews = v4_host_trial_packet.prepare("codex", output)
            self.assertTrue(data.is_file())
            with reviews.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 12)
            self.assertEqual({row["host"] for row in rows}, {"codex"})
            self.assertTrue(all(not row["overall_pass"] for row in rows))
            self.assertTrue(all(not row["reviewer_id"] for row in rows))
            with self.assertRaises(FileExistsError):
                v4_host_trial_packet.prepare("codex", output)

    def test_packet_rejects_unsupported_host(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                v4_host_trial_packet.prepare(
                    "unknown", pathlib.Path(folder) / "trials"
                )


if __name__ == "__main__":
    unittest.main()
