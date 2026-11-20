# v3.4 Clean-Archive and Dual-Host Smoke-Testing Strategy

The program must not mistake mocked filesystem layouts for real Antigravity/Codex model behavior. This smoke test launches each CLI command as a separate subprocess with an isolated fake HOME on both CI operating systems and Python 3.12/3.14.

## Research and choices

| Candidate | License/dependencies | Latency and functional trade-off | Decision |
| --- | --- | --- | --- |
| [Python stdlib tarfile](https://docs.python.org/3.12/library/tarfile.html) with `filter="data"`, subprocess and tempfile | PSF; zero Python runtime deps; Git CLI already used in release tooling | Directly tests `git archive` output and supported OS in CI; startup per subprocess | **Selected**, expected low seconds total, performance evidence from CI only |
| [pytest](https://github.com/pytest-dev/pytest) + tmp_path | MIT; adds pytest dependency to dev test runner | Better fixtures and parametrization; not needed for one deterministic smoke | Rejected for simpler stdlib CI integration |
| [Docker CLI](https://github.com/docker/cli) orchestration | Apache-2.0, requires container engine/host setup | Stronger Linux environment isolation; Windows native plugin layout not faithfully covered | Rejected for cross-host matrix |
| Native Antigravity/Codex host UI automation | Different host binaries/authentication, not provisioned in public CI | Highest fidelity; may require credentials and non-public tool permissions | Deferred: no unsupervised host capability claims |

## Verified operations demanded

The test launches `doctor`, `inventory`, `intake`, `inspect`, `promote --dry-run`, `session init/update`, `plan-search`, and compatibility-wrapper `--version` on a clean Git archive. Skills are created under both fake Antigravity and Codex locations. No real HOME, production skill directories, network discovery or scripts are modified. No actual installation or promotion occurs.

This does not test actual interactive LLMs or true host plugin loading. Record CI result and any failures before calling the matrix verified.
