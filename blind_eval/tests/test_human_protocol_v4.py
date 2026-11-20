"""Synthetic human-review fixtures; never represent actual human judgments."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

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

    def test_write_once_will_not_overwrite_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "packet.jsonl"
            protocol.write_once_jsonl(path, [{"query_id": "q1"}])
            with self.assertRaises(FileExistsError):
                protocol.write_once_jsonl(path, [{"query_id": "q2"}])


if __name__ == "__main__":
    unittest.main()
