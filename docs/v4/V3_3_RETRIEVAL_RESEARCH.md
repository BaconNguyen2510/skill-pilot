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

1. \`eval/queries.jsonl\` (80 dev cases; the 48 holdout cases are excluded by the existing evaluator).
2. \`eval/dev_v2_challenge.jsonl\` (32 dev adversarial cases).

It compares baseline to three non-production experimental scoring variants: extra name-field weighting, field-frequency/length normalization (BM25F-inspired, *not true corpus-IDF BM25F*), and lower alias contribution.

Outputs: overall and four language-slice MRR@5, Recall@5, nDCG@5, Forbidden@5; abstention metrics from the underlying evaluator, p50/p95 runtime, and an explicit proposed integration gate. A proposed gate is **not** permission to integrate. Results and rejected experiments must be documented after actual execution.

**Gate:** no increase in Forbidden@5 on any language slice, no English MRR@5 or Recall@5 regression, and overall MRR@5 improvement with no recall regression on both dev datasets. If none passes, leave production retrieval unchanged and document the negative result.

## Limitations

This does not independently validate natural-language host translation, real-user intent correctness, or installed third-party skill quality. It is a deterministic lexical search benchmark on synthetic catalogs, not evidence of deployment safety or human relevance judgments.
