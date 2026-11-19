"""Bounded validation for separate blind-evaluation query and label files.

Lexical overlap screening is a filter, not evidence of annotator independence.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
MAX_CASES = 1000
MAX_EXPOSED_FILES = 8
MAX_EXPOSED_CASES = 4096
MAX_QUERY_CHARS = 512
MAX_FIELD_CHARS = 256
MAX_ID_CHARS = 128
MAX_SKILLS = 128
LANGUAGES = frozenset({"en", "vi", "vi_no_diacritic", "mixed"})
SCHEMA_VERSION = "blind-eval-jsonl/v1"
QUERY_REQUIRED = frozenset(
    {"id", "query", "language", "category", "intent_family", "provenance"}
)
QUERY_OPTIONAL = frozenset({"ambiguity", "difficulty"})
LABEL_REQUIRED = frozenset(
    {
        "id",
        "relevant",
        "forbidden",
        "expected_abstain",
        "annotation_provenance",
        "adjudication_status",
    }
)
PROVENANCE_FIELDS = frozenset({"author", "source", "independence"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


class ContractError(ValueError):
    """Input violates the dataset contract or leakage screen."""


def _reject_constant(_value: str) -> None:
    raise ContractError("Non-finite JSON numbers are not allowed")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("Duplicate JSON object key")
        result[key] = value
    return result


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a bounded UTF-8 JSONL file without interpreting its content as code."""
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise ContractError(f"Cannot read dataset: {type(exc).__name__}") from exc
    if not data or len(data) > MAX_FILE_BYTES:
        raise ContractError("Dataset is empty or exceeds file byte limit")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError("Dataset must be UTF-8") from exc
    lines = text.splitlines()
    if not lines or len(lines) > MAX_CASES:
        raise ContractError("Dataset has no cases or exceeds case limit")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip() or len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ContractError(f"Line {line_number}: empty or exceeds byte limit")
        try:
            record = json.loads(
                line, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
        except (ValueError, RecursionError) as exc:
            raise ContractError(
                f"Line {line_number}: invalid JSON or duplicate key"
            ) from exc
        if not isinstance(record, dict):
            raise ContractError(f"Line {line_number}: expected a JSON object")
        records.append(record)
    return records


def _fields(
    record: dict[str, Any],
    required: frozenset[str],
    optional: frozenset[str],
    line: int,
) -> None:
    keys = set(record)
    if required - keys:
        raise ContractError(f"Line {line}: missing required fields")
    if keys - required - optional:
        raise ContractError(f"Line {line}: unexpected fields")


def _text(value: Any, label: str, line: int, limit: int = MAX_FIELD_CHARS) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError(
            f"Line {line}: {label} must be a non-empty string within its length limit"
        )
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ContractError(f"Line {line}: {label} contains control characters")
    return value


def _identifier(value: Any, label: str, line: int) -> str:
    result = _text(value, label, line, MAX_ID_CHARS)
    if not _ID.fullmatch(result):
        raise ContractError(f"Line {line}: invalid {label} format")
    return result


def _provenance(value: Any, label: str, line: int) -> None:
    if not isinstance(value, dict) or set(value) != PROVENANCE_FIELDS:
        raise ContractError(
            f"Line {line}: {label} requires only author, source and independence"
        )
    for field in PROVENANCE_FIELDS:
        _text(value[field], f"{label}.{field}", line)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    return " ".join(
        "".join(
            c if c.isalnum() else " "
            for c in decomposed
            if not unicodedata.combining(c)
        ).split()
    )


def _features(query: str) -> tuple[str, frozenset[str], frozenset[str]]:
    normalized = _normalized(query)
    if not normalized:
        raise ContractError("Query has no searchable characters")
    tokens = frozenset(normalized.split())
    trigrams = frozenset(
        normalized[i : i + 3] for i in range(max(0, len(normalized) - 2))
    )
    return normalized, tokens, trigrams


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _near_duplicate(
    a: tuple[str, frozenset[str], frozenset[str]],
    b: tuple[str, frozenset[str], frozenset[str]],
) -> bool:
    if a[0] == b[0]:
        return True
    return _overlap(a[1], b[1]) >= 0.9 or _overlap(a[2], b[2]) >= 0.88


def validate_queries(
    path: str | Path, exposed_paths: Iterable[str | Path] = ()
) -> list[dict[str, Any]]:
    """Validate inference-only cases and screen against exposed datasets.

    Prior datasets are read only for ``id``, ``query``, and ``intent_family``;
    validation cannot establish authorship, provenance, or semantic independence.
    """
    records = _read_jsonl(path)
    old_ids: set[str] = set()
    old_families: set[str] = set()
    old_features: list[tuple[str, frozenset[str], frozenset[str]]] = []
    for index, exposed_path in enumerate(exposed_paths):
        if index >= MAX_EXPOSED_FILES:
            raise ContractError("Too many exposed datasets for bounded screening")
        for line, record in enumerate(_read_jsonl(exposed_path), 1):
            if len(old_features) >= MAX_EXPOSED_CASES:
                raise ContractError("Too many exposed cases for bounded screening")
            old_ids.add(_identifier(record.get("id"), "exposed id", line).casefold())
            old_families.add(
                _normalized(
                    _text(record.get("intent_family"), "exposed intent_family", line)
                )
            )
            old_features.append(
                _features(
                    _text(record.get("query"), "exposed query", line, MAX_QUERY_CHARS)
                )
            )

    seen_ids: set[str] = set()
    seen_features: list[tuple[str, frozenset[str], frozenset[str]]] = []
    for line, record in enumerate(records, 1):
        _fields(record, QUERY_REQUIRED, QUERY_OPTIONAL, line)
        case_id = _identifier(record["id"], "id", line).casefold()
        if case_id in seen_ids or case_id in old_ids:
            raise ContractError(f"Line {line}: duplicate or previously exposed case ID")
        seen_ids.add(case_id)
        query = _text(record["query"], "query", line, MAX_QUERY_CHARS)
        if (
            not isinstance(record["language"], str)
            or record["language"] not in LANGUAGES
        ):
            raise ContractError(f"Line {line}: invalid language")
        _text(record["category"], "category", line)
        family = _normalized(_text(record["intent_family"], "intent_family", line))
        if not family or family in old_families:
            raise ContractError(
                f"Line {line}: previously exposed or invalid intent family"
            )
        for optional in QUERY_OPTIONAL & record.keys():
            _text(record[optional], optional, line)
        _provenance(record["provenance"], "provenance", line)
        features = _features(query)
        if any(
            _near_duplicate(features, old) for old in (*seen_features, *old_features)
        ):
            raise ContractError(
                f"Line {line}: duplicate or near-duplicate query detected"
            )
        seen_features.append(features)
    return records


def validate_labels(
    path: str | Path, queries: list[dict[str, Any]], valid_skill_ids: set[str]
) -> list[dict[str, Any]]:
    """Validate finalized labels against the frozen catalog and query IDs."""
    if (
        not isinstance(valid_skill_ids, set)
        or not valid_skill_ids
        or not all(isinstance(s, str) and s for s in valid_skill_ids)
    ):
        raise ContractError("Frozen skill catalog is empty or invalid")
    query_ids: set[str] = set()
    normalized_ids: set[str] = set()
    for line, query in enumerate(queries, 1):
        if not isinstance(query, dict):
            raise ContractError("Invalid query record supplied for label validation")
        case_id = _identifier(query.get("id"), "query id", line)
        if case_id.casefold() in normalized_ids:
            raise ContractError("Duplicate query ID supplied for label validation")
        normalized_ids.add(case_id.casefold())
        query_ids.add(case_id)
    if not query_ids:
        raise ContractError("No query IDs supplied for label validation")

    labels = _read_jsonl(path)
    seen: set[str] = set()
    for line, record in enumerate(labels, 1):
        _fields(record, LABEL_REQUIRED, frozenset(), line)
        case_id = _identifier(record["id"], "id", line)
        if case_id in seen or case_id not in query_ids:
            raise ContractError(f"Line {line}: duplicate or unknown label ID")
        seen.add(case_id)
        for field in ("relevant", "forbidden"):
            values = record[field]
            if not isinstance(values, list) or len(values) > MAX_SKILLS:
                raise ContractError(f"Line {line}: {field} must be a bounded array")
            if not all(
                isinstance(item, str) and item in valid_skill_ids for item in values
            ):
                raise ContractError(
                    f"Line {line}: {field} contains an invalid skill ID"
                )
            if len(values) != len(set(values)):
                raise ContractError(f"Line {line}: {field} contains duplicate IDs")
        if set(record["relevant"]) & set(record["forbidden"]):
            raise ContractError(f"Line {line}: relevant and forbidden labels overlap")
        if not isinstance(record["expected_abstain"], bool):
            raise ContractError(f"Line {line}: expected_abstain must be boolean")
        if record["expected_abstain"] == bool(record["relevant"]):
            raise ContractError(
                f"Line {line}: abstention is inconsistent with relevant labels"
            )
        _provenance(record["annotation_provenance"], "annotation_provenance", line)
        if record["adjudication_status"] != "final":
            raise ContractError(f"Line {line}: adjudication_status must be final")
    if seen != query_ids:
        raise ContractError("Label IDs do not cover all query IDs")
    return labels
