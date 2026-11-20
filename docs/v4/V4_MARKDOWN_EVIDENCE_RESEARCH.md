# V4 Markdown Inert-Source Evidence Research

## Threat and baseline

`extract_skill_capabilities` currently reads the entire SKILL.md into a flattened string and gathers Markdown headings on every line. A quoted instruction inside a fenced code example, or an HTML comment not visible in rendered instructions, can establish `direct` capability coverage. Likewise, a limitation appearing **only** in a code sample can contradict a genuine prose capability. A third defect is that a real heading may be matched as a substring inside a fabricated, longer quotation that never occurs in the file.

The pinned before-code baseline is `178ac1a9e5836fd88187bd9780f01332a1ecc0e3`, verified CI #44693872987. Separate `eval/v4_markdown_evidence_challenges.jsonl` contains 16 synthetic EN engineering cases (8 positives, 8 negatives). No sealed, holdout, or real reviewer examples.

## Research-first candidates

| Candidate | Primary source / license | Dependencies and latency / fit | Decision |
| --- | --- | --- | --- |
| Minimal stdlib line scanner using CommonMark fence semantics, plus HTML comment suppression and exact-heading equality | [CommonMark specification](https://spec.commonmark.org/current/#fenced-code-blocks); Python PSF | O(bytes) scan on already capped 1 MiB input, no external runtime packages; test across OS | **Prototype selected** for this narrow trust-boundary defect |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) AST renderer | MIT | Full CommonMark parser, new runtime dependency and mdurl transitive package; more complete Markdown compliance, extra startup/load time | Rejected until reproducible advantage outweighs stdlib constraint |
| [lepture/mistune](https://github.com/lepture/mistune) AST parsing | BSD-3-Clause | Maintained Markdown parser, new runtime dependency and complex parse rules relative to narrow task | Rejected for default lightweight CLI |
| Regex-only fenced-code `re.sub` removal | PSF, zero deps | Easy but incorrect for mismatched fence markers, nested longer fences and unclosed code blocks | Rejected as unsound |

Primary behavior: a CommonMark fenced block opens with at least 3 backticks or tildes, up to 3 spaces indentation; it closes only with the same marker type and at least opening length. An unclosed block extends to the end. HTML comments are inert in rendered text.

## Evaluation

`python eval/v4_markdown_evidence_ablation.py` compares the pinned before-code verifier with the checked-out verifier using only synthetic development fixtures. Its output includes confusion counts, error slices, incorrect case IDs and p50/p95 per-case latency. The existing 32-case EN/VI contradiction benchmark continues to run independently and must remain nonregressing.

Selection gate (to be applied after observed baseline metrics): reduce false source-grounding positives without losing legitimate source evidence or invalidating prior EN/VI contradiction cases. No assistant, human or host-model validation is implied by engineering labels.

## Verification boundary

New source-provenance tests must check both backtick/tilde fences, nested longer fences, unclosed fences, HTML comments, exact-heading versus substring matches, source-local prose and fenced-only limitations. The entire four-cell CI must pass at the exact changed commit before any approval.

## Actual baseline findings — CI #44694714253

The frozen before-change verifier at `178ac1a9e5836fd88187bd9780f01332a1ecc0e3` was evaluated in the four-cell matrix (all passed) on the separately checked-in **16 synthetic dev cases**. One Ubuntu 3.12 job measured:

| Metric | Baseline |
| --- | ---: |
| Positive / negative engineered cases | 8 / 8 |
| True positives | 5 |
| True negatives | 0 |
| False positives | 8 |
| False negatives | 3 |
| p50 / p95 per-case median latency | 0.1489 / 0.1555 ms |

**Observed failure modes:** code fenced quotes/headings and hidden HTML comments were accepted; negative claims inside code fences vetoed genuine visible prose; a fabricated quoted sentence containing the name of a real heading passed as an exact heading match.

These percentages are not representative field accuracy. All labels were predeclared synthetic engineering assertions, not independently annotated user requests.

## Candidate behavior and acceptance

The implementation candidate filters fenced code and HTML comments before heading, statement and quote extraction; a cited heading must match the standalone evidence text rather than merely appear as a substring in longer text. It follows the CommonMark 0–3-space fence indentation and marker-type/length rules, caps source line count, and fails closed on unclosed fences. The original 32-case EN/VI contradiction benchmark must remain green.

The dev-only Markdown benchmark rejects a candidate if synthetic false positives or false negatives regress, or if neither improves. Full Windows/Linux CI and measured latency results must be recorded after implementation; this benchmark is not a v4 release gate or human semantic-validation claim.

## Observed post-change CI #44695311575

On 16 synthetic Markdown cases, pinned baseline TP=5,TN=0,FP=8,FN=3 and filtered verifier TP=8,TN=8,FP=0,FN=0. Sampled p50/p95 per-case median latency 0.1049/0.1191→0.1031/0.1137 ms. Four OS/Python CI jobs passed, including the previous EN/VI dev gate. Not a production/human-judged accuracy claim.
