"""Pure stdlib ranking and statistical evaluation metrics (EVAL-06, EVAL-08)."""

from __future__ import annotations

import math
import random
from collections.abc import Collection, Mapping, Sequence
from typing import Any


def _unique_top_k(ranked_ids: Sequence[str], k: int) -> list[str]:
    """Return up to k unique IDs from ranked_ids while preserving rank order."""
    if k <= 0:
        return []
    seen: set[str] = set()
    top_k: list[str] = []
    for item in ranked_ids[:k]:
        if item not in seen:
            seen.add(item)
            top_k.append(item)
    return top_k


def hit_rate_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Collection[str],
    k: int,
) -> float:
    """Return 1.0 if any relevant ID appears in the top k unique predictions, else 0.0.

    Formula:
        hit_rate@k = 1.0 if |top_k(ranked_ids) & relevant_ids| > 0 else 0.0
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    return (
        1.0
        if any(item in relevant_set for item in _unique_top_k(ranked_ids, k))
        else 0.0
    )


def recall_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Collection[str],
    k: int,
) -> float:
    """Compute fraction of relevant IDs retrieved in the top k unique predictions.

    Formula:
        recall@k = |top_k(ranked_ids) & relevant_ids| / |relevant_ids|
    Returns 0.0 when k <= 0 or relevant_ids is empty.
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    hits = sum(1 for item in _unique_top_k(ranked_ids, k) if item in relevant_set)
    return hits / len(relevant_set)


def mrr_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Collection[str],
    k: int,
) -> float:
    """Compute Mean Reciprocal Rank at k for the first relevant ID in ranked_ids[:k].

    Formula:
        mrr@k = 1.0 / rank_of_first_relevant_item (1-indexed), or 0.0 if none in top k.
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    for rank, item in enumerate(ranked_ids[:k], start=1):
        if item in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_ids: Sequence[str],
    required_ids: Collection[str],
    alternate_ids: Collection[str],
    k: int,
) -> float:
    """Compute Normalized Discounted Cumulative Gain at k with graded relevance.

    Relevance grades:
        required_ids  -> 2
        alternate_ids -> 1
        other         -> 0
    If an ID is present in both collections, grade 2 takes precedence.

    Formula:
        DCG@k  = sum_{i=1..min(k, |top_k|)} (2**rel_i - 1) / log2(i + 1)
        IDCG@k = DCG@k of the ideal descending relevance ordering up to k
        NDCG@k = DCG@k / IDCG@k (0.0 when IDCG@k == 0 or k <= 0)
    """
    if k <= 0:
        return 0.0

    req_set = set(required_ids)
    alt_set = set(alternate_ids) - req_set
    ideal_grades = [2] * len(req_set) + [1] * len(alt_set)
    if not ideal_grades:
        return 0.0

    def _dcg(grades: Sequence[int]) -> float:
        total = 0.0
        for idx, rel in enumerate(grades[:k], start=1):
            if rel > 0:
                total += ((2**rel) - 1) / math.log2(idx + 1)
        return total

    idcg = _dcg(ideal_grades)
    if idcg == 0.0:
        return 0.0

    top_k = _unique_top_k(ranked_ids, k)
    actual_grades = [
        2 if item in req_set else (1 if item in alt_set else 0) for item in top_k
    ]
    return _dcg(actual_grades) / idcg


def precision_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Collection[str],
    k: int,
) -> float:
    """Compute Precision at k over top k unique predictions.

    Formula:
        precision@k = |top_k(ranked_ids) & relevant_ids| / k
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    hits = sum(1 for item in _unique_top_k(ranked_ids, k) if item in relevant_set)
    return hits / k


def forbidden_hit_rate(
    ranked_ids: Sequence[str],
    forbidden_ids: Collection[str],
    k: int,
) -> float:
    """Return 1.0 if any forbidden ID appears in the top k predictions, else 0.0."""
    if k <= 0 or not forbidden_ids:
        return 0.0
    forbidden_set = set(forbidden_ids)
    return 1.0 if any(item in forbidden_set for item in ranked_ids[:k]) else 0.0


def abstention_metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Compute precision, recall, and F1 for abstention predictions.

    Each element in predictions must contain:
        - expected_abstain (bool): ground truth whether the router should abstain.
        - predicted_ids or ranked_ids (Sequence[str]): predicted skills; empty means abstain.
    """
    tp = 0
    fp = 0
    fn = 0
    tn = 0

    for item in predictions:
        expected = bool(item.get("expected_abstain", False))
        predicted_list = item.get("predicted_ids")
        if predicted_list is None:
            predicted_list = item.get("ranked_ids", ())
        predicted_abstain = len(predicted_list) == 0

        if expected and predicted_abstain:
            tp += 1
        elif not expected and predicted_abstain:
            fp += 1
        elif expected and not predicted_abstain:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2.0 * precision * recall) / (precision + recall)
        if (precision + recall) > 0.0
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "support": float(tp + fn),
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "tn": float(tn),
    }


def paired_bootstrap_ci(
    baseline_scores: Sequence[float],
    candidate_scores: Sequence[float],
    n_resamples: int = 1000,
    seed: int = 42,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Compute paired bootstrap mean difference and confidence interval.

    Returns (mean_diff, ci_low, ci_high) where diff = candidate - baseline.
    """
    if len(baseline_scores) != len(candidate_scores):
        raise ValueError("baseline_scores and candidate_scores must have equal length.")
    if not baseline_scores:
        raise ValueError("Score sequences must not be empty.")
    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive.")
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must be strictly between 0 and 1.")

    diffs = [
        float(cand) - float(base)
        for base, cand in zip(baseline_scores, candidate_scores, strict=True)
    ]
    n = len(diffs)
    mean_diff = sum(diffs) / n

    rng = random.Random(seed)
    resample_means = sorted(
        sum(rng.choices(diffs, k=n)) / n for _ in range(n_resamples)
    )

    alpha = 1.0 - confidence
    low_idx = max(0, min(n_resamples - 1, int((alpha / 2.0) * (n_resamples - 1))))
    high_idx = max(
        0, min(n_resamples - 1, math.ceil((1.0 - alpha / 2.0) * (n_resamples - 1)))
    )
    return (mean_diff, resample_means[low_idx], resample_means[high_idx])
