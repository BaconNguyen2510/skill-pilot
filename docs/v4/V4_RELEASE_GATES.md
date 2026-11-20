# Skill Pilot v4.0 — Non-negotiable release qualification

**Stable v4.0 status: HOLD.** A public `v4.0.0-beta.1` **prerelease** is separately authorized as a test vehicle; it does **not** close the P0 or approve stable publication.

## Mandatory v4.0 submilestones (no v4.1 deferral)

| ID | v4.0 workstream | Current stage | Release pass condition |
| --- | --- | --- | --- |
| **21** | Goal persistence after blocked source | Host policy implemented; native-host verification pending | User's original objective persists across fetch failure, without redundant goal questioning |
| **22** | Bounded source-access fallback | Reference workflow documented; native-host verification pending | Authorized alternatives attempted or correctly ruled out; one useful missing-input request instead of a dead end |
| **23** | Relevant skill discovery or grounded abstention | Scout recovery path covered by deterministic CLI tests; native-host verification pending | Actual available skill lookup/inspection shown in tool traces, or an accurate reason it could not be used |
| **24** | EN/VI native social-link end-to-end evaluation | 12 synthetic dev scenarios defined; real trials not run | Actual Codex **and** Antigravity passes, independent EN/VI assessment, no fabricated media claims and no skipped recovery when viable |

**All four are part of v4.0.** None may be silently moved to a later version to clear a release. [Issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2) stays open until the real-host and independent-review gates are satisfied.

 This is the release-readiness checklist for `feat/v4-development`, not an approved release or a substitute for GitHub branch protections.

| Gate | Pass criterion | Status |
| --- | --- | --- |
| Correctness & deterministic regressions | Ruff formatting/lint, configured typing, all suites, release verifier and cross-platform CI pass on the exact proposed release commit | Requires final candidate rerun |
| EN/VI retrieval quality | Development performance, holdout nonregression gate, forbidden recommendation quality and independently reviewed domain fixtures | Real human review pending |
| Evidence security | Quote/source provenance, access boundaries, injection and adversarial tests; no unsafe skill execution | Further review pending |
| Native host compatibility | Actual Codex and Antigravity installed skill runs with transcripts, tool traces and representative user tasks | **NOT RUN** |
| **Goal persistence on blocked links (P0 issue #2)** | Host preserves objective after 403/login/deleted/timeout; does relevant authorized skill discovery or logs grounded abstention, does not invent content or dead-end, asks only for missing source | **OPEN — RELEASE BLOCKER** |
| Real EN/VI human evaluation | Independent bilingual raters and adjudication, with predefined minimum acceptance thresholds | **NOT DONE** |
| Documentation/migration | Accurate version, changed behaviors, rollback, remaining risks and release receipts | Requires final review |
| Release authorization | Beta-only tag/GitHub prerelease authorized; stable v4.0 tag, protected main merge and deployment require separate approval | **BETA ONLY** |

No “good enough” workaround may silently move a P0 release blocker to v4.1. A release decision requires explicit recorded resolution, with test evidence and independent review. A limitation external to the product, such as a platform denying access, is not itself a release defect; **failing to recover helpfully within permitted scope is**.

See [blocked-source recovery research](V4_BLOCKED_SOURCE_RECOVERY.md), [durable handoff](STATUS_HANDOFF.md), and [architecture](V4_ARCHITECTURE.md).
