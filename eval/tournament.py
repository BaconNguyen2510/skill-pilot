"""Retrieval algorithm tournament on the dev split (SEARCH-01..09, VI-01..03)."""

from __future__ import annotations

import json
import math
import pathlib
import re
import sys
import tempfile
import time
import unicodedata
from collections import Counter
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
    paired_bootstrap_ci,
    precision_at_k,
    recall_at_k,
)
from run_eval import _run_scout_search, load_scout_module
from validate_eval import load_jsonl, validate_records


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return (
        "".join(ch for ch in nfkd if not unicodedata.combining(ch))
        .replace("đ", "d")
        .replace("Đ", "D")
    )


def _tokens(text: str, *, fold: bool = False) -> list[str]:
    norm = _strip_accents(text) if fold else text
    return [
        t
        for t in re.findall(r"[a-zA-Z0-9\u00C0-\u024F\u1E00-\u1EFF_-]+", norm.lower())
        if len(t) >= 2
    ]


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    clean = re.sub(r"\s+", " ", _strip_accents(text.lower())).strip()
    if len(clean) < n:
        return {clean} if clean else set()
    return {clean[i : i + n] for i in range(len(clean) - n + 1)}


def _load_synthetic_docs(scout: Any, env: dict[str, Any]) -> list[dict[str, Any]]:
    """Load synthetic skill corpus identically to cmd_search without side effects."""
    active_dir = pathlib.Path(env["active_dir"])
    codex_dir = pathlib.Path(env["codex_dir"])
    warehouses = [pathlib.Path(w) for w in env["warehouses"]]

    from unittest import mock

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
    ):
        active = [
            s
            for s in scout.collect_active_skills(harness="all")
            if not s.get("shadowed")
        ]
        docs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in active:
            sid = str(item.get("name") or "")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                docs.append(
                    {
                        "id": sid,
                        "name": sid,
                        "description": str(item.get("description") or ""),
                        "category": "",
                        "tags": [],
                        "tier": "active",
                    }
                )
        for wh in warehouses:
            for rec in scout._load_warehouse_records(wh):
                risk = str(rec.get("risk") or "unknown").strip().lower()
                if risk == "offensive":
                    continue
                sid = str(rec.get("id") or rec.get("name") or "")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    docs.append(
                        {
                            "id": sid,
                            "name": str(rec.get("name") or sid),
                            "description": str(rec.get("description") or ""),
                            "category": str(rec.get("category") or ""),
                            "tags": [str(t) for t in rec.get("tags", [])],
                            "tier": "warehouse",
                        }
                    )
        return docs


_EXTRA_VI_ALIASES: dict[str, tuple[str, ...]] = {
    "ty gia": ("fx", "currency", "exchange", "hedging"),
    "hoi doai": ("fx", "foreign", "exchange", "currency"),
    "ky han": ("forward", "contracts", "hedging"),
    "phong ngua": ("hedging", "risk"),
    "dong tien": ("cash", "flow", "dcf"),
    "chiet khau": ("discounted", "dcf", "valuation"),
    "dinh gia": ("valuation", "dcf", "wacc"),
    "tiep can": ("accessibility", "wcag", "aria"),
    "ban phim": ("keyboard", "focus", "aria"),
    "hieu nang": ("performance", "perf", "animation", "tuning"),
    "bao mat": ("security", "hardening", "audit"),
    "trien khai": ("deploy", "worker", "hosting"),
    "kiem thu": ("testing", "unittest", "fuzzing", "e2e"),
    "trich dan": ("citation", "apa", "literature"),
    "tong quan": ("literature", "synthesis"),
    "viet bai": ("copywriting", "writing"),
    "cham soc": ("customer", "support", "cham-soc"),
    "cham tien do": ("delay", "milestone", "cham-tien-do"),
    "dep": ("ui", "design", "tokens", "aesthetics"),
}


_CLAUSE_SPLIT_RE = re.compile(
    r"\b(?:nhung can|nhung|chi can|but|instead|only)\b|[,;]",
    re.IGNORECASE,
)
_NEG_CLAUSE_RE = re.compile(
    r"\b(?:khong dung|khong can|khong|tranh|bo qua|loai bo|without|avoid|exclude|not|no|do not use|never)\b",
    re.IGNORECASE,
)


def _split_pos_neg_clauses(
    query: str, *, clause_negation: bool, extra_aliases: bool
) -> tuple[list[str], list[str]]:
    folded = _strip_accents(query.lower())
    if not clause_negation:
        if _NEG_CLAUSE_RE.search(folded) and not any(
            k in folded for k in ("nhung", "chi can", "but", "only", "without", "avoid")
        ):
            return [], _tokens(folded, fold=True)
        # Fallback simple split on first negation if present.
        pos_tokens = _tokens(folded, fold=True)
        neg_tokens: list[str] = []
        for m in re.finditer(
            r"(?:without|avoid|khong dung|tranh)\s+([a-z0-9_-]+(?:\s+[a-z0-9_-]+)?)",
            folded,
        ):
            neg_tokens.extend(_tokens(m.group(1), fold=True))
        return pos_tokens, neg_tokens

    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(folded) if c.strip()]
    pos_parts: list[str] = []
    neg_parts: list[str] = []
    for cl in clauses:
        # Handle inline "X without Y" or "X tránh Y".
        inline = re.split(
            r"\b(?:without|avoid|tranh|khong dung|khong can)\b", cl, maxsplit=1
        )
        if len(inline) == 2:
            if inline[0].strip():
                pos_parts.append(inline[0].strip())
            if inline[1].strip():
                neg_parts.append(inline[1].strip())
        elif _NEG_CLAUSE_RE.search(cl):
            neg_parts.append(cl)
        else:
            pos_parts.append(cl)

    pos_text = " ".join(pos_parts)
    neg_text = " ".join(neg_parts)
    pos_tokens = _tokens(pos_text, fold=True)
    neg_tokens = _tokens(neg_text, fold=True)

    if extra_aliases and pos_text:
        for phrase, expansions in _EXTRA_VI_ALIASES.items():
            if phrase in pos_text:
                pos_tokens.extend(expansions)
    return pos_tokens, neg_tokens


def _build_doc_index(
    docs: list[dict[str, Any]],
) -> tuple[dict[str, float], float, list[dict[str, Any]]]:
    df: Counter[str] = Counter()
    indexed: list[dict[str, Any]] = []
    lengths: list[int] = []
    for d in docs:
        name_toks = _tokens(d["name"], fold=True)
        cat_toks = _tokens(d["category"], fold=True)
        tag_toks = [t for tag in d["tags"] for t in _tokens(tag, fold=True)]
        desc_toks = _tokens(d["description"], fold=True)
        all_toks = name_toks * 3 + cat_toks * 2 + tag_toks * 2 + desc_toks
        tf = Counter(all_toks)
        for tok in set(all_toks):
            df[tok] += 1
        lengths.append(len(all_toks))
        indexed.append(
            {
                **d,
                "tf": tf,
                "doc_len": len(all_toks),
                "name_toks": set(name_toks),
                "tag_toks": set(tag_toks),
                "all_tok_set": set(all_toks),
                "ngrams": _char_ngrams(
                    f"{d['name']} {' '.join(d['tags'])} {d['description']}"
                ),
            }
        )
    n_docs = max(len(docs), 1)
    idf = {
        tok: math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1.0)
        for tok, freq in df.items()
    }
    avgdl = sum(lengths) / n_docs if lengths else 1.0
    return idf, avgdl, indexed


def _score_candidate(
    query: str,
    idf: dict[str, float],
    avgdl: float,
    indexed: list[dict[str, Any]],
    *,
    mode: str,
    clause_negation: bool = False,
    extra_aliases: bool = False,
    use_ngram: bool = False,
    abstain_floor: float = 0.0,
    ratio_cutoff: float = 0.0,
    active_bonus: float = 2.0,
    limit: int = 5,
) -> list[str]:
    pos_tokens, neg_tokens = _split_pos_neg_clauses(
        query, clause_negation=clause_negation, extra_aliases=extra_aliases
    )
    if not pos_tokens:
        return []
    pos_set = list(dict.fromkeys(pos_tokens))
    neg_set = set(neg_tokens) - set(pos_set)
    q_ngrams = _char_ngrams(query) if use_ngram else set()

    scored: list[tuple[float, str]] = []
    for d in indexed:
        # Exclude if negated term matches skill name/tags strongly.
        if neg_set and (neg_set & (d["name_toks"] | d["tag_toks"])):
            continue

        s = 0.0
        if mode == "bm25":
            k1, b = 1.5, 0.75
            dl = max(d["doc_len"], 1)
            for tok in pos_set:
                f = d["tf"].get(tok, 0)
                if f > 0:
                    w = idf.get(tok, 1.0)
                    s += w * (f * (k1 + 1.0)) / (f + k1 * (1.0 - b + b * dl / avgdl))
        elif mode == "tfidf":
            for tok in pos_set:
                f = d["tf"].get(tok, 0)
                if f > 0:
                    s += (1.0 + math.log(f)) * idf.get(tok, 1.0)
        else:  # lexical_weighted
            for tok in pos_set:
                if tok in d["name_toks"]:
                    s += 4.0
                elif tok in d["tag_toks"]:
                    s += 2.5
                elif tok in d["all_tok_set"]:
                    s += 1.0

        if use_ngram and q_ngrams and d["ngrams"]:
            inter = len(q_ngrams & d["ngrams"])
            union = len(q_ngrams | d["ngrams"])
            if union > 0:
                s += 4.0 * (inter / union)

        if s <= 0.0:
            continue
        if d["tier"] == "active" and active_bonus > 0.0 and s >= abstain_floor:
            s += active_bonus
        scored.append((s, d["id"]))

    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    top_score = scored[0][0]
    if abstain_floor > 0.0 and top_score < abstain_floor:
        return []
    if ratio_cutoff > 0.0:
        min_keep = top_score * ratio_cutoff
        scored = [pair for pair in scored if pair[0] >= min_keep]
    return [sid for _, sid in scored[:limit]]


def _eval_dev_variant(
    dev_queries: list[dict[str, Any]],
    scorer_fn: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    t_start = time.perf_counter()
    for rec in dev_queries:
        t0 = time.perf_counter()
        ranked = scorer_fn(rec["query"])
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        relevant = set(rec["required_skills"]) | set(rec["acceptable_alternates"])
        rows.append(
            {
                "id": rec["id"],
                "language": rec["language"],
                "expected_abstain": rec["expected_abstain"],
                "predicted_ids": ranked,
                "latency_ms": elapsed_ms,
                "recall@5": recall_at_k(ranked, relevant, 5),
                "mrr@5": mrr_at_k(ranked, relevant, 5),
                "ndcg@5": ndcg_at_k(
                    ranked, rec["required_skills"], rec["acceptable_alternates"], 5
                ),
                "precision@5": precision_at_k(ranked, relevant, 5),
                "forbidden_hit_rate@5": forbidden_hit_rate(
                    ranked, rec["forbidden_skills"], 5
                ),
            }
        )
    total_ms = (time.perf_counter() - t_start) * 1000.0
    non_abstain = [r for r in rows if not r["expected_abstain"]]
    ab = abstention_metrics(rows)

    def mean(k: str, sub: list[dict[str, Any]]) -> float:
        return round(sum(float(r[k]) for r in sub) / len(sub), 4) if sub else 0.0

    by_lang = {}
    for lang in ("en", "vi", "vi_no_diacritic", "mixed"):
        sub_na = [r for r in non_abstain if r["language"] == lang]
        sub_all = [r for r in rows if r["language"] == lang]
        by_lang[lang] = {
            "recall@5": mean("recall@5", sub_na),
            "mrr@5": mean("mrr@5", sub_na),
            "forbidden_hit_rate@5": mean("forbidden_hit_rate@5", sub_all),
        }

    summary = {
        "recall@5": mean("recall@5", non_abstain),
        "mrr@5": mean("mrr@5", non_abstain),
        "ndcg@5": mean("ndcg@5", non_abstain),
        "precision@5": mean("precision@5", non_abstain),
        "forbidden_hit_rate@5": mean("forbidden_hit_rate@5", rows),
        "abstention_f1": round(ab["f1"], 4),
        "total_ms": round(total_ms, 2),
        "by_language": by_lang,
    }
    return summary, rows


def main() -> int:
    records, errs = load_jsonl(EVAL_DIR / "queries.jsonl")
    if errs or validate_records(records):
        raise SystemExit("Invalid queries.jsonl")
    dev_queries = [r for r in records if r["split"] == "dev"]

    scout = load_scout_module()
    with tempfile.TemporaryDirectory() as tmp:
        env = build_eval_environment(pathlib.Path(tmp), seed=42)
        docs = _load_synthetic_docs(scout, env)
        idf, avgdl, indexed = _build_doc_index(docs)

        # 1. Frozen v2.1.0 baseline on dev split
        base_summary, base_rows = _eval_dev_variant(
            dev_queries,
            lambda q: [
                str(m.get("id") or m.get("name") or "")
                for m in (_run_scout_search(scout, env, q, limit=5)[1] or {}).get(
                    "ranked_matches", []
                )
            ],
        )
        base_mrr_vec = [r["mrr@5"] for r in base_rows if not r["expected_abstain"]]

        variants = {
            "X-01_bm25_only": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="bm25"
            ),
            "X-04_tfidf_only": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="tfidf"
            ),
            "X-02_bm25_plus_ngram": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="bm25", use_ngram=True
            ),
            "X-14_bm25_clause_negation": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="bm25", clause_negation=True
            ),
            "X-23_bm25_abstention_cutoff": lambda q: _score_candidate(
                q,
                idf,
                avgdl,
                indexed,
                mode="bm25",
                abstain_floor=2.2,
                ratio_cutoff=0.45,
            ),
            "VI-01_bm25_vi_aliases": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="bm25", extra_aliases=True
            ),
            "X-05_bm25_low_tier_bonus": lambda q: _score_candidate(
                q, idf, avgdl, indexed, mode="bm25", active_bonus=0.25
            ),
            "CANDIDATE_hybrid_v3": lambda q: _score_candidate(
                q,
                idf,
                avgdl,
                indexed,
                mode="bm25",
                clause_negation=True,
                extra_aliases=True,
                use_ngram=True,
                abstain_floor=2.2,
                ratio_cutoff=0.45,
                active_bonus=0.25,
            ),
        }

        report: dict[str, Any] = {"baseline_dev": base_summary, "experiments": {}}
        for name, fn in variants.items():
            summary, rows = _eval_dev_variant(dev_queries, fn)
            cand_mrr_vec = [r["mrr@5"] for r in rows if not r["expected_abstain"]]
            mrr_diff, ci_lo, ci_hi = paired_bootstrap_ci(
                base_mrr_vec, cand_mrr_vec, seed=42
            )
            summary["mrr@5_diff_vs_baseline"] = round(mrr_diff, 4)
            summary["mrr@5_ci95"] = [round(ci_lo, 4), round(ci_hi, 4)]
            report["experiments"][name] = summary

    out_path = REPO_ROOT / "docs" / "v3" / "TOURNAMENT_DEV.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
