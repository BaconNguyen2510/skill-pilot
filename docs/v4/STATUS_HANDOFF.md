# Skill Pilot V4 — Durable Engineering Handoff

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
