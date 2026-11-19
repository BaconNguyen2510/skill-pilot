# Skill Pilot v3.0 Release Qualification Package (`Phase BO–BR`)

- **Public Release Foundation:** `ci/v3-public-safe` (hosted CI `4/4` passed at `099bc5d5ac1b34741d8a68afe4b39d485140a4b2`, Run [#44624700661](https://github.com/BaconNguyen2510/skill-pilot/actions/runs/44624700661); evidence archived at `0c84950f7fd68e3a48b5a8c7072fbdffc205e7ae`)
- **Frozen Candidate:** `2c8daab7ae7a8b06dcfc64863c4043183fd35261` (`32/32` canonical Git-blob equivalence preserved)
- **Current Gate:** **GO** for independent evaluator onboarding and release preparation; **HOLD** for `v3.0.0` publication

---

## 1. Independent Evaluator Onboarding & Custody (`Workstream 1`)

- **Team Structure (Currently `Not appointed`):**
  1. Two independent EN/VI annotators (unfamiliar with `eval/queries.jsonl`, `eval/dev_v2_challenge.jsonl`, and `eval/sealed_queries.jsonl`).
  2. One separate independent adjudicator / evaluation lead.
- **Independence & Acceptance Checklist:**
  - [ ] Signed conflict-of-interest and prior-exposure declaration for each annotator and adjudicator.
  - [ ] Written acceptance of `blind_eval/SCHEMA.md` and `blind_eval/README.md` (two-stage prediction/scoring contract, `>= 200` cases, `>= 50` per `en`/`vi`/`vi_no_diacritic`/`mixed`, `>= 40` abstention, `>= 40` multi-intent).
  - [ ] Custody separation: sealed labels (`labels.jsonl`) stored in a separate access-controlled location from the prediction runner until `predictions.json` and its SHA-256 receipt are finalized.

## 2. One-Shot Blind Evaluation Readiness (`Workstream 2`)

- **Frozen Candidate Binding:** `blind_eval/harness.py` exports `ARCHIVE_PATHS` via `git archive` (`core.autocrlf=false`, `core.eol=lf`) and enforces all `7` pinned SHA-256 digests (including `skill_scout.py` `95c8fe505ba3214788c0ba51e850ee5913bfeb376102f0e9ab8ef89eb8ced3d3`).
- **Leakage Prevention:** `predict()` accepts only unlabeled `queries.jsonl` + lowercase 64-hex `label_sha256` commitment, screens against exposed datasets, and reserves `final-<candidate>` atomically (`exist_ok=False`). `score()` consumes `scoring.started` before reading `labels.jsonl` and verifies `predictions_sha256`, `config_sha256`, and `labels_sha256`.
- **Execution Rule:** **Not executed** until independent data and custody are supplied.

## 3. Final GO/NO-GO Checklist, Merge Strategy & Rollback (`Workstream 3`)

- **Public Release Source Tree:** Use **`ci/v3-public-safe`** as the sole foundation for `v3.0.0` on public `main`. **Never** merge `feat/v3-research-program` into `main`, so `eval/sealed_queries.jsonl` and `docs/v3/SEALED_EVAL_REPORT.json` never enter public history.
- **GO/NO-GO Criteria (All Required Before `REL-09`):**
  - [x] `4/4` Hosted Ubuntu/Windows x Python `3.12`/`3.14` CI passed (`099bc5d`, Run `#44624700661`).
  - [ ] Independent final blind evaluation completed once and dispositioned (including `NEG-01` clause-scoping boundary and diagnostic `recall@5_diff = -0.0076`).
  - [ ] Separate explicit user authorization for version alignment (`3.0.0` across `skill_scout.py.__version__`, `plugin.json`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, and `tests/test_skill_scout.py:874`), merge into `main`, and annotated tag `v3.0.0`.
- **Rollback Plan:** If any post-merge defect is found on `main`, revert the merge commit on `main` or restore `v2.1.1` (`7d173bf88bdb2f07eeb2e9d7a6382e540ba96b4d`).
