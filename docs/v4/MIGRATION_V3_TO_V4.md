# Migration: Skill Pilot v3.1.1 to v4 Development Candidate

**This is not a released v4.0.0 package.** The active public version remains v3.1.1; do not change production installations based on an unreleased development branch.

## Compatibility retained

- Python 3.12+ standard-library-only runtime, standalone skill and repository wrapper entrypoints.
- CLI names: `doctor`, `inventory`, `intake`, `search`, `inspect`, `promote`, `validate`, `session`, `plan-search`, and existing flags.
- Codex/Antigravity active skill folders, optional skill warehouses, and score-tier architecture.
- Fast/Guided/Deep host instructions and explicit one-question interview gate.

## Important behavior changes

1. `ready_for_discovery` now requires confirmed intent, success criteria, resolved blockers and a **current, valid** dependency-aware plan. Missing prerequisites return `DISCOVERY_BLOCKED_NOT_READY`.
2. Material interview-state changes invalidate prior plans or discoveries unless the patch supplies an explicit replacement plan. Never falsely set `intent_confirmed` to unblock progress.
3. Duplicate or blank plan IDs are invalid; valid plans expose stable topological `execution_order`.
4. `partial` without explicit missing capability details downgrades to `unverified_fit`; anything below `direct` appears as a review gap.
5. `session spec` rejects unversioned or stale discovery, shows execution order and tells the host when review is still required.
6. Reading skill evidence now rejects symlinks/nonregular inputs and caps at 1 MiB, potentially downgrading previously accepted oversized files.
7. Session lock files use a token and PID. Abandoned-lock recovery is conservative; old long-running live sessions no longer lose a lock solely by time.
8. Recognizable instruction override strings in skill-search descriptions are flagged/withheld; absence of such flags is not a security approval.
9. Development-only ablation and blind human-eval tooling have been added without changing the production ranking implementation.

## Validation commands

Run on a **temporary checkout**, never directly against production skill folders:

```bash
python -m unittest discover -s tests
python -m unittest discover -s blind_eval/tests
python -m unittest discover -s .github/tests
python eval/verify_rc.py
python eval/v4_retrieval_ablation.py
python eval/v4_host_smoke.py
```

Ruff and the type checker are **development/CI tools**, not runtime dependencies. Versions are pinned in `.github/workflows/ci.yml`. The archive smoke needs a local Git executable.

## Session migration

Review existing JSON sessions manually. If a session has no success criteria, get genuine user confirmation first. Any changed goal requires explicit updated requirements, a replacement plan, readiness recheck, and new `plan-search`. Do not recycle unversioned `last_discovery` output.

## Rollback

Protected `main` remains on v3.1.1 at `2c917158ccc3105804d99552cae0b5daeb461d4a`. Rollback any disposable development install to the pre-upgrade skill and saved session data. The v4 branch cannot become an official release without an independently evaluated candidate and separate authorization.

## Deferred / unsupported

Native host model behavior, actual external human annotation, semantic evidence correctness and live deployment safety remain unverified. No high-level 'production ready' claim is justified yet.

## New development-candidate evidence behavior

As of v4 development commit `be8e9ee965d995c7853803fc3fe913e7e9256827`, source-backed direct coverage excludes Markdown fenced examples and hidden HTML comments, requires exact heading citations, and fails closed on relevant EN/VI contradictions. Old plans relying on these weaker source strings may downgrade to `unverified_fit` and require reinspection. This change is not published in v3.1.1.

## Additional unreleased v4 evidence behavior (milestones 17–20)

Indented Markdown and raw HTML literal-content examples are no longer credited as direct capability evidence. A direct composite step containing explicit conjunctions (`and`, `và`, `&`, `+`) now requires source-backed grounding for each clause **within one skill**. Omitted code/HTML blocks form provenance boundaries, so quotes cannot span removed blocks. Some previous `direct` assessments may legitimately downgrade to `unverified_fit`; they require reinspection, not automatic overrides. No change has been published in v3.1.1.
