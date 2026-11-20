# V4 user-intent, skill-selection, and acquisition flow

## Confirmed product problem

The previous v4 contract prevented an unconfirmed goal from reaching
`plan-search`, but it did not represent a second decision after discovery. A
host could therefore treat a ranked skill as permission to use it, skip the
recommendation report, or treat a failed source fetch as the end of the task.
That behavior does not meet the product workflow:

1. interview to understand the user's outcome;
2. confirm the interpreted goal and constraints;
3. discover and inspect relevant skills;
4. report the recommended skill set and wait for confirmation;
5. acquire a missing skill only with separate approval; then execute and report.

## Options considered

| Option | Result | Decision |
| --- | --- | --- |
| Instruction-only interview text | Improves prompts, but provides no observable state that distinguishes discovery from approval | Rejected |
| Existing single `intent_confirmed` flag | Blocks speculative planning, but permits a host to jump from discovery to action | Rejected |
| Two-stage session gate: intent confirmation, then skill-selection confirmation | Keeps discovery read-only and makes the execution precondition observable, invalidatable and testable | Selected |
| Automatically download or enable the highest-ranked missing skill | Treats rank as authorization and expands supply-chain/permission risk | Rejected |

The selected design follows the local `interview-me` skill's one-question and
explicit-intent-confirmation discipline. It also follows OpenAI's guidance to
treat skills as privileged instructions and gate write/high-impact actions with
explicit approval. The acquisition rule is deliberately stricter than skill
selection: approval to use installed skills is not permission to download,
enable, promote or execute an absent one. See [OpenAI Skills safety guidance](https://developers.openai.com/api/docs/guides/tools-skills).

## Implemented contract

- `session init` starts with both `intent_confirmed: false` and
  `skill_selection_confirmed: false`.
- `plan-search` remains unavailable until intent, user-backed requirements,
  unresolved questions, assumptions, success criteria and plan validity are
  ready. Its persisted result always resets skill-selection approval.
- `session approve-selection` succeeds only with current persisted discovery.
  It records a confirmation receipt without changing the goal/plan revision.
- Any material goal, constraint, requirement, assumption, success-criterion or
  plan change invalidates discovery and selection approval.
- `ready_for_execution` is true only when the discovery is current and the
  current skill selection is explicitly confirmed.
- The rendered specification reports `CONFIRMATION REQUIRED` and forbids skill
  execution or installation until that state is reached.

The runtime cannot independently prove that a human gave the confirmation; the
skill instructions require the host to call the state transition only after an
explicit user response. This is an auditable protocol control, not a claim of
host-model enforcement.

## Verification

`tests/test_skill_selection_confirmation_v4.py` proves the following:

1. discovered skills do not make a session execution-ready;
2. explicit selection confirmation does;
3. a material update invalidates that confirmation and discovery;
4. the specification tells the host to stop and wait before execution or
   acquisition.

The existing interview, recovery, session, security and v4 regression suites
remain part of the full release qualification.
