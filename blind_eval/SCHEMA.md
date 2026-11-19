# Blind evaluation dataset contract: `blind-eval-jsonl/v1`

This contract applies to two **separate** UTF-8 JSONL files. Each nonempty line is one JSON object. There is no implicit default, automatic repair, label inference, or code execution. The exact keys are fixed by `contract.py`; extra keys, duplicate JSON keys, invalid UTF-8, and non-finite numbers fail validation. The file limit is 2 MiB, 1,000 records and 16 KiB per line; queries are limited to 512 characters, other strings to 256, IDs to 128, and each skill-label list to 128 IDs. Control characters, blank fields, and unsupported languages fail closed.

**Inference file**, one record per case:

| Field | Type and meaning |
| --- | --- |
| `id` | Unique stable ASCII identifier using letters, digits, `.`, `_`, `:`, or `-`; starts with a letter or digit. |
| `query` | Nonempty user request. This file must contain no label fields. |
| `language` | One of `en`, `vi`, `vi_no_diacritic`, `mixed`. Abstention is a label, not a language. |
| `category` | Nonempty independently assigned category; use exactly `multi_intent` for the coverage count. |
| `intent_family` | Nonempty family identifier for leakage screening and cluster bootstrap; family comparison normalizes case, accents and punctuation. |
| `provenance` | Object with exactly nonempty `author`, `source`, `independence` strings. These are attestations, not proven facts. |
| `ambiguity`, `difficulty` | Optional nonempty strings. |

**Sealed labels**, one record per inference ID:

| Field | Type and meaning |
| --- | --- |
| `id` | Exact case ID; IDs must match the inference file one-to-one. |
| `relevant` | Unique frozen-catalog IDs judged relevant. |
| `forbidden` | Unique frozen-catalog IDs judged harmful or contradictory; disjoint from `relevant`. |
| `expected_abstain` | Boolean. `true` requires no relevant IDs; `false` requires at least one. |
| `annotation_provenance` | Object with exactly nonempty `author`, `source`, `independence` strings. |
| `adjudication_status` | Exactly `final`. |

Exposed-set screening rejects matching IDs, normalized intent-family names, exact normalized query matches, and near matches by token Jaccard ≥ 0.90 or character-trigram Jaccard ≥ 0.88. The exposed data are read from the frozen Git archive. The prior files do not carry comparable annotation-provenance fields, so shared authorship or source overlap requires independent manual investigation. These lexical checks can both miss paraphrases and flag legitimate cases; review rejected cases independently. Screening cannot prove semantic novelty, provenance, or evaluator independence. Do not change this contract or thresholds after examining final predictions without recording a new, separately authorized evaluation protocol.
