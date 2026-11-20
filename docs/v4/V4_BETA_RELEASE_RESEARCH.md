# v4.0.0-beta.1 release automation research and security review

**User approval:** explicitly authorizes a **v4.0 beta prerelease for testing**. This does not authorize a stable v4.0 release, merger into protected main or production deployment.

## Candidate selection (primary sources)

| Strategy | License/dependencies | Performance/fit/risks | Decision |
| --- | --- | --- | --- |
| Same GitHub Actions CI job with `needs: test`, narrow branch + explicit commit marker gate, `gh release create --prerelease`, scoped `contents: write` token | GitHub-hosted Actions/GitHub CLI; no Python runtime dependency | Publishing follows all four OS/Python test cells, no local credentials; platform GitHub runner cost and write permission only for release job | **Selected** |
| Use GitHub connector direct create-tag/create-release action | No runtime packages | Connector only exposes repository/branch writers; no create-release/tag tool here | Not available for this session |
| Third-party [softprops/action-gh-release](https://github.com/softprops/action-gh-release) action | MIT, third-party GitHub Action | Shorter YAML but another trusted supply-chain component, requires pinning and permissions; does not improve actual beta validation | Rejected |
| Manual browser/GitHub CLI release from developer workstation | GitHub CLI (MIT), operator GitHub credentials | Easy in principle, but user requested autonomous delivery, and this session has no local GitHub credentials | Rejected as primary approach |

Primary references: [GitHub Actions workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [GitHub GITHUB_TOKEN trigger behavior](https://docs.github.com/en/actions/concepts/security/github_token), [GitHub prerelease management](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository), and [Agent Skills format](https://agentskills.io/specification).

## Security invariant and release path

Only a push to `feat/v4-development` whose head commit message contains `[beta-release]` may execute `beta_release`. It uses `needs: test` to wait for the **entire 4-cell matrix**, and receives `contents: write` only for that job; global jobs remain `contents: read`. The checkout uses pinned official Actions and `persist-credentials: false`. Python source/release manifest invariants are checked again in the publish job. Release notes explicitly disclose pending native host/human review and stable-release blockers.

The build script permits only whitelisted plugin files and `skills/skill-pilot/` (no sealed eval, arbitrary repository files or machine-local receipts), creates a reproducible ZIP and SHA256 checksum using Python stdlib, and refuses overwriting existing assets. The GitHub-generated source archives provide full tests; historical ablations require **full Git history**.

The release is labeled `v4.0.0-beta.1` and `--prerelease`. Existing releases/tags are **never overwritten**: reruns verify that any existing tag points at the same tested commit. No `main` merge, force push, stable v4 tag, live deployment or sealed data publication occurs.

## Verification limitations

GitHub Actions must actually execute the publish job and return the release URL before claiming publication. CI alone cannot prove model behavior in real Codex or Antigravity hosts; those are user-run **beta acceptance trials** and their receipts remain pending. Repository permission settings may block a write-scoped GITHUB_TOKEN; if that occurs, leave the beta unreleased and report the exact job failure instead of fabricating a release.

Avoid a future automation that republishes a prerelease on every development push; additional candidates should use new beta tag numbers and fresh explicit approval.
