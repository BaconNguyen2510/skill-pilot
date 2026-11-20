# V4 Indented Markdown Evidence — Source-Context Research

## Problem and reproducible baseline

The existing `_visible_skill_markdown` filters fenced Markdown examples but retains indented code blocks (four leading spaces or an equivalent tab). A capability quoted only in code can therefore be promoted to direct coverage despite being an example. Removing every indented line would instead reject legitimate paragraph/list continuations.

This change uses a separate, predeclared **16-case synthetic engineering dev corpus** (8 negative, 8 positive, EN/VI) in `eval/v4_indented_markdown_challenges.jsonl`. The baseline implementation is pinned to `9a9a66740a24873f79a38d7d28abe067fe584224`. These cases are not holdout, real user queries or human labels.

## Research-first alternatives

| Candidate | Primary source and license | Dependencies and performance fit | Decision |
| --- | --- | --- | --- |
| Stdlib line-state tracking for indentation and paragraph continuations | [CommonMark indented code](https://spec.commonmark.org/current/#indented-code-blocks), Python PSF | Zero extra runtime packages; O(lines) with existing 8192-line/1MiB bounds | **Selected** for the narrow defect |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) AST | MIT | Complete parser but additional dependency and startup/memory burden | Rejected without benchmark advantage |
| [Mistune](https://github.com/lepture/mistune) Markdown parser | BSD-3-Clause | More complete parser, extra dependency and broader integration surface | Rejected under stdlib invariant |
| Remove every line with four leading spaces | Python stdlib | Fast, but causes false negatives on paragraph/list continuations | Rejected as incorrect |

CommonMark states that an indented block cannot interrupt a paragraph; tab stops count toward four columns. The selected conservative scanner tracks paragraphs and lists while filtering stand-alone indented examples.

## Verification and boundaries

- Synthetic regressions cover BOF and after-heading code, tabs, multi-line blocks, indented headings, visible prose before/after code, and paragraph/list continuation.
- The dev-only benchmark compares the pinned baseline to the candidate, reporting confusion counts, language slices and p50/p95 median per-case latency.
- Preserve both prior evidence benchmarks (32 EN/VI contradictions, 16 fenced-code/comment cases), release verifier, four-platform CI and the stdlib-only runtime.
- This is **not** a full CommonMark implementation: nested lists, blockquotes, raw HTML and inline code are separately unresolved. Independent bilingual human and native-host evaluation are still required.

**Metrics remain unverified until GitHub Actions runs on the exact post-change SHA.**

## Measured post-change verification

At source commit `e5611a7e6aaf915dabba760d197ba87261258a65`, CI #44697474119 passed all four OS/Python jobs. The separate 16-case synthetic indented Markdown development fixture measured **FP/FN 7/0 → 0/0**, preserving all 8 true positives. Sampled p95 median-per-case latency on one Ubuntu job changed 0.1212→0.1132 ms. This is not representative human-evaluation precision.
