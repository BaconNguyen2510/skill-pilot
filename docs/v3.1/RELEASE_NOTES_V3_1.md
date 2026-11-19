# Skill Pilot v3.1.0 Release Notes

## 1. What's New in v3.1.0
- **Vietnamese `trừ` & Exclusion-Scope Handling (`skill_scout.py`):**
  - Added Unicode-aware `_VI_UNICODE_TRU_RE` (`\btrừ(?:\s+ra)?\b`) with NegEx-inspired pseudo-negation guards (`phép trừ`, `toán trừ`, `trừ khi`), plus `trừ ra`, `không tính`, and `chứ không phải` cues.
  - Added `"dung"` (`dùng`) to `STOP_WORDS` so conflicting Vietnamese intents (`"dùng react trừ react"`) abstain cleanly.
  - Resolved `test_17_vietnamese_tru_negation` (`@unittest.expectedFailure` removed) and added 10 Vietnamese exclusion/pseudo-negation tests (`tests/test_vietnamese_intent_v31.py`).
- **Exact-Quote / Exact-Heading Capability Grounding (`session_planner.py`):**
  - `verify_capability_evidence()` now requires an exact quoted passage (`>= 12` chars) or exact heading match from the inspected `SKILL.md` on disk (rejecting scattered token overlap and title-only claims by downgrading `direct` to `unverified_fit`).
- **Research-First Engineering Policy (`AGENTS.md`):**
  - Codified the 7-step Research-First workflow (`docs/v3.1/VIETNAMESE_NEGATION_RESEARCH.md`, `docs/v3.1/SKILL_RECOMMENDATION_RESEARCH.md`).

## 2. Shipped Behavior vs. Experimental Benchmarks
- **Production Behavior (`SKILL.md` + `skill_scout.py`):** Structured Vietnamese-to-English query translation is **not** enforced by `SKILL.md` in `v3.1.0`; it remains an **experimental** benchmark (`eval/vi_translation_eval_v31.py`, 8 untouched queries). Do not treat that 8-query experiment as general multilingual retrieval proof.
- **Static Glossary Expansion Rejected:** Excluded from production after isolated dev benchmarking (`eval/vi_retrieval_prototype.py`) showed `forbidden@5` worsened from `0.2778` to `0.3889`.

## 3. Known Limitations & Pending v3.2 Milestone
- **Independent Human EN/VI Evaluation Pending (`v3.2`):** `docs/v3.1/HUMAN_EVAL_PROTOCOL_V3_1.md` is ready, but no external human annotators have executed it yet. `v3.1.0` ships on the automated engineering gates; human evaluation is tracked for `v3.2`.
- **Provenance & Confidentiality:** Preserves `v3.0.0` (`d7e845c`) and historical `2c8daab` provenance; `0` sealed evaluation artifacts or `feat/v3-research-program` history in `main`.
