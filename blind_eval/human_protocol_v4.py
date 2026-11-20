"""Offline blind human-review packet and agreement tools; no human labels generated."""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
from typing import Any

LANGUAGES = frozenset({"en", "vi", "vi_no_diacritic", "mixed"})
FITS = frozenset({"direct", "partial", "none"})
EVIDENCE = frozenset({"verified", "weak", "unsupported"})
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_QUERY_CHARS = 2000
MAX_EXCERPT_CHARS = 2000


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input JSONL exceeds maximum size")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"Expected JSON object at line {line_number}")
            records.append(value)
    return records


def _only_keys(record: dict[str, Any], allowed: set[str]) -> None:
    extra = set(record) - allowed
    if extra:
        raise ValueError(f"Unsupported fields in blind input: {sorted(extra)}")


def build_packets(
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Accept only pre-anonymized queries and score-free candidate evidence."""
    query_map: dict[str, dict[str, Any]] = {}
    for query in queries:
        _only_keys(query, {"query_id", "language", "anonymized_query"})
        key = str(query.get("query_id", "")).strip()
        language = query.get("language")
        content = query.get("anonymized_query")
        if not key or key in query_map or language not in LANGUAGES:
            raise ValueError("Duplicate/invalid query identifier or language")
        if not isinstance(content, str) or not 0 < len(content) <= MAX_QUERY_CHARS:
            raise ValueError("Missing or oversized anonymized query")
        query_map[key] = query

    by_query: dict[str, list[dict[str, str]]] = {key: [] for key in query_map}
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        _only_keys(candidate, {"query_id", "candidate_id", "skill_md_excerpt"})
        key = str(candidate.get("query_id", "")).strip()
        candidate_id = str(candidate.get("candidate_id", "")).strip()
        excerpt = candidate.get("skill_md_excerpt")
        pair = (key, candidate_id)
        if key not in by_query or not candidate_id or pair in seen:
            raise ValueError("Unknown query or duplicate/invalid candidate identifier")
        if not isinstance(excerpt, str) or not 0 < len(excerpt) <= MAX_EXCERPT_CHARS:
            raise ValueError("Missing or oversized skill excerpt")
        seen.add(pair)
        by_query[key].append(
            {"candidate_id": candidate_id, "skill_md_excerpt": excerpt}
        )

    rng = random.Random(seed)
    packets: list[dict[str, Any]] = []
    for key, query in query_map.items():
        skills = sorted(by_query[key], key=lambda item: item["candidate_id"])
        rng.shuffle(skills)
        packets.append(
            {
                "query_id": key,
                "language": query["language"],
                "anonymized_query": query["anonymized_query"],
                "candidate_skills": skills,
            }
        )
    return packets


def cohens_kappa(first: list[str], second: list[str]) -> dict[str, Any]:
    """Unweighted Cohen kappa. Undefined when expected agreement is 1."""
    if len(first) != len(second) or not first:
        raise ValueError("Paired, nonempty label vectors are required")
    count = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / count
    left = collections.Counter(first)
    right = collections.Counter(second)
    expected = sum(
        left[label] * right[label] for label in left.keys() | right.keys()
    ) / (count * count)
    value = (observed - expected) / (1 - expected) if expected < 1 else None
    return {
        "n": count,
        "agreement": round(observed, 6),
        "expected_agreement": round(expected, 6),
        "kappa": round(value, 6) if value is not None else None,
    }


def _validate_annotations(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    allowed = {
        "query_id",
        "candidate_id",
        "language",
        "relevance",
        "capability_fit",
        "evidence_quality",
        "inappropriate",
    }
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        _only_keys(rec, allowed)
        key = (str(rec.get("query_id", "")), str(rec.get("candidate_id", "")))
        relevance = rec.get("relevance")
        if (
            not all(key)
            or key in result
            or rec.get("language") not in LANGUAGES
            or type(relevance) is not int
            or relevance not in range(4)
            or rec.get("capability_fit") not in FITS
            or rec.get("evidence_quality") not in EVIDENCE
            or type(rec.get("inappropriate")) is not bool
        ):
            raise ValueError("Incomplete or invalid human annotation")
        result[key] = rec
    return result


def score_agreement(
    reviewer_a: list[dict[str, Any]],
    reviewer_b: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare independent raters; disagreements await third-party adjudication."""
    left = _validate_annotations(reviewer_a)
    right = _validate_annotations(reviewer_b)
    if not left or left.keys() != right.keys():
        raise ValueError("Reviewers must rate identical nonempty query/candidate pairs")
    keys = sorted(left)
    for key in keys:
        if left[key]["language"] != right[key]["language"]:
            raise ValueError("Language mismatch between reviewers")

    by_language: dict[str, Any] = {}
    for language in LANGUAGES:
        selected = [key for key in keys if left[key]["language"] == language]
        if not selected:
            continue
        relevance_a = [str(left[key]["relevance"] >= 2) for key in selected]
        relevance_b = [str(right[key]["relevance"] >= 2) for key in selected]
        fit_a = [left[key]["capability_fit"] for key in selected]
        fit_b = [right[key]["capability_fit"] for key in selected]
        by_language[language] = {
            "relevance_ge_2": cohens_kappa(relevance_a, relevance_b),
            "capability_fit": cohens_kappa(fit_a, fit_b),
        }

    adjudication = [
        {"query_id": key[0], "candidate_id": key[1]}
        for key in keys
        if (
            left[key]["capability_fit"] != right[key]["capability_fit"]
            or left[key]["inappropriate"] != right[key]["inappropriate"]
            or abs(left[key]["relevance"] - right[key]["relevance"]) >= 2
        )
    ]
    return {
        "status": "synthetic_or_unverified_human_inputs",
        "paired_items": len(keys),
        "by_language": by_language,
        "adjudication_required": adjudication,
        "automatically_adjudicated": False,
    }


def write_once_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline blind evaluation packet and agreement helpers"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    packet = sub.add_parser("packet")
    packet.add_argument("--queries", type=pathlib.Path, required=True)
    packet.add_argument("--candidates", type=pathlib.Path, required=True)
    packet.add_argument("--output", type=pathlib.Path, required=True)
    packet.add_argument("--seed", type=int, default=42)
    agreement = sub.add_parser("agreement")
    agreement.add_argument("--reviewer-a", type=pathlib.Path, required=True)
    agreement.add_argument("--reviewer-b", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "packet":
            rows = build_packets(
                load_jsonl(args.queries),
                load_jsonl(args.candidates),
                seed=args.seed,
            )
            write_once_jsonl(args.output, rows)
            result = {"status": "packet_created", "queries": len(rows)}
        else:
            result = score_agreement(
                load_jsonl(args.reviewer_a), load_jsonl(args.reviewer_b)
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error_code": "HUMAN_EVAL_INPUT_ERROR", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
