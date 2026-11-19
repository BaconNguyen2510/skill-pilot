"""Synthetic fixtures only: do not use these cases as final evaluation data."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blind_eval.contract import (
    MAX_FILE_BYTES,
    ContractError,
    validate_labels,
    validate_queries,
)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.provenance = {
            "author": "synthetic",
            "source": "fixture",
            "independence": "synthetic only",
        }
        self.query = {
            "id": "synthetic-001",
            "query": "Design a household energy dashboard",
            "language": "en",
            "category": "ui",
            "intent_family": "synthetic-energy-ui",
            "provenance": self.provenance,
        }
        self.label = {
            "id": "synthetic-001",
            "relevant": ["ui-skill"],
            "forbidden": ["other-skill"],
            "expected_abstain": False,
            "annotation_provenance": self.provenance,
            "adjudication_status": "final",
        }
        self.catalog = {"ui-skill", "other-skill"}

    def write(self, name: str, *records: dict) -> Path:
        path = self.root / name
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        return path

    def test_accepts_valid_separated_files(self) -> None:
        queries = validate_queries(self.write("queries.jsonl", self.query))
        labels = validate_labels(
            self.write("labels.jsonl", self.label), queries, self.catalog
        )
        self.assertEqual(queries, [self.query])
        self.assertEqual(labels, [self.label])
        self.assertNotIn("relevant", queries[0])
        self.assertNotIn("query", labels[0])

    def test_accepts_valid_abstention(self) -> None:
        label = {**self.label, "relevant": [], "expected_abstain": True}
        self.assertEqual(
            validate_labels(
                self.write("labels.jsonl", label), [self.query], self.catalog
            ),
            [label],
        )

    def test_rejects_missing_empty_oversize_and_non_utf8(self) -> None:
        with self.assertRaises(ContractError):
            validate_queries(self.root / "missing")
        path = self.root / "data.jsonl"
        for content in (b"", b"\xff", b"x" * (MAX_FILE_BYTES + 1)):
            path.write_bytes(content)
            with (
                self.subTest(content_length=len(content)),
                self.assertRaises(ContractError),
            ):
                validate_queries(path)

    def test_rejects_bad_json_duplicate_keys_and_nonfinite_numbers(self) -> None:
        path = self.root / "bad.jsonl"
        for raw in ('{"id":', '{"id":"one","id":"two"}', '{"x":NaN}', "[]", "\n"):
            path.write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                validate_queries(path)

    def test_rejects_excessive_nesting_long_lines_and_case_flood(self) -> None:
        path = self.root / "bad.jsonl"
        path.write_text('{"x":' + "[" * 2000 + "0" + "]" * 2000 + "}", encoding="utf-8")
        with self.assertRaises(ContractError):
            validate_queries(path)
        path.write_text('{"x":"' + "a" * 17000 + '"}', encoding="utf-8")
        with self.assertRaises(ContractError):
            validate_queries(path)
        path.write_text("{}\n" * 1001, encoding="utf-8")
        with self.assertRaises(ContractError):
            validate_queries(path)

    def test_rejects_unexpected_fields_and_invalid_queries(self) -> None:
        for change in (
            {"answer": ["ui-skill"]},
            {"id": "../bad"},
            {"query": " "},
            {"query": "x" * 513},
            {"query": "!!!"},
            {"language": "fr"},
            {"language": []},
            {"category": ""},
            {"provenance": {}},
            {"provenance": {**self.provenance, "secret": "extra"}},
        ):
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_queries(self.write("bad.jsonl", {**self.query, **change}))
        missing = dict(self.query)
        del missing["query"]
        with self.assertRaises(ContractError):
            validate_queries(self.write("bad.jsonl", missing))

    def test_rejects_duplicate_ids_and_near_duplicate_queries(self) -> None:
        second = {**self.query, "query": "Summarize the annual population survey"}
        with self.assertRaises(ContractError):
            validate_queries(self.write("queries.jsonl", self.query, second))
        second = {
            **self.query,
            "id": "synthetic-002",
            "query": "design a household energy dashboard!",
        }
        with self.assertRaises(ContractError):
            validate_queries(self.write("queries.jsonl", self.query, second))
        second["query"] = "Design a household energy dashboards"
        with self.assertRaises(ContractError):
            validate_queries(self.write("queries.jsonl", self.query, second))

    def test_exposed_id_family_exact_and_near_query_are_rejected(self) -> None:
        prior = {
            "id": "old-1",
            "query": "Survey bird populations in urban gardens",
            "intent_family": "old-family",
        }
        exposed = self.write("exposed.jsonl", prior)
        for change in (
            {"id": "old-1"},
            {"intent_family": "old_family"},
            {"query": "survey bird populations in urban gardens!"},
            {"query": "Survey bird populations in urban garden"},
        ):
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_queries(
                    self.write("queries.jsonl", {**self.query, **change}), [exposed]
                )
        self.assertEqual(
            validate_queries(self.write("queries.jsonl", self.query), [exposed]),
            [self.query],
        )

    def test_missing_or_corrupt_exposed_dataset_fails_closed(self) -> None:
        queries = self.write("queries.jsonl", self.query)
        with self.assertRaises(ContractError):
            validate_queries(queries, [self.root / "missing"])
        exposed = self.write("exposed.jsonl", {"id": "old"})
        with self.assertRaises(ContractError):
            validate_queries(queries, [exposed])

    def test_synthetic_case_screened_against_all_exposed_datasets(self) -> None:
        root = Path(__file__).resolve().parents[2]
        exposed = [
            root / "eval" / name
            for name in (
                "queries.jsonl",
                "dev_v2_challenge.jsonl",
            )
        ]
        self.assertTrue(all(path.is_file() for path in exposed))
        self.assertFalse((root / "eval" / "sealed_queries.jsonl").exists())
        self.assertEqual(
            validate_queries(self.write("synthetic.jsonl", self.query), exposed),
            [self.query],
        )

    def test_invalid_or_conflicting_labels_rejected(self) -> None:
        for change in (
            {"relevant": ["unknown"]},
            {"relevant": ["ui-skill", "ui-skill"]},
            {"forbidden": ["ui-skill"]},
            {"expected_abstain": True},
            {"relevant": []},
            {"expected_abstain": 1},
            {"id": "unknown"},
            {"adjudication_status": "pending"},
            {"annotation_provenance": {"author": "synthetic"}},
            {"unexpected": True},
        ):
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_labels(
                    self.write("labels.jsonl", {**self.label, **change}),
                    [self.query],
                    self.catalog,
                )

    def test_missing_extra_and_duplicate_labels_fail_closed(self) -> None:
        second = {**self.query, "id": "synthetic-002", "query": "Summarize weather"}
        with self.assertRaises(ContractError):
            validate_labels(
                self.write("labels.jsonl", self.label),
                [self.query, second],
                self.catalog,
            )
        with self.assertRaises(ContractError):
            validate_labels(
                self.write("labels.jsonl", self.label, self.label),
                [self.query],
                self.catalog,
            )
        with self.assertRaises(ContractError):
            validate_labels(self.write("labels.jsonl", self.label), [self.query], set())

    def test_final_label_content_never_allowed_in_query_input(self) -> None:
        with self.assertRaises(ContractError):
            validate_queries(
                self.write("queries.jsonl", {**self.query, "relevant": ["ui-skill"]})
            )


if __name__ == "__main__":
    unittest.main()
