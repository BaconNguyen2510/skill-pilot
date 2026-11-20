# v4 Correctness Follow-up — Plan Freshness and Cross-Process Locks

Baseline: `feat/v4-development` at `ccb300b8ff25da316cd5aa3eafe33bbc1ebb11e7`, four-cell Actions run #44652886389 passed. No release-version changes authorized.

## Reproduced source defects

- `update_session` treated the **presence** of `plan_steps` in any patch (including `[]`, a malformed object, or a merge of unchanged steps) as evidence of a newly approved plan. This could clear `plan_stale` and cause outdated plans to be searched after requirements changed.
- `compute_readiness` defaulted `intent_confirmed` to true on older/malformed session JSON without that field.
- `persist_discovery_to_session` checked session ID/revision but not readiness under its lock, allowing callers bypassing CLI preflight to save discovery for an unready session.
- On Windows, `ctypes.WinDLL` calls returned an untyped `OpenProcess` `HANDLE` via default C `int`, potentially truncating 64-bit handles. `GetExitCodeProcess` returning `STILL_ACTIVE` can also be ambiguous with an actual exit code 259.

## Primary sources and alternatives — state transitions

| Candidate | License/deps | Latency/fit | Decision |
| --- | --- | --- | --- |
| Existing stdlib explicit transitions + irreversible stale until new or explicitly replaced nonempty plan | PSF, zero runtime deps | O(number of changed fields), no runtime bootstrap; measured CI still required | **Selected**; minimal safe compatibility change |
| [pytransitions/transitions](https://github.com/pytransitions/transitions) state machine | MIT, new runtime package | Rich transitions; migration cost and unnecessary dependency | Rejected |
| [fgmacedo/python-statemachine](https://github.com/fgmacedo/python-statemachine) | MIT, new runtime package | Declarative schema, added dependency and cross-platform package validation | Rejected |
| Ignore `plan_stale` and infer freshness from a matching score | Stdlib only | Unsound; scores measure relevance not user-confirmed intent | Rejected |

## Primary sources and alternatives — cross-process liveness

| Candidate | License/deps | Latency/fit | Decision |
| --- | --- | --- | --- |
| Windows `ctypes.WinDLL` correctly typed `OpenProcess(SYNCHRONIZE)` + nonblocking `WaitForSingleObject`; POSIX `kill(pid, 0)` | PSF/std-lib, zero new deps | Nonblocking OS probe, only on lock contention; measured CI needed | **Selected** |
| `GetExitCodeProcess` with typed handles | Win32 API, stdlib `ctypes` | Still ambiguous when a terminated process exits with code 259 | Rejected |
| [psutil](https://github.com/giampaolo/psutil) process-state probes | BSD-3-Clause, external native dependency | Ergonomic, but installation/platform build and licensing review needed | Rejected |
| `tasklist` / shell subprocess polling | OS-specific, stdlib subprocess | Process creation/locale overhead and parsing failures | Rejected |

Primary specs: [Python 3.12 ctypes](https://docs.python.org/3.12/library/ctypes.html), [Microsoft OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess), [Microsoft WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).

## Verification plan

Add deterministic negative tests for empty/malformed/merge-only plan patch, explicit replacement, missing confirmation, discovery persistence bypass, and live/dead **separate-process** PID recovery on both Windows and POSIX. No simultaneous multi-host filesystem locking claim. No holdout tuning.

CI passes/failures and exact SHA must be added only after executing the final edit. Release/version/main history remains untouched.
