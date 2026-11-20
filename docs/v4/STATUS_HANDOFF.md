# Skill Pilot V4 — Durable Engineering Handoff

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
