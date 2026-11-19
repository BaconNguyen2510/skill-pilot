"""X-03 / SEARCH-14 / INTENT-01: Multi-intent splitting & fusion experiment on dev split."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
import tempfile
import time
from typing import Any

EVAL_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent

if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from corpus_builder import build_eval_environment
from metrics import (
    abstention_metrics,
    forbidden_hit_rate,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)
from run_eval import _extract_ranked_ids, _run_scout_search, load_scout_module
from validate_eval import load_jsonl, validate_records

# Deterministic separators for compound positive intent splitting.
_MULTI_INTENT_SEP_RE = re.compile(
    r"\s*(?:,|;|\b(?:and|va|và|then|roi|rồi|plus|with)\b)\s*",
    flags=re.IGNORECASE | re.UNICODE,
)


def _extract_positive_clauses(scout: Any, query: str) -> tuple[list[str], str]:
    """Extract positive clauses preserving comma/semicolon boundaries and negation text."""
    coord_re = re.compile(
        r"(?i)\b(?:nhưng\s+cần|nhung\s+can|nhưng|nhung|chỉ\s+cần|chi\s+can|but\s+only|but|instead)\b"
    )
    raw_clauses: list[str] = []
    for sentence in re.split(r"[.!?;,\n]+", query):
        raw_clauses.extend(coord_re.split(sentence))

    pos_clauses: list[str] = []
    neg_parts: list[str] = []
    for raw_clause in raw_clauses:
        clause = raw_clause.strip()
        if not clause:
            continue
        norm_clause = " ".join(
            re.findall(r"[a-z0-9']+", scout._strip_accents_lower(clause))
        )
        matches = [
            m
            for regex in (scout.VI_NEGATION_RE, scout.EN_NEGATION_RE)
            for m in [regex.search(norm_clause)]
            if m is not None
        ]
        if re.search(r"\bno\b", clause.lower()) and not scout.VI_CONTEXT_HINT_RE.search(
            norm_clause
        ):
            m_no = scout.EN_NO_RE.search(norm_clause)
            if m_no is not None:
                matches.append(m_no)
        if not matches:
            pos_clauses.append(clause)
            continue
        first = min(matches, key=lambda m: m.start())
        pos_prefix = norm_clause[: first.start()].strip()
        neg_suffix = norm_clause[first.end() :].strip()
        if pos_prefix:
            prefix_word_count = len(pos_prefix.split())
            pos_clauses.append(" ".join(clause.split()[:prefix_word_count]))
        if neg_suffix:
            neg_parts.append(neg_suffix)
    return pos_clauses, " ".join(neg_parts)


def _searchable_token_count(scout: Any, text: str) -> int:
    direct_tokens, _ = scout._query_term_groups(text)
    return len(direct_tokens)


def split_multi_intent(scout: Any, query: str) -> tuple[list[str], str]:
    """Split positive intent text into sub-intents when each has >= 2 searchable tokens."""
    pos_clauses, neg_query = _extract_positive_clauses(scout, query)
    if not pos_clauses:
        return [], neg_query

    # First, keep comma/semicolon-separated positive clauses if each has >= 2 searchable
    # tokens; otherwise merge adjacent small clauses back together.
    merged_clauses: list[str] = []
    for clause in pos_clauses:
        if (
            merged_clauses
            and _searchable_token_count(scout, clause) < 2
            or merged_clauses
            and _searchable_token_count(scout, merged_clauses[-1]) < 2
        ):
            merged_clauses[-1] = f"{merged_clauses[-1]} {clause}"
        else:
            merged_clauses.append(clause)

    sub_intents: list[str] = []
    for clause in merged_clauses:
        parts = [p.strip() for p in _MULTI_INTENT_SEP_RE.split(clause) if p.strip()]
        if len(parts) > 1 and all(
            _searchable_token_count(scout, part) >= 2 for part in parts
        ):
            sub_intents.extend(parts)
        else:
            sub_intents.append(clause)

    return sub_intents, neg_query


def _merge_max_score(
    sub_results: list[list[dict[str, Any]]],
    limit: int = 5,
) -> list[str]:
    """Merge ranked_matches across sub-intents by max score."""
    best_score: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for matches in sub_results:
        for rank, item in enumerate(matches, start=1):
            sid = str(item.get("id") or item.get("name") or "").strip()
            if not sid:
                continue
            sc = float(item.get("score") or 0.0)
            if sid not in best_score or sc > best_score[sid]:
                best_score[sid] = sc
            if sid not in best_rank or rank < best_rank[sid]:
                best_rank[sid] = rank
    ordered = sorted(
        best_score,
        key=lambda sid: (-best_score[sid], best_rank[sid], sid),
    )
    return ordered[:limit]


def _merge_rrf(
    sub_results: list[list[dict[str, Any]]],
    limit: int = 5,
    rrf_k: int = 60,
) -> list[str]:
    """Merge ranked_matches across sub-intents using Reciprocal Rank Fusion."""
    rrf_score: dict[str, float] = {}
    best_score: dict[str, float] = {}
    for matches in sub_results:
        for rank, item in enumerate(matches, start=1):
            sid = str(item.get("id") or item.get("name") or "").strip()
            if not sid:
                continue
            rrf_score[sid] = rrf_score.get(sid, 0.0) + (1.0 / (rrf_k + rank))
            sc = float(item.get("score") or 0.0)
            if sid not in best_score or sc > best_score[sid]:
                best_score[sid] = sc
    ordered = sorted(
        rrf_score,
        key=lambda sid: (-rrf_score[sid], -best_score[sid], sid),
    )
    return ordered[:limit]


def _score_predictions(
    records: list[dict[str, Any]],
    predictions: dict[str, list[str]],
    latencies_ms: dict[str, float],
) -> dict[str, Any]:
    """Compute required ranking, safety, abstention, and latency metrics."""
    rows: list[dict[str, Any]] = []
    for rec in records:
        qid = rec["id"]
        ranked_ids = predictions[qid]
        relevant = set(rec["required_skills"]) | set(rec["acceptable_alternates"])
        rows.append(
            {
                "id": qid,
                "expected_abstain": rec["expected_abstain"],
                "expected_skill_count": rec["expected_skill_count"],
                "predicted_ids": ranked_ids,
                "recall@5": recall_at_k(ranked_ids, relevant, 5),
                "mrr@5": mrr_at_k(ranked_ids, relevant, 5),
                "ndcg@5": ndcg_at_k(
                    ranked_ids,
                    rec["required_skills"],
                    rec["acceptable_alternates"],
                    5,
                ),
                "forbidden_hit_rate@5": forbidden_hit_rate(
                    ranked_ids, rec["forbidden_skills"], 5
                ),
                "latency_ms": latencies_ms[qid],
            }
        )

    def _summarize(subset: list[dict[str, Any]]) -> dict[str, Any]:
        non_abstain = [r for r in subset if not r["expected_abstain"]]

        def _mean(key: str, group: list[dict[str, Any]]) -> float:
            if not group:
                return 0.0
            return round(sum(float(r[key]) for r in group) / len(group), 4)

        lats = sorted(float(r["latency_ms"]) for r in subset)
        p50 = statistics.median(lats) if lats else 0.0
        p95_idx = min(len(lats) - 1, int(0.95 * (len(lats) - 1))) if lats else 0
        p95 = lats[p95_idx] if lats else 0.0
        abstain = abstention_metrics(subset)
        return {
            "count_total": len(subset),
            "count_non_abstain": len(non_abstain),
            "recall@5": _mean("recall@5", non_abstain),
            "mrr@5": _mean("mrr@5", non_abstain),
            "ndcg@5": _mean("ndcg@5", non_abstain),
            "forbidden_hit_rate@5": _mean("forbidden_hit_rate@5", subset),
            "abstention_f1": round(abstain["f1"], 4),
            "latency_ms": {
                "mean": round(sum(lats) / len(lats), 3) if lats else 0.0,
                "p50": round(p50, 3),
                "p95": round(p95, 3),
            },
        }

    return {
        "full_dev": _summarize(rows),
        "multi_skill_dev": _summarize(
            [r for r in rows if r["expected_skill_count"] >= 2]
        ),
        "single_skill_dev": _summarize(
            [r for r in rows if r["expected_skill_count"] == 1]
        ),
    }


def _audit_short_tokens(scout: Any) -> dict[str, Any]:
    """Inspect STOP_WORDS vs short domain tokens (go, d1, ai, r, c)."""
    probe_tokens = ["go", "d1", "ai", "r", "c"]
    token_checks: dict[str, Any] = {}
    for tok in probe_tokens:
        tokenized = scout.tokenize(tok)
        direct, alias = scout._query_term_groups(tok)
        token_checks[tok] = {
            "length": len(tok),
            "tokenized": tokenized,
            "dropped_by_min_len_2": len(tokenized) == 0,
            "in_stop_words": tok in scout.STOP_WORDS,
            "survives_query_term_groups": direct,
            "alias_expansion": alias,
        }
    two_char_stop_words = sorted(w for w in scout.STOP_WORDS if len(w) <= 2)
    return {
        "probe_tokens": token_checks,
        "stop_words_len_le_2": two_char_stop_words,
        "findings": [
            "go, d1, and ai have length 2, are absent from STOP_WORDS, and survive tokenize() and _query_term_groups().",
            "r and c have length 1, so tokenize() drops them via len(t) >= 2 before STOP_WORDS is checked (only c++ -> cpp and c# -> csharp are special-cased).",
            "STOP_WORDS contains 'va' (Vietnamese conjunction) and 'and'/'with' (English conjunctions), which aligns with multi-intent separator splitting.",
        ],
    }


def run_experiment(
    queries_path: pathlib.Path,
    limit: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    records, parse_errors = load_jsonl(queries_path)
    if parse_errors:
        raise ValueError(f"Invalid eval JSONL: {parse_errors[0]}")
    errors = validate_records(records)
    if errors:
        raise ValueError(f"Invalid eval dataset: {errors[0]}")

    dev_records = [r for r in records if r["split"] == "dev"]
    scout = load_scout_module()

    baseline_preds: dict[str, list[str]] = {}
    baseline_lats: dict[str, float] = {}
    max_preds: dict[str, list[str]] = {}
    rrf_preds: dict[str, list[str]] = {}
    multi_lats: dict[str, float] = {}
    split_examples: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        env = build_eval_environment(pathlib.Path(tmp) / "corpus", seed=seed)

        for rec in dev_records:
            qid = rec["id"]
            query = rec["query"]

            # 1. Single-query baseline
            t0 = time.perf_counter()
            _, payload = _run_scout_search(scout, env, query, limit=limit)
            baseline_lats[qid] = (time.perf_counter() - t0) * 1000.0
            baseline_preds[qid] = _extract_ranked_ids(payload)

            # 2. Deterministic multi-intent split + merge
            t1 = time.perf_counter()
            sub_intents, neg_query = split_multi_intent(scout, query)
            if neg_query and not sub_intents:
                sub_matches_list: list[list[dict[str, Any]]] = []
            elif len(sub_intents) <= 1:
                _, p_single = _run_scout_search(scout, env, query, limit=limit)
                sub_matches_list = [
                    list(p_single.get("ranked_matches", [])) if p_single else []
                ]
            else:
                sub_matches_list = []
                for sub in sub_intents:
                    sub_q = f"{sub}, not {neg_query}" if neg_query.strip() else sub
                    _, p_sub = _run_scout_search(scout, env, sub_q, limit=limit)
                    sub_matches_list.append(
                        list(p_sub.get("ranked_matches", [])) if p_sub else []
                    )

            max_preds[qid] = _merge_max_score(sub_matches_list, limit=limit)
            rrf_preds[qid] = _merge_rrf(sub_matches_list, limit=limit)
            multi_lats[qid] = (time.perf_counter() - t1) * 1000.0

            if rec["expected_skill_count"] >= 2:
                split_examples.append(
                    {
                        "id": qid,
                        "sub_intents": sub_intents,
                        "neg_query": neg_query,
                        "baseline_top5": baseline_preds[qid],
                        "max_score_top5": max_preds[qid],
                        "rrf_top5": rrf_preds[qid],
                        "required_skills": rec["required_skills"],
                    }
                )

    return {
        "experiment": "X-03_MULTI_INTENT",
        "tasks": ["X-03", "SEARCH-14", "INTENT-01"],
        "split": "dev",
        "limit": limit,
        "seed": seed,
        "strategies": {
            "single_query_baseline": _score_predictions(
                dev_records, baseline_preds, baseline_lats
            ),
            "multi_intent_max_score": _score_predictions(
                dev_records, max_preds, multi_lats
            ),
            "multi_intent_rrf": _score_predictions(dev_records, rrf_preds, multi_lats),
        },
        "stop_words_short_token_audit": _audit_short_tokens(scout),
        "multi_skill_split_trace": split_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark deterministic multi-intent splitting on dev split."
    )
    parser.add_argument(
        "--queries",
        default=str(EVAL_DIR / "queries.jsonl"),
        help="Path to gold JSONL queries",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "docs" / "v3" / "X03_MULTI_INTENT_DEV.json"),
        help="Path to save JSON report",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    report = run_experiment(
        pathlib.Path(args.queries), limit=args.limit, seed=args.seed
    )
    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
