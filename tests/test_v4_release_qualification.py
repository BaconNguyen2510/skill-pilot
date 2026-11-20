"""Tests for the host-independent v4 stable-release qualification."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_release_qualification as qualification


class ReleaseQualificationTests(unittest.TestCase):
    def test_contract_explicitly_excludes_host_runtime_claims(self) -> None:
        with (
            mock.patch.object(
                qualification.runner,
                "create_report",
                return_value={"all_required_checks_passed": True, "checks": []},
            ),
            mock.patch.object(
                qualification,
                "read_doctor",
                return_value={
                    "manifest_versions_consistent": True,
                    "cli_matches_manifests": True,
                    "cli_version": qualification.package.VERSION,
                    "manifest_versions": {},
                },
            ),
            mock.patch.object(
                qualification,
                "run",
                return_value={"name": "ruff", "passed": True},
            ),
            mock.patch.object(
                qualification,
                "package_check",
                return_value={"name": "package", "passed": True},
            ),
        ):
            report = qualification.qualification()
        self.assertTrue(report["all_passed"])
        self.assertEqual(
            report["host_runtime_claim"],
            "not evaluated and not required by this qualification",
        )

    def test_receipt_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = pathlib.Path(folder) / "receipt.json"
            qualification.write_create_only(output, {"all_passed": True})
            with self.assertRaises(FileExistsError):
                qualification.write_create_only(output, {"all_passed": False})


if __name__ == "__main__":
    unittest.main()
