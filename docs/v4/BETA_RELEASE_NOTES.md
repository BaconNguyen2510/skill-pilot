# Skill Pilot v4.0.0-beta.1

**Public testing beta — not production/stable v4.0.**

This prerelease exposes the accumulated v4 development work for actual Codex/Antigravity installation, reproducible offline testing and independent EN/VI evaluation.

## Included

- Correctness/reliability hardening: session state, readiness, concurrency, graph validation and stale discovery.
- Zero-external-runtime-dependency lexical retrieval and conservative evidence provenance; Unicode EN/VI exclusion and contradiction checks, Markdown/HTML hidden-source handling and composite capability checks.
- Blind human-review packet tooling (synthetic harness tests are **not** independent human evaluation).
- **New** `recover-source` CLI for goal-preserving fallback after blocked videos/articles/images, with read-only local skill discovery and truthful content-access status.
- **New** `eval/v4_beta_runner.py` offline test/benchmark receipts and `eval/v4_host_trial_packet.py` for unscored native host evaluations.
- Reproducible plugin ZIP and SHA256 checksum, plus GitHub-generated complete source archives.

## Known limits

**Issue #2 remains open:** native Codex and Antigravity model traces, source-access recovery behavior, and independent bilingual human review are not yet verified. No success on those gates is implied. Existing tests use simulated host layouts and synthetic development fixtures. Skill Pilot cannot guarantee access to Facebook or other login-walled media and must never bypass restrictions or invent content.

**Stable main remains v3.1.1**. This prerelease is tagged from the v4 development branch only. No stable v4.0 tag, protected main merge or deployment.

## Recommended testing

Read [beta installation and testing](docs/v4/BETA_INSTALL_AND_TEST.md). For complete historical dev ablations clone this tag with **full Git history**; the plugin ZIP alone does not contain benchmark sources. Use `python eval/v4_beta_runner.py` and then generate a Codex/Antigravity trial packet. Keep raw private tool traces local.

Feedback: [v4.0 goal persistence release blocker #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2).
