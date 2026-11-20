# V4 Output Boundary and Promotion Lock Follow-up

Baseline: development SHA `2e79a51ae23ea6f6da2df3172645b29e3a4a355a`, all four hosted CI jobs passed.

## Confirmed failure modes

1. `cmd_search` previously redacted only the deduplicated `ranked_matches` candidate's `description`. Its `tier2_warehouse_matches` still retained the original, untrusted raw warehouse `description` dictionary. `name`, `tags` and other candidate string fields were not scanned. The JSON alternative view and compact view could therefore still echo malicious instructions into a host LLM's context.
2. `skill_scout._is_pid_alive` duplicated the Windows Win32 process probing routine, still calling `OpenProcess` without pointer-sized `restype` and interpreting exit code 259 as unambiguously alive. A separate corrected helper exists in `session_planner`.
3. Windows process IDs larger than the DWORD API maximum must not be silently truncated during Win32 liveness probes.

## Research-first selection

Three candidate policies for untrusted search records:

| Candidate | License/runtime deps | Latency/quality trade-off | Decision |
| --- | --- | --- | --- |
| Recursive **output-only per-field redaction** of known prompt-injection signals, applied consistently to every emitted candidate array and compact result | Python stdlib/PSF; zero extra deps | Regex scan for a small bounded result set; preserves benign fields/ranking; latency measured by CI | **Selected** |
| Drop any candidate containing a suspicious token in any metadata field | Python stdlib/PSF; zero deps | Stronger quarantine for known patterns, but can hide useful security-analysis skills and degrade recall | Rejected for default search |
| Existing description-only redaction on deduplicated results | Python stdlib/PSF; zero deps | Fastest but leaks raw text through secondary arrays, names/tags and compact output | Rejected as incomplete |
| External ML classifier / embeddings | May require model weights/frameworks and open-source license review | Potentially broader detection but unpredictable latency, errors and violates lightweight stdlib runtime | Rejected pending independent quality benchmark |

Primary security context: [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/), [OWASP prompt-injection prevention cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html), [OpenAI model specification](https://model-spec.openai.com/2025-09-12.html). **Text redaction is not a trust boundary or proof of injection immunity**; host tools must treat all retrieved skill records as data.

Three shared-process probe options: (a) use the already-corrected stdlib `session_planner._session_lock_pid_alive` (selected, no duplicated Win32 ctypes call), (b) repair and maintain two separate ctypes implementations (rejected for drift), (c) add `psutil` BSD-3-Clause native dependency (rejected for runtime platform/license/installation burden). The source Windows API is Microsoft's `WaitForSingleObject`; one shared implementation keeps pointer-width fixes consistent.

## Regression and acceptance

- Search with a synthetic warehouse containing injection text independently in name, tags and description; verify neither `ranked_matches`, `tier2_warehouse_matches`, nor compact output repeats the phrase.
- Verify benign metadata stays identical and no ranking weights change.
- Spawn a real child process; verify both `skill_scout` and `session_planner` process probes agree before/after exit on Windows and Linux.
- Reject oversized Windows PID rather than implicit DWORD truncation.
- Run all existing tests and the four-cell CI after the final edit; document any failures before declaring verified.

**Residual risks:** malicious paths, encoded/rewritten attacks, Unicode confusables beyond existing filters, unsafe actions in SKILL.md and human-model behavior are not solved by regex. Real host red-team evaluation is required before release.
