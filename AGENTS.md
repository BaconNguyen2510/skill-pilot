# Skill Pilot Engineering Directives

## Research-First Engineering Policy

**RESEARCH FIRST. REUSE WHEN POSSIBLE. BUILD ONLY WHEN JUSTIFIED.**

Before implementing any nontrivial feature, fixing a complex bug, or designing a new subsystem:

1. **Define the problem:** Identify the actual failure, constraints, expected behavior, and acceptance tests before selecting a solution.
2. **Search externally:** Investigate current GitHub repositories, maintained open-source libraries, existing agent skills, official documentation, and proven implementations. Inspect primary sources.
3. **Compare candidates:** Evaluate functional fit, maintenance activity, licensing, security, dependencies, platform compatibility, performance, and integration complexity.
4. **Reuse or adapt:** Prefer an existing proven implementation when it solves the problem better than custom code. Adapt its design or algorithms when direct integration would introduce unnecessary dependencies. Respect licenses and attribution requirements.
5. **Implement only the missing functionality:** Avoid rebuilding capabilities already provided by suitable tools. Document why rejected alternatives were not used.
6. **Benchmark and verify:** Compare the chosen solution against the existing baseline using reproducible tests (regressions, performance, reliability, security) before committing.
7. **Preserve research evidence:** Record repository URLs, versions/commit SHAs, evaluation results, architectural decisions, and rejected alternatives in `docs/`.

## Runtime & Packaging Invariants

- Keep `skills/skill-pilot/scripts/skill_scout.py` and `session_planner.py` pure Python 3.12+ standard library (zero external pip/JVM runtime dependencies).
- Never commit sealed evaluation datasets (`eval/sealed_queries.jsonl`, `docs/v3/SEALED_EVAL_REPORT.json`) or fabricate human evaluation results.
