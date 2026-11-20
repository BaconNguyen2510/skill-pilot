# Skill Pilot v4 Architecture — Development Candidate

**Beta candidate:** `feat/v4-development` carries version `4.0.0-beta.1` for an explicitly authorized **GitHub prerelease only**. Stable `main` remains v3.1.1; no protected main merge, stable v4.0 tag or production deployment is authorized. Real native-host and independent human validation are pending.

The v4.0 host-level contract also includes **goal-persistent source recovery**: external fetch failure is a subtask failure, not permission to abandon an otherwise clear user objective. Recovery uses existing read-only skill discovery and permitted alternative content; no bypass of authentication or unsupported video-content claims.

## End-to-end design

```text
User -> host LLM task triage -> Fast / Guided / Deep
Guided / Deep -> one-question interview + explicit user confirmation
  -> revisioned JSON session (requirements, assumptions, decisions, acceptance)
  -> strict discovery gate (intent, blockers, acceptance, current DAG plan)
  -> plan-search (topological step order, active + dormant + warehouse discovery)
  -> lexical/alias/exclusion retrieval -> bounded on-disk SKILL.md grounding
  -> coverage classification (direct / partial / unverified_fit / none)
  -> revision-bound specification and explicit handoff / review gates
  -> host/user executes only within already-authorized scope -> observed tests
```

## Components and responsibilities

| Component | Purpose | Runtime dependencies |
| --- | --- | --- |
| `skills/skill-pilot/SKILL.md` | Triage, interview, trust boundaries, host instructions | Host model |
| `references/compiler.md` and `pipeline-blueprints.md` | On-demand handoff and domain hints | None |
| `skills/skill-pilot/scripts/skill_scout.py` | Inventory, EN/VI retrieval, exclusion parsing, inspection, promotion and CLI | Python 3.12+ stdlib |
| `skills/skill-pilot/scripts/source_recovery.py` | Read-only goal-preserving source-failure contract and bounded skill-discovery state | Python 3.12+ stdlib |
| `eval/v4_beta_runner.py` and `eval/v4_host_trial_packet.py` | Local reproducible receipts and **unscored** native host test packs | Python stdlib + Git CLI for historical ablations |
| `skills/skill-pilot/scripts/session_planner.py` | Revisioned sessions, readiness, DAG, evidence, lock, specs | Python 3.12+ stdlib |
| `scripts/skill_scout.py` | Repository compatibility entrypoint | Python stdlib |
| `eval/v4_retrieval_ablation.py` | Dev-only candidate ranking comparisons | Python stdlib |
| `eval/v4_host_smoke.py` | Clean-archive CLI tests in two simulated host filesystem layouts | Python stdlib + Git CLI |
| `blind_eval/human_protocol_v4.py` | Blind packets and two-reviewer agreement, not labels | Python stdlib |

## Trust boundaries

- Third-party warehouse descriptions, index entries, headings, and SKILL.md contents are **untrusted data**, not authority. Host-model prompt injection is not solved by keyword detectors.
- Lexical ranking is not semantic capability validation. Exact quotes or headings establish **source presence** only; a `direct` label must not be marketed as independently proven functional fit.
- Search, inventory, intake and inspect do not run third-party scripts. Promotion uses explicit risk and overwrite acknowledgements but does not sandbox a skill.
- State writes use atomic replacement guarded by a session lock; token/PID checking prevents ordinary stale-lock takeover of known live owners. PID reuse, adversarial file mutation and cross-machine network filesystem locking remain risks.
- Evidence reads reject non-regular/symlinked sources and exceedance of the 1 MiB budget. This is a specific DoS/link mitigation, not a general safe parser.
- CI uses a moving v4 development branch without v3 frozen source hash gates; release and main still enforce frozen source hashes.
- Never store sealed benchmark labels, real reviewer data, credentials or private user prompts in this public repository.

## Measurement and verification

1. `tests/`: adversarial, state, security, CLI compatibility and concurrency regressions.
2. `blind_eval/tests/`: synthetic fixtures validate blind-harness integrity, packet format and Cohen kappa; **no independent human judgments** exist.
3. `.github/tests/`: test CI workflow controls.
4. `eval/verify_rc.py`: existing qualification, including frozen holdout nonregression; never tune rankings based on holdout cases.
5. `eval/v4_retrieval_ablation.py`: 80-case physically separated dev snapshot and 32 dev adversarial cases; all 3 weighting prototypes rejected for no demonstrated relevance gain.
6. `eval/v4_host_smoke.py`: `git archive` + fake HOME subprocess smoke for Antigravity/Codex layouts across Windows/Linux and Python 3.12/3.14; no native host LLM execution.

## Release qualification gates

- 4/4 hosted CI cells green at exact final candidate commit, including formatting, lint, type checks, main and blind tests, dev ablation, release verifier and clean-archive smoke.
- Independently curated EN/VI (accented, unaccented, mixed) human-evaluation cases, bilingual raters and separate adjudicator, with pre-registered thresholds and protected custody.
- Actual Codex and Antigravity host installation, weak/strong-model task completion studies, prompt-injection attempts and rollback scenarios.
- Resolve or knowingly accept remaining semantic-fit, lock/TOCTOU and integration risks and document failures honestly.
- **P0 v4.0 blocked-source recovery:** [Issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2) must be resolved **before** v4.0 release. After an inaccessible Facebook/Instagram/TikTok/YouTube link, hosts must preserve the user's original goal, perform relevant authorized skill discovery or record a grounded abstention, disclose non-access without inventing content, and give one useful recovery action instead of a dead end. Require actual native Codex **and** Antigravity traces and independent EN/VI review, not just a SKILL.md prompt check or fake host smoke. See [release gates](V4_RELEASE_GATES.md) and [source recovery research](V4_BLOCKED_SOURCE_RECOVERY.md). **Current status: HOLD.**
- Explicit authorization to modify versions, merge into main, tag or publish. **None has been granted**.

## Architectural debt

The canonical scout remains a large module. A clean modular decomposition is desirable but not urgent enough to risk breaking direct script entrypoints. Decompose only after defining stable interfaces and proving parity via clean-archive smoke and fault-injection benchmarks. Do not add embeddings or agent frameworks until independent relevance and latency tests support the extra dependencies.

## 2026-11-20 evidence provenance evolution

Scoped EN/VI contradiction checking now rejects direct evidence when a relevant source statement denies the requested capability. Markdown code fences (backtick/tilde) and HTML comments are excluded from evidence extraction; heading citations must match exactly. These are bounded stdlib heuristics, not a semantic model or full CommonMark renderer. Source code verified in four-cell CI #44695311575.

## Milestones 17–20: evidence-source integrity (development only)

The stdlib evidence extractor now excludes indented Markdown code and CommonMark type-1 raw HTML blocks, inserts non-whitespace separators when omitting entire blocks to prevent fabricated cross-block exact quotes, and requires coverage for each explicitly conjunctive step-title clause from the **same grounded skill**. Retrieval queries cannot hide a missing title requirement. These are conservative lexical checks, not semantic entailment or a complete CommonMark/HTML parser. GitHub Actions #44699486091 passed across Windows/Linux Python 3.12/3.14.
