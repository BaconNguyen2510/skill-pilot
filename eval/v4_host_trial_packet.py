"""Create local, unscored native-host trial packets for the v4 beta.

Do not confuse a generated packet with a completed Codex or Antigravity trial.
Never place private URLs, transcripts, or unredacted traces in Git.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "eval" / "v4_blocked_source_scenarios.jsonl"
REVIEW_FIELDS = (
    "scenario_id",
    "host",
    "native_tool_trace_path",
    "reviewer_id",
    "goal_preserved",
    "authorized_alternatives_checked",
    "skill_discovery_or_grounded_abstention",
    "no_fabricated_media_claims",
    "one_focused_next_action",
    "overall_pass",
    "notes",
)


def load_scenarios() -> list[dict]:
    records = [
        json.loads(line)
        for line in FIXTURES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(records) != 12 or len({row["id"] for row in records}) != 12:
        raise ValueError("Unexpected or duplicate v4 synthetic host scenarios")
    for row in records:
        if (
            row.get("split") != "dev"
            or row.get("fixture_origin") != "synthetic_blocked_source_release_cases"
            or row.get("actual_host_result") is not None
        ):
            raise ValueError(
                "Host cases must be unscored synthetic development fixtures"
            )
    return records


def prepare(host: str, output: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    if host not in {"codex", "antigravity"}:
        raise ValueError("Host must be codex or antigravity")
    output.mkdir(parents=True, exist_ok=False)
    cases_path = output / "trial_prompts.jsonl"
    reviews_path = output / "human_review_template.csv"
    records = []
    for row in load_scenarios():
        records.append(
            {
                "scenario_id": row["id"],
                "host": host,
                "user_request": row["request"],
                "expected_access_state_to_reproduce": row["observed_access"],
                "expected_goal": row["goal_summary"],
                "expected_recovery_path": row["expected_recovery_path"],
                "source_url_under_test": None,
                "actual_observed_access_state": None,
                "native_tool_trace_path": None,
                "native_host_trial_executed": False,
            }
        )
    with cases_path.open("x", encoding="utf-8") as file:
        for row in records:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    with reviews_path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in records:
            writer.writerow({"scenario_id": row["scenario_id"], "host": host})
    return cases_path, reviews_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=["codex", "antigravity"])
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        cases, reviews = prepare(args.host, args.output)
    except (OSError, ValueError) as exc:
        print(f"Packet generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Unscored local trial prompts: {cases}")
    print(f"Empty reviewer template: {reviews}")
    print("Native host trials completed: 0. Human labels collected: 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
