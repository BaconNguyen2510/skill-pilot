# V4 Raw HTML Evidence — Source-Provenance Hardening

## Confirmed failure mode

The existing SKILL.md evidence extractor removes Markdown fences, HTML comments, and indented code but still includes raw HTML type-1 blocks. Code or instructions embedded inside `<script>`, `<style>`, `<pre>` and `<textarea>` can therefore be credited as direct capability declarations, while a negative claim in an invisible code block can incorrectly veto genuine visible prose.

## Primary-source research and candidate comparison

| Candidate | License and dependency | Functional and latency trade-off | Decision |
| --- | --- | --- | --- |
| Bounded stdlib state tracking for CommonMark type-1 raw HTML blocks | Python PSF; zero extra deps | Reuses existing O(lines) Markdown scan with 1MiB and 8192-line limits; narrow set of inert tags | **Selected** |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) block AST | MIT; external Python package and transitives | Broad CommonMark support, but increased cold start and runtime footprint | Rejected pending demonstrated advantage |
| [Mistune](https://github.com/lepture/mistune) parser | BSD-3-Clause; external runtime package | Broader syntax coverage, nontrivial integration and maintenance | Rejected under zero-dependency constraint |
| Drop every HTML tag and everything between any tags | Python stdlib | Would suppress visible HTML such as `<div>` and `<b>`; unacceptable false negatives | Rejected |

Primary specification: [CommonMark 0.31.2 HTML blocks](https://spec.commonmark.org/0.31.2/#html-blocks) says these four type-1 tag starts end at a corresponding raw-tag close, or at EOF when unclosed. Blocks can contain blank lines and cannot be treated as visible Markdown paragraphs.

## Reproducible synthetic dev-only benchmark

- `eval/v4_raw_html_challenges.jsonl`: exactly 16 predeclared synthetic cases, eight negative and eight positive, EN/VI.
- `eval/v4_raw_html_evidence_ablation.py`: pins the last verified pre-change code at `e5611a7e6aaf915dabba760d197ba87261258a65` and compares it with the current verifier; reports TP/TN/FP/FN and language-specific errors and p50/p95 latency.
- `tests/test_v4_raw_html_evidence.py`: deterministic source-level assertions; older EN/VI, fenced Markdown, and indented-code fixtures remain separate non-regression gates.
- Selection gate: reduce engineered false positives or false negatives with no regression in either language slice. All results must originate from post-edit GitHub Actions, not estimates.

## Scope and limitations

Only CommonMark type-1 raw HTML blocks are filtered; visible formatting tags and ordinary prose remain eligible for evidence. Unclosed blocks stay inert until EOF. This narrow source-provenance mitigation is not a full HTML renderer, an instruction-injection defense, or proof of semantic capability fitness. It does not authorize tool execution. Further review of nested HTML, inline `<script>` inside paragraphs, and stitched cross-block quotations remains required.

**No independent human labels, holdout case tuning, paid runtime dependencies, merge into main, or release are authorized.**

## Measured post-change verification

At source commit `4a38bb2298f2e0ee84920d1ea42646434c08f9ae`, CI #44698091690 passed all four OS/Python jobs. The separate 16-case synthetic raw HTML fixture measured **FP/FN 8/3 → 0/0**, preserving all 8 positives. Sampled p95 median-per-case latency on one Ubuntu job changed 0.0739→0.0759 ms. These are not field or human-label metrics.
