"""Deterministic synthetic skill corpus and permission fixture builder.

Builds reproducible Tier 1 (active/codex) and Tier 2 (warehouse) skill trees
for offline retrieval evaluation, hard-negative decoy testing, scale
benchmarking (10/100/1k/10k), and OS-aware permission edge-case testing.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import stat
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillSpec:
    """Canonical specification for a synthetic skill fixture."""

    skill_id: str
    name: str
    category: str
    description: str
    tags: tuple[str, ...]
    risk: str | None = "low"
    tier: str = "warehouse"
    warehouse: str = "primary"
    has_script: bool = False
    malformed_frontmatter: bool = False
    body: str = ""


CANONICAL_CATALOG: tuple[SkillSpec, ...] = (
    # Finance / Valuation (3)
    SkillSpec(
        skill_id="dcf-valuation",
        name="dcf-valuation",
        category="finance",
        description=(
            "Discounted cash flow valuation, WACC calculation, terminal value "
            "sensitivity tables, and corporate finance modeling."
        ),
        tags=("finance", "valuation", "dcf", "wacc", "excel"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="fx-exposure",
        name="fx-exposure",
        category="finance",
        description=(
            "Foreign exchange transaction and translation exposure hedging, "
            "forward contracts, currency risk, and J-curve analysis."
        ),
        tags=("finance", "fx", "hedging", "currency", "derivatives"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="financial-ratio-audit",
        name="financial-ratio-audit",
        category="finance",
        description=(
            "Audit corporate financial statements, liquidity ratios, ROE, "
            "debt-to-equity, and working capital variance reports."
        ),
        tags=("finance", "accounting", "audit", "ratios", "reporting"),
        risk="low",
        warehouse="primary",
    ),
    # Frontend / UI (4)
    SkillSpec(
        skill_id="react-accessibility",
        name="react-accessibility",
        category="frontend",
        description=(
            "WCAG 2.2 accessibility audit for React components, ARIA roles, "
            "keyboard focus trapping, and screen reader labels."
        ),
        tags=("frontend", "react", "a11y", "wcag", "aria"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="tailwind-design-tokens",
        name="tailwind-design-tokens",
        category="frontend",
        description=(
            "Design system token architecture for Tailwind CSS v4, semantic "
            "color palettes, typography scales, and dark mode variables."
        ),
        tags=("frontend", "tailwind", "css", "design-system", "tokens"),
        risk="low",
        tier="codex",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="landing-page-builder",
        name="landing-page-builder",
        category="frontend",
        description=(
            "Responsive SaaS landing page layout, hero conversion sections, "
            "pricing matrices, and semantic HTML structure."
        ),
        tags=("frontend", "landing-page", "ui", "responsive", "html"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="animation-perf",
        name="animation-perf",
        category="frontend",
        description=(
            "Optimize CSS and React motion performance, eliminate layout "
            "thrashing, and use GPU compositor transforms safely."
        ),
        tags=("frontend", "animation", "performance", "fps", "css"),
        risk="low",
        warehouse="primary",
    ),
    # Backend / DB (4)
    SkillSpec(
        skill_id="postgres-query-tuning",
        name="postgres-query-tuning",
        category="backend",
        description=(
            "PostgreSQL EXPLAIN ANALYZE query plan tuning, B-tree and GIN "
            "indexing, N+1 elimination, and vacuum configuration."
        ),
        tags=("backend", "postgres", "sql", "database", "performance"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="sqlite-migrations",
        name="sqlite-migrations",
        category="backend",
        description=(
            "Zero-downtime SQLite schema migrations, WAL mode tuning, "
            "expand-and-contract table changes, and rollback scripts."
        ),
        tags=("backend", "sqlite", "migrations", "database", "schema"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="oauth-hardening",
        name="oauth-hardening",
        category="backend",
        description=(
            "OAuth 2.1 PKCE authentication hardening, JWT signature validation, "
            "refresh token rotation, and session cookie security."
        ),
        tags=("backend", "auth", "oauth", "jwt", "security"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="rest-api-design",
        name="rest-api-design",
        category="backend",
        description=(
            "OpenAPI REST endpoint design, pagination contracts, idempotency "
            "keys, rate limiting headers, and problem-details errors."
        ),
        tags=("backend", "api", "rest", "openapi", "contracts"),
        risk="low",
        warehouse="primary",
    ),
    # Mobile / Flutter (3)
    SkillSpec(
        skill_id="flutter-state-riverpod",
        name="flutter-state-riverpod",
        category="mobile",
        description=(
            "Flutter Riverpod state management, AsyncNotifier providers, "
            "immutable models, and widget rebuild optimization."
        ),
        tags=("mobile", "flutter", "riverpod", "dart", "state"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="expo-native-ui",
        name="expo-native-ui",
        category="mobile",
        description=(
            "Expo React Native native navigation, Apple HIG sheets, SF Symbols, "
            "and adaptive iOS/Android screen layouts."
        ),
        tags=("mobile", "expo", "react-native", "ios", "android"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="mobile-offline-sync",
        name="mobile-offline-sync",
        category="mobile",
        description=(
            "Offline-first mobile data synchronization queue, conflict "
            "resolution, local SQLite cache, and background retry."
        ),
        tags=("mobile", "offline", "sync", "cache", "sqlite"),
        risk="low",
        warehouse="secondary",
    ),
    # DevOps / Security (5)
    SkillSpec(
        skill_id="docker-compose-hardening",
        name="docker-compose-hardening",
        category="devops",
        description=(
            "Harden Docker Compose services with non-root users, read-only "
            "filesystems, capability drops, and pinned image digests."
        ),
        tags=("devops", "docker", "containers", "security", "hardening"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="github-actions-pinning",
        name="github-actions-pinning",
        category="devops",
        description=(
            "Pin GitHub Actions workflows to immutable commit SHAs, least "
            "privilege GITHUB_TOKEN permissions, and OIDC deployment."
        ),
        tags=("devops", "ci", "github-actions", "security", "supply-chain"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="secret-scanning",
        name="secret-scanning",
        category="security",
        description=(
            "Detect leaked API keys, private certificates, and hardcoded "
            "credentials in git history and pre-commit hooks."
        ),
        tags=("security", "secrets", "git", "scanning", "compliance"),
        risk="low",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="cloudflare-d1-worker",
        name="cloudflare-d1-worker",
        category="devops",
        description=(
            "Deploy Cloudflare Workers with D1 SQLite bindings, Wrangler "
            "environments, edge caching, and KV session storage."
        ),
        tags=("devops", "cloudflare", "workers", "d1", "serverless"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="kubernetes-helm-audit",
        name="kubernetes-helm-audit",
        category="devops",
        description=(
            "Audit Kubernetes manifests and Helm charts for pod security "
            "standards, resource limits, network policies, and RBAC."
        ),
        tags=("devops", "kubernetes", "helm", "k8s", "security"),
        risk="low",
        warehouse="secondary",
    ),
    # Academic / Writing (3)
    SkillSpec(
        skill_id="apa-citation-audit",
        name="apa-citation-audit",
        category="academic",
        description=(
            "Verify APA 7th edition in-text citations, DOI resolution, "
            "hanging indents, and peer-reviewed reference list accuracy."
        ),
        tags=("academic", "apa7", "citations", "doi", "writing"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="literature-synthesis",
        name="literature-synthesis",
        category="academic",
        description=(
            "Systematic literature review synthesis using PRISMA screening, "
            "thematic evidence matrices, and empirical research gaps."
        ),
        tags=("academic", "literature", "prisma", "research", "synthesis"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="vietnamese-copywriting",
        name="vietnamese-copywriting",
        category="writing",
        description=(
            "Vietnamese marketing and editorial copywriting, brand tone "
            "adaptation, social hooks, and localized campaign messaging."
        ),
        tags=("writing", "vietnamese", "marketing", "copywriting", "content"),
        risk="low",
        warehouse="secondary",
    ),
    # Testing / Eval (3)
    SkillSpec(
        skill_id="python-unittest-fixtures",
        name="python-unittest-fixtures",
        category="testing",
        description=(
            "Design isolated Python unittest TestCase suites, TemporaryDirectory "
            "fixtures, mock patches, and deterministic assertions."
        ),
        tags=("testing", "python", "unittest", "fixtures", "qa"),
        risk="low",
        tier="codex",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="property-fuzzing",
        name="property-fuzzing",
        category="testing",
        description=(
            "Property-based testing and parser fuzzing for edge-case inputs, "
            "invariant verification, and shrinking minimal counterexamples."
        ),
        tags=("testing", "fuzzing", "property-testing", "invariants", "qa"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="browser-e2e-smoke",
        name="browser-e2e-smoke",
        category="testing",
        description=(
            "End-to-end browser smoke testing for login flows, console error "
            "checks, responsive viewports, and form submission."
        ),
        tags=("testing", "e2e", "browser", "smoke", "qa"),
        risk="low",
        warehouse="secondary",
    ),
    # Hard-negative lookalikes & active-tier decoys (8)
    SkillSpec(
        skill_id="generic-helper",
        name="generic-helper",
        category="general",
        description=(
            "General assistant helper for miscellaneous notes, checklists, "
            "and broad project tasks."
        ),
        tags=("general", "helper", "misc", "notes"),
        risk="low",
        tier="active",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="react-legacy-v1",
        name="react-legacy-v1",
        category="frontend",
        description=(
            "Legacy React v15 class component lifecycle patterns, mixins, and "
            "deprecated string refs migration reference."
        ),
        tags=("frontend", "react", "legacy", "deprecated"),
        risk="low",
        tier="codex",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="finance-blog-template",
        name="finance-blog-template",
        category="writing",
        description=(
            "Personal finance blog post template for lifestyle budgeting tips "
            "and newsletter formatting."
        ),
        tags=("finance", "blog", "template", "newsletter"),
        risk="low",
        tier="active",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="deploy-unsafe-script",
        name="deploy-unsafe-script",
        category="devops",
        description=(
            "Quick SSH deployment shell wrapper that skips checksum checks "
            "and restarts services directly."
        ),
        tags=("devops", "deploy", "ssh", "quick"),
        risk="medium",
        tier="active",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="cham-soc-khach-hang",
        name="cham-soc-khach-hang",
        category="operations",
        description=(
            "Quy trinh cham soc khach hang, tiep nhan phan hoi, giai dap "
            "thac mac va nang cao trai nghiem dich vu."
        ),
        tags=("vietnamese", "customer-care", "support", "service"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="cham-tien-do-audit",
        name="cham-tien-do-audit",
        category="operations",
        description=(
            "Kiem tra du an bi cham tien do, phan tich nut that milestone, "
            "tre han ban giao va ke hoach khac phuc."
        ),
        tags=("vietnamese", "schedule", "delay", "audit", "project"),
        risk="low",
        warehouse="secondary",
    ),
    SkillSpec(
        skill_id="dep-code-formatter",
        name="dep-code-formatter",
        category="tooling",
        description=(
            "Format source code cleanly for readability, consistent indentation, "
            "and neat style conventions (lam dep code)."
        ),
        tags=("formatting", "style", "lint", "cleanup"),
        risk="low",
        tier="active",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="cloudflare-dns-only",
        name="cloudflare-dns-only",
        category="devops",
        description=(
            "Manage static Cloudflare DNS A, CNAME, and TXT records without "
            "Workers, D1 databases, or serverless compute."
        ),
        tags=("devops", "cloudflare", "dns", "records"),
        risk="low",
        tier="active",
        warehouse="secondary",
    ),
    # Risky / offensive / malformed items (4)
    SkillSpec(
        skill_id="shell-exec-unreviewed",
        name="shell-exec-unreviewed",
        category="system",
        description=(
            "Execute arbitrary shell commands and unreviewed Python automation "
            "scripts on the host machine."
        ),
        tags=("shell", "exec", "automation", "script"),
        risk="high",
        has_script=True,
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="risky-unannotated",
        name="risky-unannotated",
        category="system",
        description=(
            "Modify local system files and registry settings with no declared "
            "risk metadata."
        ),
        tags=("system", "files", "unannotated"),
        risk=None,
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="offensive-recon",
        name="offensive-recon",
        category="security",
        description=(
            "Offensive port scanning, credential brute-forcing, and exploit "
            "payload generation for unauthorized targets."
        ),
        tags=("security", "offensive", "exploit", "recon"),
        risk="offensive",
        warehouse="primary",
    ),
    SkillSpec(
        skill_id="malformed-metadata-skill",
        name="malformed-metadata-skill",
        category="testing",
        description="Fixture with unclosed YAML frontmatter delimiter.",
        tags=("malformed", "fixture"),
        risk="unknown",
        malformed_frontmatter=True,
        warehouse="secondary",
    ),
)


def _render_skill_md(spec: SkillSpec) -> str:
    if spec.malformed_frontmatter:
        return (
            f"---\nname: {spec.name}\n"
            f"description: {spec.description}\n"
            "# Missing closing delimiter for malformed metadata fixture\n"
        )
    lines = [
        "---",
        f"name: {spec.name}",
        f"description: {spec.description}",
    ]
    if spec.risk is not None:
        lines.append(f"risk: {spec.risk}")
    lines.extend(
        [
            "---",
            "",
            f"# {spec.name}",
            "",
            spec.body or spec.description,
            "",
        ]
    )
    return "\n".join(lines)


def _write_skill_dir(base_dir: pathlib.Path, spec: SkillSpec) -> pathlib.Path:
    skill_dir = base_dir / spec.skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_render_skill_md(spec), encoding="utf-8")
    if spec.has_script:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "run_task.py").write_text(
            "#!/usr/bin/env python3\n"
            '"""Unreviewed fixture script; never executed by eval."""\n\n'
            "def main() -> int:\n"
            "    return 0\n",
            encoding="utf-8",
        )
    return skill_dir


def _write_warehouse(
    wh_dir: pathlib.Path, specs: list[SkillSpec], rng: random.Random
) -> None:
    skills_root = wh_dir / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    ordered = list(specs)
    rng.shuffle(ordered)
    index_records: list[dict[str, Any]] = []
    for spec in sorted(ordered, key=lambda item: item.skill_id):
        _write_skill_dir(skills_root, spec)
        record: dict[str, Any] = {
            "id": spec.skill_id,
            "name": spec.name,
            "category": spec.category,
            "description": spec.description,
            "tags": list(spec.tags),
            "path": f"skills/{spec.skill_id}",
        }
        if spec.risk is not None:
            record["risk"] = spec.risk
        index_records.append(record)
    (wh_dir / "skills_index.json").write_text(
        json.dumps(index_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_eval_environment(
    target_dir: str | pathlib.Path, seed: int = 42
) -> dict[str, Any]:
    """Build deterministic warehouse, active plugin, and Codex fixture trees.

    Returns a mapping with keys:
    ``warehouses``, ``active_dir``, ``codex_dir``, ``catalog_ids``.
    """
    root = pathlib.Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    wh_primary = root / "warehouses" / "primary"
    wh_secondary = root / "warehouses" / "secondary"
    active_dir = root / "active"
    codex_dir = root / "codex"

    primary_specs = [s for s in CANONICAL_CATALOG if s.warehouse == "primary"]
    secondary_specs = [s for s in CANONICAL_CATALOG if s.warehouse == "secondary"]

    _write_warehouse(wh_primary, primary_specs, rng)
    _write_warehouse(wh_secondary, secondary_specs, rng)

    # Active tier: global skills + an enabled plugin with hard-negative decoys.
    active_skills_dir = active_dir / "skills"
    plugin_dir = active_dir / "plugins" / "eval-decoys"
    plugin_skills_dir = plugin_dir / "skills"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "eval-decoys", "version": "1.0.0"}, indent=2) + "\n",
        encoding="utf-8",
    )

    for spec in CANONICAL_CATALOG:
        if spec.tier == "active":
            _write_skill_dir(plugin_skills_dir, spec)
        elif spec.tier == "codex":
            _write_skill_dir(codex_dir, spec)

    # Also ensure active_skills_dir exists cleanly for global-tier tests.
    active_skills_dir.mkdir(parents=True, exist_ok=True)

    return {
        "warehouses": [wh_primary, wh_secondary],
        "active_dir": active_dir,
        "codex_dir": codex_dir,
        "catalog_ids": [spec.skill_id for spec in CANONICAL_CATALOG],
    }


_SCALE_DOMAINS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("finance", ("valuation", "accounting", "cashflow", "audit"), "Financial model"),
    ("frontend", ("react", "css", "accessibility", "layout"), "UI component guide"),
    ("backend", ("sql", "api", "auth", "migrations"), "Backend service guide"),
    (
        "devops",
        ("containers", "ci", "kubernetes", "secrets"),
        "Infrastructure playbook",
    ),
    ("mobile", ("flutter", "expo", "offline", "ios"), "Mobile architecture guide"),
    ("testing", ("unittest", "fuzzing", "e2e", "fixtures"), "Test automation harness"),
    (
        "academic",
        ("apa7", "citations", "prisma", "writing"),
        "Research synthesis guide",
    ),
)


def build_scale_warehouse(
    target_dir: str | pathlib.Path, count: int, seed: int = 42
) -> dict[str, Any]:
    """Generate a deterministic scale warehouse with ``count`` skill records."""
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")

    wh_dir = pathlib.Path(target_dir)
    skills_root = wh_dir / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    records: list[dict[str, Any]] = []
    width = max(5, len(str(count)))
    risk_choices = ("low", "low", "low", "medium", "high", "unknown")

    for idx in range(count):
        domain, domain_tags, prefix = _SCALE_DOMAINS[idx % len(_SCALE_DOMAINS)]
        tag_sample = rng.sample(domain_tags, k=min(3, len(domain_tags)))
        slug = f"{domain}-skill-{idx:0{width}d}"
        desc = (
            f"{prefix} #{idx} covering {', '.join(tag_sample)} workflows "
            f"with deterministic verification."
        )
        risk = risk_choices[rng.randrange(len(risk_choices))]

        skill_folder = skills_root / slug
        skill_folder.mkdir(parents=True, exist_ok=True)
        (skill_folder / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: {desc}\nrisk: {risk}\n---\n# {slug}\n",
            encoding="utf-8",
        )
        records.append(
            {
                "id": slug,
                "name": slug,
                "category": domain,
                "risk": risk,
                "description": desc,
                "tags": [domain, *tag_sample],
                "path": f"skills/{slug}",
            }
        )

    index_path = wh_dir / "skills_index.json"
    index_path.write_text(
        json.dumps(records, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "warehouse_dir": wh_dir,
        "index_path": index_path,
        "count": count,
        "seed": seed,
    }


def build_permission_fixtures(target_dir: str | pathlib.Path) -> dict[str, Any]:
    """Create OS-safe symlink, permission, and special filesystem fixtures.

    Records created entries and explicit OS-specific skip reasons without
    raising on unsupported primitives (such as POSIX FIFOs or unprivileged
    symlinks on Windows).
    """
    root = pathlib.Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    valid_target = root / "valid-skill"
    valid_target.mkdir(parents=True, exist_ok=True)
    (valid_target / "SKILL.md").write_text(
        "---\nname: valid-skill\ndescription: Valid baseline fixture\n---\n",
        encoding="utf-8",
    )
    created.append({"name": "valid-skill", "kind": "directory"})

    # 1. Special filename / unicode / space fixture
    unicode_dir = root / "skill with spaces & tieng viet"
    try:
        unicode_dir.mkdir(parents=True, exist_ok=True)
        (unicode_dir / "SKILL.md").write_text(
            "---\nname: unicode-space-skill\ndescription: Special path fixture\n---\n",
            encoding="utf-8",
        )
        created.append({"name": unicode_dir.name, "kind": "special_path"})
    except OSError as exc:
        skipped.append(
            {"name": unicode_dir.name, "kind": "special_path", "reason": str(exc)}
        )

    # 2. Symlink to directory and broken symlink
    sym_dir = root / "symlinked-skill"
    try:
        if sym_dir.exists() or sym_dir.is_symlink():
            sym_dir.unlink()
        os.symlink(valid_target, sym_dir, target_is_directory=True)
        created.append({"name": sym_dir.name, "kind": "symlink_dir"})
    except (OSError, NotImplementedError) as exc:
        skipped.append(
            {"name": sym_dir.name, "kind": "symlink_dir", "reason": str(exc)}
        )

    broken_sym = root / "broken-symlink"
    try:
        if broken_sym.exists() or broken_sym.is_symlink():
            broken_sym.unlink()
        os.symlink(root / "nonexistent-target", broken_sym, target_is_directory=False)
        created.append({"name": broken_sym.name, "kind": "broken_symlink"})
    except (OSError, NotImplementedError) as exc:
        skipped.append(
            {"name": broken_sym.name, "kind": "broken_symlink", "reason": str(exc)}
        )

    # 3. Unreadable SKILL.md fixture (POSIX chmod 0o000; Windows cannot deny owner read via chmod)
    unreadable_dir = root / "unreadable-skill"
    unreadable_dir.mkdir(parents=True, exist_ok=True)
    unreadable_md = unreadable_dir / "SKILL.md"
    unreadable_md.write_text(
        "---\nname: unreadable-skill\ndescription: Permission denied fixture\n---\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        skipped.append(
            {
                "name": "unreadable-skill/SKILL.md",
                "kind": "chmod_000",
                "reason": "Windows chmod only toggles read-only attribute; owner read remains allowed",
            }
        )
    else:
        try:
            os.chmod(unreadable_md, 0)
            created.append({"name": "unreadable-skill/SKILL.md", "kind": "chmod_000"})
        except OSError as exc:
            skipped.append(
                {
                    "name": "unreadable-skill/SKILL.md",
                    "kind": "chmod_000",
                    "reason": str(exc),
                }
            )

    # 4. POSIX FIFO special file
    fifo_dir = root / "fifo-skill"
    fifo_dir.mkdir(parents=True, exist_ok=True)
    fifo_path = fifo_dir / "SKILL.md"
    if hasattr(os, "mkfifo"):
        try:
            if fifo_path.exists():
                fifo_path.unlink()
            os.mkfifo(fifo_path, stat.S_IRUSR | stat.S_IWUSR)
            created.append({"name": "fifo-skill/SKILL.md", "kind": "fifo"})
        except (OSError, NotImplementedError) as exc:
            skipped.append(
                {"name": "fifo-skill/SKILL.md", "kind": "fifo", "reason": str(exc)}
            )
    else:
        skipped.append(
            {
                "name": "fifo-skill/SKILL.md",
                "kind": "fifo",
                "reason": f"os.mkfifo unavailable on platform {sys.platform}",
            }
        )

    return {
        "target_dir": root,
        "created": created,
        "skipped": skipped,
        "platform": sys.platform,
    }
