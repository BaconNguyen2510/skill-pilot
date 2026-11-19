"""Behavior and regression checks for Skill Pilot's local scout."""

import ast
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "skill_scout", ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"
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
        self.skill(warehouse / "skills", "finance-tool", "finance")
        active_dir = self.skill(self.root / "active", "finance-tool", "finance")
        dormant_dir = self.skill(self.root / "dormant", "finance-tool", "finance")
        active = {
            "name": "finance-tool",
            "description": "finance",
            "source": "plugin:demo",
            "shadowed": False,
            "skill_md_path": str(active_dir / "SKILL.md"),
        }
        dormant = {
            "name": "finance-tool",
            "description": "finance",
            "inactive": True,
            "source": "codex-plugin-inactive:demo",
            "skill_md_path": str(dormant_dir / "SKILL.md"),
        }
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
            status, force_out = self.run_command(
                "promote", "safe", "--dest", str(destination), "--force"
            )
            self.assertEqual(status, 1)
            self.assertIn("--force is deprecated", force_out)
            records[0]["path"] = "../outside"
            status, output = self.run_command(
                "promote", "safe", "--dest", str(destination), "--overwrite"
            )
            self.assertEqual(status, 1)
            self.assertIn("Invalid skill source", output)

    def test_promote_rejects_internal_symlink_or_junction(self):
        warehouse = self.root / "warehouse"
        skill_dir = self.skill(warehouse / "skills", "safe")
        secret_dir = self.root / "outside-secret"
        secret_dir.mkdir()
        (secret_dir / "secret.txt").write_text("TOP_SECRET", encoding="utf-8")
        dest = self.root / "dest"
        records = [
            {"id": "safe", "name": "safe", "path": "skills/safe", "risk": "safe"}
        ]

        if os.name == "nt":
            junction = skill_dir / "linked"
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(secret_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
            self.addCleanup(lambda: junction.exists() and os.rmdir(junction))
            with (
                mock.patch.object(
                    scout, "resolve_warehouses", return_value=[warehouse]
                ),
                mock.patch.object(
                    scout, "_load_warehouse_records", return_value=records
                ),
            ):
                status, output = self.run_command(
                    "promote", "safe", "--dest", str(dest)
                )
            self.assertEqual(status, 1)
            self.assertIn("error", output)
            self.assertFalse((dest / "safe").exists())
        else:
            symlink_file = skill_dir / "leak.txt"
            symlink_file.symlink_to(secret_dir / "secret.txt")
            with (
                mock.patch.object(
                    scout, "resolve_warehouses", return_value=[warehouse]
                ),
                mock.patch.object(
                    scout, "_load_warehouse_records", return_value=records
                ),
            ):
                status, output = self.run_command(
                    "promote", "safe", "--dest", str(dest)
                )
            self.assertEqual(status, 1)
            self.assertIn("error", output)
            self.assertFalse((dest / "safe").exists())

        nested_skill = self.skill(warehouse / "skills", "nested-safe")
        nested_secret = nested_skill / "references" / "leak.txt"
        nested_secret.parent.mkdir()
        nested_secret.write_text("secret", encoding="utf-8")
        records = [
            {
                "id": "nested-safe",
                "name": "nested-safe",
                "path": "skills/nested-safe",
                "risk": "safe",
            }
        ]
        orig_reparse = scout._is_link_or_reparse

        def fake_reparse(path):
            if path.name == "leak.txt":
                return True
            return orig_reparse(path)

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(scout, "_is_link_or_reparse", side_effect=fake_reparse),
        ):
            status, output = self.run_command(
                "promote", "nested-safe", "--dest", str(dest)
            )
        self.assertEqual(status, 1)
        self.assertIn("Symlink or junction", output)
        self.assertFalse((dest / "nested-safe").exists())

    def test_promote_separates_overwrite_allow_risky_and_rejects_force(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "unindexed-tool", "unindexed folder skill")
        self.skill(warehouse / "skills", "critical-tool", "critical skill")
        dest = self.root / "dest"
        self.assertEqual(scout._load_warehouse_records(warehouse)[0]["risk"], "unknown")
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, out = self.run_command(
                "promote", "unindexed-tool", "--dest", str(dest)
            )
            self.assertEqual(status, 1)
            self.assertIn("--allow-risky", out)

            status, _ = self.run_command(
                "promote", "unindexed-tool", "--dest", str(dest), "--allow-risky"
            )
            self.assertEqual(status, 0)

        records = [
            {
                "id": "critical-tool",
                "name": "critical-tool",
                "path": "skills/critical-tool",
                "risk": "critical",
            }
        ]
        existing = self.skill(dest, "critical-tool", "existing-keep")
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
        ):
            status, out = self.run_command(
                "promote", "critical-tool", "--dest", str(dest), "--overwrite"
            )
            self.assertEqual(status, 1)
            self.assertIn("--allow-risky", out)

            status, out = self.run_command(
                "promote", "critical-tool", "--dest", str(dest), "--allow-risky"
            )
            self.assertEqual(status, 1)
            self.assertIn("--overwrite", out)
            self.assertIn(
                "existing-keep", (existing / "SKILL.md").read_text(encoding="utf-8")
            )

            non_skill = dest / "non-skill"
            non_skill.mkdir(parents=True)
            (non_skill / "important.txt").write_text("do-not-wipe", encoding="utf-8")
            records[0]["id"] = "non-skill"
            status, out = self.run_command(
                "promote",
                "non-skill",
                "--dest",
                str(dest),
                "--overwrite",
                "--allow-risky",
            )
            self.assertEqual(status, 1)
            self.assertIn("non-skill directory", out)
            self.assertTrue((non_skill / "important.txt").is_file())

    def test_promote_fault_injection_preserves_existing_on_copy_failure(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "safe", "new-version")
        dest = self.root / "dest"
        existing = self.skill(dest, "safe", "keep-original")
        records = [
            {"id": "safe", "name": "safe", "path": "skills/safe", "risk": "safe"}
        ]
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(
                scout, "_copy_fd_stream", side_effect=OSError("simulated disk full")
            ),
        ):
            status, out = self.run_command(
                "promote", "safe", "--dest", str(dest), "--overwrite"
            )
        self.assertEqual(status, 1)
        self.assertIn("simulated disk full", out)
        self.assertIn(
            "keep-original", (existing / "SKILL.md").read_text(encoding="utf-8")
        )
        leftovers = [p.name for p in dest.iterdir() if ".stage-" in p.name]
        self.assertEqual(leftovers, [])

    def test_promote_fault_injection_rolls_back_on_swap_failure(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "safe", "new-version")
        dest = self.root / "dest"
        existing = self.skill(dest, "safe", "keep-original")
        records = [
            {"id": "safe", "name": "safe", "path": "skills/safe", "risk": "safe"}
        ]
        real_replace = os.replace
        calls = {"n": 0}

        def failing_swap(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated swap failure")
            return real_replace(src, dst)

        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(scout.os, "replace", side_effect=failing_swap),
        ):
            status, out = self.run_command(
                "promote", "safe", "--dest", str(dest), "--overwrite"
            )
        self.assertEqual(status, 1)
        self.assertIn("existing skill restored", out)
        self.assertIn(
            "keep-original", (existing / "SKILL.md").read_text(encoding="utf-8")
        )
        leftovers = [
            p.name for p in dest.iterdir() if ".stage-" in p.name or ".bak-" in p.name
        ]
        self.assertEqual(leftovers, [])

    def test_promote_rejects_windows_drive_and_unc_destination_names(self):
        warehouse = self.root / "warehouse"
        self.skill(warehouse / "skills", "safe")
        dest = self.root / "dest"
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            for bad_id in ("C:evil", r"\\server\share", r"a\b", ".."):
                records = [
                    {
                        "id": bad_id,
                        "name": bad_id,
                        "path": "skills/safe",
                        "risk": "safe",
                    }
                ]
                with mock.patch.object(
                    scout, "_load_warehouse_records", return_value=records
                ):
                    status, out = self.run_command(
                        "promote", bad_id, "--dest", str(dest)
                    )
                self.assertEqual(status, 1)
                self.assertIn("Invalid skill destination name", out)

        config = self.root / "config.toml"
        mp = self.root / "ext-plugin"
        self.skill(mp / "skills", "ext-skill")
        ext_prefix = "\\\\?\\"
        config.write_text(
            f"[marketplaces.ext]\nsource_type = \"local\"\nsource = '{ext_prefix}{mp}'\n"
            '[plugins."ext@ext"]\nenabled = true\n',
            encoding="utf-8",
        )
        with (
            mock.patch.object(scout, "CODEX_CONFIG_PATH", config),
            mock.patch.object(scout, "CODEX_CACHE_DIR", self.root / "empty-cache"),
        ):
            sources = scout._codex_plugin_sources()
        self.assertEqual(sources[0][1], mp)

    def test_jsonc_string_aware_trailing_commas_and_unterminated_comment(self):
        sample = '{\n  // keep URL\n  "url": "https://example.com/*keep*/,}",\n  "items": [1, 2,],\n}\n'
        parsed = json.loads(scout._strip_jsonc_comments(sample))
        self.assertEqual(parsed["url"], "https://example.com/*keep*/,}")
        self.assertEqual(parsed["items"], [1, 2])
        with self.assertRaises(ValueError):
            scout._strip_jsonc_comments('{"a": 1 /* never closed')
        bad_file = self.root / "broken.jsonc"
        bad_file.write_text('{"a": 1 /* unterminated', encoding="utf-8")
        self.assertEqual(scout._load_jsonc(bad_file), {})

    def test_frontmatter_rejects_unclosed_delimiter_and_handles_escapes(self):
        unclosed = self.root / "unclosed-skill"
        unclosed.mkdir()
        (unclosed / "SKILL.md").write_text(
            "---\nname: fake\ndescription: still open\n# body\n", encoding="utf-8"
        )
        parsed_unclosed = scout.parse_frontmatter(unclosed / "SKILL.md")
        self.assertEqual(parsed_unclosed["name"], "unclosed-skill")
        self.assertEqual(parsed_unclosed["description"], "")

        escaped = self.root / "escaped-skill"
        escaped.mkdir()
        (escaped / "SKILL.md").write_text(
            '---\nname: "escaped"\ndescription: "Line 1 \\"quoted\\" text"\n---\n# Ok\n',
            encoding="utf-8",
        )
        parsed_escaped = scout.parse_frontmatter(escaped / "SKILL.md")
        self.assertEqual(parsed_escaped["description"], 'Line 1 "quoted" text')

    def test_search_preserves_distinct_name_collision_and_unifies_ranking(self):
        warehouse = self.root / "wh"
        wh_file = self.skill(
            warehouse / "skills",
            "data-helper",
            "Financial ledger reconciliation and tax modeling",
        )
        active = {
            "name": "data-helper",
            "description": "Kubernetes cluster autoscaling and pod monitoring",
            "source": "plugin:infra",
            "shadowed": False,
            "skill_md_path": str(self.root / "infra" / "data-helper" / "SKILL.md"),
        }
        records = [
            {
                "id": "data-helper",
                "name": "data-helper",
                "path": "skills/data-helper",
                "risk": "low",
                "description": "Financial ledger reconciliation and tax modeling",
            },
            {
                "id": "tax-planner",
                "name": "tax-planner",
                "path": "skills/data-helper",
                "risk": "low",
                "description": "Financial ledger reconciliation and tax modeling",
            },
        ]
        # Distinct files per warehouse item to verify unified ranking order.
        self.skill(
            warehouse / "skills",
            "tax-planner",
            "Financial ledger reconciliation and tax modeling",
        )
        records[1]["path"] = "skills/tax-planner"
        self.assertTrue((wh_file / "SKILL.md").is_file())
        with (
            mock.patch.object(scout, "collect_active_skills", return_value=[active]),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
        ):
            _, raw_json = self.run_command(
                "search", "data helper", "--harness", "all", "--limit", "5"
            )
            _, compact = self.run_command(
                "search",
                "data helper",
                "--harness",
                "all",
                "--format",
                "compact",
                "--limit",
                "5",
            )
        payload = json.loads(raw_json)
        self.assertEqual(payload["ranking_policy"], "relevance_with_bounded_tier_bonus")
        ranked_names = [
            (item["tier_label"], item["name"]) for item in payload["ranked_matches"]
        ]
        self.assertEqual(
            ranked_names, [("active", "data-helper"), ("warehouse", "data-helper")]
        )
        self.assertTrue(
            all(item.get("name_collision") for item in payload["ranked_matches"])
        )
        compact_pairs = [
            (line.split(" | ")[0], line.split(" | ")[1])
            for line in compact.splitlines()
            if line.startswith(("active | ", "warehouse | ", "inactive | "))
        ]
        self.assertEqual(compact_pairs, ranked_names)

    def test_vietnamese_semantic_collision_and_negation(self):
        warehouse = self.root / "wh"
        self.skill(
            warehouse / "skills",
            "marketing-report",
            "Marketing campaign reports and banking analytics",
        )
        self.skill(
            warehouse / "skills",
            "sentiment-analysis",
            "Social media comments and customer sentiment research analysis",
        )
        self.skill(
            warehouse / "skills",
            "frontend-ui",
            "Accessible responsive web UI and dashboard design",
        )
        query = (
            "Tạo một báo cáo marketing đẹp cho chiến dịch ngân hàng, "
            "phân tích bình luận khách hàng. Không cần thiết kế web hay frontend. "
            "Hãy chọn skill phù hợp nhất."
        )
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, compact = self.run_command(
                "search", query, "--no-active", "--format", "compact", "--limit", "5"
            )
        self.assertEqual(status, 0)
        names = [
            line.split(" | ")[1]
            for line in compact.splitlines()
            if line.startswith("warehouse | ")
        ]
        self.assertEqual(set(names[:2]), {"marketing-report", "sentiment-analysis"})
        self.assertNotIn("frontend-ui", names)
        care_terms = scout.query_terms("chăm sóc khách hàng")
        self.assertNotIn("slow", care_terms)
        self.assertNotIn("performance", care_terms)
        slow_terms = scout.query_terms("truy vấn chậm")
        self.assertIn("slow", slow_terms)
        self.assertIn("performance", slow_terms)

    def test_intake_discovers_nested_rules_and_filters_negated_commands(self):
        (self.root / "AGENTS.md").write_text(
            "# Root\n- Never run `npm run deploy-prod` here.\n- Run unit tests: `uv run pytest tests/`\n",
            encoding="utf-8",
        )
        mobile_dir = self.root / "apps" / "mobile"
        mobile_dir.mkdir(parents=True)
        (mobile_dir / "AGENTS.md").write_text(
            "# Mobile\n- Mobile tests: `npm test -- --watch=false`\n",
            encoding="utf-8",
        )
        (self.root / "package.json").write_text(
            json.dumps({"name": "monorepo", "scripts": {"lint": "eslint ."}}),
            encoding="utf-8",
        )
        status, compact = self.run_command(
            "intake",
            "--workspace",
            str(self.root),
            "--target",
            "apps/mobile",
            "--format",
            "compact",
        )
        self.assertEqual(status, 0)
        self.assertIn("apps", compact)
        self.assertIn("Command candidate (unverified, check):", compact)
        self.assertIn("uv run pytest tests/ [AGENTS.md:3]", compact)
        self.assertIn("npm test -- --watch=false [apps/mobile/AGENTS.md:2]", compact)
        self.assertNotIn("npm run deploy-prod", compact)

    def test_inspect_is_bounded_and_flags_unreviewed_scripts_and_links(self):
        sdir = self.skill(self.root, "audited-skill", "Inspect edge cases")
        (sdir / "scripts").mkdir()
        (sdir / "scripts" / "helper.py").write_text("print('hi')\n", encoding="utf-8")
        git_dir = sdir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n", encoding="utf-8")
        outside = self.root / "outside-target"
        outside.mkdir()
        if os.name == "nt":
            link_path = sdir / "ext-ref"
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
            self.addCleanup(lambda: link_path.exists() and os.rmdir(link_path))
        else:
            (sdir / "ext-ref").symlink_to(outside)

        status, raw = self.run_command("inspect", str(sdir))
        self.assertEqual(status, 0)
        payload = json.loads(raw)
        self.assertFalse(payload["scripts_reviewed"])
        self.assertEqual(payload["executable_or_script_files"], ["scripts/helper.py"])
        self.assertEqual(payload["symlinks_detected"], ["ext-ref"])
        self.assertNotIn(".git/config", payload["files"])
        status, compact = self.run_command("inspect", str(sdir), "--format", "compact")
        self.assertEqual(status, 0)
        self.assertIn("Scripts (unreviewed metadata only): scripts/helper.py", compact)
        self.assertIn("Warning: symlinks/junctions detected: ext-ref", compact)

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
        for rel in (
            Path("scripts") / "skill_scout.py",
            Path("skills") / "skill-pilot" / "scripts" / "skill_scout.py",
        ):
            ast.parse((ROOT / rel).read_text(encoding="utf-8"), feature_version=(3, 12))

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

    def test_config_json_bom_and_parse_failure_warns_instead_of_silent_fail_open(self):
        plugins_dir = self.root / "plugins"
        self.skill(plugins_dir / "blocked-plugin" / "skills", "blocked-skill", "secret")
        self.skill(
            plugins_dir / "enabled-plugin" / "skills", "plugin-skill", "from plugin"
        )
        global_dir = self.root / "global-skills"
        self.skill(global_dir, "global-tool", "global verifiable skill")
        cfg = self.root / "config.json"
        cfg.write_bytes(
            "\ufeff".encode("utf-8")
            + json.dumps(
                {
                    "plugins": {
                        "blocked-plugin": {"enabled": False},
                        "enabled-plugin": {"enabled": True},
                    }
                }
            ).encode("utf-8")
        )
        with (
            mock.patch.object(scout, "CONFIG_JSON_PATH", cfg),
            mock.patch.object(scout, "PLUGINS_DIR", plugins_dir),
            mock.patch.object(scout, "GLOBAL_SKILLS_DIR", global_dir),
            mock.patch.object(scout, "BUILTIN_SKILLS_DIR", self.root / "no-builtin"),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
        ):
            status, raw = self.run_command("inventory", "--harness", "antigravity")
            self.assertEqual(status, 0)
            payload = json.loads(raw)
            names = {s["name"] for s in payload["skills"]}
            self.assertEqual(names, {"plugin-skill", "global-tool"})
            self.assertNotIn("config_warning", payload)

            cfg.write_text('{"plugins": { broken', encoding="utf-8")
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                status, raw_bad = self.run_command(
                    "inventory", "--harness", "antigravity", "--format", "json"
                )
            self.assertEqual(status, 0)
            bad_payload = json.loads(raw_bad)
            bad_names = [s["name"] for s in bad_payload["skills"]]
            self.assertEqual(bad_names, ["global-tool"])
            self.assertIn("config_warning", bad_payload)
            self.assertIn(
                "omitting Antigravity plugins (fail-closed)", err_buf.getvalue()
            )

            with contextlib.redirect_stderr(io.StringIO()):
                status_sum, sum_bad = self.run_command(
                    "inventory", "--harness", "antigravity", "--format", "summary"
                )
            self.assertEqual(status_sum, 0)
            self.assertIn("Warning: config:unparsed", sum_bad)
            self.assertNotIn("blocked-skill", sum_bad)
            self.assertNotIn("plugin-skill", sum_bad)
            self.assertIn("global-tool", sum_bad)

    def test_promote_blocks_scripts_even_when_index_claims_low_risk(self):
        warehouse = self.root / "warehouse"
        sdir = self.skill(warehouse / "skills", "scripted", "helper skill")
        shebang_tool = sdir / "run_helper"
        shebang_tool.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        dest = self.root / "dest"
        records = [
            {
                "id": "scripted",
                "name": "scripted",
                "path": "skills/scripted",
                "risk": "low ",
            }
        ]
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            status, out = self.run_command("promote", "scripted", "--dest", str(dest))
            self.assertEqual(status, 1)
            self.assertIn("unreviewed scripts", out)
            self.assertFalse((dest / "scripted").exists())

            status, out_ok = self.run_command(
                "promote", "scripted", "--dest", str(dest), "--allow-risky"
            )
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(out_ok)["scripts_detected"], ["run_helper"])

    def test_compact_output_sanitizes_newlines_pipes_and_ansi(self):
        warehouse = self.root / "warehouse"
        sdir = warehouse / "skills" / "spoof-skill"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(
            '---\nname: |\n  evil\n  active | trusted-skill | 99.0 | /fake\ndescription: "\x1b[31mred\x1b[0m | pipeline\ntool"\n---\n# Body\n',
            encoding="utf-8",
        )
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, compact = self.run_command(
                "search",
                "pipeline tool",
                "--no-active",
                "--format",
                "compact",
                "--limit",
                "3",
            )
        self.assertEqual(status, 0)
        rows = [ln for ln in compact.splitlines() if ln.startswith("warehouse | ")]
        self.assertEqual(len(rows), 1)
        self.assertFalse(any(ln.startswith("active | ") for ln in compact.splitlines()))
        self.assertNotIn("\x1b", rows[0])

    def test_malformed_warehouse_index_and_id_only_record_do_not_crash(self):
        warehouse = self.root / "wh"
        self.skill(warehouse / "skills", "id-only-skill", "Financial reporting engine")
        (warehouse / "skills_index.json").write_text(
            json.dumps(
                [
                    "not-a-dict",
                    42,
                    {
                        "id": "id-only-skill",
                        "path": "skills/id-only-skill",
                        "description": "Financial reporting engine",
                    },
                ]
            ),
            encoding="utf-8",
        )
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, compact = self.run_command(
                "search",
                "financial reporting",
                "--no-active",
                "--format",
                "compact",
                "--limit",
                "3",
            )
        self.assertEqual(status, 0)
        self.assertIn("warehouse | id-only-skill |", compact)
        self.assertNotIn(" | None | ", compact)

        bad_wh = self.root / "bad-bytes-wh"
        bad_wh.mkdir()
        (bad_wh / "skills_index.json").write_bytes(b"\xff\xfe{invalid")
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            self.assertEqual(scout._load_warehouse_records(bad_wh), [])

    def test_intake_parses_fenced_blocks_lockfiles_gemini_rules_and_kinds(self):
        (self.root / "GEMINI.md").write_text(
            "# Verify\nNever run:\n```bash\nnpm run db:reset\n```\nRun tests:\n```bash\npython -m unittest discover -s tests -v\n```\n",
            encoding="utf-8",
        )
        rules_dir = self.root / ".agents" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "custom.md").write_text(
            "- Always check lint with `uv run ruff check`\n", encoding="utf-8"
        )
        (self.root / "pnpm-lock.yaml").write_text(
            "lockfileVersion: '9.0'\n", encoding="utf-8"
        )
        (self.root / "package.json").write_text(
            json.dumps(
                {
                    "name": "app",
                    "scripts": {"test": "vitest run", "deploy": "wrangler deploy"},
                }
            ),
            encoding="utf-8",
        )
        status, raw = self.run_command(
            "intake", "--workspace", str(self.root), "--format", "json"
        )
        self.assertEqual(status, 0)
        payload = json.loads(raw)
        self.assertNotIn("commands", payload)
        by_cmd = {item["command"]: item for item in payload["command_candidates"]}
        self.assertIn("python -m unittest discover -s tests -v", by_cmd)
        self.assertFalse(by_cmd["python -m unittest discover -s tests -v"]["verified"])
        self.assertEqual(
            by_cmd["python -m unittest discover -s tests -v"]["kind"], "check"
        )
        self.assertIn("uv run ruff check", by_cmd)
        self.assertNotIn("npm run db:reset", by_cmd)
        self.assertIn("pnpm run test", by_cmd)
        self.assertFalse(by_cmd["pnpm run test"]["verified"])
        self.assertEqual(by_cmd["pnpm run test"]["kind"], "check")
        self.assertEqual(by_cmd["pnpm run deploy"]["kind"], "mutating")

    def test_retrieval_fixes_claude_case1_stopwords_single_char_and_category_leakage(
        self,
    ):
        warehouse = self.root / "wh"
        self.skill(
            warehouse / "skills",
            "postgres-tuning",
            "SQL query tuning and PostgreSQL slow database performance diagnostics",
        )
        self.skill(
            warehouse / "skills",
            "frontend-ui",
            "Do NOT use for SQL. Accessible web UI components and buttons",
        )
        query = "Trang web của tôi chạy chậm khi truy vấn đơn hàng, tối ưu giúp tôi"
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            status, compact = self.run_command(
                "search", query, "--no-active", "--format", "compact", "--limit", "3"
            )
            self.assertEqual(status, 0)
            names = [
                line.split(" | ")[1]
                for line in compact.splitlines()
                if line.startswith("warehouse | ")
            ]
            self.assertEqual(names[0], "postgres-tuning")
            self.assertNotIn("frontend-ui", names)

            status_r, out_r = self.run_command(
                "search", "R", "--no-active", "--format", "json"
            )
            self.assertEqual(status_r, 1)
            self.assertIn("No searchable keywords", out_r)

        active_items = [
            {
                "name": "R Analysis",
                "description": "Statistical R regression modeling",
                "source": "plugin:analytics",
                "shadowed": False,
                "skill_md_path": str(self.root / "r1" / "SKILL.md"),
            },
            {
                "name": "Analysis",
                "description": "Statistical regression and dataset review",
                "source": "global:skills",
                "shadowed": False,
                "skill_md_path": str(self.root / "r2" / "SKILL.md"),
            },
        ]
        with (
            mock.patch.object(
                scout, "collect_active_skills", return_value=active_items
            ),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(scout, "resolve_warehouses", return_value=[]),
        ):
            status_leak, out_leak = self.run_command(
                "search", "plugin skills", "--harness", "all", "--format", "json"
            )
            self.assertEqual(status_leak, 0)
            self.assertEqual(json.loads(out_leak)["tier1_active_matches"], [])

            status_col, out_col = self.run_command(
                "search",
                "statistical regression",
                "--harness",
                "all",
                "--format",
                "json",
            )
            self.assertEqual(status_col, 0)
            matched_names = [
                item["name"] for item in json.loads(out_col)["tier1_active_matches"]
            ]
            self.assertEqual(set(matched_names), {"R Analysis", "Analysis"})

    def test_skill_md_utf8_bom_and_codex_newest_version_and_flat_glob(self):
        bom_skill = self.root / "bom-skill"
        bom_skill.mkdir()
        (bom_skill / "SKILL.md").write_bytes(
            "\ufeff---\nname: bom-ok\ndescription: Parses BOM cleanly\n---\n# Hi\n".encode(
                "utf-8"
            )
        )
        meta = scout.parse_frontmatter(bom_skill / "SKILL.md")
        self.assertEqual(meta["name"], "bom-ok")
        self.assertEqual(meta["description"], "Parses BOM cleanly")

        config = self.root / "config.toml"
        cache = self.root / "cache"
        v1 = cache / "demo" / "helper" / "1.2.0"
        v2 = cache / "demo" / "helper" / "2.0.0"
        self.skill(v1 / "skills", "helper", "Older cached version")
        self.skill(v2 / "skills", "helper", "Newer cached version")
        self.skill(v2 / "skills" / "helper" / "examples", "nested-example", "Ignore me")
        config.write_text('[plugins."helper@demo"]\nenabled = true\n', encoding="utf-8")
        with (
            mock.patch.object(scout, "CODEX_CONFIG_PATH", config),
            mock.patch.object(scout, "CODEX_CACHE_DIR", cache),
            mock.patch.object(scout, "CODEX_SKILLS_DIR", self.root / "no-codex"),
        ):
            codex_skills = scout.collect_codex_skills()
        self.assertEqual(len(codex_skills), 1)
        self.assertEqual(codex_skills[0]["description"], "Newer cached version")

    def test_promote_blocks_hidden_git_hook_and_deep_scripts_r01(self):
        warehouse = self.root / "warehouse"
        git_hidden = self.skill(warehouse / "skills", "git-hidden", "clean desc")
        hook = git_hidden / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\necho pwn\n", encoding="utf-8")

        deep_skill = self.skill(warehouse / "skills", "too-deep", "deep files")
        deep_dir = deep_skill
        for idx in range(scout.MAX_INSPECT_DEPTH + 2):
            deep_dir = deep_dir / f"d{idx}"
        deep_dir.mkdir(parents=True)
        (deep_dir / "payload.py").write_text("print('deep')\n", encoding="utf-8")

        dest = self.root / "dest"
        records = [
            {
                "id": "git-hidden",
                "name": "git-hidden",
                "path": "skills/git-hidden",
                "risk": "low",
            },
            {
                "id": "too-deep",
                "name": "too-deep",
                "path": "skills/too-deep",
                "risk": "low",
            },
        ]
        with (
            mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
            mock.patch.object(scout, "collect_active_skills", return_value=[]),
        ):
            status_git, out_git = self.run_command(
                "promote", "git-hidden", "--dest", str(dest)
            )
            self.assertEqual(status_git, 1)
            self.assertIn("unreviewed scripts", out_git)
            self.assertFalse((dest / "git-hidden").exists())

            status_deep, out_deep = self.run_command(
                "promote", "too-deep", "--dest", str(dest), "--allow-risky"
            )
            self.assertEqual(status_deep, 1)
            self.assertIn("maximum depth", out_deep)
            self.assertFalse((dest / "too-deep").exists())

    def test_fifo_and_special_files_do_not_block_or_promote_r02(self):
        warehouse = self.root / "warehouse"
        sdir = self.skill(warehouse / "skills", "fifo-skill", "edge fixture")
        dest = self.root / "dest"
        records = [
            {
                "id": "fifo-skill",
                "name": "fifo-skill",
                "path": "skills/fifo-skill",
                "risk": "low",
            }
        ]
        if hasattr(os, "mkfifo"):
            pipe_path = sdir / "blocked.pipe"
            os.mkfifo(pipe_path)
            with (
                mock.patch.object(
                    scout, "resolve_warehouses", return_value=[warehouse]
                ),
                mock.patch.object(
                    scout, "_load_warehouse_records", return_value=records
                ),
            ):
                insp_run = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(
                            ROOT
                            / "skills"
                            / "skill-pilot"
                            / "scripts"
                            / "skill_scout.py"
                        ),
                        "inspect",
                        str(sdir),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                self.assertEqual(insp_run.returncode, 0)
                self.assertEqual(
                    json.loads(insp_run.stdout)["special_files_detected"],
                    ["blocked.pipe"],
                )
                status, out = self.run_command(
                    "promote", "fifo-skill", "--dest", str(dest), "--allow-risky"
                )
                self.assertEqual(status, 1)
                self.assertIn("non-regular file", out)
        else:
            pipe_path = sdir / "blocked.pipe"
            pipe_path.write_text("placeholder", encoding="utf-8")
            real_lstat = os.lstat

            def fake_lstat(path, *args, **kwargs):
                st = real_lstat(path, *args, **kwargs)
                if Path(path).name == "blocked.pipe":
                    seq = list(st)
                    seq[0] = (seq[0] & ~0o170000) | stat.S_IFIFO
                    return os.stat_result(seq)
                return st

            with (
                mock.patch.object(
                    scout, "resolve_warehouses", return_value=[warehouse]
                ),
                mock.patch.object(
                    scout, "_load_warehouse_records", return_value=records
                ),
                mock.patch.object(scout.os, "lstat", side_effect=fake_lstat),
            ):
                status_insp, raw_insp = self.run_command("inspect", str(sdir))
                self.assertEqual(status_insp, 0)
                self.assertEqual(
                    json.loads(raw_insp)["special_files_detected"], ["blocked.pipe"]
                )
                status, out = self.run_command(
                    "promote", "fifo-skill", "--dest", str(dest), "--allow-risky"
                )
                self.assertEqual(status, 1)
                self.assertIn("non-regular file", out)
        self.assertFalse((dest / "fifo-skill").exists())

    def test_same_name_identical_descriptions_at_different_paths_preserved_r04(self):
        wh = self.root / "wh"
        s1 = self.skill(wh / "skills", "sec-a", "Review code security")
        (s1 / "SKILL.md").write_text(
            "---\nname: security-audit\ndescription: Review code security\n---\n# Implementation A (Python AST)\n",
            encoding="utf-8",
        )
        s2 = self.skill(wh / "skills", "sec-b", "Review code security")
        (s2 / "SKILL.md").write_text(
            "---\nname: security-audit\ndescription: Review code security\n---\n# Implementation B (Go & Rust)\n",
            encoding="utf-8",
        )
        active = {
            "name": "security-audit",
            "description": "Review code security",
            "source": "plugin:sec-a",
            "shadowed": False,
            "skill_md_path": str(s1 / "SKILL.md"),
        }
        records = [
            {
                "id": "sec-b",
                "name": "security-audit",
                "path": "skills/sec-b",
                "risk": "low",
                "description": "Review code security",
            }
        ]
        with (
            mock.patch.object(scout, "collect_active_skills", return_value=[active]),
            mock.patch.object(scout, "collect_codex_skills", return_value=[]),
            mock.patch.object(scout, "resolve_warehouses", return_value=[wh]),
            mock.patch.object(scout, "_load_warehouse_records", return_value=records),
        ):
            status, raw = self.run_command(
                "search", "security audit", "--harness", "all", "--limit", "5"
            )
        self.assertEqual(status, 0)
        ranked = json.loads(raw)["ranked_matches"]
        self.assertEqual(len(ranked), 2)
        self.assertTrue(all(item.get("name_collision") for item in ranked))

    def test_negative_only_query_rejected_without_reversing_intent_r05(self):
        warehouse = self.root / "wh"
        self.skill(warehouse / "skills", "frontend-ui", "Frontend React UI design")
        with mock.patch.object(scout, "resolve_warehouses", return_value=[warehouse]):
            for query in ("Không dùng frontend.", "do not use react"):
                status, raw = self.run_command(
                    "search", query, "--no-active", "--format", "json"
                )
                self.assertEqual(status, 1)
                self.assertIn("No positive search intent", raw)

    def test_standalone_skill_installation_layout_m13(self):
        standalone = self.root / "standalone" / "skill-pilot"
        shutil.copytree(ROOT / "skills" / "skill-pilot", standalone)
        warehouse = self.root / "wh"
        self.skill(warehouse / "skills", "finance-tool", "Corporate financial report")
        script = standalone / "scripts" / "skill_scout.py"
        run = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "search",
                "finance",
                "--no-active",
                "--warehouse",
                str(warehouse),
                "--format",
                "compact",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("warehouse | finance-tool |", run.stdout)

        wrapper_run = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts" / "skill_scout.py"),
                "search",
                "finance",
                "--no-active",
                "--warehouse",
                str(warehouse),
                "--format",
                "compact",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(wrapper_run.returncode, 0, wrapper_run.stderr)
        self.assertIn("warehouse | finance-tool |", wrapper_run.stdout)


if __name__ == "__main__":
    unittest.main()
