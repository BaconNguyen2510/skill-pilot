"""Regression coverage for the approval gate between discovery and execution."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner


class SkillSelectionConfirmationTests(unittest.TestCase):
    def _ready_session(self) -> dict:
        session = session_planner.init_session("Build a documented React UI")
        return session_planner.update_session(
            session,
            {
                "intent_confirmed": True,
                "confirmed_requirements": [
                    {"id": "goal", "text": "Build the React UI", "source": "user"}
                ],
                "success_criteria": [{"id": "done", "text": "UI renders"}],
                "plan_steps": [
                    {
                        "id": "ui",
                        "title": "Build UI",
                        "query": "react ui",
                        "depends_on": [],
                    }
                ],
            },
        )

    def test_discovery_requires_explicit_selection_confirmation_for_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "session.json"
            session = self._ready_session()
            session_planner.create_session_file_locked(path, session)
            session_planner.persist_discovery_to_session(
                path,
                session["session_id"],
                session["revision"],
                {"steps": [], "capability_gaps": []},
            )
            before = session_planner.load_json_file(path)
            readiness = session_planner.compute_readiness(before)
            self.assertTrue(readiness["has_current_discovery"])
            self.assertFalse(readiness["ready_for_execution"])
            self.assertIn(
                "skill_selection_confirmed", readiness["missing_for_execution"]
            )

            approved = session_planner.confirm_skill_selection_file_locked(
                path, note="User approved the shown skill report"
            )
            self.assertTrue(approved["skill_selection_confirmed"])
            self.assertTrue(
                session_planner.compute_readiness(approved)["ready_for_execution"]
            )

    def test_material_change_invalidates_prior_selection_approval(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "session.json"
            session = self._ready_session()
            session_planner.create_session_file_locked(path, session)
            session_planner.persist_discovery_to_session(
                path,
                session["session_id"],
                session["revision"],
                {"steps": [], "capability_gaps": []},
            )
            session_planner.confirm_skill_selection_file_locked(path, note="Approved")
            changed = session_planner.update_session_file_locked(
                path,
                {"constraints": [{"id": "offline", "text": "No network"}]},
            )
            self.assertFalse(changed["skill_selection_confirmed"])
            self.assertTrue(changed["discovery_stale"])
            self.assertIsNone(changed["last_discovery"])

    def test_spec_tells_host_to_wait_for_user_selection_approval(self) -> None:
        session = self._ready_session()
        session["last_discovery"] = {
            "for_revision": session["revision"],
            "steps": [],
            "capability_gaps": [],
        }
        session["discovery_stale"] = False
        specification = session_planner.render_specification(
            session, session["last_discovery"]
        )
        self.assertIn("CONFIRMATION REQUIRED", specification)
        self.assertIn("Do not execute a skill, install/download one", specification)


if __name__ == "__main__":
    unittest.main()
