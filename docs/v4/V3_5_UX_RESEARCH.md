# v3.5 CLI and Specification UX Research

Objective: make the stored session and dependency workflow discoverable without adding dependencies or requiring interactive terminal prompts. The host agent performs interviews; the CLI provides deterministic state, gates, specifications and diagnostics.

| Approach | License/runtime deps | UX/latency trade-off | Decision |
| --- | --- | --- | --- |
| Python stdlib [argparse](https://docs.python.org/3.12/library/argparse.html) + Markdown specifications | PSF, zero extra deps | Existing CLI compatibility; minimal deterministic formatting; no measured overhead | **Selected** |
| [Pallets Click](https://github.com/pallets/click) | BSD-3-Clause, extra runtime dependency | Better command composition and rich error UX but API migration and import overhead | Rejected for current zero-dependency CLI |
| [FastAPI Typer](https://github.com/fastapi/typer) | MIT, runtime CLI dependency stack | Type-hint CLI ergonomics; substantial migration/testing cost; host invocation unaffected | Rejected |
| Host-only free-form prompts with no session CLI | No new library; host model dependent | Zero implementation but poor persistence, versioned state, and deterministic reproducibility | Rejected |

Implementation: clarify README installation and Guided/Deep session flow, add stable topological execution sequence in \`session spec\`, print actionable next-step gates for stale or uncovered plans, and explicitly state that quote grounding is not proof of semantic capability fit.

Limits: textual Markdown is not a privileged execution contract and must not elevate third-party skill instructions. No real Antigravity/Codex host usability study has been completed. Some host-specific paths remain to be tested by actual platform installations.
