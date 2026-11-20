# Skill Pilot v4.0.0-beta.1 — Prerelease candidate verification

**Candidate tag:** `v4.0.0-beta.1` (prerelease, **not** stable v4.0.0).

## Verified prepublication source

Development head before the explicit release-trigger commit: `30fcb600af5de412138f62e0b31ad1603cc24fa6`.

[Four-cell CI #44707215737](https://github.com/BaconNguyen2510/skill-pilot/actions/runs/44707215737): **4/4 passed** on Ubuntu and Windows with Python 3.12/3.14. Release job deliberately **skipped** on this non-release-marked commit.

Ubuntu Python 3.12 verification:
- `ruff format --check .`: passed in CI.
- `ruff check .`: passed in CI.
- Configured `ty`: passed in CI.
- `python -m unittest discover -s tests`: **251 passed**.
- `python -m unittest discover -s blind_eval/tests`: **40 passed**.
- `python -m unittest discover -s .github/tests`: **10 passed**.
- `eval/verify_rc.py`: all configured checks passed, including the unchanged historical holdout qualification. This is **not** a new ranking-improvement metric.
- Seven independent synthetic v4 evidence/retrieval dev ablations: passed their configured nonregression gates.
- `eval/v4_host_smoke.py`: passed **simulated** Codex/Antigravity clean-archive layouts. This does **not** count as native host-model testing.
- Reproducible plugin ZIP/package allowlist and create-only receipt tests passed.

## Release automation guard

A final commit explicitly marked `[beta-release]` triggers the same four-cell matrix again. The `beta_release` job runs **only after all four cells pass**, and is the only job with `contents: write`. It packages `v4.0.0-beta.1`, publishes a **prerelease** with checksum and immutable tag target, and refuses overwriting any existing release tag pointing at a different commit.

The **final beta tag SHA and Actions run** must be verified from the actual publish job. Prepublication source verification above is not a substitute for that final check.

## Open stable-v4 release blockers

- [Issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2): actual goal-persistence and blocked-link skill-discovery behavior in native Codex and Antigravity sessions remains **NOT VERIFIED**.
- Independent real EN/VI human review remains **NOT COMPLETED**.
- The beta offers deterministic `recover-source` CLI and local trial packet generator to gather those observations.

No stable `main` merge, production deployment or `v4.0.0` release is authorized. Stable `main` remains v3.1.1 at `2c917158ccc3105804d99552cae0b5daeb461d4a`.

## User test handoff

Read [BETA_INSTALL_AND_TEST.md](BETA_INSTALL_AND_TEST.md) before installing in an isolated test workspace. The full benchmark suite requires a full Git clone (not shallow). The plugin ZIP is a separate distribution artifact. Human or model trial success cannot be inferred from this prerelease being downloadable.
