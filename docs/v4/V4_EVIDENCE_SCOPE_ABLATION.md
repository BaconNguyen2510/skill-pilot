# V4 Evidence Scope Ablation — Independent Dev Engineering Fixtures

## Baseline and threat

Target baseline is exact commit `642cd144795a0b048eed9221fa45bddbcae7b40f` (the last verified evidence-negation gate). This source correctly rejects *some* negative quoted evidence, but the positive quotation can be contradicted elsewhere in the same SKILL.md; multi-sentence quotations with unrelated limitations can also be downgraded.

The new challenge set is **32 predeclared synthetic engineering cases**, with EN/VI positives, indirect denial, source contradiction, multi-sentence passages and generic-overlap controls. None are user queries, sealed data or human review labels. The cases are intentionally designed to expose known weaknesses. They are **not independent relevance-validation data**.

## Research-first comparison of approaches

| Candidate | Primary source / license | Dependencies / latency / fit | Decision |
| --- | --- | --- | --- |
| Stdlib `re` clause/sentence boundaries with scoped contradiction veto | [Python 3.12 regex specification](https://docs.python.org/3.12/library/re.html), PSF | Zero packages, linear scan of bounded SKILL.md text; expected lower latency than an NLP model, measure rather than assume | **Prototype next**, if measured developer cases improve without regressions |
| [jenojp/negspacy](https://github.com/jenojp/negspacy) NegEx | MIT; `spaCy>=3.8,<4` dependency | Cues and scopes for entities; requires NLP framework and tuning for code skills/VI | Rejected as standard CLI runtime |
| [explosion/spaCy](https://github.com/explosion/spaCy) dependency parsing | MIT; compiled components and model downloads | More expressive parsing, significant installation/latency and Vietnamese setup work | Rejected for zero-dependency rule |
| [rapidfuzz/RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) lexical similarity | MIT, runtime package | Similarity cannot distinguish positive from contradicted statements | Rejected as negation solution |

## Dev-only reproducibility

Run `python eval/v4_evidence_ablation.py` from a full Git checkout. The harness reads *only* `eval/v4_evidence_challenges.jsonl`, stages each synthetic SKILL.md under a temporary directory, and executes the pinned original verifier via `git show 642cd144:skills/skill-pilot/scripts/session_planner.py` alongside the checkout's verifier.

It reports confusion counts (TP/TN/FP/FN), FPR/FNR, category/language slices, median and p95 per-case median latency, and IDs of incorrect engineered cases. Baseline code is pinned to a reviewed commit, not fetched over the network. No sealed queries, holdout examples, or reviewer data are accessed.

**Selection criteria for any future candidate:** reduce synthetic false positives and/or false negatives without worsening the other; record all rejected proposals; retain positive-support checks, correct unrelated-limit handling and exact source grounding. Do not claim true field generalization or independent human validation from this synthetic set.

## Observed pre-change baseline (GitHub Actions #44693126540)

The four-cell Ubuntu/Windows Python 3.12/3.14 matrix passed at `cb75eadb4c9cbf460b8bd29c7f6d5b1c90d1272d`. The harness loaded the pinned verifier from `642cd144` and compared it with an identical production verifier.

| Slice | Synthetic cases | TP | TN | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| Overall | 32 | 12 | 3 | 17 | 0 |
| English | 18 | 7 | 2 | 9 | 0 |
| Vietnamese | 14 | 5 | 1 | 8 | 0 |

The measured baseline false-positive rate was **17/20 = 85% on deliberately adversarial synthetic negatives**, not on real-world traffic. Baseline p50/p95 median-per-case latency in the sampled Ubuntu 3.12 job was 0.1144/0.1270 ms. No real bilingual human judgments were collected. These measurements are an engineering red-team diagnostic only.

## Candidate evaluation rule

The scoped-contradiction candidate must reduce synthetic false positives and/or false negatives **without increasing either on the EN or VI slice**. The dev-only benchmark exits nonzero when this synthetic non-regression/improvement gate fails. It does not authorize release, modify rankings, or grant semantic-evidence status. The final post-change results must be collected from the exact CI commit and recorded rather than projected.

## Observed post-change CI #44693872987

On the 32 synthetic EN/VI engineering cases, pinned baseline FP/FN=17/0 and scoped-verifier FP/FN=0/0 (12 positives preserved). English FP 9→0; Vietnamese FP 8→0. Sampled p50/p95 per-case median latency 0.0407/0.0456→0.0512/0.0672 ms. Four OS/Python CI jobs passed. Synthetic accuracy is not an independent human estimate.
