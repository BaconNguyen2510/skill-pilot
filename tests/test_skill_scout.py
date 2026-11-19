"""Behavior and regression checks for Skill Pilot's local scout."""

import ast
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "skill_scout", ROOT / "scripts" / "skill_scout.py"
)
assert SPEC is not None and SPEC.loader is not None
scout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scout)


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def skill(self, parent, name, description="finance report"):
        folder = parent / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n# Guide\n",
            encoding="utf-8",
        )
        return folder

    def run_command(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = scout.build_parser().parse_args(arguments)
            status = result.func(result)
        return status, output.getvalue()

    def test_vietnamese_aliases_and_scoring(self):
        terms = scout.query_terms("Làm báo cáo tài chính doanh nghiệp")
        self.assertTrue({"report", "finance", "financial"}.issubset(terms))
        self.assertGreater(
            scout.score_record(
                "", terms, "financial-modeling", "", [], "financial report"
            ),
            0,
        )
        self.assertEqual(scout.query_terms("xác thực auth").count("authentication"), 1)
        self.assertTrue(
            {"presentation", "slides"}.issubset(
                scout.query_terms("tạo bài thuyết trình marketing")
            )
        )
        self.assertNotIn(
            "make", scout.query_terms("make a financial report for business")
        )

    def test_compact_and_json_search_skip_missing_hits(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "finance-report")
        (warehouse / "skills_index.json").write_text(
            json.dumps(
                [
                    {
                        "id": "finance-report",
                        "name": "finance-report",
                        "path": "skills/finance-report",
                        "description": "financial report",
                    },
                    {
                        "id": "missing",
                        "name": "finance-report-missing",
                        "path": "skills/missing",
                        "description": "financial report",
                    },
                ]
            ),
            encoding="utf-8",
        )
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, compact = self.run_command(
                "search",
                "bao cao tai chinh",
                "--no-active",
                "--format",
                "compact",
                "--limit",
                "1",
            )
            self.assertEqual(status, 0)
            self.assertIn("warehouse | finance-report |", compact)
            self.assertIn("risk:unknown", compact)
            self.assertNotIn("missing", compact)
            status, raw = self.run_command("search", "finance", "--no-active")
            self.assertEqual(status, 0)
            self.assertEqual(
                [item["id"] for item in json.loads(raw)["tier2_warehouse_matches"]],
                ["finance-report"],
            )

    def test_warehouse_precedence_and_fallback(self):
        cli = self.root / "cli"
        env = self.root / "env"
        fallback = self.root / "fallback"
        ecc = self.root / "ecc"
        for item in (cli, env, fallback, ecc):
            (item / "skills").mkdir(parents=True)
        with (
            mock.patch.dict(os.environ, {"SKILL_PILOT_WAREHOUSES": str(env)}),
            mock.patch.object(scout, "LOCAL_CONFIG_PATHS", ()),
            mock.patch.object(
                scout, "DEFAULT_WAREHOUSES", (self.root / "missing", fallback)
            ),
            mock.patch.object(scout, "ECC_WAREHOUSES", (ecc,)),
        ):
            self.assertEqual(
                scout.resolve_warehouses(str(cli)), [cli, env, fallback, ecc]
            )

    def test_local_config_file_loads_warehouses(self):
        local_wh = self.root / "local-warehouse"
        (local_wh / "skills").mkdir(parents=True)
        cfg = self.root / "skill-pilot.local.json"
        cfg.write_text(json.dumps({"warehouses": [str(local_wh)]}), encoding="utf-8")
        with (
            mock.patch.dict(os.environ, {"SKILL_PILOT_WAREHOUSES": ""}),
            mock.patch.object(scout, "LOCAL_CONFIG_PATHS", (cfg,)),
            mock.patch.object(scout, "DEFAULT_WAREHOUSES", ()),
            mock.patch.object(scout, "ECC_WAREHOUSES", ()),
        ):
            self.assertEqual(scout.resolve_warehouses(None), [local_wh])

    def test_codex_enabled_and_dormant_are_separate(self):
        active = self.root / "codex" / "skills"
        inactive = self.root / "codex" / "skills-inactive"
        self.skill(active, "active-one")
        self.skill(inactive, "dormant-one")
        with (
            mock.patch.object(scout, "CODEX_SKILLS_DIR", active),
            mock.patch.object(scout, "CODEX_INACTIVE_SKILLS_DIR", inactive),
            mock.patch.object(scout, "_codex_plugin_sources", return_value=[]),
        ):
            self.assertEqual(
                [s["name"] for s in scout.collect_codex_skills()], ["active-one"]
            )
            dormant = scout.collect_codex_skills(include_inactive=True)
            self.assertEqual(
                [(s["name"], s["inactive"]) for s in dormant],
                [("active-one", False), ("dormant-one", True)],
            )

    def test_disabled_registered_plugin_is_searchable_only_when_requested(self):
        config = self.root / "config.toml"
        cache = self.root / "cache"
        self.skill(cache / "example" / "example" / "1.0" / "skills", "cached-skill")
        config.write_text(
            '[plugins."example@example"]\nenabled = false\n', encoding="utf-8"
        )
        with (
            mock.patch.object(scout, "CODEX_CONFIG_PATH", config),
            mock.patch.object(scout, "CODEX_CACHE_DIR", cache),
        ):
            self.assertEqual(scout._codex_plugin_sources(), [])
            sources = scout._codex_plugin_sources(include_inactive=True)
            self.assertEqual(
                sources,
                [("example@example", cache / "example" / "example" / "1.0", False)],
            )

    def test_no_active_still_searches_dormant_skills(self):
        dormant = {
            "name": "dormant-finance",
            "description": "finance report",
            "source": "codex-skill-inactive",
            "inactive": True,
            "skill_md_path": "example/SKILL.md",
            "shadowed": False,
        }
        with (
            mock.patch.object(scout, "collect_codex_skills", return_value=[dormant]),
            mock.patch.object(scout, "resolve_warehouses", return_value=[]),
        ):
            status, output = self.run_command(
                "search", "finance", "--harness", "codex", "--no-active"
            )
        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(output)["inactive_codex_skill_matches"][0]["name"],
            "dormant-finance",
        )

    def test_duplicate_identity_prefers_active_then_warehouse(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "finance-tool")
        active = {
            "name": "finance-tool",
            "description": "finance",
            "source": "plugin:demo",
            "shadowed": False,
            "skill_md_path": "active/SKILL.md",
        }
        dormant = {**active, "inactive": True, "source": "codex-plugin-inactive:demo"}
        records = [
            {
                "id": "finance-tool",
                "name": "finance-tool",
                "path": "skills/finance-tool",
                "description": "finance",
            }
        ]
        with (
            mock.patch.object(scout, "collect_active_skills", return_value=[active]),
            mock.patch.object(scout, "collect_codex_skills", return_value=[dormant]),
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
        ):
            _, output = self.run_command("search", "finance", "--harness", "all")
            result = json.loads(output)
            self.assertEqual(len(result["tier1_active_matches"]), 1)
            self.assertEqual(result["tier2_warehouse_matches"], [])
            self.assertEqual(result["inactive_codex_skill_matches"], [])
            _, output = self.run_command(
                "search", "finance", "--harness", "all", "--no-active"
            )
            result = json.loads(output)
            self.assertEqual(len(result["tier2_warehouse_matches"]), 1)
            self.assertEqual(result["inactive_codex_skill_matches"], [])

    def test_workspace_in_codex_inventory_and_missing_workspace(self):
        workspace = self.root / "Workspaces"
        self.skill(workspace / "project" / ".agents" / "skills", "workspace-skill")
        with mock.patch.object(scout, "collect_codex_skills", return_value=[]):
            skills = scout.collect_active_skills(str(workspace), "codex")
            self.assertEqual([s["name"] for s in skills], ["workspace-skill"])
            self.assertEqual(
                scout.collect_active_skills(
                    str(self.root / "missing" / "Workspaces"), "codex"
                ),
                [],
            )

    def test_prune_honors_harness_and_excludes_workspace(self):
        observed = []

        def fake_collect(workspace, harness):
            observed.append((workspace, harness))
            return [{"name": "one", "source": "codex", "shadowed": False}]

        with mock.patch.object(
            scout, "collect_active_skills", side_effect=fake_collect
        ):
            status, output = self.run_command(
                "prune-check", "--harness", "codex", "--workspace", "ignored"
            )
        self.assertEqual(status, 0)
        self.assertEqual(observed, [(None, "codex")])
        self.assertEqual(json.loads(output)["active_skills_total"], 1)

    def test_promote_preserves_existing_and_rejects_escape(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "safe")
        destination = self.root / "dest"
        existing = self.skill(destination, "safe", "original")
        records = [
            {"id": "safe", "name": "safe", "path": "skills/safe", "risk": "safe"}
        ]
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
        ):
            status, _ = self.run_command("promote", "safe", "--dest", str(destination))
            self.assertEqual(status, 1)
            self.assertIn(
                "original", (existing / "SKILL.md").read_text(encoding="utf-8")
            )
            records[0]["path"] = "../outside"
            status, output = self.run_command(
                "promote", "safe", "--dest", str(destination), "--force"
            )
            self.assertEqual(status, 1)
            self.assertIn("Invalid skill source", output)

    def test_promote_codex_target_copies_one_skill(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "safe")
        codex_dest = self.root / "codex-skills"
        records = [
            {"id": "safe", "name": "safe", "path": "skills/safe", "risk": "safe"}
        ]
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(scout, "CODEX_SKILLS_DIR", codex_dest),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            status, output = self.run_command("promote", "safe", "--target", "codex")
        self.assertEqual(status, 0)
        self.assertEqual(Path(json.loads(output)["installed_to"]), codex_dest / "safe")
        self.assertTrue((codex_dest / "safe" / "SKILL.md").is_file())

    def test_parser_rejects_invalid_limit_and_harness(self):
        parser = scout.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["search", "foo", "--limit", "0"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["inventory", "--harness", "unknown"])

    def test_intake_extracts_documented_commands_and_rule_pointers(self):
        (self.root / "AGENTS.md").write_text(
            "# Commands\n- Run tests: `uv run pytest tests/test_example.py`\n",
            encoding="utf-8",
        )
        (self.root / "pyproject.toml").write_text(
            '[project]\nname="example"\nrequires-python=">=3.12"\n', encoding="utf-8"
        )
        status, output = self.run_command(
            "intake", "--workspace", str(self.root), "--format", "compact"
        )
        self.assertEqual(status, 0)
        self.assertIn("AGENTS.md", output)
        self.assertIn("Python >=3.12", output)
        self.assertIn("uv run pytest tests/test_example.py", output)
        self.assertLessEqual(len(output.splitlines()), 25)

    def test_python312_syntax(self):
        source = (ROOT / "scripts" / "skill_scout.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 12))

    def test_bilingual_routing_and_warehouse_category(self):
        warehouse = self.root / "team-skills"
        catalog = {
            "frontend-ui": "Accessible responsive web UI and dashboard design",
            "postgres-optimization": "SQL and PostgreSQL slow query optimization",
            "code-simplification": "Simplify and refactor code for clarity",
            "fastapi-auth": "FastAPI authentication and JWT security",
            "financial-modeling": "Corporate financial report and spreadsheet modeling",
            "slide-deck": "Presentation slides and marketing deck authoring",
            "security-audit": "Audit authentication security vulnerabilities",
        }
        for slug, description in catalog.items():
            self.skill(warehouse / "skills", slug, description)

        records = scout._load_warehouse_records(warehouse)
        self.assertEqual(len(records), len(catalog))
        self.assertTrue(all(item["category"] == "team-skills" for item in records))
        self.assertTrue(all(item["tags"] == ["team-skills"] for item in records))

        cases = [
            ("lam web dashboard dep", "frontend-ui"),
            ("toi uu truy van sql postgres cham", "postgres-optimization"),
            ("don gian hoa", "code-simplification"),
            ("fastapi authentication", "fastapi-auth"),
            ("lam bao cao tai chinh", "financial-modeling"),
            ("tao bai thuyet trinh", "slide-deck"),
            ("audit authentication security", "security-audit"),
        ]
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            for query, expected in cases:
                status, compact = self.run_command(
                    "search",
                    query,
                    "--no-active",
                    "--format",
                    "compact",
                    "--limit",
                    "3",
                )
                self.assertEqual(status, 0)
                hits = [
                    line.split(" | ", 4)[1]
                    for line in compact.splitlines()
                    if line.startswith("warehouse | ")
                ]
                self.assertIn(expected, hits, f"missing {expected!r} for {query!r}")
                self.assertEqual(
                    len(hits), len(set(hits)), f"duplicate hits for {query!r}"
                )

    def test_manifests_and_optional_local_marketplace(self):
        antigravity = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(antigravity["name"], codex["name"])
        self.assertEqual(codex["version"], marketplace["plugins"][0]["version"])
        self.assertEqual(codex["license"], "MIT")
        self.assertTrue((ROOT / antigravity["logo"]).is_file())
        self.assertTrue((ROOT / codex["skills"] / "skill-pilot" / "SKILL.md").is_file())
        if scout.CODEX_CONFIG_PATH.is_file():
            config = tomllib.loads(scout.CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
            plugin_entry = config.get("plugins", {}).get("skill-pilot@skill-pilot")
            if plugin_entry is not None:
                self.assertTrue(plugin_entry["enabled"])

    def test_instruction_tracks_and_references_are_present(self):
        skill = (ROOT / "skills" / "skill-pilot" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for label in ("**Fast:**", "**Guided:**", "**Deep:**"):
            self.assertIn(label, skill)
        self.assertLess(len(skill.splitlines()), 160)
        for name in ("compiler.md", "pipeline-blueprints.md"):
            self.assertTrue(
                (ROOT / "skills" / "skill-pilot" / "references" / name).is_file()
            )


if __name__ == "__main__":
    unittest.main()
