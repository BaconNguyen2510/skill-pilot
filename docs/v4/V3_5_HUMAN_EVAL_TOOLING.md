# v3.5 Human Evaluation Tooling (V4 Development)

Status: **tooling only; no independent human evaluation performed**.

This feature implements a blind packet generator and independent rater agreement scorer. It implements the roles and dimensions specified in `docs/v3.1/HUMAN_EVAL_PROTOCOL_V3_1.md`: two bilingual independent annotators, separate adjudicator, relevance, capability fit, evidence quality, unsafe recommendations, and flags for inappropriate recommendations. It does **not** create judgments or claim that synthetic fixtures constitute human labels.

## Research-first choices

| Approach | License and dependencies | Fit, performance trade-off | Decision |
| --- | --- | --- | --- |
| Python 3.12+ stdlib counters/formula | PSF; no external dependencies | Exact unweighted Cohen kappa, negligible cost at human-review packet scales | **Selected** |
| [scikit-learn cohen_kappa_score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html) | BSD-3-Clause; NumPy/SciPy and scikit-learn | Mature API, heavyweight for this small offline check | Rejected for zero-dependency helper |
| [statsmodels cohens_kappa](https://www.statsmodels.org/stable/generated/statsmodels.stats.inter_rater.cohens_kappa.html) | BSD-3-Clause; NumPy/SciPy and statsmodels | Strong broader statistics, extra installation/runtime | Rejected as unnecessary |
| [Krippendorff alpha implementation](https://pypi.org/project/krippendorff/) | Python package plus numerical stack; check exact package license | Useful for >2 raters/missing observations, different requested measure | Rejected for this two-rater protocol |

No timing benchmark was claimed; for simple counter operations and small human packets, runtime dependencies add avoidable operational cost.

## CLI

Run from the repository root:

```bash
python blind_eval/human_protocol_v4.py packet --queries anonymized_queries.jsonl --candidates score_free_candidates.jsonl --output protected_blind_packets.jsonl
python blind_eval/human_protocol_v4.py agreement --reviewer-a reviewer_a.jsonl --reviewer-b reviewer_b.jsonl
```

**Query schema:** `{"query_id":"q1","language":"vi","anonymized_query":"..."}`. Anonymization must be performed and checked by the evaluator; this tool only validates field shape and bounds. Do not supply raw private user requests.

**Candidate schema:** `{"query_id":"q1","candidate_id":"skill-1","skill_md_excerpt":"..."}`. Retrieval scores, method identities, labels, and AI assessments are rejected as unexpected fields. Candidate list order is deterministically shuffled within a packet.

**Rater schema:** `query_id`, `candidate_id`, `language`, `relevance` (0–3), `capability_fit` (`direct|partial|none`), `evidence_quality` (`verified|weak|unsupported`), and `inappropriate` (boolean).

The scorer requires the exact same query/candidate pairs in both independent annotation files. It computes per-language percentage agreement and Cohen kappa for relevance >= 2 and capability fit. Undefined kappa (both marginals constant) is reported as `null`, not 1. Capability-fit disagreement, unsafe disagreement, or relevance difference >=2 is queued for separate adjudication. No adjudication occurs automatically.

**Custody:** Keep real labels and sealed datasets in access-controlled external storage. Do not commit independent reviewer outputs to this public repository. The CLI tests use synthetic fixtures only. Agree on sampling, adjudicator independence, pre-registration and final thresholds before collecting data. The tool is not proof of evaluator independence.

## Remaining work

Add support for *missing capabilities* in a future optional reviewer schema and independently assess evidence-quality disagreement, while preserving backward-compatible packets. Arrange actual external bilingual annotators; score their outputs only after they complete blind review. Native host model test comparisons are also still needed.
