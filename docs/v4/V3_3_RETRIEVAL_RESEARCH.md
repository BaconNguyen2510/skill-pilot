# v3.3 Retrieval Research and Dev-Only Ablation

## Objective and invariants

Improve EN / VI / unaccented VI / mixed search without increasing forbidden recommendations. Do not tune on \`eval/queries.jsonl\` holdout. Do not promote synthetic scoring results to semantic capability validation. No external runtime dependencies.

## Research candidates considered (primary sources)

| Candidate | License | Runtime dependencies | Latency / relevance evidence | Decision |
| --- | --- | --- | --- | --- |
| Stdlib field-weighted lexical scorer (BM25F-inspired) | PSF-compatible own implementation | 0 | Requires local measured dev latency and relevance | **Prototype only**, compare with baseline |
| [dorianbrown/rank_bm25](https://github.com/dorianbrown/rank_bm25) | Apache-2.0 | NumPy dependency | No benchmark on this repository's catalog | Reject for runtime dependency; reference BM25 family |
| [xhluca/bm25s](https://github.com/xhluca/bm25s) | Apache-2.0 | NumPy/SciPy family; extra tokenizer requirements | Claims fast sparse retrieval but no verified local head-to-head | Reject for current zero-dependency CLI |
| [BAAI/bge-m3](https://github.com/FlagOpen/FlagEmbedding) | MIT | ML framework and model weights | Potential multilingual semantic retrieval; runtime footprint and model load exceed local CLI design | Reject for default runtime; revisit only as optional adapter |

Alternatives like Reciprocal Rank Fusion can combine rankings but require meaningful independent retrieval streams; fusing only different variants of a shared token index is unlikely to recover unseen bilingual meanings. Vietnamese compound segmentation, prompt-based translation, and BM25+ need independent tests and must be checked for exclusion-scope preservation before integration.

## Reproducible experiment

\`python eval/v4_retrieval_ablation.py\` runs **only** the \`dev\` split of two checked-in datasets:

1. \`eval/v4_dev_snapshot.jsonl\` (80 checked-in dev cases; contains no holdout records).
2. \`eval/dev_v2_challenge.jsonl\` (32 dev adversarial cases).

It compares baseline to three non-production experimental scoring variants: extra name-field weighting, field-frequency/length normalization (BM25F-inspired, *not true corpus-IDF BM25F*), and lower alias contribution.

Outputs: overall and four language-slice MRR@5, Recall@5, nDCG@5, Forbidden@5, Abstention F1, p50/p95 runtime, and an explicit proposed integration gate. A proposed gate is **not** permission to integrate. Results and rejected experiments must be documented after actual execution.

**Gate:** no increase in Forbidden@5 on any language slice, no English MRR@5 or Recall@5 regression, and overall MRR@5 improvement with no recall regression on both dev datasets. If none passes, leave production retrieval unchanged and document the negative result.

## Limitations

This does not independently validate natural-language host translation, real-user intent correctness, or installed third-party skill quality. It is a deterministic lexical search benchmark on synthetic catalogs, not evidence of deployment safety or human relevance judgments.

## Observed initial dev ablation and rejected experiments

Evidence: GitHub Actions #44649502873, commit \`89f7b8b\`, Ubuntu Python 3.14. Only the original evaluator's \`dev\` split was ranked. The harness now uses a physically separate 80-case dev-only snapshot, with no holdout rows.

| Dataset / variant | MRR@5 | Recall@5 | nDCG@5 | Forbidden@5 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 80 dev / baseline | 1.0000 | 0.9375 | 0.9582 | 0.0500 | Control |
| 80 / name-field boost | 1.0000 | 0.9375 | 0.9582 | 0.0500 | Reject: no gain |
| 80 / normalized fields | 1.0000 | 0.9375 | 0.9582 | 0.0375 | Reject: per-language forbidden regression; no relevance gain |
| 80 / alias downweight | 1.0000 | 0.9375 | 0.9582 | 0.0500 | Reject: no gain |
| 32 adversarial / baseline | 0.9500 | 0.9000 | 0.9070 | 0.0625 | Control |
| 32 adversarial / all three trials | 0.9500 | 0.9000 | 0.9070 | 0.0625 | Reject: no gain |

The first-run baseline p50/p95 latency on the GitHub host was 4.495/5.339 ms (80 dev cases) and 3.985/5.542 ms (32 adversarial cases). It is not a controlled hardware benchmark. Abstention F1 was omitted from the initial output; later runs report it.

**Decision:** Keep production ranking unchanged. Near-saturation on the synthetic dev set limits the value of further weight tuning. The next experiment needs independently sourced real queries and labels.
