"""Sprint G & H ablation study on dev split: Vietnamese intelligence + abstention calibration (VI-02..06, SEARCH-09)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unicodedata
from typing import Any

EVAL_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from corpus_builder import build_eval_environment
from metrics import paired_bootstrap_ci
from run_eval import _run_scout_search, load_scout_module
from tournament import _eval_dev_variant
from validate_eval import load_jsonl

PHRASE_ALIASES_V3: dict[str, str] = {
    "co so du lieu": "database sql postgres sqlite",
    "kiem thu tu dong": "testing unittest e2e",
    "phan quyen": "auth oauth rbac security",
    "dang nhap": "auth oauth login",
    "tich hop api": "api rest integration",
    "giam sat": "monitoring observability audit",
    "trien khai ung dung": "deploy docker kubernetes",
    "lam dep giao dien": "frontend ui design tailwind",
    "cham soc khach hang": "customer support service",
    "cham tien do": "delay milestone schedule audit",
    "toi uu hieu nang": "performance optimization tuning",
    "truy van du lieu": "sql query database postgres",
}


def _char_trigrams(text: str) -> set[str]:
    clean = " ".join(text.lower().split())
    if len(clean) < 3:
        return set()
    return {clean[i : i + 3] for i in range(len(clean) - 2)}


def run_ablation() -> dict[str, Any]:
    records, errs = load_jsonl(EVAL_DIR / "queries.jsonl")
    if errs:
        raise SystemExit(errs[0])
    dev_queries = [r for r in records if r["split"] == "dev"]

    scout = load_scout_module()
    orig_aliases = dict(scout.QUERY_ALIASES)

    with tempfile.TemporaryDirectory() as tmp:
        env = build_eval_environment(pathlib.Path(tmp), seed=42)

        def eval_with_opts(
            *,
            extra_phrases: bool = False,
            diacritic_rerank: bool = False,
            gated_trigram: bool = False,
            min_raw: float = 1.1,
            min_non_name_raw: float = 1.1,
        ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            scout.QUERY_ALIASES = (
                {**orig_aliases, **PHRASE_ALIASES_V3} if extra_phrases else orig_aliases
            )
            orig_min = scout.MIN_SEARCH_RAW_SCORE
            scout.MIN_SEARCH_RAW_SCORE = min_raw
            try:

                def fn(q: str) -> list[str]:
                    _, payload = _run_scout_search(scout, env, q, limit=8)
                    if not payload:
                        return []
                    matches = list(payload.get("ranked_matches", []))
                    if min_non_name_raw > min_raw:
                        q_toks = set(scout.tokenize(q))
                        filtered = []
                        for m in matches:
                            tier = m.get("tier_label", "warehouse")
                            raw = float(m["score"]) - (
                                2.0
                                if tier == "active"
                                else (-0.5 if tier == "inactive" else 0.0)
                            )
                            name_toks = set(scout.tokenize(str(m.get("name") or "")))
                            if (q_toks & name_toks) or raw >= min_non_name_raw:
                                filtered.append(m)
                        matches = filtered
                    if not matches:
                        return []
                    if diacritic_rerank or gated_trigram:
                        q_nfc = unicodedata.normalize("NFC", q.lower())
                        q_tri = _char_trigrams(q_nfc) if gated_trigram else set()
                        rescored = []
                        for m in matches:
                            sc = float(m["score"])
                            if diacritic_rerank:
                                desc_nfc = unicodedata.normalize(
                                    "NFC", str(m.get("description") or "").lower()
                                )
                                if "chậm" in q_nfc and "chậm" in desc_nfc:
                                    sc += 2.0
                                if "chăm" in q_nfc and "chăm" in desc_nfc:
                                    sc += 2.0
                                if "đẹp" in q_nfc and any(
                                    k in desc_nfc
                                    for k in ("design", "ui", "tailwind", "đẹp")
                                ):
                                    sc += 1.0
                            if gated_trigram and q_tri:
                                target_tri = _char_trigrams(
                                    f"{m.get('name', '')} {m.get('description', '')}"
                                )
                                union = len(q_tri | target_tri)
                                if union > 0:
                                    sc += 1.5 * (len(q_tri & target_tri) / union)
                            rescored.append(
                                (sc, str(m.get("id") or m.get("name") or ""))
                            )
                        rescored.sort(key=lambda x: (-x[0], x[1]))
                        return [sid for _, sid in rescored[:5]]
                    return [
                        str(m.get("id") or m.get("name") or "") for m in matches[:5]
                    ]

                return _eval_dev_variant(dev_queries, fn)
            finally:
                scout.MIN_SEARCH_RAW_SCORE = orig_min
                scout.QUERY_ALIASES = orig_aliases

        base_sum, base_rows = eval_with_opts()
        base_mrr = [r["mrr@5"] for r in base_rows if not r["expected_abstain"]]

        configs = {
            "A_phrase_aliases_only": {"extra_phrases": True},
            "B_diacritic_rerank_only": {"diacritic_rerank": True},
            "C_gated_trigram_only": {"gated_trigram": True},
            "D_abstention_non_name_2.0": {"min_non_name_raw": 2.0},
            "E_abstention_min_raw_1.5": {"min_raw": 1.5},
            "F_combined_ABC_D": {
                "extra_phrases": True,
                "diacritic_rerank": True,
                "gated_trigram": True,
                "min_non_name_raw": 2.0,
            },
        }
        report: dict[str, Any] = {"baseline_dev": base_sum, "ablations": {}}
        for label, kw in configs.items():
            summ, rows = eval_with_opts(**kw)
            cand_mrr = [r["mrr@5"] for r in rows if not r["expected_abstain"]]
            diff, lo, hi = paired_bootstrap_ci(base_mrr, cand_mrr, seed=42)
            summ["mrr@5_diff"] = round(diff, 4)
            summ["mrr@5_ci95"] = [round(lo, 4), round(hi, 4)]
            report["ablations"][label] = summ

    out_path = REPO_ROOT / "docs" / "v3" / "SPRINT_GH_ABLATION_DEV.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


if __name__ == "__main__":
    run_ablation()
