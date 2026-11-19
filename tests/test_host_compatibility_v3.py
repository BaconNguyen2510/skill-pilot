"""Host compatibility and fake-home isolation tests for Skill Pilot (COMP-01..08, COMP-10)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"
SKILL_MD_PATH = ROOT / "skills" / "skill-pilot" / "SKILL.md"
if str(SCRIPT_PATH.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH.parent))

import skill_scout as scout


class FakeHomeMixin:
    """Provide an isolated fake HOME layout with zero dependency on real user HOME."""

    def _init_fake_home(self, base: pathlib.Path) -> pathlib.Path:
        home = base / "fake_home"
        home.mkdir(parents=True, exist_ok=True)
        self.home = home
        self.gemini_dir = home / ".gemini" / "config"
        self.plugins_dir = self.gemini_dir / "plugins"
        self.global_skills_dir = self.gemini_dir / "skills"
        self.builtin_skills_dir = (
            home / ".gemini" / "antigravity" / "builtin" / "skills"
        )
        self.config_json_path = self.gemini_dir / "config.json"

        self.codex_dir = home / ".codex"
        self.codex_skills_dir = self.codex_dir / "skills"
        self.codex_inactive_dir = self.codex_dir / "skills-inactive"
        self.codex_config_path = self.codex_dir / "config.toml"
        self.codex_cache_dir = self.codex_dir / "plugins" / "cache"

        self.default_wh = home / ".agents" / "warehouses" / "agentic-awesome-skills"
        self.ecc_wh = home / ".gemini" / "antigravity" / "ecc"
        self.local_cfg_path = self.gemini_dir / "skill-pilot.local.json"
        return home

    def _patch_scout_home(self) -> contextlib.ExitStack:
        stack = contextlib.ExitStack()
        patches = {
            "HOME": self.home,
            "GEMINI_CONFIG_DIR": self.gemini_dir,
            "PLUGINS_DIR": self.plugins_dir,
            "GLOBAL_SKILLS_DIR": self.global_skills_dir,
            "BUILTIN_SKILLS_DIR": self.builtin_skills_dir,
            "CONFIG_JSON_PATH": self.config_json_path,
            "CODEX_DIR": self.codex_dir,
            "CODEX_SKILLS_DIR": self.codex_skills_dir,
            "CODEX_INACTIVE_SKILLS_DIR": self.codex_inactive_dir,
            "CODEX_CONFIG_PATH": self.codex_config_path,
            "CODEX_CACHE_DIR": self.codex_cache_dir,
            "DEFAULT_WAREHOUSES": (self.default_wh,),
            "ECC_WAREHOUSES": (self.ecc_wh,),
            "LOCAL_CONFIG_PATHS": (self.local_cfg_path,),
        }
        for attr, val in patches.items():
            stack.enter_context(mock.patch.object(scout, attr, val))
        stack.enter_context(mock.patch.object(scout, "_LAST_CONFIG_WARNING", None))
        return stack

    def _write_skill(
        self,
        parent: pathlib.Path,
        folder_name: str,
        *,
        name: str | None = None,
        description: str = "Synthetic compatibility test skill",
        body: str = "# Instructions\n",
    ) -> pathlib.Path:
        sdir = parent / folder_name
        sdir.mkdir(parents=True, exist_ok=True)
        skill_name = name or folder_name
        (sdir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: {description}\n---\n{body}",
            encoding="utf-8",
        )
        return sdir

    def _run_cli(self, *argv: str) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["skill_scout.py", *argv]),
            redirect_stdout(out_buf),
            redirect_stderr(err_buf),
        ):
            code = scout.main()
        return code, out_buf.getvalue(), err_buf.getvalue()


class HostCompatibilityV3Tests(unittest.TestCase, FakeHomeMixin):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._init_fake_home(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _setup_antigravity_host(self) -> None:
        self._write_skill(self.global_skills_dir, "ag-global")
        self._write_skill(self.builtin_skills_dir, "ag-builtin")
        plug_dir = self.plugins_dir / "ag-plug"
        plug_dir.mkdir(parents=True, exist_ok=True)
        (plug_dir / "plugin.json").write_text(
            json.dumps({"name": "ag-plug"}), encoding="utf-8"
        )
        self._write_skill(plug_dir / "skills", "ag-plug-skill")
        self.config_json_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_json_path.write_text(
            json.dumps({"plugins": {"ag-plug": {"enabled": True}}}),
            encoding="utf-8",
        )

    def _setup_codex_host(self) -> None:
        self._write_skill(self.codex_skills_dir, "cx-global")
        cache_ver = self.codex_cache_dir / "mkt" / "cx-plug" / "1.0.0"
        self._write_skill(cache_ver / "skills", "cx-plug-skill")
        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            '[marketplaces.mkt]\nsource_type = "git"\n\n'
            '[plugins."cx-plug@mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

    # COMP-01 / COMP-02 / COMP-03 / COMP-10: Host selection modes
    def test_host_modes_antigravity_only_codex_only_and_both(self) -> None:
        self._setup_antigravity_host()
        self._setup_codex_host()
        ws = self.root / "ws"
        self._write_skill(ws / ".agents" / "skills", "ws-shared")

        with self._patch_scout_home():
            ag_only = scout.collect_active_skills(str(ws), harness="antigravity")
            ag_names = {s["name"] for s in ag_only}
            self.assertEqual(
                ag_names, {"ws-shared", "ag-global", "ag-plug-skill", "ag-builtin"}
            )

            cx_only = scout.collect_active_skills(str(ws), harness="codex")
            cx_names = {s["name"] for s in cx_only}
            self.assertEqual(cx_names, {"ws-shared", "cx-global", "cx-plug-skill"})

            both_auto = scout.collect_active_skills(str(ws), harness="auto")
            both_all = scout.collect_active_skills(str(ws), harness="all")
            expected_all = {
                "ws-shared",
                "ag-global",
                "ag-plug-skill",
                "ag-builtin",
                "cx-global",
                "cx-plug-skill",
            }
            self.assertEqual({s["name"] for s in both_auto}, expected_all)
            self.assertEqual({s["name"] for s in both_all}, expected_all)

    def test_single_host_present_with_harness_auto(self) -> None:
        # Antigravity-only filesystem
        self._setup_antigravity_host()
        with self._patch_scout_home():
            ag_items = scout.collect_active_skills(harness="auto")
            self.assertEqual(
                {s["name"] for s in ag_items},
                {"ag-global", "ag-plug-skill", "ag-builtin"},
            )

        # Reset to Codex-only filesystem
        shutil.rmtree(self.home)
        self._init_fake_home(self.root)
        self._setup_codex_host()
        with self._patch_scout_home():
            cx_items = scout.collect_active_skills(harness="auto")
            self.assertEqual(
                {s["name"] for s in cx_items}, {"cx-global", "cx-plug-skill"}
            )

    # COMP-02 / COMP-03 / COMP-08: Disabled plugins across Antigravity and Codex
    def test_disabled_plugins_antigravity_and_codex(self) -> None:
        # Antigravity: disabled via config.json, disabled via plugin.json, and override via config.json
        p_cfg_off = self.plugins_dir / "cfg-off"
        p_cfg_off.mkdir(parents=True, exist_ok=True)
        (p_cfg_off / "plugin.json").write_text(
            json.dumps({"name": "cfg-off"}), encoding="utf-8"
        )
        self._write_skill(p_cfg_off / "skills", "skill-cfg-off")

        p_manifest_off = self.plugins_dir / "manifest-off"
        p_manifest_off.mkdir(parents=True, exist_ok=True)
        (p_manifest_off / "plugin.json").write_text(
            json.dumps({"name": "manifest-off", "disabled": True}), encoding="utf-8"
        )
        self._write_skill(p_manifest_off / "skills", "skill-manifest-off")

        p_override_on = self.plugins_dir / "override-on"
        p_override_on.mkdir(parents=True, exist_ok=True)
        (p_override_on / "plugin.json").write_text(
            json.dumps({"name": "override-on", "disabled": True}), encoding="utf-8"
        )
        self._write_skill(p_override_on / "skills", "skill-override-on")

        self.config_json_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_json_path.write_text(
            json.dumps(
                {
                    "plugins": {
                        "cfg-off": {"enabled": False},
                        "override-on": {"enabled": True},
                    }
                }
            ),
            encoding="utf-8",
        )

        # Codex: enabled = false plugin and enabled = true plugin
        self._write_skill(
            self.codex_cache_dir / "mkt" / "cx-off" / "1.0.0" / "skills",
            "skill-cx-off",
            description="codex disabled plugin workflow",
        )
        self._write_skill(
            self.codex_cache_dir / "mkt" / "cx-on" / "1.0.0" / "skills",
            "skill-cx-on",
            description="codex active plugin workflow",
        )
        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            '[marketplaces.mkt]\nsource_type = "git"\n\n'
            '[plugins."cx-off@mkt"]\nenabled = false\n\n'
            '[plugins."cx-on@mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

        with self._patch_scout_home():
            active = scout.collect_active_skills(harness="all")
            active_names = {s["name"] for s in active}
            self.assertEqual(active_names, {"skill-override-on", "skill-cx-on"})
            self.assertNotIn("skill-cfg-off", active_names)
            self.assertNotIn("skill-manifest-off", active_names)
            self.assertNotIn("skill-cx-off", active_names)

            # Codex include_inactive=True surfaces disabled plugin only as inactive candidate
            codex_with_inactive = scout.collect_codex_skills(include_inactive=True)
            by_name = {s["name"]: s for s in codex_with_inactive}
            self.assertTrue(by_name["skill-cx-off"]["inactive"])
            self.assertEqual(
                by_name["skill-cx-off"]["source"], "codex-plugin-inactive:cx-off@mkt"
            )
            self.assertEqual(by_name["skill-cx-off"]["tier"], "tier2-codex-inactive")
            self.assertFalse(by_name["skill-cx-on"]["inactive"])

            # Search keeps disabled plugins out of tier1_active_matches
            code, raw, _ = self._run_cli(
                "search", "codex", "plugin", "workflow", "--harness", "all"
            )
            self.assertEqual(code, 0)
            payload = json.loads(raw)
            t1_names = {m["name"] for m in payload["tier1_active_matches"]}
            inactive_names = {
                m["name"] for m in payload["inactive_codex_skill_matches"]
            }
            self.assertIn("skill-cx-on", t1_names)
            self.assertNotIn("skill-cx-off", t1_names)
            self.assertIn("skill-cx-off", inactive_names)

    # COMP-02 / COMP-03: Missing and malformed config.json (fail-closed) and malformed config.toml
    def test_missing_config_json_allows_non_disabled_plugins(self) -> None:
        plug_ok = self.plugins_dir / "plug-ok"
        plug_ok.mkdir(parents=True, exist_ok=True)
        (plug_ok / "plugin.json").write_text(
            json.dumps({"name": "plug-ok"}), encoding="utf-8"
        )
        self._write_skill(plug_ok / "skills", "skill-ok")

        plug_dis = self.plugins_dir / "plug-dis"
        plug_dis.mkdir(parents=True, exist_ok=True)
        (plug_dis / "plugin.json").write_text(
            json.dumps({"name": "plug-dis", "disabled": True}), encoding="utf-8"
        )
        self._write_skill(plug_dis / "skills", "skill-dis")

        with self._patch_scout_home():
            disabled, enabled, err = scout._parse_plugin_states()
            self.assertEqual(disabled, set())
            self.assertEqual(enabled, set())
            self.assertIsNone(err)

            active = scout.collect_active_skills(harness="antigravity")
            self.assertEqual({s["name"] for s in active}, {"skill-ok"})

    def test_malformed_config_json_fails_closed_and_malformed_config_toml_omits_plugins(
        self,
    ) -> None:
        self._setup_antigravity_host()
        self._setup_codex_host()
        # Corrupt config.json
        self.config_json_path.write_text("{invalid json", encoding="utf-8")
        # Corrupt config.toml
        self.codex_config_path.write_text("[plugins\nbroken = ", encoding="utf-8")

        with self._patch_scout_home():
            code, out, err_text = self._run_cli("inventory", "--harness", "all")
            self.assertEqual(code, 0)
            self.assertIn("fail-closed", err_text)
            payload = json.loads(out)
            self.assertIsNotNone(payload.get("config_warning"))
            names = {s["name"] for s in payload["skills"]}
            # Antigravity plugins omitted fail-closed; global/builtin remain
            self.assertNotIn("ag-plug-skill", names)
            self.assertIn("ag-global", names)
            self.assertIn("ag-builtin", names)
            # Codex plugins omitted on TOMLDecodeError; codex global remains
            self.assertNotIn("cx-plug-skill", names)
            self.assertIn("cx-global", names)

            # Non-object root JSON (e.g. []) also fails closed
            self.config_json_path.write_text("[]", encoding="utf-8")
            _, _, err_val = scout._parse_plugin_states()
            self.assertEqual(err_val, "root JSON value is not an object")

    # COMP-06: Duplicate skill names across hosts & identical content across distinct plugins
    def test_duplicate_names_and_identical_content_preserve_provenance(self) -> None:
        # Same name, different content across Antigravity and Codex
        self._write_skill(
            self.global_skills_dir,
            "shared-name",
            body="# Antigravity variant\n",
        )
        self._write_skill(
            self.codex_skills_dir,
            "shared-name",
            body="# Codex variant\n",
        )

        # Identical content across two distinct plugins (Antigravity plugin vs Codex plugin)
        identical_body = "# Identical Shared Skill\n\nStep 1: Verify.\n"
        ag_plug = self.plugins_dir / "plug-alpha"
        ag_plug.mkdir(parents=True, exist_ok=True)
        (ag_plug / "plugin.json").write_text(
            json.dumps({"name": "plug-alpha"}), encoding="utf-8"
        )
        self._write_skill(ag_plug / "skills", "twin-skill", body=identical_body)

        cx_plug_ver = self.codex_cache_dir / "mkt" / "plug-beta" / "1.0.0"
        self._write_skill(cx_plug_ver / "skills", "twin-skill", body=identical_body)
        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            '[marketplaces.mkt]\nsource_type = "git"\n\n'
            '[plugins."plug-beta@mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

        with self._patch_scout_home():
            skills = scout.collect_active_skills(harness="all")
            shared_entries = [s for s in skills if s["name"] == "shared-name"]
            self.assertEqual(len(shared_entries), 2)
            self.assertEqual(
                {s["source"] for s in shared_entries},
                {"global:skills", "codex:global-skills"},
            )
            self.assertTrue(all(s["name_collision"] for s in shared_entries))
            self.assertTrue(all(not s["shadowed"] for s in shared_entries))
            self.assertTrue(
                all(not s.get("duplicate_candidate") for s in shared_entries)
            )

            twin_entries = [s for s in skills if s["name"] == "twin-skill"]
            self.assertEqual(len(twin_entries), 2)
            self.assertEqual(
                {s["source"] for s in twin_entries},
                {"plugin:plug-alpha", "codex-plugin:plug-beta@mkt"},
            )
            self.assertTrue(all(s["name_collision"] for s in twin_entries))
            self.assertTrue(all(s.get("duplicate_candidate") for s in twin_entries))
            self.assertTrue(all(not s["shadowed"] for s in twin_entries))

    def test_same_physical_directory_deduplicated_across_hosts(self) -> None:
        # Codex local marketplace pointing to the exact same Antigravity plugin dir
        ag_plug = self.plugins_dir / "shared-phys"
        ag_plug.mkdir(parents=True, exist_ok=True)
        (ag_plug / "plugin.json").write_text(
            json.dumps({"name": "shared-phys"}), encoding="utf-8"
        )
        self._write_skill(ag_plug / "skills", "phys-skill")

        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            f'[marketplaces.local_mkt]\nsource_type = "local"\nsource = {json.dumps(str(ag_plug))}\n\n'
            '[plugins."shared-phys@local_mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

        with self._patch_scout_home():
            skills = scout.collect_active_skills(harness="all")
            phys_entries = [s for s in skills if s["name"] == "phys-skill"]
            self.assertEqual(len(phys_entries), 1)
            self.assertEqual(phys_entries[0]["source"], "plugin:shared-phys")

    # COMP-07: Outdated vs newest Codex cache versions & local marketplace precedence
    def test_codex_cache_selects_newest_numeric_version_with_skills(self) -> None:
        plugin_cache = self.codex_cache_dir / "mkt" / "versioned"
        self._write_skill(
            plugin_cache / "0.9.0" / "skills",
            "ver-skill",
            description="version 0.9.0",
        )
        self._write_skill(
            plugin_cache / "1.2.0" / "skills",
            "ver-skill",
            description="version 1.2.0",
        )
        self._write_skill(
            plugin_cache / "1.10.0" / "skills",
            "ver-skill",
            description="version 1.10.0",
        )
        # Empty 2.0.0 dir without skills/*/SKILL.md should be skipped in favor of 1.10.0
        (plugin_cache / "2.0.0").mkdir(parents=True, exist_ok=True)

        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            '[marketplaces.mkt]\nsource_type = "git"\n\n'
            '[plugins."versioned@mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

        with self._patch_scout_home():
            sources = scout._codex_plugin_sources()
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0][1], plugin_cache / "1.10.0")
            codex_items = scout.collect_codex_skills()
            self.assertEqual(len(codex_items), 1)
            self.assertEqual(codex_items[0]["description"], "version 1.10.0")

    def test_codex_local_marketplace_extended_prefix_precedence(self) -> None:
        local_repo = self.root / "local_codex_plugin"
        self._write_skill(
            local_repo / "skills", "local-skill", description="local copy"
        )
        self._write_skill(
            self.codex_cache_dir / "local_mkt" / "myplug" / "9.9.9" / "skills",
            "local-skill",
            description="cached copy",
        )
        raw_source = "\\\\?\\" + str(local_repo)
        self.codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config_path.write_text(
            f'[marketplaces.local_mkt]\nsource_type = "local"\nsource = {json.dumps(raw_source)}\n\n'
            '[plugins."myplug@local_mkt"]\nenabled = true\n',
            encoding="utf-8",
        )

        with self._patch_scout_home():
            items = scout.collect_codex_skills()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["description"], "local copy")

    # COMP-04 / COMP-10: Standalone skill copy layout (SKILL.md + scripts/skill_scout.py)
    def test_standalone_skill_copy_layout_in_isolated_fake_home(self) -> None:
        standalone_dir = self.home / ".agents" / "skills" / "skill-pilot"
        scripts_dir = standalone_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL_MD_PATH, standalone_dir / "SKILL.md")
        standalone_script = scripts_dir / "skill_scout.py"
        shutil.copy2(SCRIPT_PATH, standalone_script)

        # Also place a standalone warehouse config inside SKILL_ROOT
        wh = self.root / "standalone_wh"
        self._write_skill(
            wh / "skills", "wh-sample", description="standalone warehouse sample"
        )
        (standalone_dir / ".skill-pilot.local.json").write_text(
            json.dumps({"warehouses": [str(wh)]}), encoding="utf-8"
        )

        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        env.pop("SKILL_PILOT_WAREHOUSES", None)

        inv_proc = subprocess.run(
            [
                sys.executable,
                str(standalone_script),
                "inventory",
                "--harness",
                "auto",
                "--workspace",
                str(self.home),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(inv_proc.returncode, 0, msg=inv_proc.stderr)
        inv_payload = json.loads(inv_proc.stdout)
        self.assertIn("skill-pilot", {s["name"] for s in inv_payload["skills"]})

        proc = subprocess.run(
            [
                sys.executable,
                str(standalone_script),
                "search",
                "standalone",
                "warehouse",
                "sample",
                "--harness",
                "auto",
                "--workspace",
                str(self.home),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        t2_names = {m["name"] for m in payload["tier2_warehouse_matches"]}
        self.assertIn("wh-sample", t2_names)

        # Verify PLUGIN_ROOT fell back to SKILL_ROOT in standalone layout
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util, pathlib; "
                    f"p = pathlib.Path({str(standalone_script)!r}); "
                    "spec = importlib.util.spec_from_file_location('s', p); "
                    "m = importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(m); "
                    "print(m.PLUGIN_ROOT == m.SKILL_ROOT)"
                ),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, msg=probe.stderr)
        self.assertEqual(probe.stdout.strip(), "True")

    # COMP-01 / COMP-10: Warehouse resolution precedence in fake-home isolation
    def test_resolve_warehouses_precedence_isolated(self) -> None:
        cli_wh = self.root / "wh_cli"
        env_wh = self.root / "wh_env"
        cfg_wh = self.root / "wh_cfg"
        for wh in (cli_wh, env_wh, cfg_wh, self.default_wh, self.ecc_wh):
            (wh / "skills").mkdir(parents=True, exist_ok=True)
        self.local_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_cfg_path.write_text(
            json.dumps({"warehouses": [str(cfg_wh)]}), encoding="utf-8"
        )

        with (
            self._patch_scout_home(),
            mock.patch.dict(os.environ, {"SKILL_PILOT_WAREHOUSES": str(env_wh)}),
        ):
            resolved = scout.resolve_warehouses(str(cli_wh))
            self.assertEqual(
                resolved, [cli_wh, env_wh, cfg_wh, self.default_wh, self.ecc_wh]
            )

    # COMP-11: CLI --version / -V interface
    def test_cli_version_flag_outputs_semver(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn(scout.__version__, proc.stdout)

    # SPEC-07 / SPEC-08 / QA-07: Optional metadata, cross-host manifests, CRLF/LF & BOM parity
    def test_spec07_08_qa07_optional_metadata_and_cross_platform_parity(self) -> None:
        sdir = self.root / "opt-meta-skill"
        sdir.mkdir()
        crlf_skill = (
            "---\r\n"
            "name: opt-meta-skill\r\n"
            "description: Cross-host optional metadata check\r\n"
            "license: MIT\r\n"
            "compatibility: Python 3.12+ stdlib\r\n"
            'argument-hint: "[task]"\r\n'
            "metadata:\r\n"
            "  author: test\r\n"
            "---\r\n"
            "# Body\r\n"
        )
        (sdir / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + crlf_skill.encode("utf-8"))
        code, raw, _ = self._run_cli("validate", str(sdir))
        self.assertEqual(code, 0, raw)
        payload = json.loads(raw)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["warnings"], [])

        # Oversized compatibility (>500 chars) emits non-fatal warning
        long_compat = "x" * 505
        (sdir / "SKILL.md").write_text(
            "---\nname: opt-meta-skill\ndescription: ok\n"
            f"compatibility: {long_compat}\n---\n",
            encoding="utf-8",
        )
        code2, raw2, _ = self._run_cli("validate", str(sdir))
        self.assertEqual(code2, 0, raw2)
        self.assertTrue(
            any(
                "Compatibility exceeds 500 chars" in w
                for w in json.loads(raw2)["warnings"]
            )
        )

        # SPEC-08: Verify Antigravity vs Codex manifest schemas in repo root
        ag_manifest = json.loads((ROOT / "plugin.json").read_text("utf-8"))
        cx_manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text("utf-8")
        )
        self.assertEqual(ag_manifest["name"], cx_manifest["name"])
        self.assertEqual(ag_manifest["version"], cx_manifest["version"])
        self.assertIn("suggestedPrompts", ag_manifest)
        self.assertIn("interface", cx_manifest)
        self.assertEqual(cx_manifest["skills"], "./skills/")


if __name__ == "__main__":
    unittest.main()
