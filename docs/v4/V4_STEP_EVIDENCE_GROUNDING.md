# V4 Capability Evidence: Step-Specific Grounding Gate

Baseline: `b10bcc995eb7f17b59d514b898a1b99ce9988a02`, green CI #44659543441.

## Reproduced failure

`verify_capability_evidence()` accepted a verbatim quotation anywhere in any matched SKILL.md as verified, even when the quoted capability did not match the requested plan step. Example: a multi-purpose SKILL.md mentioning Kubernetes and React could promote Kubernetes text as direct evidence for a React UI step. Existing verification proved *source occurrence*, not *step relevance*.

## Research-first candidates

| Candidate | Primary source and license | Runtime and latency trade-off | Decision |
| --- | --- | --- | --- |
| Unicode-aware stdlib `re` content-term overlap, on top of exact quote/heading grounding | [Python Unicode regex HOWTO](https://docs.python.org/3/howto/unicode.html); Python PSF | Zero new deps, linear in bounded quote/step text, cross-platform; lexical only | **Selected as conservative first gate** |
| RapidFuzz fuzzy token similarity | [rapidfuzz/RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), MIT | Fast C++ and pure-Python fallback; extra package and fuzzy overlap can bless semantically irrelevant text | Rejected |
| spaCy NLP pipelines | [explosion/spaCy](https://github.com/explosion/spaCy), MIT | Rich language tooling, substantial native/model dependencies and startup/memory costs; violates zero-dependency invariant | Rejected |

## Implementation and constraints

For each candidate, the exact grounded passage or heading must share at least one nontrivial Unicode-aware content token with the **specific step title/query**. Previously unrelated quotations no longer promote a step to `direct`; no extra file reads are introduced. Existing source verification, 1 MiB cap and symlink checks remain unchanged.

This is intentionally **not semantic proof**. Generic shared words can still create false positives, and translated/paraphrased EN/VI capabilities can produce false negatives. Host inspection and independent human validation remain required. Avoid tuning on sealed/holdout evaluation data. Deterministic tests demonstrate both unrelated-quote rejection and related-quote acceptance; only CI after the final edit qualifies the implementation.
