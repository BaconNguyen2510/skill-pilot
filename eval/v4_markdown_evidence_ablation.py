"""Dev-only Markdown evidence provenance check, using a pinned pre-change verifier.

All examples are synthetic engineering specifications, NOT human labels.
Run: python eval/v4_markdown_evidence_ablation.py
"""

from __future__ import annotations

import json
import pathlib
import tempfile

from v4_evidence_ablation import (
    MARKDOWN_BASELINE_SHA,
    load_pinned_baseline,
    score_cases,
)
from v4_evidence_ablation import candidate_module as current

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "eval" / "v4_markdown_evidence_challenges.jsonl"


def load_cases() -> list[dict]:
    cases = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) != 16 or len({item["id"] for item in cases}) != 16:
        raise ValueError("Unexpected synthetic Markdown fixture count/IDs")
    for item in cases:
        if (
            item["split"] != "dev"
            or item["fixture_origin"] != "synthetic_markdown_source"
            or item["language"] != "en"
            or type(item["expected_verified"]) is not bool
        ):
            raise ValueError("Non-development or invalid Markdown fixture")
    return cases


def main() -> int:
    cases = load_cases()
    with tempfile.TemporaryDirectory() as folder:
        temp = pathlib.Path(folder)
        old = load_pinned_baseline(temp, sha=MARKDOWN_BASELINE_SHA)
        before = score_cases(old, cases, temp / "baseline")
        after = score_cases(current, cases, temp / "candidate")
    result = {
        "protocol": "synthetic_dev_markdown_evidence_only",
        "baseline_sha": MARKDOWN_BASELINE_SHA,
        "holdout_evaluated": False,
        "fixture_count": len(cases),
        "baseline": before,
        "candidate": after,
        "delta": {
            "false_positives": after["overall"]["fp"] - before["overall"]["fp"],
            "false_negatives": after["overall"]["fn"] - before["overall"]["fn"],
        },
        "review_status": "manual_review_only",
    }
    nonregression = (
        after["overall"]["fp"] <= before["overall"]["fp"]
        and after["overall"]["fn"] <= before["overall"]["fn"]
    )
    improvement = (
        after["overall"]["fp"] < before["overall"]["fp"]
        or after["overall"]["fn"] < before["overall"]["fn"]
    )
    result["gate"] = {
        "synthetic_nonregression": nonregression,
        "synthetic_improvement": improvement,
        "eligible_for_manual_review": nonregression and improvement,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["gate"]["eligible_for_manual_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
