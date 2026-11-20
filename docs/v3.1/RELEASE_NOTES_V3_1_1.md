# Skill Pilot v3.1.1 Patch Release Notes

## Fixes
- **Adaptive Interview Gate (`skills/skill-pilot/SKILL.md`):** Enforces one-question-per-turn stop-and-wait when material ambiguity remains, optionally paired with a `GUESS:` that is never treated as user confirmation. Preserves an abbreviated path for detailed, unambiguous prompts.
- **Runtime Confirmation Provenance (`session_planner.py`, `skill_scout.py`):**
  - `init_session()` sets `intent_confirmed: false`.
  - `update_session()` demotes any `confirmed_requirements` entry with `source` in `("agent_guess", "guess", "inferred", "assumption")` into unacknowledged `assumptions`.
  - `plan-search --session` fails closed (`DISCOVERY_BLOCKED_UNCONFIRMED_INTENT`) until `ready_for_planning` (`intent_confirmed: true`) is satisfied.
- **Behavioral Regression Tests (`tests/test_interview_gate.py`):** Verified guess demotion, pre-confirmation discovery blocking, and post-confirmation unblocking, alongside live EN/VI host-agent stop-and-wait tests.
