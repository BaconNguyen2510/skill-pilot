# V4 Plan Graph Fail-Closed Discovery

Baseline: `feat/v4-development` at `f6b2ae0981f046bc21c7ee35d2cfb4586763a55a` (CI #44656665375: 4/4 passed).

## Reproduced defect

`validate_plan_dependencies` returned `valid=False` for cycles, duplicate IDs and missing dependencies. However `run_plan_search` still iterated the invalid original plan and invoked the search callback, returning apparent per-step skill recommendations. The standalone `plan-search --plan` CLI then exited with status 0. Non-dictionary steps could raise `AttributeError` before a diagnostic was returned. This violated the explicit readiness gate used for session-backed plans.

## Three evaluated alternatives

| Candidate | Runtime/license | Trade-off | Decision |
| --- | --- | --- | --- |
| Validate DAG, return diagnostics with `discovery_blocked=true`, no callback, CLI exit 1 | Python 3.12+ stdlib / PSF; no new dependency | Fast O(V+E) gate, predictable output; invalid standalone plans cannot yield results | **Selected** |
| Raise `ValueError` on any invalid graph | Python stdlib | Strong rejection, but loses structured graph diagnostics useful to callers | Rejected |
| Auto-repair cycles/missing IDs and continue discovery | Python stdlib | May invent intent, mutate ordering, and mask unsafe dependency errors | Rejected |

Primary reference: [Python 3.12 exceptions](https://docs.python.org/3.12/library/exceptions.html) and [Python 3.12 data structures](https://docs.python.org/3.12/tutorial/datastructures.html). No third-party dependency is warranted for an existing bounded graph validator.

## Behavior and tests

The core returns `dependency_validation`, `discovery_blocked=true`, zero steps and zero covered steps without invoking `search_fn`. The CLI returns nonzero and prints the same diagnostics. Valid plans continue to execute in stable topological order. Malformed non-dict plan items are reported under `invalid_step_indices`, not interpreted as steps. Tests include cycles, missing dependencies, duplicate IDs, non-list dependencies and non-dict entries with a callback that fails if invoked. Existing cycle CLI test is updated to assert the new fail-closed contract.

This is an intentionally breaking correction for callers that previously treated invalid-plan search as successful. No fabricated semantic fit or external-host validation is claimed. Run all four CI cells on the exact change commit before declaring success.
