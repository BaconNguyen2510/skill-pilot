"""Dev-only raw HTML evidence ablation; no holdout/human labels."""

from __future__ import annotations

import json
import pathlib
import tempfile

from v4_evidence_ablation import (
    RAW_HTML_BASELINE_SHA,
    candidate_module,
    load_pinned_baseline,
    score_cases,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "eval" / "v4_raw_html_challenges.jsonl"


def load_cases() -> list[dict]:
    rows = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 16 or len({r["id"] for r in rows}) != 16:
        raise ValueError("Unexpected synthetic raw HTML fixture count/IDs")
    expected_keys = {
        "id",
        "language",
        "category",
        "step_text",
        "evidence_text",
        "skill_md",
        "expected_verified",
        "split",
        "fixture_origin",
    }
    for row in rows:
        if (
            set(row) != expected_keys
            or row["split"] != "dev"
            or row["fixture_origin"] != "synthetic_raw_html"
            or row["language"] not in {"en", "vi"}
            or type(row["expected_verified"]) is not bool
        ):
            raise ValueError("Invalid, non-development or non-synthetic case")
    return rows


def main() -> int:
    cases = load_cases()
    with tempfile.TemporaryDirectory() as folder:
        temporary = pathlib.Path(folder)
        before = score_cases(
            load_pinned_baseline(temporary, sha=RAW_HTML_BASELINE_SHA),
            cases,
            temporary / "baseline",
        )
        after = score_cases(candidate_module, cases, temporary / "candidate")
    before_total, after_total = before["overall"], after["overall"]
    nonregression = all(
        after["languages"][language][metric] <= before["languages"][language][metric]
        for language in ("en", "vi")
        for metric in ("fp", "fn")
    )
    improvement = (
        after_total["fp"] < before_total["fp"] or after_total["fn"] < before_total["fn"]
    )
    result = {
        "protocol": "synthetic_dev_raw_html_only",
        "baseline_sha": RAW_HTML_BASELINE_SHA,
        "holdout_evaluated": False,
        "fixture_count": len(cases),
        "baseline": before,
        "candidate": after,
        "delta": {
            "false_positives": after_total["fp"] - before_total["fp"],
            "false_negatives": after_total["fn"] - before_total["fn"],
        },
        "gate": {
            "language_nonregression": nonregression,
            "improved_on_synthetic_dev": improvement,
            "eligible_for_manual_review": nonregression and improvement,
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if nonregression and improvement else 1


if __name__ == "__main__":
    raise SystemExit(main())
