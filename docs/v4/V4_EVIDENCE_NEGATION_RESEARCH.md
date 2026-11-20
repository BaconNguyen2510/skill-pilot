# V4 Evidence Negation and Generic-Term Adversarial Gate

Baseline: `7cf282f591c7c6b4bbb4f5b7061672108fe80670`, CI #44660479436 green (4/4).

## Concrete source-level defects

The lexical gate accepted exact negative passages such as `Does not support React UI components.` as proof of direct React UI capability because of shared `React`/`UI` tokens. A heading `React UI components are not supported` could likewise pass as direct evidence. The token `Build` was not a stopword, so `Build Kubernetes deployment manifests.` could support an unrelated `Build React UI` step solely by that generic verb.

## Primary-source candidates and tradeoffs

| Option | License and dependency | Performance/fit | Outcome |
| --- | --- | --- | --- |
| Python 3.12+ stdlib Unicode `re`, explicit bounded denial patterns + generic-term filter | PSF, no new dependency | O(text) per bounded evidence span; Windows/Linux, EN/VI; conservative false negatives | **Selected** |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) approximate matching | MIT, third-party package / native or Python fallback | Efficient string similarity but cannot distinguish `supports` from `does not support`; introduces dependency | Rejected |
| [spaCy](https://github.com/explosion/spaCy) dependency parsing / trained NLP | MIT, native/model dependencies | Can model some syntactic negation but requires trained bilingual pipelines, memory/startup overhead and benchmarking | Rejected |

Primary specifications: [Python regular expressions](https://docs.python.org/3/library/re.html) and [Unicode behavior](https://docs.python.org/3/howto/unicode.html). The project retains its Python 3.12+ standard-library runtime invariant.

## Scope

The denial gate applies to the **specific exact quote or heading** being credited, not every sentence in a multi-purpose SKILL.md. This avoids rejecting a positive React capability just because the same skill cannot deploy Kubernetes. Generic action verbs are removed from the single-token overlap signal. Regression fixtures explicitly exercise EN/VI denial, generic overlap, and a positive capability next to an unrelated denial.

This is a conservative heuristic, not semantic entailment or security isolation. Unrecognized negation, mixed positive/negative statements within one quoted span, indirect contradictions and adversarial instruction text remain unresolved. No claims of human labels or holdout quality gains. CI must verify this exact edit on four platforms before promotion.
