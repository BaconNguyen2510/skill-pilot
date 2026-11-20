# V4 v3.4 Security Hardening Audit

## Threat model

Treat warehouse metadata and third-party `SKILL.md` contents as untrusted data. An attacker may control the description, skill body, headings, scripts, path in a warehouse index, file size, and local symlinks. We do not claim a sandbox or security against a privileged attacker who can mutate the user's filesystem.

## Research-first comparison (primary sources)

| Candidate | License/deps | Expected latency/fit | Decision |
| --- | --- | --- | --- |
| Python 3.12+ stdlib `os.lstat`, `os.open(O_NOFOLLOW)`, `os.fstat`, capped reads | PSF; 0 runtime dependencies | Small single-file read, bounded to 1 MiB; latency not benchmarked independently | **Selected** to close the evidence-read DoS/link gap |
| `pathlib.Path.read_text` with post-read string-length validation | PSF; 0 deps | Simple API but memory is already consumed before validation, follows links | Rejected as insufficient |
| Separate subprocess sandbox to parse each SKILL.md | OS tools and platform-dependent containment; no pure universal sandbox | Extra process startup per candidate, Windows/Linux disparity | Rejected: high complexity with misleading guarantees |
| Keyword-only injection detection (existing approach) | 0 deps | Fast but misses paraphrases | Retained as warning signal, not trust guarantee |
| Host prompt instruction isolation and explicit tool authority | 0 extra CLI deps; host-dependent | No independent host-model enforcement available | Necessary complementary defense |
| External NLP-based injection classifier | Third-party model/runtime dependencies | Might catch paraphrases but introduces latency, model errors, and external code | Rejected for stdlib CLI |

Sources: [Python os documentation](https://docs.python.org/3.12/library/os.html), [OWASP LLM Prompt Injection guidance](https://genai.owasp.org/llmrisk/llm01-prompt-injection/), and [Python pathlib documentation](https://docs.python.org/3.12/library/pathlib.html).

## Code findings and changes

- `session_planner.extract_skill_capabilities` previously used unbounded `Path.read_text`, with no source-link restriction. A 10-MB+ malicious skill could consume unnecessary resources during per-step evidence checks. It now rejects non-regular and symlinked input and bounds reading to 1 MiB with a same-open-file identity check.
- `run_plan_search` previously equated the search index's `exists` flag and a path string with verified presence. It now only treats readable, inspected, bounded `SKILL.md` as verified on disk.
- `cmd_search` previously echoed recognizable instruction-override payloads from indexed descriptions into agent-visible JSON. The scorer may still use those strings for lexical matching, but returned descriptions containing known injection signals are withheld and annotated.
- Existing path guards already reject traversal in warehouse paths, symlinks/junctions during promotion, and risky scripts by default. These are regression-tested; not needlessly replaced.

## Unresolved risk

Textual redaction cannot detect all prompt injection; frontmatter, headings and body content still require host authority boundaries when inspected. The file checks do not guarantee an attacker cannot race and replace directory entries outside the narrow read window. Native Antigravity and Codex model-level adversarial tests still need their host environments. No claim of full isolation, human evaluation, or production-readiness is justified by these static tests.

## Verification

The complete Windows/Linux CI matrix and local test evidence will be appended only after the new commit executes; prior v3.1.1 CI cannot validate these changes.
