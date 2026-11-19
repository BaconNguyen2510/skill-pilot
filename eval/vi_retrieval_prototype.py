"""Isolated Vietnamese retrieval prototype benchmark on the dev split (does not modify production)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))

import corpus_builder
import metrics
import skill_scout

# Small domain-specific Vietnamese -> English terminology map (dev prototype only)
VI_DOMAIN_GLOSSARY: dict[str, str] = {
    "xac thuc": "authentication auth login",
    "dang nhap": "login authentication",
    "co so du lieu": "database sql schema",
    "kiem thu": "testing test unit",
    "trien khai": "deploy deployment",
    "hieu nang": "performance optimization",
    "giao dien": "ui frontend interface",
    "bao mat": "security hardening",
    "bieu do": "chart visualization",
    "tai lieu": "documentation",
}


def _expand_vi_glossary(query: str) -> str:
    norm = skill_scout._strip_accents_lower(query)
    extras = [eng for vi, eng in VI_DOMAIN_GLOSSARY.items() if vi in norm]
    return f"{query} {' '.join(extras)}".strip() if extras else query


def _run_variant(
    queries: list[dict], catalog: list[dict], *, use_glossary: bool
) -> dict:
    latencies: list[float] = []
    by_lang: dict[str, list[dict]] = {}
    for q in queries:
        if q.get("abstain"):
            continue
        raw_q = q["query"]
        if use_glossary and q.get("language") in ("vi", "vi_no_diacritic", "mixed"):
            raw_q = _expand_vi_glossary(raw_q)
        pos_q, neg_q = skill_scout._split_query_negations(raw_q)
        direct, alias = skill_scout._query_term_groups(pos_q or raw_q)
        excl = set(skill_scout.query_terms(neg_q)) if neg_q else set()
        t0 = time.perf_counter()
        scored = []
        for s in catalog:
            sc = skill_scout.score_record(
                pos_q or raw_q,
                direct,
                s["name"],
                s.get("category", ""),
                s.get("tags", []),
                s.get("description", ""),
                alias_tokens=alias,
                excluded_tokens=excl,
            )
            if sc > 0:
                scored.append((sc, s["name"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        latencies.append((time.perf_counter() - t0) * 1000.0)
        preds = [name for _, name in scored[:5]]
        gold = set(q.get("relevant_skills", []))
        forb = set(q.get("forbidden_skills", []))
        row = {
            "mrr@5": metrics.mrr_at_k(preds, gold, 5),
            "recall@5": metrics.recall_at_k(preds, gold, 5),
            "forbidden@5": 1.0 if (set(preds) & forb) else 0.0,
        }
        by_lang.setdefault(q["language"], []).append(row)

    summary = {}
    for lang, rows in sorted(by_lang.items()):
        n = len(rows)
        summary[lang] = {
            "count": n,
            "mrr@5": round(sum(r["mrr@5"] for r in rows) / n, 4),
            "recall@5": round(sum(r["recall@5"] for r in rows) / n, 4),
            "forbidden@5": round(sum(r["forbidden@5"] for r in rows) / n, 4),
        }
    latencies.sort()
    return {
        "by_language": summary,
        "p50_ms": round(latencies[len(latencies) // 2], 3),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 3),
    }


def main() -> int:
    all_queries = [
        json.loads(line)
        for line in (ROOT / "eval" / "queries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    dev_queries = [q for q in all_queries if q.get("split") == "dev"]
    with tempfile.TemporaryDirectory() as tmp:
        env = corpus_builder.build_eval_environment(tmp)
        catalog: list[dict] = []
        for wh in env["warehouses"]:
            catalog.extend(
                json.loads(
                    (pathlib.Path(wh) / "skills_index.json").read_text(encoding="utf-8")
                )
            )
        baseline = _run_variant(dev_queries, catalog, use_glossary=False)
        glossary = _run_variant(dev_queries, catalog, use_glossary=True)
    print(
        json.dumps(
            {
                "dev_count": len(dev_queries),
                "baseline": baseline,
                "vi_glossary_prototype": glossary,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
