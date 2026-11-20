"""Regression: uncertainty about a skill is not a request to exclude it."""

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
import skill_scout


class NonExclusionV4Tests(unittest.TestCase):
    def test_knowledge_uncertainty_remains_positive_english(self) -> None:
        for query in (
            "I don't know how to build React components",
            "I do not know how to build React components",
            "I'm not sure how to build React components",
            "I don't understand how to build React components",
        ):
            with self.subTest(query=query):
                positive, negative = skill_scout._split_query_negations(query)
                self.assertIn("React", positive)
                self.assertEqual(negative, "")

    def test_knowledge_uncertainty_remains_positive_vietnamese(self) -> None:
        for query in (
            "Tôi không biết cách viết app React",
            "khong biet cach trien khai React",
            "Tôi không biết nên dùng React thế nào",
        ):
            with self.subTest(query=query):
                positive, negative = skill_scout._split_query_negations(query)
                self.assertIn("React", positive)
                self.assertEqual(negative, "")

    def test_explicit_exclusions_still_apply(self) -> None:
        for query in (
            "Build web UI but don't use React",
            "Build web UI without React",
            "Xây dựng web nhưng không dùng React",
            "Thiết kế UI trừ React",
        ):
            with self.subTest(query=query):
                _positive, negative = skill_scout._split_query_negations(query)
                self.assertIn("react", negative.lower())

    def test_cli_recovers_uncertain_react_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            skill = root / "skills" / "react-ui"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: react-ui\ndescription: Build React web apps.\n---\n"
                "# React UI\nBuild React web apps.\n",
                encoding="utf-8",
            )
            (root / "skills_index.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "react-ui",
                            "name": "react-ui",
                            "path": "skills/react-ui",
                            "risk": "low",
                            "description": "Build React web apps.",
                            "tags": ["react"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with (
                mock.patch.object(
                    skill_scout, "resolve_warehouses", return_value=[root]
                ),
                mock.patch.object(
                    skill_scout, "collect_active_skills", return_value=[]
                ),
                mock.patch.object(skill_scout, "collect_codex_skills", return_value=[]),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "skill_scout.py",
                        "search",
                        "I don't know how to build React",
                        "--format",
                        "json",
                    ],
                ),
                contextlib.redirect_stdout(buffer),
            ):
                rc = skill_scout.main()
            self.assertEqual(rc, 0)
            matches = json.loads(buffer.getvalue())["ranked_matches"]
            self.assertIn("react-ui", [item["id"] for item in matches])


if __name__ == "__main__":
    unittest.main()
