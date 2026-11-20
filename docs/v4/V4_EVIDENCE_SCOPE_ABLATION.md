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

Initial metrics must be populated only from actual GitHub Actions after this harness commit; no numerical improvements are claimed before the run.
