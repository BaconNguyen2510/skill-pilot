# Skill Pilot V4 — Durable Engineering Handoff

## v4.0 P0 release blocker: goal persistence and inaccessible media (open)

**Tracking:** [GitHub issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2). The user specifically requires this to be fixed **in v4.0, not v4.1**. A reported Facebook-reel interaction showed a blocked fetch and a caption request but no visible skill discovery or alternative permitted recovery. That screenshot does not prove hidden tools were absent; real host traces are still required.

- Added a blocked-source recovery gate to `skills/skill-pilot/SKILL.md` and a detailed `references/source-recovery.md` workflow. A blocked link with an already-clear goal must not restart the Interview Gate or terminate the original task. Relevant media-analysis skills must be searched by capability when permitted; inspect candidate SKILL.md files and never invent tool activity.
- Added `docs/v4/V4_BLOCKED_SOURCE_RECOVERY.md` (3+ candidate design comparison), `docs/v4/V4_RELEASE_GATES.md` and 12 EN/VI synthetic **development scenarios** for later host trials. These are not observed native host successes or human labels.
- **Current status: UNVERIFIED / RELEASE HOLD.** No v4.0 merge, tag, release or deployment may proceed while issue #2 lacks real native Codex and Antigravity acceptance evidence plus independent bilingual review. CI passing only proves the written skill contract and CLI discovery mechanics, not actual model obedience.

**Next action:** run the complete post-change CI matrix, then collect redacted native host tool traces across the frozen blocked-link scenarios, adjudicate skipped skill discovery/fabricated media claims, fix underlying causes and rerun both hosts. User's intent must remain intact across fetch failure. Do not loosen privacy or invent access.

---

## Verified continuation: milestones 17–20 (2026-11-20)

**Latest verified source commit:** `b827876d9beaeb2e82461c4ac14bf601e374283b`, GitHub Actions **#44699486091**, four of four Windows/Ubuntu × Python 3.12/3.14 jobs passed. On Ubuntu Python 3.12: 232 main regression tests, 40 blind-tooling tests and 8 workflow tests; Ruff format/check, configured type checks, release verifier, dev ablations and simulated clean-archive host smoke passed.

| Milestone | Source commit | Verified Actions | Synthetic dev confusion counts FP/FN (before → after) | Sampled p95 latency (ms) |
| --- | --- | --- | --- | --- |
| 17: indented Markdown code provenance | `e5611a7e6aaf915dabba760d197ba87261258a65` | #44697474119 4/4 | 7/0 → **0/0** on 16 | 0.1212 → 0.1132 |
| 18: raw HTML literal-content blocks | `4a38bb2298f2e0ee84920d1ea42646434c08f9ae` | #44698091690 4/4 | 8/3 → **0/0** on 16 | 0.0739 → 0.0759 |
| 19: explicit composite-step coverage | `dbaad6ec5ae8527c6c4e00fb74f87363cb9c751b` | #44698892964 4/4 | 8/0 → **0/0** on 16 | 0.1654 → 0.1780 |
| 20: hidden-block cross-boundary quote protection | `b827876d9beaeb2e82461c4ac14bf601e374283b` | #44699486091 4/4 | 8/0 → **0/0** on 16 | 0.1244 → 0.1184 |

**Important:** Every fixture is a deliberately authored *synthetic development challenge*, not representative real-world accuracy, an independent human-evaluation study or a semantic guarantee. Latency is noisy median-per-case timing from one CI runner, not a throughput SLA. Holdout was not used to choose these changes.

Research and rejected candidates are in `V4_INDENTED_MARKDOWN_RESEARCH.md`, `V4_RAW_HTML_EVIDENCE_RESEARCH.md`, `V4_COMPOSITE_EVIDENCE_RESEARCH.md` and `V4_SOURCE_BOUNDARY_RESEARCH.md`. Across these, full Markdown parsers and spaCy/RapidFuzz were rejected as new production dependencies without reproducible advantage over the stdlib-only narrow fixes; blanket line/HTML removal and merging a single skill's evidence from unrelated skill files were rejected as unsound.

**Next session priority:** confirm the exact docs-only final commit/CI, review inline-code and inline/multiline HTML comment provenance as independent threat cases, then arrange **real** bilingual human labels and native Antigravity/Codex task completion. The current heuristics do not prove semantic skill fit, host prompt-injection safety or real user success. Main is protected at `2c917158ccc3105804d99552cae0b5daeb461d4a`; do not merge, tag, deploy, release, or expose sealed data.

---

## Continuation milestones 15–16: capability-source integrity (2026-11-20)

**Latest verified source SHA:** `be8e9ee965d995c7853803fc3fe913e7e9256827`, GitHub Actions #44695311575 **4/4 passed** (Ubuntu/Windows × Python 3.12/3.14). Ubuntu 3.12: 222 main-suite, 40 blind, 8 workflow tests passed; Ruff format/lint, configured type checks, release verifier, dev ablations and clean-archive simulated host smoke passed.

- **Milestone 15 — scoped EN/VI capability denials:** commit `178ac1a9e5836fd88187bd9780f01332a1ecc0e3`, CI #44693872987 (4/4): the synthetic 32-case engineering fixture changed from **17 false positives / 0 false negatives** to **0 / 0**. English FP 9→0, Vietnamese FP 8→0; all 12 positives retained. Sampled p95 per-case median latency 0.0456→0.0672 ms.
- **Milestone 16 — Markdown source provenance:** commit `be8e9ee965d995c7853803fc3fe913e7e9256827`, CI #44695311575 (4/4): the synthetic 16-case Markdown fixture changed from **8 false positives / 3 false negatives** to **0 / 0**. Sampled p95 per-case median latency 0.1191→0.1137 ms. Code fences, hidden comments and fabricated heading substrings are no longer positive direct evidence.
- **Boundary:** these are deliberately synthetic *dev* cases, NOT external human evaluation, representative production error rates, or proof of semantic entailment. No hidden/holdout cases were used to select the changes. Latency readings are small/noisy CI samples.
- **Rejected alternatives:** spaCy/negspaCy/RapidFuzz for negation, full Markdown-it-py/Mistune parsers for Markdown, pending independent value over the stdlib-only runtime. Neither change modifies protected main, plugin versions, sealed data or release tags.

**Exact next step:** confirm the post-documentation branch head and its CI; independently review indented Markdown blocks, unusual HTML, encoded negation and multi-skill ambiguity using separate predeclared *dev* fixtures. Obtain real bilingual human labels and native Codex/Antigravity host tests before proposing any v4 release. Do not merge, tag or publish without separate authorization.

---

## Continuation verified on 2026-11-20 (newer than milestones below)

Protected baseline `main` remains at `2c917158ccc3105804d99552cae0b5daeb461d4a` (`v3.1.1`). Branch `feat/v4-development` now includes:

- **Milestone 6 / State & lock (`2e79a51ae23ea6f6da2df3172645b29e3a4a355a`)**: empty/partial plan patches cannot clear stale state; missing intent confirmation fails closed; persistence rechecks readiness under lock; Windows PID liveness uses correctly typed `HANDLE` and nonblocking wait, exercised by real child processes. CI #44654442669: 4/4 green.
- **Milestone 7 / Search output boundary (`1e6706954ae4ea3923538926ccb75b3f37accd29`)**: redacts recognized instruction-override cues across JSON primary and secondary arrays and compact display; shares the same cross-platform PID probe for promotion locks. CI #44655024205: 4/4 green.
- **Milestone 8 / Human-eval diagnostics (`0900c870c948eaac65538fdb62420bc587e9409e`)**: adds overall/per-language Cohen kappa for full 0–3 relevance, fit, evidence quality and inappropriate labels; optional missing-capability labels must be complete for both raters; synthetic regressions. CI #44655515263: 4/4 green. **No real human labels.**
- **Milestone 9 / Blind packet publication (`3539d885ebd03b886a9076fd4fd5846e7733c945`)**: securely stages JSONL and publishes via exclusive hardlink; tests injected link failure and concurrent writers; fails closed on filesystems without hardlinks. CI #44656105204: 4/4 green.
- **Milestone 10 / Session create-only (`31faf06994c053cf494a3b2013592d64e6adcd17`)**: new session initialization takes session lock and rejects existing paths rather than overwriting approval history. Two real CLI processes verify one succeeds and one fails. CI #44656412562: 4/4 green.

**Latest source verification at milestone 10** (Ubuntu Python 3.12 CI #44656412562): `ruff format --check .`, `ruff check .`, configured type checks, 206 main-suite tests, 40 blind-evaluation tests, 8 workflow-control tests, `eval/verify_rc.py`, dev-only retrieval ablation, and simulated clean-archive Antigravity/Codex CLI smoke all passed. Other matrix cells (Ubuntu 3.14, Windows 3.12/3.14) also passed. The holdout verifier is a historical **qualification** gate, not a ranking-development dataset. Reported MRR@5 diff 0.0, Recall@5 diff -0.0076, Forbidden@5 diff -0.1145 vs historical v2.1 baseline; these are not v4 quality-improvement deltas.

### Rejected or deferred alternatives in continuation

- Reject adding `psutil` or duplicated Win32 ctypes liveness logic; use the shared stdlib probe and avoid truncated/ambiguous handles.
- Reject description-only masking; it misses secondary arrays, name and tags. Recursive regex redaction is still **not** a host prompt-injection security boundary.
- Reject partial/no-op plan re-affirmation because it revives stale intent.
- Reject `os.replace` for write-once human-review packets because it overwrites protected labels, and direct `open('x')` because interruptions expose partial files.
- Reject new external statistical dependencies (`scikit-learn`, `statsmodels`, Krippendorff alpha) for current two-rater nominal diagnostics; no actual human judgments have been collected.
- All previous retrieval reweighting variants remain rejected; do not revisit against the holdout.

### Exact next step to resume

1. Read `docs/v4/STATUS_HANDOFF.md`, verify branch head and its exact completed CI run after this doc-only update, and inspect `main` for unexpected movement.
2. Audit `session_planner.run_plan_search` against tampered step dictionaries/invalid graph input and quote-grounding false positives. Reproduce any flaw in a deterministic security test **before** patching; document >=3 primary-source candidates in `docs/v4/`.
3. Arrange **real** bilingual independent reviewer labels and true native Codex/Antigravity test sessions outside this public repo. Neither can be substituted by synthetic tests or fake host folders.
4. Maintain pure Python 3.12+ stdlib runtime. Never merge/tag/release or publish sealed files without explicit authorization. Preserve v3.1.1 on protected main.

---

## Ground truth

- Protected baseline: `main` v3.1.1, commit `2c917158ccc3105804d99552cae0b5daeb461d4a`, CI #44646874805 green.
- Development: `feat/v4-development` (moving head). No push/merge/tag/release to main; runtime manifests intentionally stay v3.1.1.
- All engineering write operations target branch heads with expected SHA. GitHub Actions is authoritative for verification because this conversation's container cannot clone GitHub over network.

## Completed phases

**v3.2 correctness:** readiness including success criteria and freshness, revision invalidation, duplicate/missing dependency IDs, stable DAG order, consistent coverage accounting, versioned specification, owner-aware session lock. Four-cell CI #44649027991 green, 180 main + 28 blind + 8 CI tests.

**v3.3 dev retrieval:** 80-case dev-only snapshot plus 32-case dev adversarial corpus; name boost, field-length normalization and alias-downweight ablations. All rejected: no MRR/recall benefit. Baseline (80 dev): MRR@5 1.0000, recall .9375, forbidden .0500. (32 adversarial): MRR@5 .9500, recall .9000, forbidden .0625. Four-cell CI #44649960688 green. No production ranking changes.

**v3.4 security:** capped non-following skill-evidence reads, readable file checks, suppression of recognizable injection payloads in retrieved descriptions, regression tests. CI #44650386817 four cells green.

**v3.5 independent-eval tooling:** packet validator, score-free anonymized input contract, Cohen kappa and adjudication queues, six synthetic reviewer tests. No real human labels. CI #44651099962 four cells green.

**v3.5 UX:** session spec dependency sequence and review/handoff conditions; README guided session walkthrough and research alternatives. Fixtures updated after test-gate failures.

**v3.4 clean archive:** `eval/v4_host_smoke.py` tests Python CLI on a `git archive` with fake HOME and Antigravity/Codex skill layout using `doctor`, `inventory`, `intake`, `inspect`, `promote --dry-run`, session updates, `plan-search`, wrapper. CI #44651878437 four cells green, source commit `9f9a7acddac75be0f016931036e17c5e7e352314`. This is not a native LLM-host test.

## Research and experiments not integrated

- Rejected field-boost, BM25F-inspired scoring and alias-downweight because of zero retrieval relevance gain and one forbidden language-slice regression.
- Rejected runtime dependency additions (`rank_bm25`, dense embeddings, Click/Typer, external state machine and lock libraries) without evidence overcoming the stdlib invariant.
- Did not perform actual independent human evaluation, live native Antigravity/Codex execution, semantic capability audits or v4 release packaging/merge.

## Next work for new session

1. Confirm exact latest SHA and 4/4 CI run on the moving v4 branch; never assume prior run covers later edits.
2. Finish architecture/migration/README parity and source review, ensure all v4 docs link cleanly and GitHub Release manifests remain untouched.
3. Run security/concurrency regression review against live lock ownership, TOCTOU and prompt injection handling without implying full sandboxing.
4. Independently source genuinely unseen real task EN/VI labels and real native-host compatibility evidence. Do not fabricate.
5. Freeze/review a candidate and decide release readiness, but require separate approval to update versions, merge main, tag or publish.

## Invariants

Pure Python 3.12+ stdlib runtime; read files before claims; research 3 alternatives and record rejects for every nontrivial change; after last edit run ruff format/check, `unittest discover` for tests, blind and .github tests, and hosted 4-cell smoke. Do not tune on holdout or copy sealed files into public history.
