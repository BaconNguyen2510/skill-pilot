"""V4 phase-1 regression cases: readiness, graph ordering, and evidence gaps."""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner
import skill_scout


def ready_session() -> dict:
    session = session_planner.init_session("Build a React web application")
    return session_planner.update_session(
        session,
        {
            "intent_confirmed": True,
            "confirmed_requirements": [{"id": "r1", "text": "React web app"}],
            "success_criteria": [{"id": "a1", "text": "Login works"}],
            "plan_steps": [
                {"id": "ui", "title": "React UI", "depends_on": []},
            ],
        },
    )


class V4CorrectnessTests(unittest.TestCase):
    def test_success_criteria_are_required_for_discovery(self) -> None:
        session = ready_session()
        self.assertTrue(
            session_planner.compute_readiness(session)["ready_for_discovery"]
        )
        session["success_criteria"] = []
        readiness = session_planner.compute_readiness(session)
        self.assertFalse(readiness["ready_for_discovery"])
        self.assertIn("has_success_criteria", readiness["missing_criteria"])

    def test_interview_change_invalidates_existing_plan(self) -> None:
        session = ready_session()
        for patch in (
            {
                "assumptions": [
                    {"id": "a1", "text": "Offline use", "acknowledged": True}
                ]
            },
            {
                "unresolved_questions": [
                    {"id": "q1", "text": "Need privacy?", "resolved": True}
                ]
            },
            {"decisions": [{"id": "d1", "text": "New mobile constraint"}]},
            {"intent_confirmed": False},
        ):
            with self.subTest(patch=patch):
                changed = session_planner.update_session(session, patch)
                self.assertTrue(changed["plan_stale"])
                self.assertTrue(changed["discovery_stale"])
                self.assertFalse(
                    session_planner.compute_readiness(changed)["ready_for_discovery"]
                )

    def test_valid_plan_is_stably_toposorted(self) -> None:
        steps = [
            {"id": "deploy", "title": "Deploy", "depends_on": ["test"]},
            {"id": "test", "title": "Test", "depends_on": ["code"]},
            {"id": "code", "title": "Code", "depends_on": []},
        ]
        deps = session_planner.validate_plan_dependencies(steps)
        self.assertTrue(deps["valid"])
        self.assertEqual(deps["execution_order"], ["code", "test", "deploy"])

        def search(_query: str, _limit: int) -> int:
            print(json.dumps({"ranked_matches": []}))
            return 0

        output = session_planner.run_plan_search(steps, search)
        self.assertEqual(
            [item["step_id"] for item in output["steps"]],
            ["code", "test", "deploy"],
        )

    def test_invalid_graphs_reject_duplicate_and_missing_ids(self) -> None:
        duplicate = session_planner.validate_plan_dependencies(
            [{"id": "x", "depends_on": []}, {"id": "x", "depends_on": []}]
        )
        self.assertFalse(duplicate["valid"])
        self.assertEqual(duplicate["duplicate_step_ids"], ["x"])
        blank = session_planner.validate_plan_dependencies(
            [{"id": "", "depends_on": []}]
        )
        self.assertFalse(blank["valid"])
        self.assertEqual(blank["missing_step_id_indices"], [0])

    def test_partial_without_uncovered_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill = pathlib.Path(temp) / "SKILL.md"
            skill.write_text("# React\nBuild the UI.\n", encoding="utf-8")

            def search(_query: str, _limit: int) -> int:
                print(
                    json.dumps(
                        {
                            "ranked_matches": [
                                {
                                    "id": "react-ui",
                                    "exists": True,
                                    "skill_md_path": str(skill),
                                }
                            ]
                        }
                    )
                )
                return 0

            output = session_planner.run_plan_search(
                [
                    {
                        "id": "ui",
                        "title": "Build React UI",
                        "coverage_level": "partial",
                        "depends_on": [],
                    }
                ],
                search,
            )
            self.assertEqual(output["covered_steps"], 0)
            self.assertEqual(output["steps"][0]["coverage_level"], "unverified_fit")
            self.assertTrue(output["steps"][0]["capability_gap"])

    def test_spec_shows_execution_order_and_review_gate(self) -> None:
        session = ready_session()
        session["discovery_stale"] = False
        session["plan_steps"] = [
            {"id": "verify", "title": "Verify", "depends_on": ["ui"]},
            {"id": "ui", "title": "Build UI", "depends_on": []},
        ]
        discovery = {
            "for_revision": session["revision"],
            "steps": [
                {"step_id": "ui", "coverage_level": "unverified_fit"},
                {"step_id": "verify", "coverage_level": "partial"},
            ],
        }
        rendered = session_planner.render_specification(session, discovery)
        self.assertIn("## 6. Dependency Order & Next Action", rendered)
        self.assertIn("1. `ui`", rendered)
        self.assertIn("2. `verify`", rendered)
        self.assertIn("REVIEW REQUIRED", rendered)
        self.assertNotIn("**Handoff:**", rendered)

    def test_spec_only_offers_handoff_for_direct_coverage(self) -> None:
        session = ready_session()
        session["discovery_stale"] = False
        discovery = {
            "for_revision": session["revision"],
            "steps": [{"step_id": "ui", "coverage_level": "direct"}],
        }
        rendered = session_planner.render_specification(session, discovery)
        self.assertIn("**Handoff:**", rendered)
        self.assertIn("semantic capability fit", rendered)

    def test_spec_rejects_unversioned_discovery(self) -> None:
        session = ready_session()
        output = session_planner.render_specification(
            session, {"steps": [{"step_id": "ui", "title": "Old candidate"}]}
        )
        self.assertIn("WARNING:", output)
        self.assertNotIn("Old candidate", output)

    def test_lock_never_reclaims_old_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = pathlib.Path(temp) / "session.json"
            with session_planner.session_lock(session, stale_after_s=0.01):
                lock = session.with_name(f".{session.name}.lock")
                old = __import__("time").time() - 100
                __import__("os").utime(lock, (old, old))
                with (
                    self.assertRaises(TimeoutError),
                    session_planner.session_lock(
                        session, timeout_s=0.03, stale_after_s=0.01
                    ),
                ):
                    pass
                self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())

    def test_lock_cleanup_never_deletes_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = pathlib.Path(temp) / "session.json"
            lock = session.with_name(f".{session.name}.lock")
            with session_planner.session_lock(session):
                lock.unlink()
                lock.write_text(
                    json.dumps({"pid": 999999, "token": "other-owner"}),
                    encoding="utf-8",
                )
            self.assertTrue(lock.exists())

    def test_expired_unparseable_lock_can_be_recovered(self) -> None:
        import os
        import time

        with tempfile.TemporaryDirectory() as temp:
            session = pathlib.Path(temp) / "session.json"
            lock = session.with_name(f".{session.name}.lock")
            lock.write_text("{corrupt", encoding="utf-8")
            past = time.time() - 120
            os.utime(lock, (past, past))
            with session_planner.session_lock(session):
                self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())

    def test_corrupt_session_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = pathlib.Path(temp) / "session.json"
            invalid = "{corrupt session json"
            session.write_text(invalid, encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                session_planner.update_session_file_locked(session, {})
            self.assertEqual(session.read_text(encoding="utf-8"), invalid)
            self.assertFalse(session.with_name(f".{session.name}.lock").exists())

    def test_empty_plan_patch_cannot_revalidate_stale_plan(self) -> None:
        base = ready_session()
        stale = session_planner.update_session(
            base,
            {"constraints": [{"id": "c1", "text": "New privacy requirement"}]},
        )
        self.assertTrue(stale["plan_stale"])
        for patch in (
            {"plan_steps": []},
            {"plan_steps": [{"id": "ui", "title": "React UI", "depends_on": []}]},
            {
                "success_criteria": [{"id": "a1", "text": "Login works"}],
                "plan_steps": [],
            },
        ):
            with self.subTest(patch=patch):
                updated = session_planner.update_session(stale, patch)
                self.assertTrue(updated["plan_stale"])
                self.assertFalse(
                    session_planner.compute_readiness(updated)["ready_for_discovery"]
                )

    def test_material_change_with_partial_plan_update_stays_stale(self) -> None:
        base = ready_session()
        changed = session_planner.update_session(
            base,
            {
                "constraints": [{"id": "c1", "text": "Mobile devices supported"}],
                "plan_steps": [{"id": "ui", "title": "React UI", "depends_on": []}],
            },
        )
        self.assertTrue(changed["plan_stale"])
        replacement = session_planner.update_session(
            changed,
            {
                "replace_plan": True,
                "plan_steps": [
                    {"id": "ui", "title": "Responsive UI", "depends_on": []}
                ],
            },
        )
        self.assertFalse(replacement["plan_stale"])
        self.assertTrue(
            session_planner.compute_readiness(replacement)["ready_for_discovery"]
        )

    def test_missing_intent_flag_fails_closed(self) -> None:
        session = ready_session()
        del session["intent_confirmed"]
        readiness = session_planner.compute_readiness(session)
        self.assertFalse(readiness["ready_for_discovery"])
        self.assertIn("intent_confirmed", readiness["missing_for_planning"])

    def test_malformed_plan_patch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "plan_steps must be a list"):
            session_planner.update_session(
                ready_session(), {"plan_steps": {"id": "ui"}}
            )

    def test_persistence_cannot_bypass_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "session.json"
            session = session_planner.init_session("Unconfirmed goal")
            session_planner.save_json_file(path, session)
            with self.assertRaisesRegex(ValueError, "no longer ready"):
                session_planner.persist_discovery_to_session(
                    path,
                    session["session_id"],
                    session["revision"],
                    {"steps": [{"step_id": "ui"}]},
                )
            saved = session_planner.load_json_file(path)
            self.assertNotIn("last_discovery", saved)
            self.assertFalse(path.with_name(f".{path.name}.lock").exists())

    def test_cli_blocks_stale_and_incomplete_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "session.json"
            for update, expected in (
                ({"success_criteria": []}, "has_success_criteria"),
                ({"plan_stale": True}, "plan_current"),
            ):
                with self.subTest(expected=expected):
                    session = ready_session()
                    session.update(update)
                    session_planner.save_json_file(path, session)
                    stdout = io.StringIO()
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            [
                                "skill_scout.py",
                                "plan-search",
                                "--session",
                                str(path),
                            ],
                        ),
                        contextlib.redirect_stdout(stdout),
                    ):
                        rc = skill_scout.main()
                    self.assertEqual(rc, 1)
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(
                        payload["error_code"], "DISCOVERY_BLOCKED_NOT_READY"
                    )
                    self.assertIn(expected, payload["missing_criteria"])


if __name__ == "__main__":
    unittest.main()
