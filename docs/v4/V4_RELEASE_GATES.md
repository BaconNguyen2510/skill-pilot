# Skill Pilot v4.0 — Non-negotiable release qualification

**Status: HOLD.** This is the release-readiness checklist for `feat/v4-development`, not an approved release or a substitute for GitHub branch protections.

| Gate | Pass criterion | Status |
| --- | --- | --- |
| Correctness & deterministic regressions | Ruff formatting/lint, configured typing, all suites, release verifier and cross-platform CI pass on the exact proposed release commit | Requires final candidate rerun |
| EN/VI retrieval quality | Development performance, holdout nonregression gate, forbidden recommendation quality and independently reviewed domain fixtures | Real human review pending |
| Evidence security | Quote/source provenance, access boundaries, injection and adversarial tests; no unsafe skill execution | Further review pending |
| Native host compatibility | Actual Codex and Antigravity installed skill runs with transcripts, tool traces and representative user tasks | **NOT RUN** |
| **Goal persistence on blocked links (P0 issue #2)** | Host preserves objective after 403/login/deleted/timeout; does relevant authorized skill discovery or logs grounded abstention, does not invent content or dead-end, asks only for missing source | **OPEN — RELEASE BLOCKER** |
| Real EN/VI human evaluation | Independent bilingual raters and adjudication, with predefined minimum acceptance thresholds | **NOT DONE** |
| Documentation/migration | Accurate version, changed behaviors, rollback, remaining risks and release receipts | Requires final review |
| Release authorization | Separate explicit approval for version bump, protected main merge, tag, GitHub Release or deployment | **NOT GRANTED** |

No “good enough” workaround may silently move a P0 release blocker to v4.1. A release decision requires explicit recorded resolution, with test evidence and independent review. A limitation external to the product, such as a platform denying access, is not itself a release defect; **failing to recover helpfully within permitted scope is**.

See [blocked-source recovery research](V4_BLOCKED_SOURCE_RECOVERY.md), [durable handoff](STATUS_HANDOFF.md), and [architecture](V4_ARCHITECTURE.md).
