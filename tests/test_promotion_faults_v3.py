"""Promotion fault matrix, concurrency, rollback, hardlink, and dry-run tests (PROM-02/03/05/06/07)."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "skills" / "skill-pilot" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import skill_scout as scout


def _promote_args(
    skill_id: str,
    dest: pathlib.Path,
    *,
    overwrite: bool = False,
    allow_risky: bool = False,
    dry_run: bool = False,
    break_stale_lock: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        skill_id=skill_id,
        target="antigravity",
        dest=str(dest),
        warehouse=None,
        overwrite=overwrite,
        allow_risky=allow_risky,
        dry_run=dry_run,
        break_stale_lock=break_stale_lock,
        force=False,
    )


class PromotionFaultsV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_wh_skill(
        self,
        wh: pathlib.Path,
        skill_id: str,
        *,
        risk: str = "low",
        body: str = "# Doc\n",
    ) -> pathlib.Path:
        sdir = wh / "skills" / skill_id
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: Synthetic fault test skill\n---\n{body}",
            encoding="utf-8",
        )
        index_path = wh / "skills_index.json"
        records = (
            json.loads(index_path.read_text(encoding="utf-8"))
            if index_path.is_file()
            else []
        )
        records.append(
            {
                "id": skill_id,
                "name": skill_id,
                "path": f"skills/{skill_id}",
                "description": "Synthetic fault test skill",
                "risk": risk,
            }
        )
        index_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return sdir

    def _run_promote_captured(
        self, args: argparse.Namespace
    ) -> tuple[int, dict[str, object]]:
        lines: list[str] = []

        def _capture_print(*values: object, **kwargs: object) -> None:
            lines.append(" ".join(str(v) for v in values))

        with mock.patch("builtins.print", _capture_print):
            code = scout.cmd_promote(args)
        payload = json.loads("\n".join(lines)) if lines else {}
        return code, payload

    def test_concurrent_promotes_different_ids_succeed_independently(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "alpha-skill", body="# Alpha\n")
        self._write_wh_skill(wh, "beta-skill", body="# Beta\n")
        dest = self.root / "dest"

        barrier = threading.Barrier(2, timeout=5.0)
        real_copy = scout._copy_skill_tree_safely
        outputs: dict[str, tuple[int, dict[str, object]]] = {}
        out_lock = threading.Lock()
        thread_lines: dict[int, list[str]] = {}

        def _synchronized_copy(*c_args: object, **c_kwargs: object) -> dict[str, int]:
            barrier.wait()
            return real_copy(*c_args, **c_kwargs)

        def _thread_print(*values: object, **kwargs: object) -> None:
            tid = threading.get_ident()
            with out_lock:
                thread_lines.setdefault(tid, []).append(
                    " ".join(str(v) for v in values)
                )

        def _worker(skill_id: str) -> None:
            tid = threading.get_ident()
            code = scout.cmd_promote(_promote_args(skill_id, dest))
            with out_lock:
                raw = "\n".join(thread_lines.get(tid, []))
                outputs[skill_id] = (code, json.loads(raw) if raw else {})

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
            mock.patch.object(
                scout, "_copy_skill_tree_safely", side_effect=_synchronized_copy
            ),
            mock.patch("builtins.print", _thread_print),
        ):
            t1 = threading.Thread(target=_worker, args=("alpha-skill",))
            t2 = threading.Thread(target=_worker, args=("beta-skill",))
            t1.start()
            t2.start()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

        self.assertEqual(outputs["alpha-skill"][0], 0, outputs["alpha-skill"])
        self.assertEqual(outputs["beta-skill"][0], 0, outputs["beta-skill"])
        self.assertTrue((dest / "alpha-skill" / "SKILL.md").is_file())
        self.assertTrue((dest / "beta-skill" / "SKILL.md").is_file())
        self.assertEqual(
            sorted(p.name for p in dest.iterdir()), ["alpha-skill", "beta-skill"]
        )

    def test_concurrent_promote_same_dest_blocks_cleanly(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "shared-skill", body="# Shared\n")
        dest = self.root / "dest"

        entered = threading.Event()
        release = threading.Event()
        real_copy = scout._copy_skill_tree_safely
        out_lock = threading.Lock()
        thread_lines: dict[int, list[str]] = {}
        winner_result: list[tuple[int, dict[str, object]]] = []

        def _blocking_copy(*c_args: object, **c_kwargs: object) -> dict[str, int]:
            entered.set()
            if not release.wait(timeout=5.0):
                raise TimeoutError("Timed out waiting to release lock holder")
            return real_copy(*c_args, **c_kwargs)

        def _thread_print(*values: object, **kwargs: object) -> None:
            tid = threading.get_ident()
            with out_lock:
                thread_lines.setdefault(tid, []).append(
                    " ".join(str(v) for v in values)
                )

        def _holder() -> None:
            tid = threading.get_ident()
            code = scout.cmd_promote(_promote_args("shared-skill", dest))
            with out_lock:
                raw = "\n".join(thread_lines.get(tid, []))
                winner_result.append((code, json.loads(raw) if raw else {}))

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
            mock.patch("builtins.print", _thread_print),
            mock.patch.object(
                scout, "_copy_skill_tree_safely", side_effect=_blocking_copy
            ),
        ):
            t1 = threading.Thread(target=_holder)
            t1.start()
            self.assertTrue(entered.wait(timeout=5.0))

            loser_tid = threading.get_ident()
            loser_code = scout.cmd_promote(_promote_args("shared-skill", dest))
            with out_lock:
                loser_raw = "\n".join(thread_lines.get(loser_tid, []))
                loser_payload = json.loads(loser_raw) if loser_raw else {}

            self.assertEqual(loser_code, 1, loser_payload)
            self.assertIn(
                "Destination is locked by another promote operation",
                str(loser_payload.get("error", "")),
            )
            release.set()
            t1.join(timeout=10.0)

        self.assertEqual(len(winner_result), 1)
        self.assertEqual(winner_result[0][0], 0, winner_result[0])
        self.assertTrue((dest / "shared-skill" / "SKILL.md").is_file())
        self.assertEqual([p.name for p in dest.iterdir()], ["shared-skill"])

    def test_symlinked_lockfile_rejected_and_never_unlinked(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "sym-lock-skill")
        dest = self.root / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        sentinel = self.root / "sentinel.txt"
        sentinel.write_text("untouched", encoding="utf-8")
        lock_path = dest / ".skill-pilot-sym-lock-skill.lock"
        try:
            os.symlink(sentinel, lock_path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS disallowed symlink creation: {exc}")

        with mock.patch.object(scout, "resolve_warehouses", return_value=[wh]):
            code, payload = self._run_promote_captured(
                _promote_args("sym-lock-skill", dest, break_stale_lock=True)
            )

        self.assertEqual(code, 1, payload)
        self.assertIn(
            "Refusing symlinked destination lockfile", str(payload.get("error", ""))
        )
        self.assertTrue(lock_path.is_symlink())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
        self.assertFalse((dest / "sym-lock-skill").exists())

    def test_symlinked_lockfile_rejected_via_reparse_mock(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "reparse-lock-skill")
        dest = self.root / "dest"
        dest.mkdir(parents=True, exist_ok=True)
        lock_path = dest / ".skill-pilot-reparse-lock-skill.lock"
        lock_path.write_text(
            '{"pid": 1, "token": "x", "created_at": 0}\n', encoding="utf-8"
        )

        real_is_link = scout._is_link_or_reparse

        def _mock_is_link(path: pathlib.Path) -> bool:
            if path == lock_path:
                return True
            return real_is_link(path)

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "_is_link_or_reparse", side_effect=_mock_is_link),
        ):
            code, payload = self._run_promote_captured(
                _promote_args("reparse-lock-skill", dest, break_stale_lock=True)
            )

        self.assertEqual(code, 1, payload)
        self.assertIn(
            "Refusing symlinked destination lockfile", str(payload.get("error", ""))
        )
        self.assertTrue(lock_path.exists())
        self.assertFalse((dest / "reparse-lock-skill").exists())

    def test_swap_failure_rollback_preserves_prior_dir_and_cleans_stage(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "swap-skill", body="# V2 Content\n")
        dest = self.root / "dest"
        prior_dir = dest / "swap-skill"
        prior_dir.mkdir(parents=True, exist_ok=True)
        (prior_dir / "SKILL.md").write_text("# V1 Content\n", encoding="utf-8")
        (prior_dir / "notes.txt").write_text("preserve-me", encoding="utf-8")

        real_replace = os.replace
        calls = 0

        def _fail_second_replace(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated stage swap failure")
            real_replace(src, dst)

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(os, "replace", side_effect=_fail_second_replace),
        ):
            code, payload = self._run_promote_captured(
                _promote_args("swap-skill", dest, overwrite=True)
            )

        self.assertEqual(code, 1, payload)
        self.assertEqual(calls, 3)
        self.assertIn("existing skill restored", str(payload.get("error", "")))
        self.assertEqual(
            (prior_dir / "SKILL.md").read_text(encoding="utf-8"), "# V1 Content\n"
        )
        self.assertEqual(
            (prior_dir / "notes.txt").read_text(encoding="utf-8"), "preserve-me"
        )
        self.assertEqual([p.name for p in dest.iterdir()], ["swap-skill"])

    def test_hardlink_in_source_tree_does_not_alias_promoted_file(self) -> None:
        wh = self.root / "wh"
        sdir = self._write_wh_skill(wh, "hardlink-skill")
        external = self.root / "external_source.md"
        external.write_text("original-payload", encoding="utf-8")
        linked_file = sdir / "linked.md"
        try:
            os.link(external, linked_file)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS disallowed hardlink creation: {exc}")

        dest = self.root / "dest"
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            code, payload = self._run_promote_captured(
                _promote_args("hardlink-skill", dest)
            )

        self.assertEqual(code, 0, payload)
        promoted_copy = dest / "hardlink-skill" / "linked.md"
        self.assertEqual(promoted_copy.read_text(encoding="utf-8"), "original-payload")

        external.write_text("mutated-after-promote", encoding="utf-8")
        self.assertEqual(promoted_copy.read_text(encoding="utf-8"), "original-payload")

    def test_dry_run_zero_mutation_invariant(self) -> None:
        wh = self.root / "wh"
        self._write_wh_skill(wh, "dry-skill", body="# New\n")

        fresh_dest = self.root / "nonexistent_dest"
        with mock.patch.object(scout, "resolve_warehouses", return_value=[wh]):
            code_fresh, payload_fresh = self._run_promote_captured(
                _promote_args("dry-skill", fresh_dest, dry_run=True)
            )

        self.assertEqual(code_fresh, 0, payload_fresh)
        self.assertTrue(payload_fresh.get("dry_run"))
        self.assertFalse(fresh_dest.exists())

        existing_dest = self.root / "existing_dest"
        installed = existing_dest / "dry-skill"
        installed.mkdir(parents=True, exist_ok=True)
        (installed / "SKILL.md").write_text("# Installed V1\n", encoding="utf-8")

        with mock.patch.object(scout, "resolve_warehouses", return_value=[wh]):
            code_existing, payload_existing = self._run_promote_captured(
                _promote_args("dry-skill", existing_dest, overwrite=True, dry_run=True)
            )

        self.assertEqual(code_existing, 0, payload_existing)
        self.assertTrue(payload_existing.get("dry_run"))
        self.assertTrue(payload_existing.get("would_overwrite"))
        self.assertEqual(
            (installed / "SKILL.md").read_text(encoding="utf-8"), "# Installed V1\n"
        )
        self.assertEqual([p.name for p in existing_dest.iterdir()], ["dry-skill"])


if __name__ == "__main__":
    unittest.main()
