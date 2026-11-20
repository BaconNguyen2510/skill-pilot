# Skill Pilot v4 Engineering Continuation — Milestones 17–20

**Status:** all source milestones and the four-cell CI are verified; development branch remains unreleased. Protected main stays at `2c917158ccc3105804d99552cae0b5daeb461d4a`.

| Milestone | Commit | CI run | Synthetic FP before → after | Synthetic FN before → after |
| --- | --- | --- | ---: | ---: |
| 17 · Indented Markdown code | `e5611a7e6aaf915dabba760d197ba87261258a65` | #44697474119 (4/4) | 7 → 0 | 0 → 0 |
| 18 · Raw HTML literal blocks | `4a38bb2298f2e0ee84920d1ea42646434c08f9ae` | #44698091690 (4/4) | 8 → 0 | 3 → 0 |
| 19 · Composite-step evidence | `dbaad6ec5ae8527c6c4e00fb74f87363cb9c751b` | #44698892964 (4/4) | 8 → 0 | 0 → 0 |
| 20 · Quote boundaries | `b827876d9beaeb2e82461c4ac14bf601e374283b` | #44699486091 (4/4) | 8 → 0 | 0 → 0 |

**Latest source verification:** 232 tests under `tests`, 40 under `blind_eval/tests`, 8 under `.github/tests` on Ubuntu Python 3.12; full matrix Windows/Linux Python 3.12/3.14 green. Ruff format/check, configured types, release verifier, all independent synthetic development benchmarks, retrieval ablation and clean-archive smoke green.

**Benchmark caveats:** all 64 newly added cases across four separate suites are synthetic developer-created EN/VI engineering cases (not sealed, not random traffic, not human rater labels). Latency measurements use one CI runner and cannot be compared as a controlled performance study. No independent product quality uplift is claimed.

**Approaches rejected:** blanket indentation/HTML removal, source-evidence merging across separate skills, acceptance of a single conjunct, global quote concatenation, and new external parsing/NLP dependencies (markdown-it-py, Mistune, spaCy, RapidFuzz) without demonstrated necessity. Decisions and primary source links are recorded in the individual `V4_*_RESEARCH.md` documents.

**Residual risks:** inline Markdown code, comments at block/paragraph boundaries, deeply nested CommonMark containers, obfuscated/indirect negation, actual semantic capability fit, and native host LLM prompts/actions. None is resolved by synthetic green tests. Real bilingual blind human review and native Codex/Antigravity end-to-end testing remain hard release gates.

**Exact next step:** verify the latest docs-only branch head and its four-cell CI, then research/test inline HTML comment source boundaries without sacrificing visibly contiguous inline prose. Obtain independent real reviewer and host task evidence before proposing a release. Never merge into main, tag, publish, deploy, or leak sealed data without separate approval.
