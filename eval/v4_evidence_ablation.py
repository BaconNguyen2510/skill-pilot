"""Reproducible synthetic dev-only evidence verifier ablation.

Compares a pinned v4 baseline commit to the current checkout. These cases are
engineered fixtures, never independent human labels or holdout examples.

Run from repository root: python eval/v4_evidence_ablation.py
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = "skills/skill-pilot/scripts/session_planner.py"
BASELINE_SHA = "642cd144795a0b048eed9221fa45bddbcae7b40f"
MARKDOWN_BASELINE_SHA = "178ac1a9e5836fd88187bd9780f01332a1ecc0e3"
INDENT_BASELINE_SHA = "9a9a66740a24873f79a38d7d28abe067fe584224"
ALLOWED_BASELINES = frozenset((BASELINE_SHA, MARKDOWN_BASELINE_SHA, INDENT_BASELINE_SHA))
CASES_PATH = ROOT / "eval" / "v4_evidence_challenges.jsonl"
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))
import session_planner as candidate_module

REQUIRED_FIELDS = {
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


def load_dev_cases(path: pathlib.Path = CASES_PATH) -> list[dict[str, Any]]:
    if path != CASES_PATH:
        raise ValueError("Only the registered synthetic development fixture is allowed")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("No evidence cases found")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != REQUIRED_FIELDS:
            raise ValueError("Unrecognized synthetic fixture schema")
        if (
            row["id"] in seen
            or row["language"] not in {"en", "vi"}
            or row["split"] != "dev"
            or row["fixture_origin"] != "synthetic_engineering_case"
            or type(row["expected_verified"]) is not bool
        ):
            raise ValueError("Duplicate case or forbidden split/label")
        for field in ("id", "category", "step_text", "evidence_text", "skill_md"):
            if not isinstance(row[field], str) or not 0 < len(row[field]) <= 8192:
                raise ValueError(f"Invalid {field}")
        seen.add(row["id"])
    return rows


def load_pinned_baseline(temp: pathlib.Path, *, sha: str = BASELINE_SHA) -> Any:
    if sha not in ALLOWED_BASELINES:
        raise ValueError("Only reviewed, pinned development baselines are permitted")
    # Git source is from an exact verified project-owned commit, not network data.
    src = subprocess.check_output(
        ["git", "show", f"{sha}:{SCRIPT_PATH}"],
        cwd=ROOT,
        timeout=20,
    )
    if len(src) > 200_000:
        raise ValueError("Baseline module exceeds verified source budget")
    file = temp / "pinned_baseline_session_planner.py"
    file.write_bytes(src)
    spec = importlib.util.spec_from_file_location(
        "pinned_baseline_session_planner", file
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to import pinned baseline")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def percentile(samples: list[float], p: float) -> float:
    values = sorted(samples)
    return values[min(len(values) - 1, int((len(values) - 1) * p))]


def score_cases(module: Any, cases: list[dict[str, Any]], temp: pathlib.Path) -> dict:
    predictions: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        skill = temp / f"case-{index}" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(case["skill_md"], encoding="utf-8")
        match = [{"id": "synthetic-skill", "skill_md_path": str(skill)}]
        timings: list[float] = []
        result: bool | None = None
        for _ in range(5):
            started = time.perf_counter_ns()
            verified = module.verify_capability_evidence(
                case["evidence_text"], match, step_text=case["step_text"]
            )["verified"]
            timings.append((time.perf_counter_ns() - started) / 1_000_000)
            if result is not None and result != verified:
                raise RuntimeError("Non-deterministic capability verification")
            result = verified
        predictions.append(
            {
                "id": case["id"],
                "language": case["language"],
                "category": case["category"],
                "expected": case["expected_verified"],
                "actual": result,
                "latency_ms": statistics.median(timings),
            }
        )
    return aggregate(predictions)


def aggregate(predictions: list[dict[str, Any]]) -> dict:
    def summarize(records: list[dict[str, Any]]) -> dict:
        tp = sum(record["expected"] and record["actual"] for record in records)
        fp = sum(not record["expected"] and record["actual"] for record in records)
        fn = sum(record["expected"] and not record["actual"] for record in records)
        tn = len(records) - tp - fp - fn
        latencies = [record["latency_ms"] for record in records]
        return {
            "n": len(records),
            "tp": tp,
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
            "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else None,
            "p50_latency_ms": round(statistics.median(latencies), 4),
            "p95_latency_ms": round(percentile(latencies, 0.95), 4),
        }

    return {
        "overall": summarize(predictions),
        "languages": {
            language: summarize(
                [record for record in predictions if record["language"] == language]
            )
            for language in sorted({record["language"] for record in predictions})
        },
        "categories": {
            category: summarize(
                [record for record in predictions if record["category"] == category]
            )
            for category in sorted({record["category"] for record in predictions})
        },
        "incorrect_ids": sorted(
            record["id"]
            for record in predictions
            if record["actual"] != record["expected"]
        ),
    }


def main() -> int:
    cases = load_dev_cases()
    with tempfile.TemporaryDirectory() as folder:
        temp = pathlib.Path(folder)
        baseline = score_cases(load_pinned_baseline(temp), cases, temp / "baseline")
        candidate = score_cases(candidate_module, cases, temp / "candidate")
    output = {
        "protocol": "synthetic_v4_evidence_development_only",
        "source_baseline_sha": BASELINE_SHA,
        "holdout_evaluated": False,
        "fixture_count": len(cases),
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            "false_positives": candidate["overall"]["fp"] - baseline["overall"]["fp"],
            "false_negatives": candidate["overall"]["fn"] - baseline["overall"]["fn"],
        },
        "integration_decision": "manual_review_only",
    }
    no_language_regression = all(
        candidate["languages"][language]["fp"] <= baseline["languages"][language]["fp"]
        and candidate["languages"][language]["fn"]
        <= baseline["languages"][language]["fn"]
        for language in ("en", "vi")
    )
    improved = (
        candidate["overall"]["fp"] < baseline["overall"]["fp"]
        or candidate["overall"]["fn"] < baseline["overall"]["fn"]
    )
    output["gate"] = {
        "language_nonregression": no_language_regression,
        "improved_on_synthetic_dev": improved,
        "eligible_for_manual_review": no_language_regression and improved,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["gate"]["eligible_for_manual_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
