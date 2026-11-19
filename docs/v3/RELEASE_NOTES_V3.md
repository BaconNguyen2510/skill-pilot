# Skill Pilot v3.0 Release Notes & Execution Plan

## 1. Core Capabilities (v3.0)
- **Adaptive Discovery & Planning (`skills/skill-pilot/SKILL.md` + `session_planner.py`):** Structured session state (`session init/update/revise/status/spec`), two-stage observable readiness (`ready_for_planning` vs `ready_for_discovery`), and dependency-aware `plan_steps` validation.
- **Per-Step Skill Discovery (`plan-search`):** Ranks local skills per plan step, filters unverified or `risk=offensive` skills, enforces `capability_evidence` before allowing `direct` coverage, and reports explicit `capability_gaps`.
- **Atomic & Concurrency-Safe Persistence:** `session_lock` (`O_CREAT | O_EXCL` with `stale_after_s=60.0` abandoned-lock recovery and `timeout_s=5.0`), `os.fsync()` + `os.replace()`, and `session_id`/`revision` validation.
- **Negation-Aware Ranking (`skill_scout.py`):** Supports English (`not`, `except`) and Vietnamese (`không`, `khong`) negation cues with quote masking and conflicting-intent abstention.

## 2. Known Limitations & Accepted Risks
1. **Vietnamese `trừ` Negation Cue:** Not supported in `v3.0` (tracked via `tests/test_adversarial_auto_eval_v3.py::test_17_vietnamese_tru_negation` `@unittest.expectedFailure`, deferred to `v3.1`).
2. **Human EN/VI Evaluation Deferred:** Replaced for `v3.0` by the Automated Verification Gate (`tests/`, `blind_eval/tests/`, `.github/tests/`, `eval/verify_rc.py`, and live host-agent scenarios). Independent human EN/VI ranking evaluation remains a tracked `v3.1` requirement.
3. **Security / Prompt-Injection Scope:** `SKILL.md` treats retrieved skills as untrusted data and `plan-search` filters `risk=offensive` by default; isolated synthetic prompt-injection tests passed, but this is not a formal guarantee against novel LLM prompt-injection attacks.

## 3. Provenance & Confidentiality
- **Historical Candidate Preserved:** `2c8daab7ae7a8b06dcfc64863c4043183fd35261` is retained in `blind_eval/harness.py` (`HISTORICAL_CANDIDATES`) and `docs/v3/CANDIDATE_MANIFEST_V3_RC.json`.
- **Confidential Isolation:** `feat/v3-research-program` and sealed evaluation artifacts (`eval/sealed_queries.jsonl`, `docs/v3/SEALED_EVAL_REPORT.json`) are excluded from `feat/v3-project-discovery` and public `main`.

## 4. Authorized Release Execution Plan (Pending Owner Approval)
1. **Version Alignment (`3.0.0-rc.1` -> `3.0.0`):** Update `skills/skill-pilot/scripts/skill_scout.py` (`__version__`), `plugin.json`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `tests/test_skill_scout.py`, and `docs/v3/CANDIDATE_MANIFEST_V3_RC.json` / `blind_eval/harness.py`.
2. **Merge & Tag:** Merge `feat/v3-project-discovery` into `main` (`git merge --no-ff`), create annotated tag `git tag -a v3.0.0 -m "Skill Pilot v3.0.0"`, and push `main` and `v3.0.0` to `origin`.
3. **Rollback:** Publish a corrective `v3.0.1` release (or `git revert -m 1 <merge-commit>` on `main` without rewriting published history).
