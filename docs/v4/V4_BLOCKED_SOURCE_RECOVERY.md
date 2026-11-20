# V4.0 release blocker: Goal persistence and source-access recovery

**Tracking:** [GitHub issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2). **Target: v4.0.0; NOT v4.1.** Status: **OPEN / RELEASE HOLD** pending actual host validation.

## Reported symptom versus inspected facts

**Reported symptom:** In a supplied screenshot, the user asked Skill Pilot for an opinion about an idea in a Facebook reel. The host attempted a single web fetch, reported that Facebook blocked it, and asked for a caption/description without any visible further tool or installed-skill discovery. It did not fabricate the reel contents. The screenshot alone does not establish whether discovery was hidden or what tool capabilities were available.

**Observed repository state (pre-change):** The v4 development `SKILL.md` specified Fast/Guided/Deep, a one-question Interview Gate and normal `intake`/`plan-search`. It had no explicit policy for source fetch failures, preserving goal across a blocked URL, or discovering media-analysis skills before a one-input recovery request. Existing clean-archive smoke tests are not real Codex/Antigravity model sessions.

**Reproducible risk:** A model can interpret a blocked fetch as a terminal task failure, or re-ask for the original goal, although the user's actual goal (e.g. evaluate an idea) is already clear. A mere caption request may be honest but incomplete when authorized media-analysis skills or public alternatives could help.

## Research-first alternative analysis

| Candidate | Primary source / license | Dependencies, fit and relative cost | Outcome |
| --- | --- | --- | --- |
| Extend Skill Pilot's existing Agent Skills instructions and call its current read-only scout before a goal-preserving input request | [Agent Skills specification](https://github.com/agentskills/agentskills) (Apache-2.0 specification; this project's existing stdlib tools); Python 3.12+ stdlib | Zero new runtime dependencies, one bounded local skill discovery, no additional browser install; actual host latency to be measured | **Selected** |
| Add [LangGraph fault-tolerance](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/fault-tolerance.mdx) retry and recovery graph | [LangGraph MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) | New runtime packages, state infrastructure and host-adapter integration; powerful but unnecessary to fix a targeted skill instruction gap | Rejected under current invariants |
| Bundle [Playwright](https://github.com/microsoft/playwright) browser automation to open blocked media | [Apache-2.0](https://github.com/microsoft/playwright/blob/main/LICENSE) | Heavy browser deployment, more platform/security surface; cannot guarantee passage through Facebook login/access controls | Rejected as default recovery |
| Leave failure as “can't fetch, paste a caption” with no skill discovery | No dependency | Fastest but does not verify whether a usable recovery capability exists and risks abandonment | Rejected as v4 behavior |

This comparison informs implementation; **it is not a measured performance benchmark**. No new runtime package is introduced, and no paid service is required.

## v4.0 milestone breakdown

- **Milestone 21:** Persist the actual user goal when a reel/URL fetch fails; do not restart a clear Interview Gate.
- **Milestone 22:** Use bounded permitted fallback sources, then offer a single concrete source-input request when material is still missing.
- **Milestone 23:** Search suitable installed/warehouse skills by capability and inspect their SKILL.md, or record a truthful tool/skill abstention.
- **Milestone 24:** Run frozen EN/VI link-failure cases inside **real** Codex and Antigravity hosts, independently review tool traces, and close all observed failures before release.

These four milestones are **mandatory acceptance work for v4.0**. Deterministic CI is a prerequisite, not a replacement for native-host completion.

## v4 implementation contract

1. **Preserve original intent:** distinguish the requested result from the input source. Clear intent + blocked material must not automatically restart interview/confirmation.
2. **Trigger a bounded recovery pass:** inspect accessible public information or authorized alternate sources; for specialist tasks, discover relevant installed/local skills by capability (active, dormant and warehouse). Read any relevant SKILL.md; a search result is only a candidate, not proof that its tools work.
3. **Respect source boundaries:** never bypass login, private accounts, CAPTCHA, paywalls or other access controls; never claim to have viewed or transcribed an inaccessible reel.
4. **Prefer useful continuation:** if material is still inaccessible, provide the analysis dimensions relevant to the user's original task, disclose exact limitations, ask only for the smallest missing source input, and avoid “can't access it” as a terminal answer.
5. **Do not invent workflow evidence:** cite actual tool calls and results; state when a scout command, plugin, browser or video tool was unavailable. A read-only recovery lookup does not authorize a speculative `plan-search` for unconfirmed requirements.
6. **Keep Fast efficient:** ordinary fully answerable requests retain Fast's no-search default. The special recovery pass applies to blocked evidence when a relevant tool/skill could materially help.

## Acceptance matrix required before v4.0 release

| Gate | Minimum criterion | Current evidence |
| --- | --- | --- |
| Instructions | `SKILL.md` and `source-recovery.md` define goal persistence, bounded public alternatives, skill discovery, privacy and one-input fallback | Code change must pass CI |
| CLI discovery | Relevant installed media-analysis skill is discoverable via `skill_scout.py search` in a synthetic warehouse; unsuitable or absent skills are not claimed usable | Deterministic tests pending |
| EN/VI scenarios | Frozen development fixtures include Facebook/TikTok/Instagram/YouTube, 403/login/timeout/404/deleted, content supplied, no available tools, clear vs ambiguous goal, privacy and partial evidence | Scenarios pending |
| Native Codex | Real host model sessions with tool traces, source redaction and multiple independent prompts, no invented media claims or abandonment | **NOT RUN — HOLD** |
| Native Antigravity | Equivalent real host model sessions (not fake HOME) | **NOT RUN — HOLD** |
| Independent evaluation | Independent human review (EN/VI) of intent preservation, actual tool discovery, blocked-source recovery utility, truthful disclosure and quality | **NOT DONE — HOLD** |
| General release | Four-cell CI, regression/nonregression checks, qualified source validation, final security review, explicit release authorization | **HOLD** |

**Host behavior must be verified from tool traces, not judged from a pretty final answer alone.** If relevant skills were available but the host skipped discovery, the test fails. If the host reports a reel summary without observed media evidence, the test fails. If source access remains blocked but the host preserves the goal and makes an appropriate focused recovery request after checking available tools, that is acceptable.

## Release prohibition

This is a **P0 v4.0 release blocker**. No green unit suite, Markdown instructions, pseudo-host filesystem or assistant assertion can close it. Keep issue #2 OPEN until genuine native-host regression receipts and independent EN/VI review exist and failures are resolved. No v4.0 tag, merge to protected `main`, GitHub Release or deployment is authorized now.

## Limits

An inaccessible platform cannot be forced open. The user expects the agent to continue serving the original goal, not to bypass privacy or fabricate unseen content. The gate should be attainable through valid fallback workflow while openly explaining any remaining content gap.
