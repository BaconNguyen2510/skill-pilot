"""Validate gold evaluation queries against EVAL-01 and EVAL-04 invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "query",
    "language",
    "domain",
    "split",
    "intent_family",
    "required_skills",
    "acceptable_alternates",
    "forbidden_skills",
    "ambiguity_tags",
    "expected_abstain",
    "expected_skill_count",
)

VALID_LANGUAGES: frozenset[str] = frozenset({"en", "vi", "vi_no_diacritic", "mixed"})
VALID_SPLITS: frozenset[str] = frozenset({"dev", "holdout"})
STRING_FIELDS: tuple[str, ...] = ("id", "query", "domain", "intent_family")
STRING_LIST_FIELDS: tuple[str, ...] = (
    "required_skills",
    "acceptable_alternates",
    "forbidden_skills",
    "ambiguity_tags",
)


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_empty_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_str(item) for item in value)


def validate_record(record: dict[str, Any], line_no: int | None = None) -> list[str]:
    """Validate a single gold query record and return a list of error messages."""
    prefix = f"Line {line_no}: " if line_no is not None else ""
    if not isinstance(record, dict):
        return [f"{prefix}Record must be a JSON object."]

    errors: list[str] = []

    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        errors.append(f"{prefix}Missing required fields: {', '.join(missing)}.")
        return errors

    unknown = sorted(set(record.keys()) - set(REQUIRED_FIELDS))
    if unknown:
        errors.append(f"{prefix}Unexpected fields: {', '.join(unknown)}.")

    for field in STRING_FIELDS:
        if not _is_non_empty_str(record[field]):
            errors.append(f"{prefix}Field '{field}' must be a non-empty string.")

    if record["language"] not in VALID_LANGUAGES:
        allowed = ", ".join(sorted(VALID_LANGUAGES))
        errors.append(
            f"{prefix}Invalid language {record['language']!r}; expected one of: {allowed}."
        )

    if record["split"] not in VALID_SPLITS:
        allowed = ", ".join(sorted(VALID_SPLITS))
        errors.append(
            f"{prefix}Invalid split {record['split']!r}; expected one of: {allowed}."
        )

    for field in STRING_LIST_FIELDS:
        if not _is_non_empty_str_list(record[field]):
            errors.append(
                f"{prefix}Field '{field}' must be a list of non-empty strings."
            )

    if not isinstance(record["expected_abstain"], bool):
        errors.append(f"{prefix}Field 'expected_abstain' must be a boolean.")

    skill_count = record["expected_skill_count"]
    if (
        isinstance(skill_count, bool)
        or not isinstance(skill_count, int)
        or skill_count < 0
    ):
        errors.append(
            f"{prefix}Field 'expected_skill_count' must be a non-negative integer."
        )

    if errors:
        return errors

    req_set = set(record["required_skills"])
    alt_set = set(record["acceptable_alternates"])
    forb_set = set(record["forbidden_skills"])

    req_alt = sorted(req_set & alt_set)
    if req_alt:
        errors.append(
            f"{prefix}Overlap between required_skills and acceptable_alternates: {', '.join(req_alt)}."
        )

    req_forb = sorted(req_set & forb_set)
    if req_forb:
        errors.append(
            f"{prefix}Overlap between required_skills and forbidden_skills: {', '.join(req_forb)}."
        )

    alt_forb = sorted(alt_set & forb_set)
    if alt_forb:
        errors.append(
            f"{prefix}Overlap between acceptable_alternates and forbidden_skills: {', '.join(alt_forb)}."
        )

    if record["expected_abstain"] and record["required_skills"]:
        errors.append(
            f"{prefix}expected_abstain=True requires required_skills to be empty."
        )

    return errors


def validate_records(records: list[dict[str, Any]]) -> list[str]:
    """Validate a collection of gold query records including cross-split leakage."""
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    intent_splits: dict[str, set[str]] = {}

    for idx, record in enumerate(records, start=1):
        record_errors = validate_record(record, line_no=idx)
        errors.extend(record_errors)
        if record_errors:
            continue

        query_id = record["id"]
        if query_id in seen_ids:
            errors.append(
                f"Line {idx}: Duplicate query id {query_id!r} (first seen at line {seen_ids[query_id]})."
            )
        else:
            seen_ids[query_id] = idx

        intent = record["intent_family"]
        intent_splits.setdefault(intent, set()).add(record["split"])

    leaked_intents = sorted(
        intent for intent, splits in intent_splits.items() if len(splits) > 1
    )
    for intent in leaked_intents:
        errors.append(
            f"Split leakage detected: intent_family {intent!r} appears in both dev and holdout."
        )

    return errors


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load records from a JSONL file, returning parsed records and parse errors."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    if not path.is_file():
        return records, [f"Evaluation file not found: {path}"]

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_no}: Invalid JSON ({exc.msg}).")
                continue
            if not isinstance(parsed, dict):
                errors.append(f"Line {line_no}: Expected a JSON object.")
                continue
            records.append(parsed)

    return records, errors


def validate_file(path: Path) -> list[str]:
    """Load and validate a JSONL evaluation file."""
    records, parse_errors = load_jsonl(path)
    if parse_errors:
        return parse_errors
    if not records:
        return [f"Evaluation file contains no records: {path}"]
    return validate_records(records)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for validating eval/queries.jsonl."""
    parser = argparse.ArgumentParser(
        description="Validate Skill Pilot gold evaluation queries."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("eval/queries.jsonl"),
        help="Path to the JSONL evaluation file (default: eval/queries.jsonl).",
    )
    args = parser.parse_args(argv)

    errors = validate_file(args.path)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"OK: {args.path} passed all validation checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
