"""Regression and benchmark tests for v3.1 Vietnamese negation and exclusion-scope handling."""

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
    spec = importlib.util.spec_from_file_location("skill_scout_vi_v31", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load skill_scout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scout = _load_scout()


class VietnameseIntentV31Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.wh = pathlib.Path(self.tmp.name) / "wh"
        self.wh.mkdir()
        items = [
            ("figma-design", "Design UI mockups and prototypes in Figma."),
            ("tailwind-css", "Style web apps with Tailwind CSS utility classes."),
            ("docker-ops", "Containerize and run applications with Docker."),
            ("react-ui", "Build React web applications and components."),
            ("math-subtraction", "Explain phep tru and basic arithmetic operations."),
        ]
        records = []
        for sid, desc in items:
            sdir = self.wh / "skills" / sid
            sdir.mkdir(parents=True)
            (sdir / "SKILL.md").write_text(
                f"---\nname: {sid}\ndescription: {desc}\n---\n# {sid}\n{desc}\n",
                encoding="utf-8",
            )
            records.append(
                {
                    "id": sid,
                    "name": sid,
                    "description": desc,
                    "risk": "low",
                    "tags": [],
                    "path": f"skills/{sid}",
                }
            )
        (self.wh / "skills_index.json").write_text(
            json.dumps(records), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _search_names(self, query: str) -> tuple[int, list[str]]:
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
        return rc, [m["name"] for m in payload.get("ranked_matches", [])]

    def test_01_tru_excludes_figma_keeps_react(self) -> None:
        rc, names = self._search_names("thiết kế react web trừ figma")
        self.assertEqual(rc, 0)
        self.assertIn("react-ui", names)
        self.assertNotIn("figma-design", names)

    def test_02_tru_ra_excludes_docker(self) -> None:
        rc, names = self._search_names("làm react app trừ ra docker")
        self.assertEqual(rc, 0)
        self.assertIn("react-ui", names)
        self.assertNotIn("docker-ops", names)

    def test_03_ngoai_tru_excludes_tailwind(self) -> None:
        rc, names = self._search_names("làm giao diện react ngoại trừ tailwind")
        self.assertEqual(rc, 0)
        self.assertIn("react-ui", names)
        self.assertNotIn("tailwind-css", names)

    def test_04_chu_khong_phai_excludes_figma(self) -> None:
        rc, names = self._search_names("làm react web chứ không phải figma")
        self.assertEqual(rc, 0)
        self.assertIn("react-ui", names)
        self.assertNotIn("figma-design", names)

    def test_05_khong_tinh_excludes_docker(self) -> None:
        rc, names = self._search_names("xây dựng react app không tính docker")
        self.assertEqual(rc, 0)
        self.assertIn("react-ui", names)
        self.assertNotIn("docker-ops", names)

    def test_06_pseudo_negation_phep_tru_not_excluded(self) -> None:
        pos, neg = scout._split_query_negations("giải thích phép trừ trong toán học")
        self.assertIn("phép trừ", pos)
        self.assertEqual(neg, "")

    def test_07_pseudo_negation_tru_khi_not_excluded(self) -> None:
        _pos, neg = scout._split_query_negations("chạy react trừ khi lỗi")
        self.assertEqual(neg, "")

    def test_08_termination_conjunction_nhung_stops_exclusion_scope(self) -> None:
        pos, neg = scout._split_query_negations("trừ figma nhưng dùng react")
        self.assertIn("react", pos)
        self.assertIn("figma", neg)
        self.assertNotIn("react", neg)

    def test_09_conflicting_vi_intent_abstains(self) -> None:
        rc, names = self._search_names("dùng react trừ react")
        self.assertIn(rc, (0, 1))
        self.assertNotIn("react-ui", names)

    def test_10_quoted_tru_literal_preserved(self) -> None:
        pos, neg = scout._split_query_negations('tìm tài liệu "trừ figma" cho react')
        self.assertIn("react", pos)
        self.assertEqual(neg, "")


if __name__ == "__main__":
    unittest.main()
