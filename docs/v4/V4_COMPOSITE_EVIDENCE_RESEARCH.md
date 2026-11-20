# V4 Composite-Step Capability Evidence Research

## Reproduced correctness defect

A plan step can require two distinct capabilities, for example 'Build React UI and PostgreSQL database'. Previously, a quote proving only React UI was accepted as `direct` coverage because it shared lexical tokens with the overall step. When the search query repeated React terms, even the missing database clause could appear sufficiently covered. This is a **plan-evidence integrity** defect, not ranking-quality tuning.

## Research-first alternatives

| Candidate | Primary source / license | Dependencies, latency and fit | Decision |
| --- | --- | --- | --- |
| Python stdlib explicit conjunction split (`and`, `và`, `&`, `+`) and per-clause grounded token checks | [Python 3.12 `re`](https://docs.python.org/3.12/library/re.html); PSF | Zero runtime deps; bounded lexical checks for explicit requirements; no semantic equivalence guarantee | **Selected** |
| [spaCy dependency parser](https://github.com/explosion/spaCy) | MIT; compiled library + model packages | Can resolve more varied clause structure but adds heavy runtime and bilingual model maintenance | Rejected pending reproducible advantage |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) string matching | MIT; extra package | Handles spelling similarity but does not establish separate conjunctive capabilities | Rejected |
| Trust the host LLM's `coverage_level=direct` and a single quote | No new package, host dependent | Fastest but reproduces the unsupported direct-coverage promotion | Rejected |

## Selected contract

- Parse explicitly conjunctive clauses in the **step title**, distinct from the retrieval query, to avoid irrelevant repeated terms masking an unverified requirement. For direct callers, use their `step_text` as the title.
- Verify every quoted passage or exact heading against readable, on-disk, bounded SKILL.md source before accumulating its terms. All required clauses must have sufficient lexical support, including a clause-distinctive term when present.
- Multiple grounded quotes **within the same skill** may jointly cover different clauses. Never combine one quote from a React skill and another from a separate database skill to declare a single skill's direct coverage.
- Do not interpret `or` as conjunction. Opaque tasks without explicit separators retain existing source-grounding behavior.

## Reproducibility and evidence quality

The frozen `eval/v4_composite_challenges.jsonl` contains 16 synthetic engineering dev assertions (8 positive, 8 negative) in EN/VI. `eval/v4_composite_evidence_ablation.py` compares the exact previously verified code SHA `4a38bb2298f2e0ee84920d1ea42646434c08f9ae` to the modified verifier. Only synthetic cases determine the integration gate; hidden/holdout or human labels are never used.

Regression tests include separate-skill non-conflation and a real plan-search callback where `query='react ui'` must not hide a missing PostgreSQL requirement from `title`. Record all confusion counts and p50/p95 latency from the actual four-cell CI, not estimates.

## Known limitations

This is a conservative lexical gate, not natural-language entailment. Ambiguous conjunctions, requirements linked by commas, implicit dependencies, synonyms, inflection/segmentation and different languages remain a review concern. The tool must not claim that a quote proves real capability, runtime safety or successful host-model execution. No main merge, version bump, sealed-data use, or release is authorized.

## Measured post-change verification

At source commit `dbaad6ec5ae8527c6c4e00fb74f87363cb9c751b`, CI #44698892964 passed all four OS/Python jobs. The separate 16-case synthetic composite-step fixture measured **FP/FN 8/0 → 0/0**, preserving all 8 positives. Sampled p95 median-per-case latency changed 0.1654→0.1780 ms on one Ubuntu job. Integration tests also proved that a repeated React query cannot mask a missing PostgreSQL title capability. No human evaluation implied.
