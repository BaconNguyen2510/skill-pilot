"""Reproducibility and allowlist checks for the optional beta plugin archive."""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import v4_package_beta as package


class BetaArchiveTests(unittest.TestCase):
    def test_version_triple_matches_beta(self) -> None:
        self.assertEqual(
            package.read_versions(),
            (package.VERSION, package.VERSION, package.VERSION),
        )

    def test_archive_is_reproducible_allowlisted_and_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = pathlib.Path(temp) / "one"
            second = pathlib.Path(temp) / "two"
            archive_a, checksum = package.build(first)
            archive_b, _ = package.build(second)
            a = archive_a.read_bytes()
            self.assertEqual(
                hashlib.sha256(a).digest(),
                hashlib.sha256(archive_b.read_bytes()).digest(),
            )
            self.assertIn(hashlib.sha256(a).hexdigest(), checksum.read_text())
            with zipfile.ZipFile(archive_a) as bundle:
                names = set(bundle.namelist())
                self.assertIn("skill-pilot/skills/skill-pilot/SKILL.md", names)
                self.assertIn(
                    "skill-pilot/skills/skill-pilot/scripts/source_recovery.py",
                    names,
                )
                self.assertIn("skill-pilot/plugin.json", names)
                self.assertFalse(any("sealed" in n.casefold() for n in names))
                self.assertFalse(any("/.git/" in n for n in names))
                self.assertTrue(all(n.startswith("skill-pilot/") for n in names))
            with self.assertRaises(FileExistsError):
                package.build(first)


if __name__ == "__main__":
    unittest.main()
