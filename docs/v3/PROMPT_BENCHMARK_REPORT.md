# Prompt Compiler Benchmark Report (v3)

Dataset: `eval/prompt_cases.jsonl` (15 representative cases, deterministic offline audit).
Token estimator: `chars / 4`.

## Template Comparison Summary

| Template | Completeness | Outcome | Scope | Forbidden | Acceptance | Unverified Labels | Evidence Sep | Clarification | Slop-Free | Mean Chars | Est. Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A: Current compiler.md | 100.00% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 93% | 945.9 | 236.5 |
| B: Outcome/Scope/Constraints/Done | 76.67% | 100% | 100% | 100% | 100% | 47% | 13% | 100% | 100% | 711.3 | 177.8 |
| C: Flat checklist | 75.56% | 100% | 100% | 100% | 100% | 40% | 13% | 93% | 100% | 548.3 | 137.1 |
| D: Evidence-first | 100.00% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 93% | 1000.0 | 250.0 |
| E: Risk-adjusted | 100.00% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 827.8 | 207.0 |

## Model Tier Breakdown (PROMPT-03)

| Template | Reasoning Completeness | Reasoning Tokens | Fast/Weak Completeness | Fast/Weak Tokens |
| --- | ---: | ---: | ---: | ---: |
| A: Current compiler.md | 100.00% | 239.0 | 100.00% | 229.4 |
| B: Outcome/Scope/Constraints/Done | 75.76% | 182.0 | 79.17% | 166.3 |
| C: Flat checklist | 74.24% | 139.2 | 79.17% | 131.3 |
| D: Evidence-first | 100.00% | 254.8 | 100.00% | 236.7 |
| E: Risk-adjusted | 100.00% | 217.5 | 100.00% | 178.0 |

## Key Findings

- **Grounding and contract completeness**: Templates A (`compiler.md`), D (`Evidence-first`), and E (`Risk-adjusted`) achieve 100% contract completeness, preserving all forbidden actions and marking unverified claims/commands explicitly.
- **Compact schemas trade off grounding**: Template B (`Outcome/Scope/Constraints/Done`) and Template C (`Flat checklist`) reduce token footprint, but omitting explicit Observed/Reported/Unverified separation causes grounding trap failures on adversarial cases.
- **Short handoff bloat (PROMPT-10)**: Template D (`Evidence-first`) adds verbose sections even on `fast` track tasks, increasing token footprint without improving completeness over Templates A or E.
- **Model-tier calibration (PROMPT-03)**: Template A adapts output shape to `reasoning` vs `fast_weak` tiers while keeping full contract fidelity, and Template E scales section overhead by risk track.
