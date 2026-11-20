"""Cross-process session-lock liveness checks on Windows and POSIX."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner
import skill_scout


class CrossProcessLockV4Tests(unittest.TestCase):
    def test_live_process_old_lock_cannot_be_stolen_and_dead_one_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = pathlib.Path(temp) / "session.json"
            lock = session.with_name(f".{session.name}.lock")
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            try:
                self.assertIsNone(child.poll())
                self.assertTrue(session_planner._session_lock_pid_alive(child.pid))
                self.assertTrue(skill_scout._is_pid_alive(child.pid))
                lock.write_text(
                    json.dumps({"pid": child.pid, "token": "other-process"}),
                    encoding="utf-8",
                )
                past = time.time() - 120
                os.utime(lock, (past, past))
                with (
                    self.assertRaises(TimeoutError),
                    session_planner.session_lock(
                        session, timeout_s=0.08, stale_after_s=0.01
                    ),
                ):
                    pass
                self.assertTrue(lock.exists())
                child.terminate()
                child.wait(timeout=8)
                self.assertFalse(session_planner._session_lock_pid_alive(child.pid))
                self.assertFalse(skill_scout._is_pid_alive(child.pid))
                with session_planner.session_lock(
                    session, timeout_s=2.0, stale_after_s=0.01
                ):
                    self.assertTrue(lock.exists())
                self.assertFalse(lock.exists())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=8)

    def test_init_is_create_only_and_preserves_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "session.json"
            initial = session_planner.init_session("Original approved task")
            session_planner.create_session_file_locked(path, initial)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                session_planner.create_session_file_locked(
                    path, session_planner.init_session("Unauthorized replacement")
                )
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_name(f".{path.name}.lock").exists())

    def test_two_cli_initializers_cannot_overwrite_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "session.json"
            script = ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        str(script),
                        "session",
                        "init",
                        "--session",
                        str(path),
                        "--request",
                        request,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for request in ("First task", "Second task")
            ]
            try:
                responses = [proc.communicate(timeout=15) for proc in processes]
            finally:
                for proc in processes:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=5)
            self.assertCountEqual([p.returncode for p in processes], [0, 1])
            self.assertEqual(len(responses), 2)
            stored = session_planner.load_json_file(path)
            self.assertIn(stored["initial_request"], ("First task", "Second task"))
            self.assertEqual(stored["revision"], 1)
            self.assertEqual(len(stored["revision_history"]), 1)
            self.assertFalse(path.with_name(f".{path.name}.lock").exists())

    def test_invalid_pid_never_reclaims_unknown_process(self) -> None:
        self.assertIsNone(session_planner._session_lock_pid_alive(None))
        self.assertIsNone(session_planner._session_lock_pid_alive(-1))
        self.assertIsNone(session_planner._session_lock_pid_alive(True))
        self.assertIsNone(skill_scout._is_pid_alive(True))
        if os.name == "nt":
            self.assertIsNone(session_planner._session_lock_pid_alive(0x100000000))


if __name__ == "__main__":
    unittest.main()
