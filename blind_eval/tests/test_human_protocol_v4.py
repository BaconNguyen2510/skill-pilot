"""Synthetic human-review fixtures; never represent actual human judgments."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blind_eval"))
import human_protocol_v4 as protocol


def annotation(
    qid: str,
    cid: str,
    relevance: int,
    fit: str,
    *,
    language: str = "en",
    inappropriate: bool = False,
) -> dict:
    return {
        "query_id": qid,
        "candidate_id": cid,
        "language": language,
        "relevance": relevance,
        "capability_fit": fit,
        "evidence_quality": "verified",
        "inappropriate": inappropriate,
    }


class SyntheticHumanProtocolTests(unittest.TestCase):
    def test_kappa_matches_known_manual_result(self) -> None:
        result = protocol.cohens_kappa(
            ["direct", "direct", "partial", "none"],
            ["direct", "partial", "partial", "none"],
        )
        self.assertEqual(result["agreement"], 0.75)
        self.assertAlmostEqual(result["kappa"], 0.636364, places=5)

    def test_kappa_undefined_when_both_marginals_constant(self) -> None:
        result = protocol.cohens_kappa(["direct"] * 3, ["direct"] * 3)
        self.assertIsNone(result["kappa"])
        self.assertEqual(result["agreement"], 1.0)

    def test_packet_generator_drops_no_scores_because_it_rejects_them(self) -> None:
        queries = [{"query_id": "q1", "language": "vi", "anonymized_query": "Làm UI"}]
        candidates = [
            {
                "query_id": "q1",
                "candidate_id": "ui",
                "skill_md_excerpt": "# UI",
            }
        ]
        packet = protocol.build_packets(queries, candidates)
        self.assertEqual(len(packet), 1)
        self.assertNotIn("score", str(packet))
        with self.assertRaises(ValueError):
            protocol.build_packets(queries, [{**candidates[0], "retrieval_score": 99}])

    def test_reviewer_agreement_flags_disagreement_without_adjudication(self) -> None:
        first = [
            annotation("q1", "ui", 3, "direct"),
            annotation("q2", "db", 2, "partial"),
        ]
        second = [
            annotation("q1", "ui", 1, "none"),
            annotation("q2", "db", 2, "partial"),
        ]
        scored = protocol.score_agreement(first, second)
        self.assertEqual(scored["paired_items"], 2)
        self.assertEqual(
            scored["adjudication_required"],
            [{"query_id": "q1", "candidate_id": "ui"}],
        )
        self.assertFalse(scored["automatically_adjudicated"])

    def test_agreement_refuses_missing_and_duplicate_labels(self) -> None:
        records = [annotation("q1", "ui", 3, "direct")]
        with self.assertRaises(ValueError):
            protocol.score_agreement(records, [])
        with self.assertRaises(ValueError):
            protocol.score_agreement(records + records, records)

    def test_agreement_reports_evidence_safety_and_full_scale(self) -> None:
        first = [
            annotation("q1", "ui", 3, "direct", language="en"),
            annotation("q2", "ui", 1, "none", language="vi"),
        ]
        second = [
            annotation("q1", "ui", 3, "direct", language="en"),
            annotation("q2", "ui", 1, "none", language="vi"),
        ]
        second[1]["evidence_quality"] = "weak"
        second[1]["inappropriate"] = True
        scored = protocol.score_agreement(first, second)
        self.assertEqual(scored["paired_items"], 2)
        self.assertIn("relevance", scored["overall"])
        self.assertIn("evidence_quality", scored["overall"])
        self.assertIn("inappropriate", scored["overall"])
        self.assertIn("evidence_quality", scored["by_language"]["vi"])
        self.assertEqual(
            scored["adjudication_required"],
            [{"query_id": "q2", "candidate_id": "ui"}],
        )
        self.assertFalse(scored["missing_capability_annotated"])

    def test_missing_capability_labels_must_be_complete_and_paired(self) -> None:
        first = [
            annotation("q1", "ui", 3, "direct"),
            annotation("q2", "db", 1, "none"),
        ]
        second = [
            annotation("q1", "ui", 3, "direct"),
            annotation("q2", "db", 1, "none"),
        ]
        first[0]["missing_capability"] = False
        with self.assertRaisesRegex(ValueError, "must be complete"):
            protocol.score_agreement(first, second)
        for ratings in (first, second):
            for rating in ratings:
                rating["missing_capability"] = rating["capability_fit"] == "none"
        scored = protocol.score_agreement(first, second)
        self.assertTrue(scored["missing_capability_annotated"])
        self.assertIn("missing_capability", scored["overall"])

        second[1]["missing_capability"] = False
        scored = protocol.score_agreement(first, second)
        self.assertIn(
            {"query_id": "q2", "candidate_id": "db"},
            scored["adjudication_required"],
        )

    def test_missing_capability_rejects_non_boolean_labels(self) -> None:
        first = annotation("q1", "ui", 3, "direct")
        first["missing_capability"] = "false"
        with self.assertRaisesRegex(ValueError, "invalid human annotation"):
            protocol.score_agreement([first], [first])

    def test_packet_generator_refuses_empty_query_sample(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            protocol.build_packets([], [])

    def test_failed_packet_publication_leaves_no_partial_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            path = folder / "packet.jsonl"
            with (
                mock.patch.object(
                    protocol.os, "link", side_effect=OSError("synthetic link failure")
                ),
                self.assertRaisesRegex(OSError, "synthetic link failure"),
            ):
                protocol.write_once_jsonl(path, [{"query_id": "q1"}])
            self.assertFalse(path.exists())
            self.assertEqual(list(folder.glob("*.tmp")), [])
            protocol.write_once_jsonl(path, [{"query_id": "q1"}])
            self.assertEqual(protocol.load_jsonl(path), [{"query_id": "q1"}])

    def test_concurrent_packet_writers_publish_exactly_one_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            path = folder / "packet.jsonl"
            ready = threading.Barrier(2)
            results: list[str] = []

            def writer(qid: str) -> None:
                ready.wait(timeout=5)
                try:
                    protocol.write_once_jsonl(path, [{"query_id": qid}])
                    results.append("created")
                except FileExistsError:
                    results.append("exists")

            threads = [
                threading.Thread(target=writer, args=(label,)) for label in ("q1", "q2")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            self.assertCountEqual(results, ["created", "exists"])
            self.assertIn(
                protocol.load_jsonl(path),
                [[{"query_id": "q1"}], [{"query_id": "q2"}]],
            )
            self.assertEqual(list(folder.glob("*.tmp")), [])

    def test_write_once_will_not_overwrite_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "packet.jsonl"
            protocol.write_once_jsonl(path, [{"query_id": "q1"}])
            with self.assertRaises(FileExistsError):
                protocol.write_once_jsonl(path, [{"query_id": "q2"}])


if __name__ == "__main__":
    unittest.main()
