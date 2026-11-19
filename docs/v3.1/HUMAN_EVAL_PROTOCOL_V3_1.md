# EN/VI Independent Human-Evaluation Protocol (`v3.1`)

## 1. Purpose & Blindness Rules
- Evaluate real-world skill recommendation quality across English and Vietnamese queries without leaking retrieval method identity or automated scores.
- **Blindness:** Annotators receive only `(query_id, language, anonymized_query, candidate_skills, skill_md_excerpts)` with all retrieval scores, method names, and AI-generated assessments stripped.

## 2. Evaluation Dimensions (Per Query & Recommended Skill)
1. **Recommendation Relevance (0–3):**
   - `3`: Directly enables execution of the requested step.
   - `2`: Useful partial/supporting guidance.
   - `1`: Tangentially related; noisy.
   - `0`: Irrelevant or wrong domain.
2. **Actual Capability Fit (`direct` | `partial` | `none`):** Whether the inspected `SKILL.md` actually provides actionable instructions for the step.
3. **Evidence Quality (`verified` | `weak` | `unsupported`):** Whether cited quotes/sections in `SKILL.md` genuinely support the claimed capability.
4. **Missing Capabilities:** Free-text list of essential task capabilities absent from all recommended skills.
5. **Inappropriate / Unsafe Recommendations:** Flag any skill that violates user exclusions (`not`, `except`, `không`, `trừ`) or introduces unsafe/off-scope instructions.

## 3. Annotator Structure, Agreement & Adjudication
- **Team:** Two independent bilingual (EN/VI) annotators + one separate adjudicator (none involved in `skill_scout.py` or `session_planner.py` implementation).
- **Agreement Metric:** Report percent agreement and **Cohen's kappa** on `relevance >= 2` and `capability_fit` across EN and VI slices separately.
- **Adjudication:** Any disagreement on `capability_fit`, `inappropriate`, or `relevance` delta `>= 2` is resolved independently by the adjudicator using the same blind packet.
- **Separation Rule:** Human judgments must be stored separately from automated (`eval/run_eval.py`) and AI-designed (`tests/test_adversarial_auto_eval_v3.py`) scores; automated scores never override human verdicts.
