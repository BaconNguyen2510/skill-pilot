# Skill Pilot v3.0 Public-Safe CI Branch & Disclosure Audit (`Phase BC–BF`)

- **Sanitized CI Branch:** `ci/v3-public-safe` (constructed directly from public baseline `origin/main` at `7d173bf88bdb2f07eeb2e9d7a6382e540ba96b4d`)
- **Preserved Development Branch:** `feat/v3-research-program` at `7a044383840c395c96835579e7313313420418a1` (`17` commits ahead of `origin/main`, untouched)
- **Original Frozen Candidate:** `2c8daab7ae7a8b06dcfc64863c4043183fd35261` (historical superseded baseline `f3cc0c0fb405f35b8692de6c0062293b90e111e7`)
- **Push / Remote CI Status:** **NOT EXECUTED** (awaits explicit user authorization for `ci/v3-public-safe`)

## 1. Phase BC: Full-History Disclosure Audit (`origin/main..feat/v3-research-program`)

All `17` outgoing commits (`8daee54` through `7a04438`) and all `83` distinct changed file paths were audited:

| Classification | Count | Paths / Scope | Disposition on `ci/v3-public-safe` |
| :--- | ---: | :--- | :--- |
| `PUBLIC_SAFE` | `46` | `32` frozen candidate files (`skills/skill-pilot/**`, `tests/**`, `eval/**` minus `sealed_queries.jsonl`, `plugin.json`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`) + `blind_eval/**` (`6` files) + `.github/**` (`2` files) + `docs/v3/v2_1_0_eval_baseline.json`, `docs/v3/PROMPT_BENCHMARK.json`, `docs/v3/PROMPT_BENCHMARK_REPORT.md`, `docs/v3/FROZEN_GIT_BLOB_HASHES_V3.json`, `docs/v3/PUBLIC_SAFE_CI_READINESS_V3.md`, `.gitignore` | **Included** |
| `SEALED_EVALUATION` | `2` | `eval/sealed_queries.jsonl` (`2a5bfae221761fe965a80e9ef5e190775fbe2d0f38492a12e9fb38f4681ddc74`), `docs/v3/SEALED_EVAL_REPORT.json` (introduced in `2dbdc51`) | **Excluded & Gitignored** (zero reachable objects from `ci/v3-public-safe`) |
| `INTERNAL_ONLY` | `35` | Internal sprint status, experiment ledgers, local host config SHA tables, and draft evaluator packets under `docs/v3/` | **Excluded** (retained locally on `feat/v3-research-program`) |
| `SECRET` | `0` | Verified zero private keys, GitHub/AWS/Slack/OpenAI tokens, or credentials across all `17` commits | **None present** |
| `UNKNOWN` | `0` | All `83` paths classified | **None remaining** |

## 2. Phase BD & BE: Candidate Equivalence (`32/32` Canonical Git Blobs)

- Every one of the `32` public-safe frozen candidate files in `docs/v3/FROZEN_GIT_BLOB_HASHES_V3.json` has the exact same canonical Git-blob SHA-256 digest (`git show HEAD:<path>`) as in `2c8daab7ae7a8b06dcfc64863c4043183fd35261`.
- Only `eval/sealed_queries.jsonl` (`1` of the original `33` frozen files) is intentionally excluded to prevent public disclosure.
- No candidate runtime source (`skills/skill-pilot/scripts/skill_scout.py`, SHA-256 `95c8fe505ba3214788c0ba51e850ee5913bfeb376102f0e9ab8ef89eb8ced3d3`), candidate unit test (`tests/test_*.py`), public evaluation harness (`eval/*.py`), or distribution manifest (`2.1.1`) was modified.
- `blind_eval/harness.py` archives from `CANDIDATE` when present locally and falls back to `HEAD` in public CI while enforcing the pinned `skill_scout.py` SHA-256 (`95c8fe505ba3214788c0ba51e850ee5913bfeb376102f0e9ab8ef89eb8ced3d3`).

## 3. Phase BF: CI Workflow & Local Verification

- `.github/workflows/ci.yml` triggers on `push` to `[main, feat/v3-research-program, ci/v3-public-safe]`, uses `permissions: contents: read`, pins actions by commit SHA, verifies `32/32` canonical Git-blob hashes at `HEAD`, asserts `eval/sealed_queries.jsonl` and `docs/v3/SEALED_EVAL_REPORT.json` are absent from `git ls-files`, and runs the 4-cell matrix (`ubuntu-latest`, `windows-latest` x Python `3.12`, `3.14`).
- **Exact Proposed Future Push Command (NOT EXECUTED):**
  ```powershell
  git push --set-upstream origin ci/v3-public-safe:refs/heads/ci/v3-public-safe
  ```
