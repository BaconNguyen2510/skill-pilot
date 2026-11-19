"""Release-blocker verification tests (PROM-09/13/14, COMP-09, QA-06, UX-05/08)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCOUT_PATH = REPO_ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"


def _load_scout():
    spec = importlib.util.spec_from_file_location("skill_scout_rel_v3", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load skill_scout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scout = _load_scout()


def _run_cli(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with (
        mock.patch.object(sys, "argv", ["skill_scout.py", *argv]),
        contextlib.redirect_stdout(buf),
    ):
        code = scout.main()
    return code, buf.getvalue()


class ReleaseBlockersV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_warehouse_skill(
        self, wh: pathlib.Path, skill_id: str, body: str = "body"
    ) -> pathlib.Path:
        sdir = wh / "skills" / skill_id
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: test {skill_id}\n---\n# {skill_id}\n{body}\n",
            encoding="utf-8",
        )
        index_path = wh / "skills_index.json"
        records = (
            json.loads(index_path.read_text("utf-8")) if index_path.exists() else []
        )
        records.append(
            {
                "id": skill_id,
                "name": skill_id,
                "description": f"test {skill_id}",
                "risk": "low",
                "path": f"skills/{skill_id}",
            }
        )
        index_path.write_text(json.dumps(records), encoding="utf-8")
        return sdir

    def test_prom09_13_14_conflict_cleanup_and_idempotence(self) -> None:
        wh = self.root / "wh"
        self._make_warehouse_skill(wh, "alpha", "v1")
        dest = self.root / "dest"
        dest.mkdir()
        sibling = dest / "sibling-skill"
        sibling.mkdir()
        (sibling / "SKILL.md").write_text(
            "---\nname: sibling-skill\ndescription: keep\n---\n", encoding="utf-8"
        )
        non_skill = dest / "notes-dir"
        non_skill.mkdir()
        (non_skill / "keep.txt").write_text("important", encoding="utf-8")

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            # PROM-14: first promote succeeds
            c1, o1 = _run_cli("promote", "alpha", "--dest", str(dest))
            self.assertEqual(c1, 0, o1)
            r1 = json.loads(o1)["install_receipt"]

            # PROM-09: conflict without --overwrite fails with DEST_EXISTS
            c_conf, o_conf = _run_cli("promote", "alpha", "--dest", str(dest))
            self.assertEqual(c_conf, 1)
            self.assertEqual(json.loads(o_conf)["error_code"], "DEST_EXISTS")

            # PROM-14: repeated promote --overwrite is idempotent on receipt hash and leaves no temp artifacts
            c2, o2 = _run_cli("promote", "alpha", "--dest", str(dest), "--overwrite")
            self.assertEqual(c2, 0, o2)
            r2 = json.loads(o2)["install_receipt"]
            self.assertEqual(r1["tree_sha256"], r2["tree_sha256"])
            self.assertEqual(r1["files_copied"], r2["files_copied"])
            self.assertEqual(r1["bytes_copied"], r2["bytes_copied"])

        # PROM-13: sibling and non-skill directories are untouched; no .stage-/.bak-/.lock left
        entries = sorted(p.name for p in dest.iterdir())
        self.assertEqual(entries, ["alpha", "notes-dir", "sibling-skill"])
        self.assertEqual((non_skill / "keep.txt").read_text("utf-8"), "important")

    def test_qa06_interrupted_promotion_recovery_with_stale_lock(self) -> None:
        wh = self.root / "wh_qa06"
        self._make_warehouse_skill(wh, "rec-skill", "recovered")
        dest = self.root / "dest_qa06"
        dest.mkdir()
        # Simulate orphaned artifacts from a SIGKILL mid-swap: .bak-*, .stage-*, and expired dead-PID lockfile
        orphan_bak = dest / ".rec-skill.bak-999999-deadbeef"
        orphan_bak.mkdir()
        (orphan_bak / "SKILL.md").write_text("old", encoding="utf-8")
        orphan_stage = dest / ".rec-skill.stage-deadbeef"
        orphan_stage.mkdir()
        (orphan_stage / "SKILL.md").write_text("partial", encoding="utf-8")
        lock_path = dest / ".skill-pilot-rec-skill.lock"
        lock_path.write_text(
            json.dumps(
                {"pid": 999999, "token": "dead", "created_at": time.time() - 900}
            ),
            encoding="utf-8",
        )
        old_ts = time.time() - (scout.LOCK_STALE_SECONDS + 120)
        os.utime(lock_path, (old_ts, old_ts))

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            # Without --break-stale-lock it must fail conservatively
            c_block, o_block = _run_cli("promote", "rec-skill", "--dest", str(dest))
            self.assertEqual(c_block, 1)
            self.assertEqual(json.loads(o_block)["error_code"], "DEST_LOCKED")

            # With --break-stale-lock it recovers cleanly without deleting unrelated pre-existing backups
            c_ok, o_ok = _run_cli(
                "promote", "rec-skill", "--dest", str(dest), "--break-stale-lock"
            )
            self.assertEqual(c_ok, 0, o_ok)
        self.assertTrue((dest / "rec-skill" / "SKILL.md").is_file())
        self.assertFalse(lock_path.exists())
        self.assertTrue(orphan_bak.exists())

    def test_comp09_corrupted_host_and_warehouse_configs_fail_safely(self) -> None:
        bad_cfg = self.root / "config.json"
        bad_cfg.write_text("{corrupt json", encoding="utf-8")
        bad_toml = self.root / "config.toml"
        bad_toml.write_text("[broken", encoding="utf-8")
        gemini_cfg = self.root / "gemini_cfg"
        gemini_cfg.mkdir()
        bad_local = gemini_cfg / "skill-pilot.local.json"
        bad_local.write_text("not-json", encoding="utf-8")
        fake_plugin_root = self.root / "fake_plugin_root"
        fake_plugin_root.mkdir()
        (fake_plugin_root / "plugin.json").write_text("[]", encoding="utf-8")
        bad_wh = self.root / "bad_wh"
        bad_wh.mkdir()
        (bad_wh / "skills_index.json").write_text("{corrupt", encoding="utf-8")

        with (
            mock.patch.object(scout, "CONFIG_JSON_PATH", bad_cfg),
            mock.patch.object(scout, "CODEX_CONFIG_PATH", bad_toml),
            mock.patch.object(scout, "GEMINI_CONFIG_DIR", gemini_cfg),
            mock.patch.object(scout, "LOCAL_CONFIG_PATHS", (bad_local,)),
            mock.patch.object(scout, "PLUGIN_ROOT", fake_plugin_root),
            mock.patch.object(scout, "GLOBAL_SKILLS_DIR", self.root / "g"),
            mock.patch.object(scout, "PLUGINS_DIR", self.root / "p"),
            mock.patch.object(scout, "BUILTIN_SKILLS_DIR", self.root / "b"),
            mock.patch.object(scout, "CODEX_SKILLS_DIR", self.root / "c"),
            mock.patch.object(scout, "CODEX_CACHE_DIR", self.root / "cc"),
            mock.patch.object(scout, "DEFAULT_WAREHOUSES", (bad_wh,)),
            mock.patch.object(scout, "ECC_WAREHOUSES", ()),
        ):
            code, out = _run_cli("doctor")
            self.assertEqual(code, 0, out)
            doc = json.loads(out)
            self.assertIsNotNone(doc["antigravity_config_error"])
            self.assertEqual(doc["cli_version"], scout.__version__)
            self.assertEqual(doc["manifest_versions"]["plugin.json"], "invalid")
            self.assertEqual(
                doc["manifest_versions"][".codex-plugin/plugin.json"], "missing"
            )
            self.assertFalse(doc["manifest_versions_consistent"])
            self.assertFalse(doc["cli_matches_manifests"])
            self.assertEqual(scout._load_warehouse_records(bad_wh), [])

    def test_ux05_structured_error_codes_and_validate_missing_name(self) -> None:
        c_search, o_search = _run_cli("search", "the", "and", "--format", "json")
        self.assertEqual(c_search, 1)
        self.assertEqual(json.loads(o_search)["error_code"], "INVALID_QUERY")

        c_neg, o_neg = _run_cli("search", "without", "postgres", "--format", "json")
        self.assertEqual(c_neg, 1)
        self.assertEqual(json.loads(o_neg)["error_code"], "INVALID_QUERY")

        missing_ws = self.root / "does-not-exist"
        c_intake, o_intake = _run_cli(
            "intake", "--workspace", str(missing_ws), "--format", "json"
        )
        self.assertEqual(c_intake, 1)
        self.assertEqual(json.loads(o_intake)["error_code"], "WORKSPACE_NOT_FOUND")

        c_empty_ws, o_empty_ws = _run_cli(
            "intake", "--workspace", "", "--format", "json"
        )
        self.assertEqual(c_empty_ws, 1)
        self.assertEqual(json.loads(o_empty_ws)["error_code"], "WORKSPACE_NOT_FOUND")

        no_name_dir = self.root / "no-name-skill"
        no_name_dir.mkdir()
        (no_name_dir / "SKILL.md").write_text(
            "---\ndescription: missing name field\n---\n# Body\n",
            encoding="utf-8",
        )
        c_val, o_val = _run_cli("validate", str(no_name_dir))
        self.assertEqual(c_val, 1)
        v_payload = json.loads(o_val)
        self.assertFalse(v_payload["valid"])
        self.assertTrue(any("Invalid skill name" in e for e in v_payload["errors"]))


if __name__ == "__main__":
    unittest.main()
