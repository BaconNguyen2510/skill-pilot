# Skill Pilot v4.0.0

## Release scope

v4.0.0 promotes the v4 recovery and evidence-integrity work into a stable,
host-independent Skill Pilot release. It preserves the original task when a
source is blocked, runs bounded read-only skill discovery, records the access
state as caller-reported, and requests only the missing source material. It
does not scrape login-walled media, bypass access controls, execute discovered
skill scripts, or invent unseen content.

For Guided and Deep work, it now requires a two-stage approval flow: explicit
intent confirmation before discovery, followed by a report of inspected skill
recommendations and explicit selection confirmation before execution. A missing
skill is never downloaded, enabled or promoted from ranking alone; acquisition
requires its own explicit approval.

## Qualification model

The stable release is qualified by executable repository contracts, not by
claims about a particular AI host. `eval/v4_release_qualification.py` requires:

- aligned `4.0.0` manifests and CLI version;
- the complete offline regression, blind, workflow, benchmark and source-boundary matrix;
- pinned Ruff format and lint checks;
- two byte-identical allowlisted plugin archives and a checksum.

The qualification intentionally makes no assertion that Codex, Antigravity, or
any other host loaded or interpreted the skill. Host behavior remains outside
this release's verified scope.

## Security and compatibility

The runtime remains Python 3.12+ standard library only. The package is built
from a tracked-file allowlist and excludes Git metadata, sealed evaluations,
local receipts and arbitrary workspace files. The release workflow is manual,
main-only, requires the literal `publish-v4.0.0` confirmation, reruns the
qualification on the exact candidate, and refuses to overwrite a tag or
release.
