"""Deterministic offline evaluator, scale latency benchmark, and baseline gate (EVAL-05..EVAL-12)."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import pathlib
import platform
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

from corpus_builder import build_eval_environment, build_scale_warehouse
from metrics import (
    abstention_metrics,
    forbidden_hit_rate,
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
    paired_bootstrap_ci,
    precision_at_k,
    recall_at_k,
)
from validate_eval import load_jsonl, validate_records


def load_scout_module() -> Any:
    """Load canonical skill_scout.py as an isolated module."""
    spec = importlib.util.spec_from_file_location("skill_scout_eval", SCOUT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load skill_scout.py from {SCOUT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_scout_search(
    scout: Any,
    env: dict[str, Any],
    query: str,
    limit: int = 5,
) -> tuple[int, dict[str, Any] | None]:
    """Execute cmd_search against the synthetic fixture environment."""
    active_dir = pathlib.Path(env["active_dir"])
    codex_dir = pathlib.Path(env["codex_dir"])
    warehouses = [pathlib.Path(w) for w in env["warehouses"]]

    args = argparse.Namespace(
        query=[query],
        limit=limit,
        workspace=None,
        harness="all",
        warehouse=None,
        include_active=True,
        allow_risky=False,
        format="json",
    )
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
        try:
            code = scout.cmd_search(args)
        except ValueError:
            # Negative-only query or empty intent triggers controlled abstention/rejection.
            return 1, None
    raw = buf.getvalue().strip()
    if code != 0 or not raw:
        return code, None
    return code, json.loads(raw)


def _extract_ranked_ids(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    ranked: list[str] = []
    for item in payload.get("ranked_matches", []):
        sid = str(item.get("id") or item.get("name") or "").strip()
        if sid:
            ranked.append(sid)
    return ranked


def _aggregate_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    non_abstain = [r for r in rows if not r["expected_abstain"]]
    abstain_summary = abstention_metrics(rows)

    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        if not subset:
            return 0.0
        return round(sum(float(r[key]) for r in subset) / len(subset), 4)

    return {
        "count_total": len(rows),
        "count_non_abstain": len(non_abstain),
        "count_abstain": len(rows) - len(non_abstain),
        "hit_rate@1": mean("hit_rate@1", non_abstain),
        "hit_rate@3": mean("hit_rate@3", non_abstain),
        "hit_rate@5": mean("hit_rate@5", non_abstain),
        "recall@1": mean("recall@1", non_abstain),
        "recall@3": mean("recall@3", non_abstain),
        "recall@5": mean("recall@5", non_abstain),
        "mrr@5": mean("mrr@5", non_abstain),
        "ndcg@5": mean("ndcg@5", non_abstain),
        "precision@5": mean("precision@5", non_abstain),
        "forbidden_hit_rate@5": mean("forbidden_hit_rate@5", rows),
        "abstention": {k: round(v, 4) for k, v in abstain_summary.items()},
    }


def evaluate_queries(
    queries_path: pathlib.Path,
    split: str = "all",
    limit: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Run deterministic offline evaluation across gold queries."""
    records, parse_errors = load_jsonl(queries_path)
    if parse_errors:
        raise ValueError(f"Invalid eval JSONL: {parse_errors[0]}")
    errors = validate_records(records)
    if errors:
        raise ValueError(f"Invalid eval dataset: {errors[0]}")

    selected = [r for r in records if split == "all" or r["split"] == split]
    scout = load_scout_module()

    with tempfile.TemporaryDirectory() as tmp:
        env = build_eval_environment(pathlib.Path(tmp) / "corpus", seed=seed)
        per_query: list[dict[str, Any]] = []
        for rec in selected:
            t0 = time.perf_counter()
            code, payload = _run_scout_search(scout, env, rec["query"], limit=limit)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            ranked_ids = _extract_ranked_ids(payload)

            relevant = set(rec["required_skills"]) | set(rec["acceptable_alternates"])
            per_query.append(
                {
                    "id": rec["id"],
                    "split": rec["split"],
                    "language": rec["language"],
                    "domain": rec["domain"],
                    "ambiguity_tags": rec["ambiguity_tags"],
                    "expected_abstain": rec["expected_abstain"],
                    "expected_skill_count": rec["expected_skill_count"],
                    "exit_code": code,
                    "ranked_ids": ranked_ids,
                    "predicted_ids": ranked_ids,
                    "latency_ms": round(elapsed_ms, 3),
                    "hit_rate@1": hit_rate_at_k(ranked_ids, relevant, 1),
                    "hit_rate@3": hit_rate_at_k(ranked_ids, relevant, 3),
                    "hit_rate@5": hit_rate_at_k(ranked_ids, relevant, 5),
                    "recall@1": recall_at_k(ranked_ids, relevant, 1),
                    "recall@3": recall_at_k(ranked_ids, relevant, 3),
                    "recall@5": recall_at_k(ranked_ids, relevant, 5),
                    "mrr@5": mrr_at_k(ranked_ids, relevant, 5),
                    "ndcg@5": ndcg_at_k(
                        ranked_ids,
                        rec["required_skills"],
                        rec["acceptable_alternates"],
                        5,
                    ),
                    "precision@5": precision_at_k(ranked_ids, relevant, 5),
                    "forbidden_hit_rate@5": forbidden_hit_rate(
                        ranked_ids, rec["forbidden_skills"], 5
                    ),
                }
            )

    by_language: dict[str, Any] = {}
    for lang in sorted({r["language"] for r in per_query}):
        by_language[lang] = _aggregate_records(
            [r for r in per_query if r["language"] == lang]
        )

    by_split: dict[str, Any] = {}
    for sp in sorted({r["split"] for r in per_query}):
        by_split[sp] = _aggregate_records([r for r in per_query if r["split"] == sp])

    by_tag: dict[str, Any] = {}
    all_tags = sorted({tag for r in per_query for tag in r["ambiguity_tags"]})
    for tag in all_tags:
        by_tag[tag] = _aggregate_records(
            [r for r in per_query if tag in r["ambiguity_tags"]]
        )

    latencies = sorted(r["latency_ms"] for r in per_query)
    p50_ms = statistics.median(latencies) if latencies else 0.0
    p95_idx = (
        min(len(latencies) - 1, int(0.95 * (len(latencies) - 1))) if latencies else 0
    )
    p95_ms = latencies[p95_idx] if latencies else 0.0

    return {
        "schema_version": "1.0",
        "split": split,
        "seed": seed,
        "python_version": platform.python_version(),
        "os": platform.system(),
        "overall": _aggregate_records(per_query),
        "by_split": by_split,
        "by_language": by_language,
        "by_ambiguity_tag": by_tag,
        "latency_ms": {"p50": round(p50_ms, 3), "p95": round(p95_ms, 3)},
        "per_query": per_query,
    }


def benchmark_scale(
    sizes: tuple[int, ...] = (10, 100, 1000),
    queries: tuple[str, ...] = (
        "react accessibility aria wcag",
        "dcf valuation wacc sensitivity",
        "postgres query index optimization",
        "flutter riverpod state",
        "docker compose security",
    ),
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Measure cold/warm p50/p95 latency and peak traced memory across warehouse sizes."""
    scout = load_scout_module()
    results: list[dict[str, Any]] = []
    for count in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            wh = pathlib.Path(tmp) / f"wh_{count}"
            build_scale_warehouse(wh, count, seed=seed)
            env = {
                "warehouses": [wh],
                "active_dir": pathlib.Path(tmp) / "empty-active",
                "codex_dir": pathlib.Path(tmp) / "empty-codex",
            }
            tracemalloc.start()
            t_cold0 = time.perf_counter()
            _run_scout_search(scout, env, queries[0], limit=5)
            cold_ms = (time.perf_counter() - t_cold0) * 1000.0
            warm_latencies: list[float] = []
            for q in queries:
                t0 = time.perf_counter()
                _run_scout_search(scout, env, q, limit=5)
                warm_latencies.append((time.perf_counter() - t0) * 1000.0)
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            warm_sorted = sorted(warm_latencies)
            p50 = statistics.median(warm_sorted)
            p95 = warm_sorted[
                min(len(warm_sorted) - 1, int(0.95 * (len(warm_sorted) - 1)))
            ]
            results.append(
                {
                    "records": count,
                    "cold_ms": round(cold_ms, 3),
                    "warm_p50_ms": round(p50, 3),
                    "warm_p95_ms": round(p95, 3),
                    "peak_tracemalloc_kb": round(peak_bytes / 1024.0, 2),
                }
            )
    return results


def compare_against_baseline(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    max_mrr_drop: float = 0.02,
    max_forbidden_increase: float = 0.02,
) -> tuple[bool, dict[str, Any]]:
    """Compare candidate scorecard against a frozen baseline with paired bootstrap CI."""
    base_map = {
        r["id"]: r for r in baseline.get("per_query", []) if not r["expected_abstain"]
    }
    cand_map = {
        r["id"]: r for r in candidate.get("per_query", []) if not r["expected_abstain"]
    }
    common_ids = sorted(set(base_map) & set(cand_map))
    if not common_ids:
        raise ValueError(
            "No overlapping non-abstain query IDs between baseline and candidate."
        )

    base_mrr = [float(base_map[qid]["mrr@5"]) for qid in common_ids]
    cand_mrr = [float(cand_map[qid]["mrr@5"]) for qid in common_ids]
    mrr_diff, mrr_lo, mrr_hi = paired_bootstrap_ci(base_mrr, cand_mrr, seed=42)

    base_rec5 = [float(base_map[qid]["recall@5"]) for qid in common_ids]
    cand_rec5 = [float(cand_map[qid]["recall@5"]) for qid in common_ids]
    rec_diff, rec_lo, rec_hi = paired_bootstrap_ci(base_rec5, cand_rec5, seed=42)

    base_forb = float(baseline["overall"]["forbidden_hit_rate@5"])
    cand_forb = float(candidate["overall"]["forbidden_hit_rate@5"])
    forb_delta = cand_forb - base_forb

    passed = (mrr_diff >= -max_mrr_drop) and (forb_delta <= max_forbidden_increase)
    diff_report = {
        "passed": passed,
        "paired_queries": len(common_ids),
        "mrr@5_diff": round(mrr_diff, 4),
        "mrr@5_ci95": [round(mrr_lo, 4), round(mrr_hi, 4)],
        "recall@5_diff": round(rec_diff, 4),
        "recall@5_ci95": [round(rec_lo, 4), round(rec_hi, 4)],
        "forbidden_hit_rate@5_delta": round(forb_delta, 4),
    }
    return passed, diff_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Skill Pilot v3 offline evaluator")
    parser.add_argument(
        "--queries",
        default=str(EVAL_DIR / "queries.jsonl"),
        help="Path to gold JSONL queries",
    )
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", help="Optional path to write JSON report")
    parser.add_argument(
        "--benchmark-scale",
        action="store_true",
        help="Run scale latency and memory benchmark (10, 100, 1000)",
    )
    parser.add_argument(
        "--compare-baseline",
        help="Optional baseline JSON report path for regression gate",
    )
    args = parser.parse_args()

    report = evaluate_queries(
        pathlib.Path(args.queries), split=args.split, limit=args.limit, seed=args.seed
    )
    if args.benchmark_scale:
        report["scale_benchmark"] = benchmark_scale(seed=args.seed)

    exit_code = 0
    if args.compare_baseline:
        baseline = json.loads(
            pathlib.Path(args.compare_baseline).read_text(encoding="utf-8")
        )
        passed, diff_report = compare_against_baseline(report, baseline)
        report["baseline_comparison"] = diff_report
        if not passed:
            exit_code = 2

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        out_path = pathlib.Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")

    # Compact summary to stdout (full JSON saved when --output is set).
    summary = {
        "split": report["split"],
        "overall": report["overall"],
        "by_language": {
            k: {
                "recall@5": v["recall@5"],
                "mrr@5": v["mrr@5"],
                "ndcg@5": v["ndcg@5"],
                "forbidden_hit_rate@5": v["forbidden_hit_rate@5"],
            }
            for k, v in report["by_language"].items()
        },
        "latency_ms": report["latency_ms"],
    }
    if "scale_benchmark" in report:
        summary["scale_benchmark"] = report["scale_benchmark"]
    if "baseline_comparison" in report:
        summary["baseline_comparison"] = report["baseline_comparison"]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
