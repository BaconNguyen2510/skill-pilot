# V4 Evidence Quote Continuity and Hidden-Block Boundaries

## Concrete defect

The verifier removes fenced Markdown examples, indented code and raw HTML blocks, then globally normalizes whitespace before testing whether a quoted sentence exists in SKILL.md. Previously this could concatenate visible text **across an omitted block** and create an exact string that never occurred as a continuous source passage. Example: `Build React` followed by a fenced example followed by `UI components.` was mistaken for a quote of `Build React UI components.`

This is a source-provenance integrity bug, not a retrieval-ranking issue.

## Research-first choices

| Candidate | License/dependencies | Latency, compatibility and trade-offs | Decision |
| --- | --- | --- | --- |
| Insert a non-whitespace boundary marker into the existing stdlib visible-source stream whenever an entire code/HTML block is suppressed | Python PSF, no new packages | O(1) per omitted block, preserves existing quote matching and no-overwrite policy | **Selected** |
| Track explicit byte/line source spans, then prove every quote lies inside a contiguous span | Python stdlib, zero deps | More formal provenance but larger parser redesign and migration/test complexity | Deferred |
| Parse with [markdown-it-py](https://github.com/executablebooks/markdown-it-py) AST | MIT, additional runtime package | Richer source locations, external parser and transitive footprint | Rejected under stdlib-only runtime invariant |
| Continue concatenating visible segments after removal | No deps | Fast but manufactures source evidence across deleted blocks | Rejected |

Primary standards: [CommonMark fenced code blocks](https://spec.commonmark.org/0.31.2/#fenced-code-blocks), [indented code blocks](https://spec.commonmark.org/0.31.2/#indented-code-blocks), and [raw HTML blocks](https://spec.commonmark.org/0.31.2/#html-blocks).

## Implementation

The source extraction path adds an internal Unicode unit-separator symbol at entry to each omitted fenced, indented or type-1 raw HTML block. This marker is **not whitespace**, so later whitespace normalization cannot merge words from opposite sides into a fabricated quote. Visible quoted passages occurring wholly before or after the omitted content remain searchable. The existing 1 MiB and 8192-line ceilings, on-disk readability checks, and no-symlink rules remain unchanged.

## Benchmark and independent regression controls

- Predeclared `eval/v4_source_boundary_challenges.jsonl`: 16 synthetic development cases (8 fabricated/negative and 8 intact/positive), including EN/VI examples. It is not holdout or independent human annotation.
- `eval/v4_source_boundary_ablation.py` compares exact pinned pre-change source commit `dbaad6ec5ae8527c6c4e00fb74f87363cb9c751b` with the candidate, measuring TP/TN/FP/FN by language and median/p95 per-case latency.
- Reuse the existing contradiction, Markdown, indentation, raw HTML and composite-step benchmarks as **unchanged** regression gates. Any increase in the engineered false-positive or false-negative counts blocks CI.

## Residual risks

Inline HTML comments currently remain a separate provenance ambiguity: removing one can produce text that the renderer displays contiguously. Overbroad sentinel insertion could incorrectly reject valid inline prose, so that behavior is deferred for a focused study. The marker is not a semantic entailment checker, tool sandbox, or protection against arbitrary novel prompt injection. Human labels and native Antigravity/Codex execution remain release prerequisites.

**Do not infer production accuracy from this synthetic challenge set.**
