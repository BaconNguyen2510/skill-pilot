"""Performance benchmark and X-20 digest experiment for skill_scout (PERF-01..04, X-10, X-20)."""

from __future__ import annotations

import argparse
import cProfile
import importlib.util
import io
import json
import pathlib
import platform
import pstats
import statistics
import sys
import tempfile
import time
import tracemalloc
from contextlib import redirect_stdout
from typing import Any
from unittest import mock

EVAL_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
SCOUT_PATH = REPO_ROOT / "skills" / "skill-pilot" / "scripts" / "skill_scout.py"

if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from corpus_builder import build_scale_warehouse

DEFAULT_QUERIES: tuple[str, ...] = (
    "react accessibility aria wcag",
    "dcf valuation wacc sensitivity",
    "postgres query index optimization",
    "flutter riverpod state",
    "docker compose security",
)

SCALE_SIZES: tuple[int, ...] = (10, 100, 1000, 10000)


def load_scout_module(module_name: str = "skill_scout_perf") -> Any:
    """Load canonical skill_scout.py as an isolated module without mutating it."""
    spec = importlib.util.spec_from_file_location(module_name, SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load skill_scout.py from {SCOUT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def percentile(values: list[float], pct: float) -> float:
    """Compute nearest-rank percentile on a non-empty list of floats."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct <= 0.0:
        return ordered[0]
    if pct >= 100.0:
        return ordered[-1]
    idx = min(len(ordered) - 1, int((pct / 100.0) * (len(ordered) - 1)))
    return ordered[idx]


def _make_search_args(query: str, limit: int = 5) -> argparse.Namespace:
    return argparse.Namespace(
        query=[query],
        limit=limit,
        workspace=None,
        harness="all",
        warehouse=None,
        include_active=True,
        allow_risky=False,
        format="json",
        explain=False,
    )


def _run_search(
    scout: Any,
    warehouses: list[pathlib.Path],
    active_dir: pathlib.Path,
    codex_dir: pathlib.Path,
    query: str,
    limit: int = 5,
) -> tuple[int, dict[str, Any] | None]:
    """Execute cmd_search against isolated synthetic directories."""
    args = _make_search_args(query, limit=limit)
    buf = io.StringIO()
    with (
        mock.patch.object(scout, "PLUGINS_DIR", active_dir / "plugins"),
        mock.patch.object(scout, "GLOBAL_SKILLS_DIR", active_dir / "skills"),
        mock.patch.object(scout, "BUILTIN_SKILLS_DIR", active_dir / "no-builtin"),
        mock.patch.object(scout, "CODEX_SKILLS_DIR", codex_dir),
        mock.patch.object(
            scout, "CODEX_INACTIVE_SKILLS_DIR", codex_dir / "no-inactive"
        ),
        mock.patch.object(scout, "_codex_plugin_sources", return_value=[]),
        mock.patch.object(
            scout, "_parse_plugin_states", return_value=(set(), set(), None)
        ),
        mock.patch.object(scout, "resolve_warehouses", return_value=warehouses),
        redirect_stdout(buf),
    ):
        code = scout.cmd_search(args)
    raw = buf.getvalue().strip()
    if code != 0 or not raw:
        return code, None
    return code, json.loads(raw)


def benchmark_cold_startup(trials: int = 5) -> dict[str, Any]:
    """PERF-01: Measure isolated module import and initialization latency."""
    import_latencies: list[float] = []
    tracemalloc.start()
    for idx in range(trials):
        mod_name = f"skill_scout_cold_import_{idx}"
        sys.modules.pop(mod_name, None)
        t0 = time.perf_counter()
        load_scout_module(mod_name)
        import_latencies.append((time.perf_counter() - t0) * 1000.0)
        sys.modules.pop(mod_name, None)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "trials": trials,
        "import_p50_ms": round(statistics.median(import_latencies), 3),
        "import_p95_ms": round(percentile(import_latencies, 95.0), 3),
        "import_mean_ms": round(statistics.mean(import_latencies), 3),
        "peak_tracemalloc_kb": round(peak_bytes / 1024.0, 2),
    }


def benchmark_scale_matrix(
    sizes: tuple[int, ...] = SCALE_SIZES,
    cold_trials: int = 5,
    warm_rounds: int = 3,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """PERF-01, PERF-02, X-10: Cold/warm p50/p95 latency and memory across scale."""
    results: list[dict[str, Any]] = []
    for count in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            wh = tmp_path / f"wh_{count}"
            build_scale_warehouse(wh, count, seed=seed)
            active_dir = tmp_path / "empty-active"
            codex_dir = tmp_path / "empty-codex"
            warehouses = [wh]

            cold_total_latencies: list[float] = []
            cold_search_latencies: list[float] = []
            tracemalloc.start()
            for idx in range(cold_trials):
                q = DEFAULT_QUERIES[idx % len(DEFAULT_QUERIES)]
                mod_name = f"skill_scout_scale_{count}_{idx}"
                sys.modules.pop(mod_name, None)
                t_cold0 = time.perf_counter()
                scout_cold = load_scout_module(mod_name)
                t_search0 = time.perf_counter()
                _run_search(scout_cold, warehouses, active_dir, codex_dir, q, limit=5)
                t_end = time.perf_counter()
                cold_total_latencies.append((t_end - t_cold0) * 1000.0)
                cold_search_latencies.append((t_end - t_search0) * 1000.0)
                sys.modules.pop(mod_name, None)

            scout_warm = load_scout_module(f"skill_scout_warm_{count}")
            warm_latencies: list[float] = []
            for _ in range(warm_rounds):
                for q in DEFAULT_QUERIES:
                    t0 = time.perf_counter()
                    _run_search(
                        scout_warm, warehouses, active_dir, codex_dir, q, limit=5
                    )
                    warm_latencies.append((time.perf_counter() - t0) * 1000.0)
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            sys.modules.pop(f"skill_scout_warm_{count}", None)

            results.append(
                {
                    "records": count,
                    "cold_trials": cold_trials,
                    "warm_trials": len(warm_latencies),
                    "cold_p50_ms": round(statistics.median(cold_total_latencies), 3),
                    "cold_p95_ms": round(percentile(cold_total_latencies, 95.0), 3),
                    "cold_search_only_p50_ms": round(
                        statistics.median(cold_search_latencies), 3
                    ),
                    "cold_search_only_p95_ms": round(
                        percentile(cold_search_latencies, 95.0), 3
                    ),
                    "warm_p50_ms": round(statistics.median(warm_latencies), 3),
                    "warm_p95_ms": round(percentile(warm_latencies, 95.0), 3),
                    "warm_mean_ms": round(statistics.mean(warm_latencies), 3),
                    "peak_tracemalloc_kb": round(peak_bytes / 1024.0, 2),
                }
            )
    return results


def _sanitize_profile_filename(filename: str) -> str:
    """Convert absolute file paths into repository-relative or stdlib labels."""
    norm = filename.replace("\\", "/")
    repo_norm = str(REPO_ROOT).replace("\\", "/").rstrip("/")
    if norm.startswith(repo_norm + "/"):
        return norm[len(repo_norm) + 1 :]
    if "lib/" in norm.lower():
        idx = norm.lower().rfind("lib/")
        return "<stdlib>/" + norm[idx + 4 :]
    return pathlib.Path(filename).name


def profile_dominant_search(
    count: int = 10000, top_n: int = 10, seed: int = 42
) -> dict[str, Any]:
    """PERF-02: Capture cProfile hotspots for cmd_search on 10,000 records."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        wh = tmp_path / f"wh_prof_{count}"
        build_scale_warehouse(wh, count, seed=seed)
        active_dir = tmp_path / "empty-active"
        codex_dir = tmp_path / "empty-codex"
        scout = load_scout_module("skill_scout_profile")

        profiler = cProfile.Profile()
        profiler.enable()
        _run_search(scout, [wh], active_dir, codex_dir, DEFAULT_QUERIES[0], limit=5)
        profiler.disable()

        stats = pstats.Stats(profiler)
        entries: list[dict[str, Any]] = []
        for func_key, stat_tuple in stats.stats.items():
            filename, lineno, func_name = func_key
            cc, nc, tt, ct, _ = stat_tuple
            entries.append(
                {
                    "file": _sanitize_profile_filename(filename),
                    "line": lineno,
                    "function": func_name,
                    "prim_calls": cc,
                    "total_calls": nc,
                    "tottime_ms": round(tt * 1000.0, 3),
                    "cumtime_ms": round(ct * 1000.0, 3),
                }
            )
        entries.sort(key=lambda item: item["cumtime_ms"], reverse=True)
        sys.modules.pop("skill_scout_profile", None)
        return {
            "records": count,
            "query": DEFAULT_QUERIES[0],
            "total_calls": stats.total_calls,
            "total_tottime_ms": round(stats.total_tt * 1000.0, 3),
            "top_hotspots": entries[:top_n],
        }


def _populate_active_skill(
    skill_dir: pathlib.Path, name: str, description: str, extra_note: str
) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )
    refs = skill_dir / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "notes.md").write_text(extra_note, encoding="utf-8")


def _build_x20_inventory(
    root: pathlib.Path,
    scenario: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Build synthetic active skill inventories for X-20 eager vs lazy digest tests."""
    global_dir = root / "skills"
    plugins_dir = root / "plugins"
    global_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)

    if scenario == "100_non_colliding":
        for idx in range(100):
            slug = f"unique-skill-{idx:03d}"
            _populate_active_skill(
                global_dir / slug,
                slug,
                f"Deterministic non-colliding skill {idx} for digest benchmark.",
                f"Reference payload for {slug}.\n",
            )
    elif scenario == "500_non_colliding":
        for idx in range(500):
            slug = f"unique-skill-{idx:03d}"
            _populate_active_skill(
                global_dir / slug,
                slug,
                f"Deterministic non-colliding skill {idx} for digest benchmark.",
                f"Reference payload for {slug}.\n",
            )
    elif scenario == "10_colliding":
        plugin_pack = plugins_dir / "collision-pack"
        plugin_skills = plugin_pack / "skills"
        plugin_skills.mkdir(parents=True, exist_ok=True)
        (plugin_pack / "plugin.json").write_text(
            json.dumps({"name": "collision-pack", "disabled": False}),
            encoding="utf-8",
        )
        for idx in range(5):
            slug = f"colliding-skill-{idx:02d}"
            desc = f"Shared colliding skill {idx} across global and plugin tiers."
            note_global = f"Shared reference payload {idx}.\n"
            note_plugin = (
                note_global
                if idx < 3
                else f"Divergent plugin reference payload {idx}.\n"
            )
            _populate_active_skill(global_dir / slug, slug, desc, note_global)
            _populate_active_skill(plugin_skills / slug, slug, desc, note_plugin)
    else:
        raise ValueError(f"Unknown X-20 scenario: {scenario}")

    return global_dir, plugins_dir


def _run_collect_mode(
    scout: Any,
    global_dir: pathlib.Path,
    plugins_dir: pathlib.Path,
    empty_dir: pathlib.Path,
    eager: bool,
    iterations: int,
) -> dict[str, Any]:
    """Run collect_active_skills in lazy (canonical) or eager digest mode."""
    orig_digest = scout._skill_content_digest
    latencies: list[float] = []
    last_digest_calls = 0
    last_skills: list[dict[str, Any]] = []

    tracemalloc.start()
    for _ in range(iterations):
        call_count = 0

        def counting_digest(skill_md_str: str) -> str | None:
            nonlocal call_count
            call_count += 1
            return orig_digest(skill_md_str)

        with (
            mock.patch.object(scout, "GLOBAL_SKILLS_DIR", global_dir),
            mock.patch.object(scout, "PLUGINS_DIR", plugins_dir),
            mock.patch.object(scout, "BUILTIN_SKILLS_DIR", empty_dir),
            mock.patch.object(
                scout, "_parse_plugin_states", return_value=(set(), set(), None)
            ),
            mock.patch.object(
                scout, "_skill_content_digest", side_effect=counting_digest
            ),
        ):
            t0 = time.perf_counter()
            collected = scout.collect_active_skills(
                workspace=None, harness="antigravity"
            )
            if eager:
                eager_cache: dict[str, str | None] = {}
                for item in collected:
                    raw_path = str(item.get("skill_md_path") or "")
                    if raw_path and raw_path not in eager_cache:
                        eager_cache[raw_path] = scout._skill_content_digest(raw_path)
            latencies.append((time.perf_counter() - t0) * 1000.0)
            last_digest_calls = call_count
            last_skills = collected

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    collisions = sum(1 for item in last_skills if item.get("name_collision"))
    duplicates = sum(1 for item in last_skills if item.get("duplicate_candidate"))

    return {
        "mode": "eager" if eager else "lazy",
        "iterations": iterations,
        "skills_collected": len(last_skills),
        "collisions_flagged": collisions,
        "duplicates_flagged": duplicates,
        "digest_calls": last_digest_calls,
        "p50_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(percentile(latencies, 95.0), 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "peak_tracemalloc_kb": round(peak_bytes / 1024.0, 2),
    }


def run_x20_digest_experiment(iterations: int = 5) -> list[dict[str, Any]]:
    """X-20, PERF-03: Compare eager vs lazy digest computation on active inventories."""
    scout = load_scout_module("skill_scout_x20")
    scenarios = ("100_non_colliding", "500_non_colliding", "10_colliding")
    results: list[dict[str, Any]] = []

    for scenario in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            global_dir, plugins_dir = _build_x20_inventory(root, scenario)
            empty_dir = root / "empty"
            empty_dir.mkdir(parents=True, exist_ok=True)

            lazy_res = _run_collect_mode(
                scout,
                global_dir,
                plugins_dir,
                empty_dir,
                eager=False,
                iterations=iterations,
            )
            eager_res = _run_collect_mode(
                scout,
                global_dir,
                plugins_dir,
                empty_dir,
                eager=True,
                iterations=iterations,
            )

            eager_p50 = eager_res["p50_ms"]
            lazy_p50 = lazy_res["p50_ms"]
            speedup = round(eager_p50 / lazy_p50, 2) if lazy_p50 > 0 else 0.0
            reduction_pct = (
                round(((eager_p50 - lazy_p50) / eager_p50) * 100.0, 2)
                if eager_p50 > 0
                else 0.0
            )
            results.append(
                {
                    "scenario": scenario,
                    "lazy": lazy_res,
                    "eager": eager_res,
                    "digest_calls_saved": eager_res["digest_calls"]
                    - lazy_res["digest_calls"],
                    "p50_speedup_x": speedup,
                    "p50_latency_reduction_pct": reduction_pct,
                }
            )
    sys.modules.pop("skill_scout_x20", None)
    return results


def verify_cache_correctness_policy() -> dict[str, Any]:
    """PERF-04: Verify no stale disabled-state or metadata persists across calls."""
    scout = load_scout_module("skill_scout_perf04")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        plugins_dir = root / "plugins"
        pack_dir = plugins_dir / "demo-plugin"
        skill_dir = pack_dir / "skills" / "demo-skill"
        _populate_active_skill(
            skill_dir,
            "demo-skill",
            "Initial alpha description for cache check.",
            "Initial note.\n",
        )
        manifest_path = pack_dir / "plugin.json"
        manifest_path.write_text(
            json.dumps({"name": "demo-plugin", "disabled": False}),
            encoding="utf-8",
        )
        empty_dir = root / "empty"
        empty_dir.mkdir(parents=True, exist_ok=True)

        with (
            mock.patch.object(scout, "PLUGINS_DIR", plugins_dir),
            mock.patch.object(scout, "GLOBAL_SKILLS_DIR", empty_dir),
            mock.patch.object(scout, "BUILTIN_SKILLS_DIR", empty_dir),
            mock.patch.object(
                scout, "_parse_plugin_states", return_value=(set(), set(), None)
            ),
        ):
            first = scout.collect_active_skills(workspace=None, harness="antigravity")
            manifest_path.write_text(
                json.dumps({"name": "demo-plugin", "disabled": True}),
                encoding="utf-8",
            )
            second = scout.collect_active_skills(workspace=None, harness="antigravity")

    sys.modules.pop("skill_scout_perf04", None)
    passed = len(first) == 1 and len(second) == 0
    return {
        "policy": "per_invocation_digest_cache_and_live_manifest_read",
        "first_call_active_count": len(first),
        "second_call_after_disable_count": len(second),
        "stale_state_observed": not passed,
        "passed": passed,
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Render human-readable performance report without em-dashes or user paths."""
    startup = payload["cold_startup"]
    scale_rows = payload["scale_matrix"]
    x20_rows = payload["x20_digest_experiment"]
    prof = payload["profile_10k"]
    cache_check = payload["cache_policy_check"]

    lines: list[str] = [
        "# Skill Pilot Performance Benchmark Report (PERF-01..04, X-10, X-20)",
        "",
        f"- Python: `{payload['python_version']}`",
        f"- OS: `{payload['os']}`",
        f"- Seed: `{payload['seed']}`",
        "- Target: `skills/skill-pilot/scripts/skill_scout.py` (read-only canonical CLI)",
        "- Benchmark script: `eval/perf_bench.py`",
        "",
        "## 1. PERF-01: Cold Startup Profile",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Trials | {startup['trials']} |",
        f"| Module Import p50 (ms) | {startup['import_p50_ms']:.3f} |",
        f"| Module Import p95 (ms) | {startup['import_p95_ms']:.3f} |",
        f"| Module Import Mean (ms) | {startup['import_mean_ms']:.3f} |",
        f"| Peak Traced Memory (KB) | {startup['peak_tracemalloc_kb']:.2f} |",
        "",
        "## 2. PERF-02 & X-10: Scale Latency and Memory (10 to 10,000 Records)",
        "",
        "| Records | Cold p50 (ms) | Cold p95 (ms) | Cold Search-Only p50 (ms) | Warm p50 (ms) | Warm p95 (ms) | Peak Traced Memory (KB) |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in scale_rows:
        lines.append(
            f"| {row['records']} | {row['cold_p50_ms']:.3f} | {row['cold_p95_ms']:.3f} | "
            f"{row['cold_search_only_p50_ms']:.3f} | {row['warm_p50_ms']:.3f} | "
            f"{row['warm_p95_ms']:.3f} | {row['peak_tracemalloc_kb']:.2f} |"
        )

    lines.extend(
        [
            "",
            f"### Dominant Search cProfile Hotspots ({prof['records']} records, query `{prof['query']}`)",
            "",
            f"Total profiled calls: `{prof['total_calls']}`; total primitive time: `{prof['total_tottime_ms']:.3f} ms`.",
            "",
            "| File | Function | Calls | Total Time (ms) | Cumulative Time (ms) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for spot in prof["top_hotspots"]:
        lines.append(
            f"| `{spot['file']}:{spot['line']}` | `{spot['function']}` | "
            f"{spot['total_calls']} | {spot['tottime_ms']:.3f} | {spot['cumtime_ms']:.3f} |"
        )

    lines.extend(
        [
            "",
            "## 3. PERF-03 & X-20: Eager vs Lazy Content Digest Computation",
            "",
            (
                "In `collect_active_skills`, `_skill_content_digest` is only invoked when two distinct paths share the same skill name (`siblings` collision). "
                "This isolated experiment compares canonical lazy hashing against eager hashing across non-colliding and colliding inventories."
            ),
            "",
            "| Scenario | Skills | Lazy Digest Calls | Eager Digest Calls | Calls Saved | Lazy p50 (ms) | Eager p50 (ms) | Lazy p95 (ms) | Eager p95 (ms) | p50 Speedup |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in x20_rows:
        lz = row["lazy"]
        eg = row["eager"]
        lines.append(
            f"| `{row['scenario']}` | {lz['skills_collected']} | {lz['digest_calls']} | "
            f"{eg['digest_calls']} | {row['digest_calls_saved']} | {lz['p50_ms']:.3f} | "
            f"{eg['p50_ms']:.3f} | {lz['p95_ms']:.3f} | {eg['p95_ms']:.3f} | {row['p50_speedup_x']:.2f}x |"
        )

    lines.extend(
        [
            "",
            "## 4. PERF-04: Cache Correctness Policy",
            "",
            f"- Policy: `{cache_check['policy']}`",
            f"- Active count before disabling plugin: `{cache_check['first_call_active_count']}`",
            f"- Active count immediately after disabling plugin: `{cache_check['second_call_after_disable_count']}`",
            f"- Stale state observed: `{cache_check['stale_state_observed']}`",
            f"- Verification status: `{'PASS' if cache_check['passed'] else 'FAIL'}`",
            "",
            "`collect_active_skills` and `cmd_search` scope `digest_cache` strictly to a single invocation and re-read `plugin.json` disabled states and `SKILL.md` frontmatter on every call, preventing stale disabled-state or risk decisions after source changes.",
            "",
        ]
    )
    return "\n".join(lines)


def run_all_benchmarks(
    cold_trials: int = 5,
    warm_rounds: int = 3,
    x20_iterations: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Execute the full PERF-01..04, X-10, and X-20 benchmark suite."""
    cold_startup = benchmark_cold_startup(trials=cold_trials)
    scale_matrix = benchmark_scale_matrix(
        sizes=SCALE_SIZES,
        cold_trials=cold_trials,
        warm_rounds=warm_rounds,
        seed=seed,
    )
    profile_10k = profile_dominant_search(count=10000, top_n=10, seed=seed)
    x20_results = run_x20_digest_experiment(iterations=x20_iterations)
    cache_check = verify_cache_correctness_policy()

    return {
        "schema_version": "1.0",
        "benchmark_suite": "PERF-01..04, X-10, X-20",
        "python_version": platform.python_version(),
        "os": platform.system(),
        "seed": seed,
        "cold_startup": cold_startup,
        "scale_matrix": scale_matrix,
        "profile_10k": profile_10k,
        "x20_digest_experiment": x20_results,
        "cache_policy_check": cache_check,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run skill-pilot PERF-01..04, X-10, and X-20 benchmarks."
    )
    parser.add_argument(
        "--json-out",
        default="docs/v3/PERF_BENCHMARK.json",
        help="Output path for JSON benchmark artifact (relative to repo root).",
    )
    parser.add_argument(
        "--report-out",
        default="docs/v3/PERF_REPORT.md",
        help="Output path for Markdown benchmark report (relative to repo root).",
    )
    parser.add_argument("--cold-trials", type=int, default=5)
    parser.add_argument("--warm-rounds", type=int, default=3)
    parser.add_argument("--x20-iterations", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    payload = run_all_benchmarks(
        cold_trials=args.cold_trials,
        warm_rounds=args.warm_rounds,
        x20_iterations=args.x20_iterations,
        seed=args.seed,
    )

    json_path = REPO_ROOT / args.json_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report_path = REPO_ROOT / args.report_out
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown_report(payload), encoding="utf-8")

    print(
        json.dumps(
            {
                "json_out": args.json_out,
                "report_out": args.report_out,
                "scale_records": [r["records"] for r in payload["scale_matrix"]],
                "x20_scenarios": [
                    r["scenario"] for r in payload["x20_digest_experiment"]
                ],
                "cache_policy_passed": payload["cache_policy_check"]["passed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
