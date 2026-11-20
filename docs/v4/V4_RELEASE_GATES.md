# Skill Pilot v4.0 — executable-contract release qualification

## Decision and scope

The release qualification is intentionally **host-independent**. Native Codex
and Antigravity trials are not release gates for v4.0.0 and must not be run or
represented as evidence for this release. A host may apply its own policy,
prompting, tools and skill-discovery rules, so a repository test cannot prove
that host's model behavior. Conversely, a host-policy denial does not establish
a defect in this package.

The release claims only what its executable contracts prove: portable Python
CLI behavior, source-boundary protections, bounded recovery decisions, version
parity, package contents and reproducibility. It does **not** claim model
obedience, arbitrary-host compatibility, access to third-party media, or human
judgment of unseen content.

## Required stable gates

| Gate | Required evidence | Pass condition |
| --- | --- | --- |
| Version integrity | `skill_scout doctor` | CLI and all three manifests are exactly `4.0.0` and agree |
| Correctness | Offline regression matrix | Main, blind and workflow suites plus RC verifier pass on the candidate |
| Retrieval and evidence safety | Frozen development ablations and historical holdout qualification | Each configured non-regression gate passes; no sealed data is exposed |
| Blocked-source recovery | 28 synthetic EN/VI development cases and deterministic CLI tests | Preserve a known goal, perform bounded read-only discovery, do not fabricate or bypass access control, request one necessary input |
| Formatting and lint | Pinned Ruff `0.17.5` | `format --check` and `check` both pass |
| Package integrity | Two fresh builds | Byte-identical, allowlisted ZIP archives and checksum |
| Release control | Manual GitHub workflow | Main-only, literal confirmation, exact-candidate qualification, and no tag/release overwrite |
| Documentation | Release notes and handoff | Scope and limits accurately describe the verified contract |

`eval/v4_release_qualification.py` writes a create-only local receipt for
these gates. The manual `stable-release.yml` workflow repeats the qualification
on `main` before creating `v4.0.0`.

## Explicit non-gates

- Native Codex or Antigravity UI/CLI trials.
- Real social-media retrieval or login-wall circumvention.
- Independent human labels or claims about model reasoning.
- Any browser automation, paid API, host-policy bypass, or untrusted skill execution.

The prior beta host-trial materials are historical development artifacts. They
remain clearly non-evidence and are not a release blocker.
