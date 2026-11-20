"""Behavioral regression tests for the v3.1.1 Interview Gate and confirmation provenance."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCOUT_PATH = REPO_ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"


def _load_scout():
    spec = importlib.util.spec_from_file_location("skill_scout_ig", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load skill_scout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scout = _load_scout()


class InterviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.wh = self.root / "wh"
        self.wh.mkdir()
        sdir = self.wh / "skills" / "react-ui"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(
            "---\nname: react-ui\ndescription: Build React web apps.\n---\n# react-ui\nBuild React web apps.\n",
            encoding="utf-8",
        )
        (self.wh / "skills_index.json").write_text(
            json.dumps(
                [
                    {
                        "id": "react-ui",
                        "name": "react-ui",
                        "description": "Build React web apps.",
                        "risk": "low",
                        "tags": [],
                        "path": "skills/react-ui",
                    }
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buf = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[self.wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(sys, "argv", ["skill_scout.py", *argv]),
            contextlib.redirect_stdout(buf),
            contextlib.redirect_stderr(err),
        ):
            rc = scout.main()
        raw = buf.getvalue().strip()
        return rc, json.loads(raw) if raw else {}

    def test_01_agent_guess_routed_to_unacknowledged_assumptions(self) -> None:
        sess = self.root / "guess.json"
        self._run_cli(
            [
                "session",
                "init",
                "--session",
                str(sess),
                "--request",
                "Build fitness app",
            ]
        )
        patch = self.root / "p.json"
        patch.write_text(
            json.dumps(
                {
                    "confirmed_requirements": [
                        {
                            "id": "r1",
                            "text": "Mobile workout logger",
                            "source": "agent_guess",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rc, out = self._run_cli(
            ["session", "update", "--session", str(sess), "--patch", str(patch)]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out["session"]["confirmed_requirements"], [])
        self.assertEqual(len(out["session"]["assumptions"]), 1)
        self.assertFalse(out["session"]["assumptions"][0]["acknowledged"])
        self.assertFalse(out["readiness"]["ready_for_planning"])

    def test_02_plan_search_blocked_before_intent_confirmed(self) -> None:
        sess = self.root / "unconf.json"
        self._run_cli(
            [
                "session",
                "init",
                "--session",
                str(sess),
                "--request",
                "Build fitness app",
            ]
        )
        patch = self.root / "p.json"
        patch.write_text(
            json.dumps(
                {
                    "confirmed_requirements": [
                        {
                            "id": "r1",
                            "text": "Fitness web app",
                            "source": "user_explicit",
                        }
                    ],
                    "plan_steps": [
                        {
                            "id": "s1",
                            "title": "React UI",
                            "query": "react",
                            "depends_on": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self._run_cli(
            ["session", "update", "--session", str(sess), "--patch", str(patch)]
        )
        rc, out = self._run_cli(["plan-search", "--session", str(sess)])
        self.assertEqual(rc, 1)
        self.assertEqual(out["error_code"], "DISCOVERY_BLOCKED_UNCONFIRMED_INTENT")

    def test_03_explicit_confirmation_unblocks_plan_search(self) -> None:
        sess = self.root / "conf.json"
        self._run_cli(
            [
                "session",
                "init",
                "--session",
                str(sess),
                "--request",
                "Build fitness app",
            ]
        )
        patch = self.root / "p.json"
        patch.write_text(
            json.dumps(
                {
                    "intent_confirmed": True,
                    "confirmed_requirements": [
                        {
                            "id": "r1",
                            "text": "Fitness web app",
                            "source": "user_confirmed",
                        }
                    ],
                    "plan_steps": [
                        {
                            "id": "s1",
                            "title": "React UI",
                            "query": "react",
                            "depends_on": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self._run_cli(
            ["session", "update", "--session", str(sess), "--patch", str(patch)]
        )
        rc, out = self._run_cli(["plan-search", "--session", str(sess)])
        self.assertEqual(rc, 0)
        self.assertEqual(out["steps"][0]["matches"][0]["id"], "react-ui")


if __name__ == "__main__":
    unittest.main()
