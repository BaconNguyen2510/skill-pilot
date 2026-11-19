# Handoff compiler

First read the applicable project rules and named source files. Run the scout's `intake` for a known project root, then inspect its rule and test pointers. If inspection fails, report what is missing; do not invent a root cause, file, command, or output.

Output one copyable prompt in the user's language. Front-load outcome, target state, exact scope, prohibited actions, and actual stop/approval conditions; then add evidence pointers, constraints, actions, and done criteria. Label reported symptoms separately from observed facts and hypotheses. For reasoning models use a concise Outcome / Scope / Done schema with a clear depth requirement. For a weak or fast model use a flat ordered checklist: inspect listed files, perform each bounded action, run the verified command, and report observed output or an explicit inability to verify. Do not request hidden chain of thought.

Micro-example (illustrative, never substitute for project evidence):

```text
Outcome: fix the reported login failure in src/login.py. Scope: that file and its tests.
Reported symptom: login fails. Cause: unknown; reproduce before deciding.
Inspect: src/login.py and the applicable project rules. Verify: use the documented login test command; report actual output, or say it could not run.
```

Preserve source pointers and user restrictions when compressing context. Do not output both an execution contract and a second copy of the prompt. If a requested target tool cannot inspect files, tell the recipient what verified input to provide and mark unverified items explicitly.
