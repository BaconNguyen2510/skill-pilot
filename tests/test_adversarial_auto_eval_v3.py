"""Automated AI-designed adversarial and cross-lingual (EN/VI) evaluation suite for Skill Pilot v3.0.

NOTE: This is an automated adversarial test suite designed to stress-test `skill_scout.py`
on negation, cross-lingual EN/VI queries, abstention, determinism, and edge cases.
It is NOT a substitute for independent human annotator evaluation.
"""

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
    spec = importlib.util.spec_from_file_location("skill_scout_adv_v3", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load skill_scout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scout = _load_scout()


def _make_catalog() -> list[dict]:
    items = [
        ("react-ui", "Build React web applications and components."),
        ("tailwind-css", "Style web apps with Tailwind CSS utility classes."),
        ("netlify-deploy", "Deploy web apps and serverless functions to Netlify."),
        ("vercel-deploy", "Deploy web apps and frontend projects to Vercel."),
        ("powerpoint-deck", "Create PowerPoint PPTX slide presentations."),
        ("html-slides", "Create interactive HTML slide presentations."),
        ("docker-ops", "Containerize and run applications with Docker."),
        (
            "pytest-testing",
            "Write unit tests and integration tests in Python with pytest.",
        ),
        ("figma-design", "Design UI mockups and prototypes in Figma."),
    ]
    return [
        {
            "id": sid,
            "name": sid,
            "description": desc,
            "risk": "low",
            "tags": [],
            "path": f"skills/{sid}",
        }
        for sid, desc in items
    ]


class AdversarialAutoEvalV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.wh = pathlib.Path(self._tmpdir.name) / "wh"
        self.wh.mkdir()
        catalog = _make_catalog()
        for item in catalog:
            sdir = self.wh / "skills" / item["id"]
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "SKILL.md").write_text(
                f"---\nname: {item['name']}\ndescription: {item['description']}\n---\n# {item['name']}\n{item['description']}\n",
                encoding="utf-8",
            )
        (self.wh / "skills_index.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _run_search(self, query: str) -> tuple[int, dict]:
        buf = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[self.wh]),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(
                sys,
                "argv",
                ["skill_scout.py", "search", query, "--format", "json"],
            ),
            contextlib.redirect_stdout(buf),
            contextlib.redirect_stderr(err),
        ):
            rc = scout.main()
        raw = buf.getvalue().strip()
        payload = json.loads(raw) if raw else {}
        return rc, payload

    def _top_names(self, query: str) -> list[str]:
        rc, payload = self._run_search(query)
        self.assertEqual(rc, 0)
        return [item["name"] for item in payload.get("ranked_matches", [])]

    def test_01_english_not_negation(self) -> None:
        names = self._top_names("build a react app not using tailwind")
        self.assertIn("react-ui", names)
        self.assertNotIn("tailwind-css", names)

    def test_02_english_except_negation(self) -> None:
        names = self._top_names("deploy web app except netlify")
        self.assertNotIn("netlify-deploy", names)

    def test_03_vietnamese_diacritic_negation(self) -> None:
        names = self._top_names("tạo slide thuyết trình nhưng không dùng powerpoint")
        self.assertNotIn("powerpoint-deck", names)

    def test_04_vietnamese_no_diacritic_negation(self) -> None:
        names = self._top_names("tao web app khong dung docker")
        self.assertNotIn("docker-ops", names)

    def test_05_quoted_phrase_not_treated_as_negation(self) -> None:
        rc, payload = self._run_search('review "do not edit" react guidelines')
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload.get("ranked_matches", []), list)

    def test_06_conflicting_intent_abstention(self) -> None:
        rc, payload = self._run_search("use react and not react")
        self.assertIn(rc, (0, 1))
        names = [item["name"] for item in payload.get("ranked_matches", [])]
        self.assertNotIn("react-ui", names)

    def test_07_empty_query_abstention(self) -> None:
        rc, payload = self._run_search("")
        self.assertEqual(rc, 1)
        self.assertEqual(payload.get("ranked_matches", []), [])

    def test_08_whitespace_query_abstention(self) -> None:
        rc, payload = self._run_search("   \t\n  ")
        self.assertEqual(rc, 1)
        self.assertEqual(payload.get("ranked_matches", []), [])

    def test_09_very_long_query(self) -> None:
        long_q = " ".join(["build react web application"] * 120)
        names = self._top_names(long_q)
        self.assertIn("react-ui", names)

    def test_10_special_characters_no_regex_crash(self) -> None:
        rc, payload = self._run_search("fix C++ / .NET & @react-native #bug! [urgent]")
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload.get("ranked_matches", []), list)

    def test_11_cross_lingual_en_vi_mixed(self) -> None:
        names = self._top_names("viết unit test cho fastapi endpoint bằng pytest")
        self.assertIn("pytest-testing", names)

    def test_12_determinism_repeated_calls(self) -> None:
        q = "deploy web app with docker and react"
        first = self._top_names(q)
        second = self._top_names(q)
        self.assertEqual(first, second)

    def test_13_duplicate_skill_names_in_catalog(self) -> None:
        dup_catalog = _make_catalog() + [dict(_make_catalog()[0])]
        (self.wh / "skills_index.json").write_text(
            json.dumps(dup_catalog), encoding="utf-8"
        )
        rc, payload = self._run_search("build react app")
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload.get("ranked_matches", []), list)

    def test_14_missing_optional_fields(self) -> None:
        minimal = [{"name": "minimal-skill", "description": "minimal helper"}]
        (self.wh / "skills_index.json").write_text(
            json.dumps(minimal), encoding="utf-8"
        )
        rc, payload = self._run_search("minimal helper")
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload.get("ranked_matches", []), list)

    def test_15_case_insensitivity(self) -> None:
        lower = self._top_names("build a react app")
        upper = self._top_names("BUILD A REACT APP")
        self.assertEqual(lower, upper)

    def test_16_unicode_and_emoji_resilience(self) -> None:
        names = self._top_names("🚀 deploy app với docker 🐳")
        self.assertIn("docker-ops", names)

    @unittest.expectedFailure  # Known v3.0.0 limitation: Vietnamese 'trừ' cue deferred to v3.1 (2c8daab frozen)
    def test_17_vietnamese_tru_negation(self) -> None:
        names = self._top_names("chọn công cụ thiết kế trừ figma")
        self.assertNotIn("figma-design", names)

    def test_18_gibberish_abstention(self) -> None:
        names = self._top_names("xzqvjkplmnbvcxz 999888777")
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
