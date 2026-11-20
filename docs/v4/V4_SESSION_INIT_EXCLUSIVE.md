# V4 Session Initialization: Exclusive Create-Only State

Baseline: `feat/v4-development`, exact pre-change verification was four-cell CI #44656105204.

## Observed failure

`cmd_session` used `save_json_file` for `session init`. That helper publishes using `os.replace`, which intentionally overwrites its destination. Running `session init --session existing.json` could therefore replace already-confirmed session state, losing its revision history. Two initializers racing also had no lock around the existence decision.

## Research-first alternatives (primary stdlib docs)

| Candidate | License / runtime dependencies | Latency, platform fit | Decision |
| --- | --- | --- | --- |
| Existing session lock + `exists/is_symlink` check + atomic `save_json_file` | PSF, 0 new deps | Uses the same Windows/Linux owner-aware lock as all session updates; one extra existence check | **Selected** |
| Direct `open('x')` and serialize JSON | PSF, 0 deps | Exclusive create but exposes partially written JSON to readers on crash | Rejected |
| `tempfile.mkstemp` + `os.replace` (previous init) | PSF, 0 deps | Atomic replacement but **clobbers** already-approved sessions | Rejected |
| `tempfile.mkstemp` + `os.link` publication | PSF, 0 deps | Exclusive publication, but relies on filesystem hard links and duplicates existing lock discipline | Rejected for session files; used for blind packets |

Primary references: [Python 3.12 os interfaces](https://docs.python.org/3.12/library/os.html), [Python 3.12 tempfile](https://docs.python.org/3.12/library/tempfile.html). No additional third-party program, framework or license risk is introduced. Runtime difference is constant extra filesystem operations and is not independently benchmarked.

## Acceptance checks

1. Repeated init of the same session path raises `FileExistsError`, preserving the exact stored bytes and revision history.
2. Two real CLI subprocesses concurrently invoking `session init` on the same path yield exactly one success, one rejection, and one complete revision-1 session file.
3. Lock ownership and post-execution cleanup are verified on Windows and Linux by the full four-cell CI.
4. No changes to `main`, releases, tags, sealed eval data, or existing session update/revise behavior.

## Limits

All cooperative CLI writers use the same session lock. A hostile external process ignoring the lock can still mutate the directory, and this patch is not a transactional filesystem security boundary. CI must run after the final edit before any pass is claimed.
