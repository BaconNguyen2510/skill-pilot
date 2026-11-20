# V4 beta validation report

## Scope and evidence boundary

This report records local validation of `v4.0.0-beta.1` and the follow-up
development-fixture expansion on `feat/v4-beta-validation`. It does not claim a
stable release, independent human evaluation, native Codex behavior, or native
Antigravity behavior.

The reported Facebook-reel failure is a symptom report, not proof of an omitted
hidden tool call. The deterministic recovery command was run with a
caller-reported `403`; it preserved the idea-evaluation goal, fetched no source,
bypassed no access control, performed one read-only local capability lookup, and
requested source material. Its output is not a video inspection or host trial.

## Development test matrix

`eval/v4_blocked_source_scenarios.jsonl` contains 28 synthetic development
cases. All use `actual_host_result: null`; none is a human label, holdout, or
native-host result.

| Coverage | Cases |
| --- | --- |
| Languages | English, Vietnamese, Vietnamese without diacritics, mixed |
| Platforms | Facebook, Instagram, TikTok, YouTube, generic media |
| Access states | 403, 404, login wall, deleted, timeout, rate limit, unsupported, unknown |
| Recovery inputs | no material, public caption/transcript, screenshot/storyboard, partial metadata |
| Discovery risks | available, absent, disabled, overclaiming, suspicious skill instructions |
| Goal state | clear goal and deliberately ambiguous goal |

The fixture checks deterministic decision routing only. It does not assert that
a host read a candidate `SKILL.md`, called a media tool, or judged an unseen
video correctly.

## Baseline verification

The isolated beta checkout was verified at
`878fc95e4139d593ebd5d4b4df9330b37862a3ef` with local receipts stored outside
the repository. The full beta runner passed on Python 3.12.10 and Python 3.14.2:
251 main tests (two Windows skips), 40 blind-tooling tests, 10 workflow tests,
the release verifier, seven synthetic development ablations, and simulated
clean-archive host smoke. Ruff 0.17.5 reported 114 formatted files and no lint
findings. These results are local and pre-change; final branch verification must
be rerun after the fixture commit.

The expanded v4-focused discovery suite passed 38 tests on Python 3.12.10 and
Python 3.14.2. After commit `c3461beb1a898a9868b5c5b998efa11a42ec7b48`, the
complete offline beta runner passed all 13 configured checks on each runtime.
Ruff was run separately because the runner correctly reports it as `not_run`
when it is not globally installed; `uvx` Ruff 0.17.5 then passed format and
lint across 115 files. The fixture work also caught and corrected a
fixture-format hazard: JSONL must remain one JSON object per line and is not
passed to Ruff's JSON formatter.

## Native-host receipts

One fresh Codex CLI session was executed against a project-local beta skill. It
identified the catalog entry but host shell policy rejected both reads of the
candidate `SKILL.md`; no valid capability discovery or candidate-skill inspection
occurred. It is a **FAILED native acceptance**, not a pass. The redacted receipt
and a precise Antigravity procedure are in
[V4_NATIVE_HOST_RECEIPTS.md](V4_NATIVE_HOST_RECEIPTS.md). The Codex packet is
prepared outside the repository with 28 unscored prompts and an empty review
template.

No Antigravity command-line host was found. No graphical controlled trial or
loaded beta skill was observed. Therefore **native Antigravity is NOT RUN**. Its
matching 28-case packet is prepared outside the repository.

## Security and compatibility review

The recovery command is stdlib-only and makes no network request. It records the
source status as caller-reported, redacts URLs from output, rejects URLs as skill
queries, does not execute discovered skill scripts, reports unavailable lookup
truthfully, and records `source_content_fetched: false` plus
`access_control_bypassed: false`. The selected instruction-plus-bounded-scout
approach remains preferred over Playwright/browser bypass and a new orchestration
framework because it preserves the zero-runtime-dependency invariant and does
not expand access-control surface. See `V4_BLOCKED_SOURCE_RECOVERY.md` for the
full alternatives and rejected options.

## Release readiness

The beta evidence remains historical. The current stable candidate is qualified
through the host-independent executable contract in
[V4_RELEASE_GATES.md](V4_RELEASE_GATES.md). Native-host and human-review
materials are not used as release evidence and no claim about them is made.
