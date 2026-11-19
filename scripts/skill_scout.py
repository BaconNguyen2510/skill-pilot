#!/usr/bin/env python3
"""Cross-plugin and multi-tier skill discovery helper for Skill Pilot.

Provides deterministic, zero-dependency indexing across:
- Tier 1: Active Antigravity and Codex skills (plugins, global, builtin, workspace)
- Tier 2: Local skill warehouses (skills_index.json or skills/*/SKILL.md)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import tomllib
import unicodedata
from typing import Any

HOME = pathlib.Path.home()
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]
GEMINI_CONFIG_DIR = HOME / ".gemini" / "config"
PLUGINS_DIR = GEMINI_CONFIG_DIR / "plugins"
GLOBAL_SKILLS_DIR = GEMINI_CONFIG_DIR / "skills"
BUILTIN_SKILLS_DIR = HOME / ".gemini" / "antigravity" / "builtin" / "skills"
CONFIG_JSON_PATH = GEMINI_CONFIG_DIR / "config.json"

LOCAL_CONFIG_PATHS = (
    PLUGIN_ROOT / ".skill-pilot.local.json",
    GEMINI_CONFIG_DIR / "skill-pilot.local.json",
)
DEFAULT_WAREHOUSES = (HOME / ".agents" / "warehouses" / "agentic-awesome-skills",)
ECC_WAREHOUSES = (HOME / ".gemini" / "antigravity" / "ecc",)
CODEX_DIR = HOME / ".codex"
CODEX_SKILLS_DIR = CODEX_DIR / "skills"
CODEX_INACTIVE_SKILLS_DIR = CODEX_DIR / "skills-inactive"
CODEX_CONFIG_PATH = CODEX_DIR / "config.toml"
CODEX_CACHE_DIR = CODEX_DIR / "plugins" / "cache"

SCRIPT_EXTENSIONS = {".py", ".sh", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".bat", ".cmd"}
HEALTHY_ACTIVE_CEILING = 90


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _strip_jsonc_comments(raw: str) -> str:
    """Remove // and /* */ comments and trailing commas for JSONC manifests."""
    out: list[str] = []
    i = 0
    n = len(raw)
    in_string = False
    escape = False
    while i < n:
        ch = raw[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "/":
            i += 2
            while i < n and raw[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "*":
            i += 2
            while i + 1 < n and not (raw[i] == "*" and raw[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def _load_jsonc(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return json.loads(_strip_jsonc_comments(text))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def parse_frontmatter(skill_md: pathlib.Path) -> dict[str, str]:
    """Parse YAML frontmatter name and description using pure stdlib."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"name": skill_md.parent.name, "description": ""}

    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)

    result: dict[str, str] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            i += 1
            continue
        key = match.group(1).strip()
        val = match.group(2).strip()
        if val in (">", ">-", "|", "|-"):
            block: list[str] = []
            i += 1
            while i < len(fm_lines):
                nxt = fm_lines[i]
                if nxt and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
                i += 1
            joined = (
                " ".join(part for part in block if part)
                if val.startswith(">")
                else "\n".join(block).strip()
            )
            result[key] = joined.strip()
            continue
        if (val.startswith("'") and val.endswith("'") and len(val) >= 2) or (
            val.startswith('"') and val.endswith('"') and len(val) >= 2
        ):
            val = val[1:-1]
        result[key] = val.strip()
        i += 1

    if not result.get("name"):
        result["name"] = skill_md.parent.name
    if "description" not in result:
        result["description"] = ""
    return result


def _disabled_plugin_dirs() -> set[str]:
    cfg = _load_jsonc(CONFIG_JSON_PATH)
    plugins_cfg = cfg.get("plugins", {}) if isinstance(cfg, dict) else {}
    disabled: set[str] = set()
    if isinstance(plugins_cfg, dict):
        for pdir, state in plugins_cfg.items():
            if isinstance(state, dict) and state.get("enabled") is False:
                disabled.add(pdir)
    return disabled


def collect_active_skills(
    workspace: str | None = None, harness: str = "antigravity"
) -> list[dict[str, Any]]:
    """Collect all Tier 1 active skills across plugins, global, builtin, and workspace."""
    skills: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    disabled_dirs = _disabled_plugin_dirs()

    def add_skill(
        skill_md: pathlib.Path, source: str, tier: str, priority: int
    ) -> None:
        meta = parse_frontmatter(skill_md)
        name = meta["name"]
        skills.append(
            {
                "name": name,
                "description": meta["description"],
                "source": source,
                "tier": tier,
                "priority": priority,
                "shadowed": name in seen_names,
                "skill_md_path": str(skill_md),
            }
        )
        seen_names.add(name)

    include_antigravity = harness in ("auto", "antigravity", "all")
    if workspace:
        ws_path = pathlib.Path(workspace).expanduser().resolve()
        workspace_roots = [ws_path]
        if ws_path.name.lower() == "workspaces" and ws_path.is_dir():
            workspace_roots.extend(
                sorted(path for path in ws_path.iterdir() if path.is_dir())
            )
        for root in workspace_roots:
            for dot_dir in (".agents", ".agent", "_agents", "_agent"):
                skills_root = root / dot_dir / "skills"
                if skills_root.is_dir():
                    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
                        add_skill(
                            skill_md, f"workspace:{root.name}", "tier1-workspace", 1
                        )

    if include_antigravity and GLOBAL_SKILLS_DIR.is_dir():
        for skill_md in sorted(GLOBAL_SKILLS_DIR.glob("*/SKILL.md")):
            add_skill(skill_md, "global:skills", "tier1-global", 2)

    if include_antigravity and PLUGINS_DIR.is_dir():
        for plugin_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()):
            manifest = _load_jsonc(plugin_dir / "plugin.json")
            if plugin_dir.name in disabled_dirs:
                continue
            if (
                manifest.get("disabled") is True
                and plugin_dir.name not in _explicitly_enabled_plugins()
            ):
                continue
            plugin_name = str(manifest.get("name") or plugin_dir.name)
            skills_dir = plugin_dir / "skills"
            if skills_dir.is_dir():
                for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
                    add_skill(skill_md, f"plugin:{plugin_name}", "tier1-plugin", 3)

    if include_antigravity and BUILTIN_SKILLS_DIR.is_dir():
        for skill_md in sorted(BUILTIN_SKILLS_DIR.glob("*/SKILL.md")):
            add_skill(skill_md, "builtin", "tier1-builtin", 4)

    if harness in ("auto", "codex", "all"):
        skills.extend(collect_codex_skills())
    return skills


def _codex_plugin_sources(
    include_inactive: bool = False,
) -> list[tuple[str, pathlib.Path, bool]]:
    """Resolve installed Codex plugin paths and report whether each is enabled."""
    try:
        config = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    sources: list[tuple[str, pathlib.Path, bool]] = []
    marketplaces = config.get("marketplaces", {})
    for plugin_id, state in config.get("plugins", {}).items():
        if not isinstance(state, dict) or "@" not in plugin_id:
            continue
        enabled = state.get("enabled") is True
        if not enabled and not include_inactive:
            continue
        plugin_name, marketplace_name = plugin_id.split("@", 1)
        marketplace = marketplaces.get(marketplace_name, {})
        local_source = (
            str(marketplace.get("source", "")) if isinstance(marketplace, dict) else ""
        )
        local_source = local_source.removeprefix("\\\\?\\")
        if (
            isinstance(marketplace, dict)
            and marketplace.get("source_type") == "local"
            and local_source
        ):
            local_path = pathlib.Path(local_source)
            if local_path.is_dir():
                sources.append((plugin_id, local_path, enabled))
        cache_root = CODEX_CACHE_DIR / marketplace_name / plugin_name
        if cache_root.is_dir():
            sources.extend(
                (plugin_id, version_dir, enabled)
                for version_dir in sorted(cache_root.iterdir())
                if version_dir.is_dir()
            )
    return sources


def collect_codex_skills(include_inactive: bool = False) -> list[dict[str, Any]]:
    """Collect Codex skills, optionally including disabled plugin skills as candidates."""
    skills: list[dict[str, Any]] = []
    seen_skills: set[tuple[str, str]] = set()

    def add(skill_md: pathlib.Path, source: str, tier: str, priority: int) -> None:
        meta = parse_frontmatter(skill_md)
        key = (source, meta["name"])
        if key in seen_skills:
            return
        seen_skills.add(key)
        skills.append(
            {
                "name": meta["name"],
                "description": meta["description"],
                "source": source,
                "tier": tier,
                "priority": priority,
                "shadowed": False,
                "skill_md_path": str(skill_md),
                "inactive": source.startswith(
                    ("codex-plugin-inactive:", "codex-skill-inactive")
                ),
            }
        )

    if CODEX_SKILLS_DIR.is_dir():
        for skill_md in sorted(CODEX_SKILLS_DIR.glob("*/SKILL.md")):
            add(skill_md, "codex:global-skills", "tier1-codex", 5)
    if include_inactive and CODEX_INACTIVE_SKILLS_DIR.is_dir():
        for skill_md in sorted(CODEX_INACTIVE_SKILLS_DIR.glob("*/SKILL.md")):
            add(skill_md, "codex-skill-inactive", "tier2-codex-inactive", 7)
    for plugin_id, plugin_root, enabled in _codex_plugin_sources(include_inactive):
        source = (
            f"codex-plugin:{plugin_id}"
            if enabled
            else f"codex-plugin-inactive:{plugin_id}"
        )
        for skill_md in sorted(plugin_root.glob("skills/**/SKILL.md")):
            add(
                skill_md,
                source,
                "tier1-codex-plugin" if enabled else "tier2-codex-inactive",
                6,
            )
    return skills


def _explicitly_enabled_plugins() -> set[str]:
    cfg = _load_jsonc(CONFIG_JSON_PATH)
    plugins_cfg = cfg.get("plugins", {}) if isinstance(cfg, dict) else {}
    enabled: set[str] = set()
    if isinstance(plugins_cfg, dict):
        for pdir, state in plugins_cfg.items():
            if isinstance(state, dict) and state.get("enabled") is True:
                enabled.add(pdir)
    return enabled


def _is_valid_warehouse(wh: pathlib.Path) -> bool:
    return (wh / "skills_index.json").is_file() or (wh / "skills").is_dir()


def _load_warehouse_records(wh: pathlib.Path) -> list[dict[str, Any]]:
    index_path = wh / "skills_index.json"
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: failed reading {index_path}: {exc}", file=sys.stderr)
            return []

    skills_root = wh / "skills"
    if not skills_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    warehouse_name = wh.name.lower()
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        meta = parse_frontmatter(skill_md)
        slug = skill_md.parent.name
        records.append(
            {
                "id": slug,
                "name": meta["name"] or slug,
                "category": warehouse_name,
                "risk": "low",
                "description": meta["description"],
                "tags": [warehouse_name],
                "path": f"skills/{slug}",
            }
        )
    return records


def _load_local_warehouse_paths() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for cfg_path in LOCAL_CONFIG_PATHS:
        data = _load_jsonc(cfg_path)
        raw = data.get("warehouses", []) if isinstance(data, dict) else []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.strip():
                    paths.append(pathlib.Path(entry.strip()).expanduser())
    return paths


def resolve_warehouses(cli_warehouse: str | None) -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    if cli_warehouse:
        paths.append(pathlib.Path(cli_warehouse).expanduser())
    env_val = os.environ.get("SKILL_PILOT_WAREHOUSES", "")
    if env_val:
        paths.extend(
            pathlib.Path(part.strip()).expanduser()
            for part in env_val.split(os.pathsep)
            if part.strip()
        )
    paths.extend(_load_local_warehouse_paths())
    valid_paths: list[pathlib.Path] = []
    for p in paths:
        if _is_valid_warehouse(p) and p not in valid_paths:
            valid_paths.append(p)
    for fallbacks in (DEFAULT_WAREHOUSES, ECC_WAREHOUSES):
        selected = next((path for path in fallbacks if _is_valid_warehouse(path)), None)
        if selected is not None and selected not in valid_paths:
            valid_paths.append(selected)
    return valid_paths


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return [
        t
        for t in re.split(r"[^a-z0-9]+", normalized.encode("ascii", "ignore").decode())
        if len(t) >= 2
    ]


def query_terms(query: str) -> list[str]:
    """Expand common English and Vietnamese task terms without external services."""
    tokens = tokenize(query)
    normalized = " ".join(tokens)
    aliases = {
        "tai chinh": "finance financial",
        "bao cao": "report reporting",
        "ke toan": "accounting",
        "nghien cuu": "research",
        "lap trinh": "programming code",
        "xac thuc": "authentication auth",
        "sua loi": "debug bug fix",
        "trinh bay": "presentation slides",
        "thuyet trinh": "presentation slides",
        "bai tap": "assignment coursework",
        "don gian hoa": "simplification simplify refactor",
        "toi uu": "optimization optimize",
        "truy van": "query sql",
        "cham": "slow performance",
        "dep": "design frontend ui",
        "web": "frontend ui",
        "dashboard": "frontend ui dashboard",
        "chi tieu": "finance budget spending",
        "comment": "comments social research analysis",
        "phan tich": "analysis analyze research",
        "auth": "authentication",
        "bug": "debug",
        "debug": "debugging error recovery",
        "failing": "debugging error recovery",
        "plan": "planning",
        "break down": "planning task breakdown",
        "spreadsheet": "excel",
    }
    stop_words = {
        "make",
        "create",
        "build",
        "help",
        "please",
        "with",
        "for",
        "the",
        "and",
        "lam",
        "tao",
        "giup",
        "cho",
        "cua",
        "theo",
        "doi",
        "gon",
    }
    expanded = [token for token in tokens if token not in stop_words]
    for phrase, terms in aliases.items():
        if f" {phrase} " in f" {normalized} ":
            expanded.extend(terms.split())
    return list(dict.fromkeys(expanded))


def score_record(
    query: str,
    q_tokens: list[str],
    name: str,
    category: str,
    tags: list[str],
    desc: str,
) -> float:
    q_lower = query.lower().strip()
    name_l = name.lower()
    cat_l = category.lower()
    tags_l = " ".join(str(t).lower() for t in tags)
    desc_l = desc.lower()

    score = 0.0
    if q_lower and q_lower == name_l:
        score += 25.0
    elif q_lower and q_lower in name_l:
        score += 12.0
    if q_lower and q_lower in desc_l:
        score += 6.0

    name_tokens = set(tokenize(name_l))
    cat_tokens = set(tokenize(cat_l))
    tag_tokens = set(tokenize(tags_l))
    desc_tokens = set(tokenize(desc_l))
    if "d3" in q_tokens and "d3" not in name_tokens | tag_tokens | desc_tokens:
        return 0.0

    matched_tokens = 0
    for tok in q_tokens:
        hit = False
        if tok in name_tokens:
            score += 6.0
            hit = True
        if tok in cat_tokens:
            score += 3.5
            hit = True
        if tok in tag_tokens:
            score += 4.0
            hit = True
        if tok in desc_tokens:
            score += 2.0
            hit = True
        if hit:
            matched_tokens += 1

    if q_tokens:
        coverage = matched_tokens / len(q_tokens)
        score *= 0.5 + coverage
    return round(score, 2)


def cmd_inventory(args: argparse.Namespace) -> int:
    skills = collect_active_skills(args.workspace, args.harness)
    active = [s for s in skills if not s["shadowed"]]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for s in active:
        by_source.setdefault(s["source"], []).append(s)

    if args.format == "summary":
        print(
            f"Active skills: {len(active)} (total discovered including shadowed: {len(skills)})"
        )
        for src, items in by_source.items():
            names = ", ".join(item["name"] for item in items)
            print(f"- {src} ({len(items)}): {names}")
        return 0

    payload = {
        "total_active": len(active),
        "by_source_counts": {k: len(v) for k, v in by_source.items()},
        "skills": active,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    """Summarize local project metadata without running project commands."""
    root = pathlib.Path(args.workspace).expanduser().resolve()
    if not root.is_dir():
        print(f"Workspace not found: {root}", file=sys.stderr)
        return 1
    rules: list[str] = []
    commands: list[str] = []
    for filename in ("AGENTS.md", "CLAUDE.md"):
        path = root / filename
        if not path.is_file():
            continue
        rules.append(str(path))
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            for command in re.findall(r"`([^`\r\n]+)`", line):
                if (
                    re.search(
                        r"\b(?:uv run|pytest|npm (?:run|test)|pnpm|yarn|cargo test|go test)\b",
                        command,
                    )
                    and command not in commands
                ):
                    commands.append(command)
    stack: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get(
                "project", {}
            )
            stack.append(
                f"Python {project.get('requires-python', 'version unspecified')} ({pyproject})"
            )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            stack.append(f"Cannot parse {pyproject}: {exc}")
    package = root / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
            stack.append(f"Node package: {package}")
            for name in data.get("scripts", {}):
                command = f"npm run {name}"
                if command not in commands:
                    commands.append(command)
        except (OSError, json.JSONDecodeError) as exc:
            stack.append(f"Cannot parse {package}: {exc}")
    result = {
        "workspace": str(root),
        "rules": rules,
        "stack": stack,
        "commands": commands,
    }
    if args.format == "compact":
        print(f"Workspace: {root}")
        for path in rules:
            print(f"Rule file (read before acting): {path}")
        for item in stack[:3]:
            print(f"Stack: {item}")
        for command in commands[:15]:
            print(f"Documented command: {command}")
        if len(commands) > 15:
            print(f"Additional documented commands omitted: {len(commands) - 15}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    q_tokens = query_terms(query)
    if not q_tokens and not query:
        print(json.dumps({"error": "Empty search query"}))
        return 1

    tier1_hits: list[dict[str, Any]] = []
    inactive_hits: list[dict[str, Any]] = []
    if args.include_active:
        for s in collect_active_skills(args.workspace, args.harness):
            if s["shadowed"] or s["name"] == "skill-pilot":
                continue
            sc = score_record(
                query, q_tokens, s["name"], s["source"], [], s["description"]
            )
            if sc > 0:
                tier1_hits.append({**s, "score": round(sc * 3.5, 2)})
        tier1_hits.sort(key=lambda x: x["score"], reverse=True)
    if args.harness in ("auto", "codex", "all"):
        for skill in collect_codex_skills(include_inactive=True):
            if not skill["inactive"]:
                continue
            score = score_record(
                query,
                q_tokens,
                skill["name"],
                skill["source"],
                [],
                skill["description"],
            )
            if score > 0:
                inactive_hits.append({**skill, "score": score})
        inactive_hits.sort(key=lambda item: item["score"], reverse=True)

    tier2_hits: list[dict[str, Any]] = []
    warehouses = resolve_warehouses(args.warehouse)
    for wh in warehouses:
        records = _load_warehouse_records(wh)
        for rec in records:
            risk = str(rec.get("risk") or "unknown").lower()
            if risk == "offensive" and not args.allow_risky:
                continue
            tags = rec.get("tags")
            sc = score_record(
                query,
                q_tokens,
                str(rec.get("name") or rec.get("id") or ""),
                str(rec.get("category") or ""),
                tags if isinstance(tags, list) else [],
                str(rec.get("description") or ""),
            )
            if sc <= 0:
                continue
            if risk == "critical":
                sc *= 0.9
            rel_path = str(rec.get("path") or "")
            skill_dir = wh / rel_path
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            tier2_hits.append(
                {
                    "id": rec.get("id"),
                    "name": rec.get("name"),
                    "category": rec.get("category"),
                    "risk": risk,
                    "description": rec.get("description"),
                    "tags": rec.get("tags", []),
                    "warehouse": str(wh),
                    "skill_md_path": str(skill_md),
                    "exists": skill_md.is_file(),
                    "score": round(sc, 2),
                }
            )
    tier2_hits.sort(key=lambda x: x["score"], reverse=True)

    # A name is the skill's declared identity; prefer the already active copy.
    unique: dict[str, tuple[str, dict[str, Any]]] = {}
    for label, matches in (
        ("active", tier1_hits),
        ("warehouse", tier2_hits),
        ("inactive", inactive_hits),
    ):
        for item in matches:
            identity = "-".join(tokenize(str(item.get("name") or item.get("id") or "")))
            if identity and identity not in unique:
                unique[identity] = (label, item)
    tier1_hits = [item for label, item in unique.values() if label == "active"]
    tier2_hits = [item for label, item in unique.values() if label == "warehouse"]
    inactive_hits = [item for label, item in unique.values() if label == "inactive"]

    output = {
        "query": query,
        "warehouses_scanned": [str(w) for w in warehouses],
        "tier1_active_matches": tier1_hits[: args.limit],
        "inactive_codex_skill_matches": inactive_hits[: args.limit],
        "tier2_warehouse_matches": tier2_hits[: args.limit],
    }
    if args.format == "compact":
        print(f"Query: {query}")
        print("Warehouses: " + (", ".join(str(w) for w in warehouses) or "none"))
        ranked = [
            (label, item)
            for label, matches in (
                ("active", tier1_hits),
                ("inactive", inactive_hits),
                ("warehouse", tier2_hits),
            )
            for item in matches
        ]
        ranked.sort(key=lambda pair: pair[1]["score"], reverse=True)
        for label, item in ranked[: args.limit]:
            risk = f" | risk:{item['risk']}" if label == "warehouse" else ""
            print(
                f"{label} | {item['name']} | {item['score']}{risk} | {item['skill_md_path']}"
            )
        if not (tier1_hits or inactive_hits or tier2_hits):
            print("No matches; try domain-specific synonyms.")
        return 0
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def _resolve_target_skill_dir(
    target: str, warehouse: str | None
) -> pathlib.Path | None:
    candidate = pathlib.Path(target).expanduser()
    if candidate.is_file() and candidate.name.upper() == "SKILL.MD":
        return candidate.parent
    if candidate.is_dir() and (candidate / "SKILL.md").is_file():
        return candidate

    for s in collect_active_skills(harness="all"):
        if s["name"] == target:
            return pathlib.Path(s["skill_md_path"]).parent

    for skill in collect_codex_skills(include_inactive=True):
        if skill["name"] == target:
            return pathlib.Path(skill["skill_md_path"]).parent

    for wh in resolve_warehouses(warehouse):
        records = _load_warehouse_records(wh)
        for rec in records:
            if rec.get("id") == target or rec.get("name") == target:
                sdir = wh / str(rec.get("path") or "")
                if (sdir / "SKILL.md").is_file():
                    return sdir
    return None


def cmd_inspect(args: argparse.Namespace) -> int:
    sdir = _resolve_target_skill_dir(args.target, args.warehouse)
    if sdir is None:
        print(json.dumps({"error": f"Skill not found: {args.target}"}))
        return 1

    skill_md = sdir / "SKILL.md"
    meta = parse_frontmatter(skill_md)
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    files: list[str] = []
    scripts: list[str] = []
    for f in sorted(sdir.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(sdir)).replace("\\", "/")
            files.append(rel)
            if f.suffix.lower() in SCRIPT_EXTENSIONS or rel.startswith("scripts/"):
                scripts.append(rel)

    headings = [ln for ln in lines if ln.startswith("#")]
    if args.format == "compact":
        print(f"{meta['name']} | {skill_md}")
        print(f"Description: {meta['description']}")
        print(f"Scripts: {', '.join(scripts) if scripts else 'none'}")
        return 0
    payload = {
        "name": meta["name"],
        "description": meta["description"],
        "skill_dir": str(sdir),
        "skill_md_path": str(skill_md),
        "line_count": len(lines),
        "headings": headings[:30],
        "files": files[:50],
        "executable_or_script_files": scripts,
        "preview_lines": "\n".join(lines[: args.preview_lines]),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    warehouses = resolve_warehouses(args.warehouse)
    matched_rec: dict[str, Any] | None = None
    matched_wh: pathlib.Path | None = None
    for wh in warehouses:
        records = _load_warehouse_records(wh)
        for rec in records:
            if rec.get("id") == args.skill_id or rec.get("name") == args.skill_id:
                matched_rec = rec
                matched_wh = wh
                break
        if matched_rec:
            break

    if matched_rec is None or matched_wh is None:
        print(
            json.dumps(
                {"error": f"Skill '{args.skill_id}' not found in local warehouses"}
            )
        )
        return 1

    risk = str(matched_rec.get("risk") or "unknown").lower()
    if risk == "offensive" and not args.force:
        print(
            json.dumps(
                {"error": "Refusing to promote 'offensive' skill without --force"}
            )
        )
        return 1

    src_dir = (matched_wh / str(matched_rec.get("path") or "")).resolve()
    if (
        not src_dir.is_relative_to(matched_wh.resolve())
        or not (src_dir / "SKILL.md").is_file()
    ):
        print(json.dumps({"error": "Invalid skill source path"}))
        return 1
    dest_root = (
        pathlib.Path(args.dest).expanduser()
        if args.dest
        else (GLOBAL_SKILLS_DIR if args.target == "antigravity" else CODEX_SKILLS_DIR)
    )
    dest_name = str(matched_rec.get("id") or args.skill_id)
    if (
        dest_name in ("", ".", "..")
        or pathlib.PureWindowsPath(dest_name).name != dest_name
        or pathlib.Path(dest_name).name != dest_name
    ):
        print(json.dumps({"error": "Invalid skill destination name"}))
        return 1
    dest_dir = dest_root / dest_name
    resolved_dest = dest_dir.resolve()
    if dest_dir.is_symlink() or not resolved_dest.is_relative_to(dest_root.resolve()):
        print(json.dumps({"error": "Destination escapes skill directory"}))
        return 1
    if (
        resolved_dest == src_dir
        or src_dir.is_relative_to(resolved_dest)
        or resolved_dest.is_relative_to(src_dir)
    ):
        print(json.dumps({"error": "Source and destination overlap"}))
        return 1

    if dest_dir.exists() and not args.force:
        print(
            json.dumps(
                {
                    "error": f"Destination already exists: {dest_dir}. Pass --force to overwrite."
                }
            )
        )
        return 1

    dest_root.mkdir(parents=True, exist_ok=True)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)

    active_count = len(
        [s for s in collect_active_skills(harness=args.target) if not s["shadowed"]]
    )
    print(
        json.dumps(
            {
                "promoted": matched_rec.get("id"),
                "risk": risk,
                "source": str(src_dir),
                "installed_to": str(dest_dir),
                "active_skills_total": active_count,
                "bloat_warning": active_count > HEALTHY_ACTIVE_CEILING,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_prune_check(args: argparse.Namespace) -> int:
    skills = collect_active_skills(None, args.harness)
    active = [s for s in skills if not s["shadowed"]]
    counts: dict[str, int] = {}
    for s in active:
        counts[s["source"]] = counts.get(s["source"], 0) + 1
    global_standalone = [s["name"] for s in active if s["source"] == "global:skills"]
    over_budget = len(active) > args.threshold
    print(
        json.dumps(
            {
                "active_skills_total": len(active),
                "healthy_ceiling": args.threshold,
                "status": "OVER_BUDGET" if over_budget else "HEALTHY",
                "counts_by_source": counts,
                "global_standalone_skills": global_standalone,
                "recommendation": (
                    "Active skill count exceeds healthy ceiling; consider removing unused skills from ~/.gemini/config/skills/ or disabling unused plugins."
                    if over_budget
                    else "Active skill count is lean; keep Tier 2 warehouse skills cold unless reused frequently."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Skill Pilot multi-tier skill discovery tool"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser(
        "inventory",
        help="List all active Tier 1 skills across plugins and global/builtin dirs",
    )
    inv.add_argument(
        "--workspace", help="Optional workspace root path to include .agents/skills"
    )
    inv.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    inv.add_argument("--format", choices=["json", "summary"], default="json")
    inv.set_defaults(func=cmd_inventory)

    intake = sub.add_parser(
        "intake", help="Read workspace rules and documented commands"
    )
    intake.add_argument("--workspace", required=True)
    intake.add_argument("--format", choices=["json", "compact"], default="compact")
    intake.set_defaults(func=cmd_intake)

    srch = sub.add_parser(
        "search", help="Search Tier 1 active skills and Tier 2 local warehouse"
    )
    srch.add_argument("query", nargs="+", help="Search keywords")
    srch.add_argument("--limit", type=positive_int, default=12)
    srch.add_argument("--workspace", help="Optional workspace root path")
    srch.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    srch.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    srch.add_argument("--include-active", action="store_true", default=True)
    srch.add_argument("--no-active", dest="include_active", action="store_false")
    srch.add_argument(
        "--allow-risky",
        action="store_true",
        help="Include skills marked risk=offensive",
    )
    srch.add_argument("--format", choices=["json", "compact"], default="json")
    srch.set_defaults(func=cmd_search)

    insp = sub.add_parser(
        "inspect", help="Inspect a skill's SKILL.md and check for executable scripts"
    )
    insp.add_argument("target", help="Skill ID/name or path to SKILL.md/folder")
    insp.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    insp.add_argument("--preview-lines", type=int, default=60)
    insp.add_argument("--format", choices=["json", "compact"], default="json")
    insp.set_defaults(func=cmd_inspect)

    prom = sub.add_parser(
        "promote",
        help="Install a Tier 2 warehouse skill permanently to a harness skill directory",
    )
    prom.add_argument("skill_id", help="Skill ID or name in a local warehouse")
    prom.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    prom.add_argument("--dest", help="Override destination skills directory")
    prom.add_argument(
        "--target", choices=["antigravity", "codex"], default="antigravity"
    )
    prom.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing skill or promote risky skill",
    )
    prom.set_defaults(func=cmd_promote)

    prune = sub.add_parser(
        "prune-check",
        help="Check whether active skill count stays under healthy context ceiling",
    )
    prune.add_argument("--workspace", help="Optional workspace root path")
    prune.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    prune.add_argument("--threshold", type=int, default=HEALTHY_ACTIVE_CEILING)
    prune.set_defaults(func=cmd_prune_check)

    return parser


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main() -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
