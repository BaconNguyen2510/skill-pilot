# V4 Program — Phase 1 / v3.2 Correctness Audit

Baseline: protected main at commit `2c917158ccc3105804d99552cae0b5daeb461d4a` (v3.1.1), GitHub Actions run `44646874805` (four cells succeeded). This is the frozen starting point, not a reimplementation of the v3.1.1 interview/negation features.

## Source-confirmed failures (before the patch)

1. `compute_readiness` exposed `has_success_criteria: false` yet returned `ready_for_discovery: true` when the other conditions passed.
2. `cmd_plan_search --session` checked `ready_for_planning`, not full discovery readiness; a stale plan or empty success criteria could reach search/persistence.
3. `validate_plan_dependencies` silently collapsed duplicate IDs into a set, accepted empty IDs, and did not return a stable execution order.
4. `run_plan_search` processed caller order rather than dependency order, while its `capability_gap` flag represented only `none` even when `capability_gaps` counted `partial` and `unverified_fit`.
5. `render_specification` trusted discovery missing a revision binding and described partial/unverified candidates as skills rather than qualifying the gap.
6. Changes to acknowledged assumptions, unresolved questions, decisions, or intent confirmation did not consistently invalidate the existing plan/discovery.

## Research-first choices (primary sources; license/dependency/fit)

Three state-machine strategies were compared before implementation:

| Candidate | License | Runtime deps | Performance evidence | Decision |
| --- | --- | --- | --- | --- |
| Python stdlib explicit validated transitions + stable topological sort | PSF, compatible | 0 | Simple O(V+E) graph traversal; actual end-to-end benchmark not measured | **Selected**: incremental, small interface delta |
| [pytransitions/transitions](https://github.com/pytransitions/transitions) | MIT | New Python package | Not benchmarked in this repository | Rejected for strict zero-runtime-dependency invariant |
| [fgmacedo/python-statemachine](https://github.com/fgmacedo/python-statemachine) | MIT | New Python package | Not benchmarked in this repository | Rejected: heavier statechart abstraction than these plain JSON transitions need |

Three locking/persistence strategies were also compared:

| Candidate | License | Runtime deps | Performance evidence | Decision |
| --- | --- | --- | --- | --- |
| Python [`os.open(O_EXCL)`/`os.replace`](https://docs.python.org/3.12/library/os.html) | PSF | 0 | No measured latency delta; rename atomicity applies on successful same-filesystem replacement | **Retain** pending a separately tested lock-ownership fix |
| [tox-dev/filelock](https://github.com/tox-dev/filelock) | MIT | New Python package | Not benchmarked | Rejected for runtime dependency/compatibility constraint |
| [wolph/portalocker](https://github.com/wolph/portalocker) | BSD-3-Clause | New Python package | Not benchmarked | Rejected for runtime dependency/extra platform semantics |

Avoided a large `skill_scout.py` split in the initial patch: direct-script execution, import paths, and cross-host layouts are public compatibility surfaces. A modularization proposal must include fixture-based archive/install tests first.

## Implementation and acceptance

- Enforce full discovery readiness, including success criteria and current plan, without altering the existing one-question interview.
- Invalidate stale recommendations after material interview state changes.
- Reject duplicate/blank plan IDs; emit stable dependency execution order; preserve cycle diagnostics for stand-alone `--plan` analysis.
- Align `covered_steps`, per-step `capability_gap`, and `capability_gaps`; incomplete `partial` coverage is `unverified_fit`.
- Unversioned or stale discovery must not appear as authoritative in `session spec`.

## Limits and follow-up

This phase does not establish semantic capability correctness; exact text present in a skill file can still be irrelevant to a task. The 60-second session-lock stale recovery may still replace a live owner's lock and needs ownership-aware hardening. Benchmark and CI results must be appended only after runs actually complete. No human evaluation was performed.

## Additional session-lock hardening (second Phase 1 milestone)

The old stale lock check unlinked any lock older than 60s, even when its owning process remained active. The new lock stores a random token and process ID, uses a conservative POSIX/Windows liveness check before stale recovery, validates regular-file identity, and only removes a lock whose token still belongs to the current process. Old numeric-PID lockfiles are recognized for safe recovery. Malformed old lockfiles can be recovered after the grace interval, but corrupt *session JSON* is never silently overwritten.

**Residual risks:** PID reuse can conservatively delay recovery; owner identity isn't cryptographically authenticated. Cross-host network filesystem locking and arbitrary hostile concurrent mutation of lock paths are out of scope. OS-level atomic `os.replace` is not equivalent to guaranteed crash-durable directory metadata. These limits must not be described as a security sandbox.
