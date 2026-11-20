"""Dev-only Skill Pilot v4 retrieval ablation; never evaluates holdout cases.

All experiments are intentionally non-production patches to the score function.
Run: python eval/v4_retrieval_ablation.py
"""

from __future__ import annotations

import collections
import json
import pathlib
from unittest import mock

import run_eval

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV_DATASETS = (
    ROOT / "eval" / "queries.jsonl",
    ROOT / "eval" / "dev_v2_challenge.jsonl",
)
LANGUAGES = ("en", "vi", "vi_no_diacritic", "mixed")
VARIANTS = (
    "baseline",
    "name_field_boost",
    "length_normalized_fields",
    "alias_downweight",
)


def variant_scorer(scout, name: str):
    """Return a score function, preserving baseline abstention and exclusions."""
    base = scout.score_record
    if name == "baseline":
        return base
    if name not in VARIANTS:
        raise ValueError(f"Unknown retrieval variant: {name}")

    def score(
        query,
        q_tokens,
        skill_name,
        category,
        tags,
        desc,
        excluded_tokens=None,
        alias_tokens=None,
    ):
        original = base(
            query,
            q_tokens,
            skill_name,
            category,
            tags,
            desc,
            excluded_tokens=excluded_tokens,
            alias_tokens=alias_tokens,
        )
        # Never resurrect candidates that the baseline has explicitly excluded.
        if original <= 0:
            return original
        if name == "alias_downweight":
            no_alias = base(
                query,
                q_tokens,
                skill_name,
                category,
                tags,
                desc,
                excluded_tokens=excluded_tokens,
                alias_tokens=[],
            )
            return round(0.7 * original + 0.3 * no_alias, 2)

        positive = set(q_tokens)
        name_terms = set(scout.tokenize(skill_name))
        if name == "name_field_boost":
            return round(original + 1.25 * len(positive & name_terms), 2)

        # A parameter-light BM25F-inspired experiment, not full corpus-IDF BM25F.
        # Field occurrence weights and document-length normalization are explicit.
        field_terms = (
            (skill_name, 3.0),
            (" ".join(str(value) for value in tags), 2.0),
            (category, 1.5),
            (desc, 1.0),
        )
        weighted = collections.Counter()
        length = 0
        for value, weight in field_terms:
            terms = scout.tokenize(value)
            length += len(terms)
            for token in terms:
                weighted[token] += weight
        norm = 0.25 + 0.75 * (length / 24.0)
        extra = sum(
            2.0 * (weighted[token] * 2.2) / (weighted[token] + 1.2 * norm + 0.2)
            for token in positive
            if weighted[token]
        )
        return round(original + min(extra, 12.0), 2)

    return score


def summarize(result: dict) -> dict:
    def metrics(part: dict) -> dict:
        return {
            key: part.get(key, 0)
            for key in (
                "mrr@5",
                "recall@5",
                "ndcg@5",
                "forbidden_hit_rate@5",
            )
        }

    return {
        "count": result["overall"]["count_total"],
        "overall": metrics(result["overall"]),
        "by_language": {
            lang: metrics(result["by_language"].get(lang, {})) for lang in LANGUAGES
        },
        "latency_ms": result["latency_ms"],
    }


def run_variant(dataset: pathlib.Path, name: str) -> dict:
    if dataset not in DEV_DATASETS:
        raise ValueError("Only registered development datasets may be evaluated")
    scout = run_eval.load_scout_module()
    scout.score_record = variant_scorer(scout, name)
    with mock.patch.object(run_eval, "load_scout_module", return_value=scout):
        # run_eval filters before passing queries to the ranker.
        result = run_eval.evaluate_queries(dataset, split="dev")
    if result["split"] != "dev":
        raise RuntimeError("Unexpected evaluation split; refusing ablation")
    return summarize(result)


def deltas(candidate: dict, baseline: dict) -> dict:
    return {
        key: round(candidate["overall"][key] - baseline["overall"][key], 4)
        for key in baseline["overall"]
    }


def gate(candidate: dict, baseline: dict) -> dict:
    """Conservative integration proposal; never auto-modifies production."""
    b_en = baseline["by_language"]["en"]
    c_en = candidate["by_language"]["en"]
    forbidden_ok = all(
        candidate["by_language"][lang]["forbidden_hit_rate@5"]
        <= baseline["by_language"][lang]["forbidden_hit_rate@5"]
        for lang in LANGUAGES
    )
    english_ok = all(c_en[key] >= b_en[key] for key in ("mrr@5", "recall@5"))
    overall_gain = (
        candidate["overall"]["mrr@5"] > baseline["overall"]["mrr@5"]
        and candidate["overall"]["recall@5"] >= baseline["overall"]["recall@5"]
    )
    return {
        "forbidden_nonregression": forbidden_ok,
        "english_nonregression": english_ok,
        "overall_improvement": overall_gain,
        "eligible_for_review": forbidden_ok and english_ok and overall_gain,
    }


def main() -> int:
    output = {
        "protocol": "v4-dev-only",
        "holdout_accessed": False,
        "candidate_integration": "none",
        "datasets": {},
    }
    for dataset in DEV_DATASETS:
        baseline = run_variant(dataset, "baseline")
        variants = {"baseline": baseline}
        for name in VARIANTS:
            if name == "baseline":
                continue
            result = run_variant(dataset, name)
            variants[name] = {
                **result,
                "delta_vs_baseline": deltas(result, baseline),
                "gate": gate(result, baseline),
            }
        output["datasets"][dataset.name] = variants
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
