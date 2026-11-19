"""Regression and metamorphic tests for NEG-01 query negation handling."""

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
    spec = importlib.util.spec_from_file_location("skill_scout_neg_v3", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load skill_scout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scout = _load_scout()


def _run_search(wh: pathlib.Path, *query_parts: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with (
        mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
        mock.patch.object(scout, "collect_active_skills", return_value=[]),
        mock.patch.object(scout, "collect_codex_skills", return_value=[]),
        mock.patch.object(
            sys,
            "argv",
            ["skill_scout.py", "search", *query_parts, "--format", "json"],
        ),
        contextlib.redirect_stdout(buf),
    ):
        code = scout.main()
    return code, json.loads(buf.getvalue())


class NegationHandlingV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.wh = pathlib.Path(self.tmp.name) / "wh"
        self.wh.mkdir()
        records = []
        skills = [
            (
                "docker-patterns",
                "Docker container deployment and compose workflows.",
                ["docker", "deployment"],
            ),
            (
                "kubernetes-ops",
                "Kubernetes deployment orchestration and helm charts.",
                ["kubernetes", "deployment"],
            ),
            (
                "linux-deploy",
                "General server deployment checklist and systemd release steps.",
                ["deployment", "linux"],
            ),
            (
                "sql-query-tuning",
                "SQL query optimization, logical NOT operators, and index design.",
                ["sql", "database"],
            ),
        ]
        for sid, desc, tags in skills:
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
                    "tags": tags,
                    "path": f"skills/{sid}",
                }
            )
        (self.wh / "skills_index.json").write_text(
            json.dumps(records), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_af1_negative_only_queries_abstain_consistently(self) -> None:
        for q in (
            "not docker",
            "without docker",
            "không docker",
            "khong docker",
            "n\u200bot docker",
            "docker but not docker",
        ):
            code, payload = _run_search(self.wh, q)
            self.assertEqual(code, 1, f"{q!r} -> {payload}")
            self.assertEqual(payload.get("error_code"), "INVALID_QUERY", q)

    def test_af1_mixed_intent_excludes_negated_skills(self) -> None:
        for q in (
            "deployment but not docker",
            "deploy nhưng không docker",
            "deploy nhung khong docker",
        ):
            code, payload = _run_search(self.wh, q)
            self.assertEqual(code, 0, f"{q!r} -> {payload}")
            ids = [m["id"] for m in payload["tier2_warehouse_matches"]]
            self.assertNotIn("docker-patterns", ids, q)
            self.assertTrue(ids, f"Expected non-docker deployment skills for {q!r}")

        code_multi, p_multi = _run_search(
            self.wh, "deploy without docker or kubernetes"
        )
        self.assertEqual(code_multi, 0, p_multi)
        ids_multi = [m["id"] for m in p_multi["tier2_warehouse_matches"]]
        self.assertNotIn("docker-patterns", ids_multi)
        self.assertNotIn("kubernetes-ops", ids_multi)
        self.assertIn("linux-deploy", ids_multi)

    def test_af1_positive_quoted_and_boolean_operator_preserved(self) -> None:
        code_pos, p_pos = _run_search(self.wh, "docker deployment")
        self.assertEqual(code_pos, 0, p_pos)
        self.assertIn(
            "docker-patterns", [m["id"] for m in p_pos["tier2_warehouse_matches"]]
        )

        code_sql, p_sql = _run_search(self.wh, "SQL NOT operator")
        self.assertEqual(code_sql, 0, p_sql)
        self.assertIn(
            "sql-query-tuning", [m["id"] for m in p_sql["tier2_warehouse_matches"]]
        )

        code_q, p_q = _run_search(self.wh, 'Explain "not docker"')
        self.assertEqual(code_q, 0, p_q)
        self.assertIn(
            "docker-patterns", [m["id"] for m in p_q["tier2_warehouse_matches"]]
        )

        # Contractions, Vietnamese "không" questions, "nó" pronoun, and hyphenated prefixes
        code_vi_q, p_vi_q = _run_search(self.wh, "tại sao không chạy được docker")
        self.assertEqual(code_vi_q, 0, p_vi_q)
        self.assertIn(
            "docker-patterns", [m["id"] for m in p_vi_q["tier2_warehouse_matches"]]
        )

        code_no_pron, p_no_pron = _run_search(
            self.wh, "deploy docker để nó chạy tự động"
        )
        self.assertEqual(code_no_pron, 0, p_no_pron)
        self.assertIn(
            "docker-patterns", [m["id"] for m in p_no_pron["tier2_warehouse_matches"]]
        )

        code_contr, p_contr = _run_search(
            self.wh, "deployment: don't use docker and can't use kubernetes"
        )
        self.assertEqual(code_contr, 0, p_contr)
        ids_contr = [m["id"] for m in p_contr["tier2_warehouse_matches"]]
        self.assertNotIn("docker-patterns", ids_contr)

        code_hyph, p_hyph = _run_search(self.wh, "linux-deploy not docker")
        self.assertEqual(code_hyph, 0, p_hyph)
        ids_hyph = [m["id"] for m in p_hyph["tier2_warehouse_matches"]]
        self.assertIn("linux-deploy", ids_hyph)
        self.assertNotIn("docker-patterns", ids_hyph)

    def test_af2_metamorphic_paraphrase_consistency(self) -> None:
        paraphrases = (
            "deployment without docker",
            "Deployment   but   not   DOCKER",
            "deployment except docker",
            "deployment tránh docker",
            "deployment loại trừ docker",
        )
        baseline_ids: list[str] | None = None
        for q in paraphrases:
            code, payload = _run_search(self.wh, q)
            self.assertEqual(code, 0, f"{q!r} -> {payload}")
            ids = [m["id"] for m in payload["tier2_warehouse_matches"]]
            self.assertNotIn("docker-patterns", ids, q)
            if baseline_ids is None:
                baseline_ids = ids
            else:
                self.assertEqual(ids, baseline_ids, q)


if __name__ == "__main__":
    unittest.main()
