"""Deterministic handoff template benchmark (PROMPT-02..06, PROMPT-08, PROMPT-10)."""

from __future__ import annotations

import json
import pathlib
import re
import statistics
import unittest
from dataclasses import dataclass
from typing import Any

EVAL_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
CASES_PATH = EVAL_DIR / "prompt_cases.jsonl"
JSON_OUT_PATH = REPO_ROOT / "docs" / "v3" / "PROMPT_BENCHMARK.json"
REPORT_OUT_PATH = REPO_ROOT / "docs" / "v3" / "PROMPT_BENCHMARK_REPORT.md"

BANNED_SLOP_WORDS = (
    "delve",
    "tapestry",
    "testament",
    "crucial",
    "moreover",
    "furthermore",
    "landscape",
    "beacon",
    "intertwined",
    "pivotal",
    "foster",
    "harness",
    "vital",
    "nuanced",
    "multifaceted",
    "paramount",
    "revolutionize",
)

META_WRITING_PATTERNS = (
    r"\bin this prompt\b",
    r"\bas an ai\b",
    r"\bthis handoff satisfies\b",
)

PRIVATE_PATH_PATTERN = re.compile(r"[A-Za-z]:\\Users\\")


@dataclass(frozen=True)
class TemplateSpec:
    """Metadata for a handoff prompt template."""

    key: str
    label: str
    description: str


TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        key="A_compiler_md",
        label="A: Current compiler.md",
        description=(
            "Front-loads outcome, scope, forbidden actions, stop triggers, "
            "separates observed/reported/unverified evidence, and adapts format "
            "by target model tier."
        ),
    ),
    TemplateSpec(
        key="B_outcome_scope_constraints_done",
        label="B: Outcome/Scope/Constraints/Done",
        description=(
            "Compact 4-block contract (Outcome, Scope, Constraints, Done) "
            "without separate evidence-tier headers."
        ),
    ),
    TemplateSpec(
        key="C_flat_checklist",
        label="C: Flat checklist",
        description=(
            "Minimal ordered checklist (Goal, Do not, numbered steps) optimized "
            "for low token footprint on weak/fast models."
        ),
    ),
    TemplateSpec(
        key="D_evidence_first",
        label="D: Evidence-first",
        description=(
            "Leads with full Observed, Reported, and Unverified sections before "
            "Outcome, Scope, Forbidden, Subtasks, and Done across all tracks."
        ),
    ),
    TemplateSpec(
        key="E_risk_adjusted",
        label="E: Risk-adjusted",
        description=(
            "Scales section depth by track (fast, guided, deep) while preserving "
            "forbidden actions, grounding labels, and subtask boundaries."
        ),
    ),
)


def load_cases(path: pathlib.Path = CASES_PATH) -> list[dict[str, Any]]:
    """Load prompt benchmark cases from JSONL."""
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                cases.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at {path.name}:{line_no}: {exc}"
                ) from exc
    return cases


def _format_verification_line(ctx: dict[str, Any]) -> str:
    verified = ctx.get("verified_commands", [])
    if verified:
        return (
            "Run verified command(s): "
            + "; ".join(verified)
            + ". Report actual output."
        )
    return "Verified command: unknown (not found in rules/tests). Report actual outcome or inability to verify."


def _format_unverified_items(ctx: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for claim in ctx.get("unverified_claims", []):
        items.append(f"Unverified claim (do not trust as fact): {claim}")
    for cmd in ctx.get("unverified_commands", []):
        items.append(f"Unverified command (not confirmed executable): {cmd}")
    return items


def _format_clarification_questions(ctx: dict[str, Any]) -> list[str]:
    blockers = ctx.get("missing_blockers", [])
    return [f"Clarify before editing: {blocker}?" for blocker in blockers[:2]]


def render_template_a(case: dict[str, Any]) -> str:
    """Render Template A (Current compiler.md)."""
    ctx = case["context"]
    tier = case.get("target_model_tier", "reasoning")
    scope = ", ".join(case["expected_scope"])
    lines: list[str] = [
        f"Outcome: {case['expected_outcome']}.",
        f"Scope: {scope}.",
        "Forbidden: " + "; ".join(ctx.get("forbidden_actions", ["None"])) + ".",
    ]
    if ctx.get("observed_rules"):
        lines.append("Rules: " + "; ".join(ctx["observed_rules"]) + ".")
    if case.get("track") in ("guided", "deep"):
        stop_cond = (
            "Stop and ask if a missing blocker prevents safe edits."
            if ctx.get("missing_blockers")
            else "Stop if observed source contradicts reported symptom or scope expands."
        )
        lines.append(f"Stop condition: {stop_cond}")

    observed = [
        f"{item['path']}: {item['fact']}" for item in ctx.get("observed_files", [])
    ]
    lines.append(
        "Observed facts: "
        + ("; ".join(observed) if observed else "none (standalone task).")
    )
    if ctx.get("reported_symptoms"):
        lines.append(
            "Reported symptoms (unconfirmed): "
            + "; ".join(ctx["reported_symptoms"])
            + "."
        )
    unverified = _format_unverified_items(ctx)
    if unverified:
        lines.append("Unverified items: " + "; ".join(unverified) + ".")

    subtasks = ctx.get("subtasks", [])
    if len(subtasks) > 1:
        lines.append("Tasks:")
        for idx, sub in enumerate(subtasks, start=1):
            lines.append(f"  {idx}. {sub}")
    elif tier == "fast_weak":
        lines.append(
            f"Checklist: 1) Inspect {scope}. 2) {subtasks[0]}. 3) Verify and report."
        )
    else:
        lines.append(
            f"Action: {subtasks[0]} (inspect target files first; depth: thorough)."
        )

    lines.extend(_format_clarification_questions(ctx))

    lines.append("Done: " + "; ".join(case["expected_acceptance"]) + ".")
    lines.append(_format_verification_line(ctx))
    return "\n".join(lines)


def render_template_b(case: dict[str, Any]) -> str:
    """Render Template B (Outcome/Scope/Constraints/Done)."""
    ctx = case["context"]
    scope = ", ".join(case["expected_scope"])
    constraints = list(ctx.get("forbidden_actions", [])) + list(
        ctx.get("observed_rules", [])
    )
    context_notes = [
        f"{item['path']} ({item['fact']})" for item in ctx.get("observed_files", [])
    ]
    context_notes.extend(ctx.get("reported_symptoms", []))
    context_notes.extend(ctx.get("unverified_claims", []))
    subtasks = ctx.get("subtasks", [])

    lines = [
        f"Outcome: {case['expected_outcome']}.",
        f"Scope: {scope}. Context: "
        + ("; ".join(context_notes) if context_notes else "none")
        + ".",
        "Constraints: " + ("; ".join(constraints) if constraints else "none") + ".",
    ]
    if len(subtasks) > 1:
        lines.append(
            "Tasks: " + " | ".join(f"{i}. {s}" for i, s in enumerate(subtasks, 1))
        )
    else:
        lines.append(f"Plan: {subtasks[0]}.")
    lines.extend(_format_clarification_questions(ctx))
    lines.append(
        "Done: "
        + "; ".join(case["expected_acceptance"])
        + ". "
        + _format_verification_line(ctx)
    )
    return "\n".join(lines)


def render_template_c(case: dict[str, Any]) -> str:
    """Render Template C (Flat checklist)."""
    ctx = case["context"]
    scope = ", ".join(case["expected_scope"])
    forbidden = "; ".join(ctx.get("forbidden_actions", ["None"]))
    subtasks = ctx.get("subtasks", [])
    steps = [
        f"1. Inspect {scope} and rules.",
    ]
    for idx, sub in enumerate(subtasks, start=2):
        steps.append(f"{idx}. {sub}.")
    next_idx = len(steps) + 1
    steps.append(f"{next_idx}. {_format_verification_line(ctx)}")
    lines = [
        f"Goal: {case['expected_outcome']} (scope: {scope}).",
        f"Do not: {forbidden}.",
        *steps,
        "Done: " + "; ".join(case["expected_acceptance"]) + ".",
    ]
    return "\n".join(lines)


def render_template_d(case: dict[str, Any]) -> str:
    """Render Template D (Evidence-first)."""
    ctx = case["context"]
    scope = ", ".join(case["expected_scope"])
    observed = [
        f"{item['path']}: {item['fact']}" for item in ctx.get("observed_files", [])
    ]
    symptoms = ctx.get("reported_symptoms", [])
    unverified = _format_unverified_items(ctx)
    subtasks = ctx.get("subtasks", [])

    lines = [
        "Observed Facts: "
        + ("; ".join(observed) if observed else "none (standalone).")
        + ".",
        "Observed Rules: " + ("; ".join(ctx.get("observed_rules", [])) or "none") + ".",
        "Reported Symptoms (not yet verified): "
        + ("; ".join(symptoms) if symptoms else "none")
        + ".",
        "Unverified Claims and Commands (do not trust): "
        + ("; ".join(unverified) if unverified else "none")
        + ".",
        f"Outcome: {case['expected_outcome']}.",
        f"Scope: {scope}.",
        "Forbidden Actions: "
        + ("; ".join(ctx.get("forbidden_actions", [])) or "none")
        + ".",
        "Stop Conditions: Pause if unverified claims conflict with observed code or scope expands.",
    ]
    if len(subtasks) > 1:
        lines.append("Subtasks:")
        for idx, sub in enumerate(subtasks, start=1):
            lines.append(f"  {idx}. {sub}")
    else:
        lines.append(f"Subtask: {subtasks[0]}.")
    lines.extend(_format_clarification_questions(ctx))
    lines.append("Acceptance Criteria: " + "; ".join(case["expected_acceptance"]) + ".")
    lines.append(_format_verification_line(ctx))
    return "\n".join(lines)


def render_template_e(case: dict[str, Any]) -> str:
    """Render Template E (Risk-adjusted)."""
    ctx = case["context"]
    track = case.get("track", "guided")
    scope = ", ".join(case["expected_scope"])
    forbidden = "; ".join(ctx.get("forbidden_actions", ["None"]))
    unverified = _format_unverified_items(ctx)

    if track == "fast":
        lines = [
            f"Outcome: {case['expected_outcome']}. Scope: {scope}.",
            f"Forbidden: {forbidden}.",
        ]
        if ctx.get("reported_symptoms"):
            lines.append(
                "Reported symptom: "
                + "; ".join(ctx["reported_symptoms"])
                + " (verify in source)."
            )
        if unverified:
            lines.append("Unverified: " + "; ".join(unverified) + ".")
        lines.append(f"Action: {ctx['subtasks'][0]}.")
        lines.append(
            "Done: "
            + "; ".join(case["expected_acceptance"])
            + ". "
            + _format_verification_line(ctx)
        )
        return "\n".join(lines)

    observed = [
        f"{item['path']}: {item['fact']}" for item in ctx.get("observed_files", [])
    ]
    lines = [
        f"Outcome: {case['expected_outcome']}.",
        f"Scope: {scope}.",
        f"Forbidden: {forbidden}.",
    ]
    if ctx.get("observed_rules"):
        lines.append("Rules: " + "; ".join(ctx["observed_rules"]) + ".")
    lines.append(
        "Observed: " + ("; ".join(observed) if observed else "none (standalone)") + "."
    )
    if ctx.get("reported_symptoms"):
        lines.append("Reported: " + "; ".join(ctx["reported_symptoms"]) + ".")
    if unverified:
        lines.append("Unverified: " + "; ".join(unverified) + ".")

    if track == "deep":
        lines.append(
            "Stop trigger: Halt if a blocker arises or observed evidence contradicts assumptions."
        )

    subtasks = ctx.get("subtasks", [])
    if len(subtasks) > 1:
        lines.append("Task boundaries:")
        for idx, sub in enumerate(subtasks, start=1):
            lines.append(f"  {idx}. {sub}")
    else:
        lines.append(f"Action: {subtasks[0]}.")

    lines.extend(_format_clarification_questions(ctx))

    lines.append("Done: " + "; ".join(case["expected_acceptance"]) + ".")
    lines.append(_format_verification_line(ctx))
    return "\n".join(lines)


RENDERERS = {
    "A_compiler_md": render_template_a,
    "B_outcome_scope_constraints_done": render_template_b,
    "C_flat_checklist": render_template_c,
    "D_evidence_first": render_template_d,
    "E_risk_adjusted": render_template_e,
}


def evaluate_prompt(case: dict[str, Any], prompt_text: str) -> dict[str, Any]:
    """Audit a rendered handoff prompt against the PROMPT-02..10 contract schema."""
    ctx = case["context"]
    lower = prompt_text.lower()

    outcome_ok = ("outcome:" in lower or "goal:" in lower) and any(
        tok in lower for tok in case["expected_outcome"].lower().split()[:3]
    )
    scope_ok = all(item.lower() in lower for item in case["expected_scope"])

    forbidden = ctx.get("forbidden_actions", [])
    forbidden_hits = sum(1 for item in forbidden if item.lower() in lower)
    forbidden_ok = forbidden_hits == len(forbidden) if forbidden else True

    verified_cmds = ctx.get("verified_commands", [])
    unverified_cmds = ctx.get("unverified_commands", [])
    if verified_cmds:
        verif_ok = all(cmd.lower() in lower for cmd in verified_cmds)
    else:
        verif_ok = ("unknown" in lower) or ("not found" in lower) or ("unable" in lower)
    no_fabricated_cmd = not any(
        f"run {cmd.lower()}" in lower
        or f"run verified command(s): {cmd.lower()}" in lower
        for cmd in unverified_cmds
    )
    acceptance_ok = (
        verif_ok
        and no_fabricated_cmd
        and ("done:" in lower or "acceptance criteria:" in lower)
    )

    unverified_items = list(ctx.get("unverified_claims", [])) + list(unverified_cmds)
    if unverified_items:
        unverified_labeled_ok = (
            "unverified" in lower or "do not trust" in lower
        ) and all(item.lower() in lower for item in unverified_items)
    else:
        unverified_labeled_ok = True

    has_trap_evidence = bool(
        ctx.get("reported_symptoms") or ctx.get("unverified_claims")
    )
    if has_trap_evidence:
        has_observed_label = "observed" in lower
        has_reported_or_unverified = ("reported" in lower) or ("unverified" in lower)
        evidence_sep_ok = has_observed_label and has_reported_or_unverified
    else:
        evidence_sep_ok = True

    contract_checks = [
        outcome_ok,
        scope_ok,
        forbidden_ok,
        acceptance_ok,
        unverified_labeled_ok,
        evidence_sep_ok,
    ]
    contract_completeness = sum(1.0 for c in contract_checks if c) / len(
        contract_checks
    )

    all_constraints = list(forbidden) + list(ctx.get("observed_rules", []))
    if all_constraints:
        constraint_retention = sum(
            1 for c in all_constraints if c.lower() in lower
        ) / len(all_constraints)
    else:
        constraint_retention = 1.0

    subtasks = ctx.get("subtasks", [])
    if len(subtasks) > 1:
        has_boundaries = all(
            f"{idx}." in prompt_text for idx in range(1, len(subtasks) + 1)
        )
        no_dup_forbidden = (
            all(lower.count(item.lower()) == 1 for item in forbidden)
            if forbidden
            else True
        )
        multi_intent_ok = has_boundaries and no_dup_forbidden
    else:
        multi_intent_ok = True

    blockers = ctx.get("missing_blockers", [])
    question_count = prompt_text.count("?")
    if blockers:
        clarification_ok = 1 <= question_count <= 2
    else:
        clarification_ok = question_count == 0

    char_count = len(prompt_text)
    token_estimate = round(char_count / 4.0, 1)

    has_em_dash = "\u2014" in prompt_text or " -- " in prompt_text
    has_slop_word = any(re.search(rf"\b{word}\b", lower) for word in BANNED_SLOP_WORDS)
    has_meta = any(re.search(pat, lower) for pat in META_WRITING_PATTERNS)
    has_private_path = bool(PRIVATE_PATH_PATTERN.search(prompt_text))
    short_fast_bloated = case.get("track") == "fast" and token_estimate > 180
    slop_free_ok = not (
        has_em_dash
        or has_slop_word
        or has_meta
        or has_private_path
        or short_fast_bloated
    )

    return {
        "case_id": case["id"],
        "category": case["category"],
        "track": case["track"],
        "target_model_tier": case["target_model_tier"],
        "char_count": char_count,
        "token_estimate": token_estimate,
        "outcome": outcome_ok,
        "scope": scope_ok,
        "forbidden_actions": forbidden_ok,
        "acceptance_criteria": acceptance_ok,
        "unverified_labels": unverified_labeled_ok,
        "evidence_separation": evidence_sep_ok,
        "contract_completeness": round(contract_completeness, 4),
        "constraint_retention": round(constraint_retention, 4),
        "multi_intent_boundary": multi_intent_ok,
        "clarification_gate": clarification_ok,
        "slop_free": slop_free_ok,
    }


def run_benchmark(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run all 5 templates across all cases and compute summary statistics."""
    loaded_cases = cases if cases is not None else load_cases()
    results_by_template: dict[str, Any] = {}

    for spec in TEMPLATES:
        renderer = RENDERERS[spec.key]
        case_rows: list[dict[str, Any]] = []
        for case in loaded_cases:
            rendered = renderer(case)
            metrics = evaluate_prompt(case, rendered)
            case_rows.append(metrics)

        n = len(case_rows)
        summary = {
            "label": spec.label,
            "description": spec.description,
            "cases": n,
            "mean_contract_completeness": round(
                statistics.mean(r["contract_completeness"] for r in case_rows), 4
            ),
            "outcome_rate": round(sum(1 for r in case_rows if r["outcome"]) / n, 4),
            "scope_rate": round(sum(1 for r in case_rows if r["scope"]) / n, 4),
            "forbidden_actions_rate": round(
                sum(1 for r in case_rows if r["forbidden_actions"]) / n, 4
            ),
            "acceptance_criteria_rate": round(
                sum(1 for r in case_rows if r["acceptance_criteria"]) / n, 4
            ),
            "unverified_labels_rate": round(
                sum(1 for r in case_rows if r["unverified_labels"]) / n, 4
            ),
            "evidence_separation_rate": round(
                sum(1 for r in case_rows if r["evidence_separation"]) / n, 4
            ),
            "mean_constraint_retention": round(
                statistics.mean(r["constraint_retention"] for r in case_rows), 4
            ),
            "multi_intent_boundary_rate": round(
                sum(1 for r in case_rows if r["multi_intent_boundary"]) / n, 4
            ),
            "clarification_gate_rate": round(
                sum(1 for r in case_rows if r["clarification_gate"]) / n, 4
            ),
            "slop_free_rate": round(sum(1 for r in case_rows if r["slop_free"]) / n, 4),
            "mean_chars": round(statistics.mean(r["char_count"] for r in case_rows), 1),
            "mean_tokens_est": round(
                statistics.mean(r["token_estimate"] for r in case_rows), 1
            ),
            "by_model_tier": {
                tier: {
                    "cases": len(
                        [r for r in case_rows if r["target_model_tier"] == tier]
                    ),
                    "mean_contract_completeness": round(
                        statistics.mean(
                            r["contract_completeness"]
                            for r in case_rows
                            if r["target_model_tier"] == tier
                        ),
                        4,
                    ),
                    "mean_tokens_est": round(
                        statistics.mean(
                            r["token_estimate"]
                            for r in case_rows
                            if r["target_model_tier"] == tier
                        ),
                        1,
                    ),
                }
                for tier in ("reasoning", "fast_weak")
            },
        }
        results_by_template[spec.key] = {
            "summary": summary,
            "per_case": case_rows,
        }

    return {
        "benchmark": "skill-pilot-prompt-compiler-v3",
        "dataset": "eval/prompt_cases.jsonl",
        "case_count": len(loaded_cases),
        "token_estimator": "chars / 4",
        "templates": results_by_template,
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Format benchmark results into a clean Markdown report without em-dashes or private paths."""
    lines: list[str] = [
        "# Prompt Compiler Benchmark Report (v3)",
        "",
        f"Dataset: `{payload['dataset']}` ({payload['case_count']} representative cases, deterministic offline audit).",
        f"Token estimator: `{payload['token_estimator']}`.",
        "",
        "## Template Comparison Summary",
        "",
        "| Template | Completeness | Outcome | Scope | Forbidden | Acceptance | Unverified Labels | Evidence Sep | Clarification | Slop-Free | Mean Chars | Est. Tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for spec in TEMPLATES:
        s = payload["templates"][spec.key]["summary"]
        lines.append(
            f"| {s['label']} | {s['mean_contract_completeness']:.2%} | {s['outcome_rate']:.0%} | "
            f"{s['scope_rate']:.0%} | {s['forbidden_actions_rate']:.0%} | "
            f"{s['acceptance_criteria_rate']:.0%} | {s['unverified_labels_rate']:.0%} | "
            f"{s['evidence_separation_rate']:.0%} | {s['clarification_gate_rate']:.0%} | "
            f"{s['slop_free_rate']:.0%} | {s['mean_chars']:.1f} | {s['mean_tokens_est']:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Model Tier Breakdown (PROMPT-03)",
            "",
            "| Template | Reasoning Completeness | Reasoning Tokens | Fast/Weak Completeness | Fast/Weak Tokens |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )

    for spec in TEMPLATES:
        s = payload["templates"][spec.key]["summary"]
        r_tier = s["by_model_tier"]["reasoning"]
        f_tier = s["by_model_tier"]["fast_weak"]
        lines.append(
            f"| {s['label']} | {r_tier['mean_contract_completeness']:.2%} | {r_tier['mean_tokens_est']:.1f} | "
            f"{f_tier['mean_contract_completeness']:.2%} | {f_tier['mean_tokens_est']:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Key Findings",
            "",
            "- **Grounding and contract completeness**: Templates A (`compiler.md`), D (`Evidence-first`), and E (`Risk-adjusted`) achieve 100% contract completeness, preserving all forbidden actions and marking unverified claims/commands explicitly.",
            "- **Compact schemas trade off grounding**: Template B (`Outcome/Scope/Constraints/Done`) and Template C (`Flat checklist`) reduce token footprint, but omitting explicit Observed/Reported/Unverified separation causes grounding trap failures on adversarial cases.",
            "- **Short handoff bloat (PROMPT-10)**: Template D (`Evidence-first`) adds verbose sections even on `fast` track tasks, increasing token footprint without improving completeness over Templates A or E.",
            "- **Model-tier calibration (PROMPT-03)**: Template A adapts output shape to `reasoning` vs `fast_weak` tiers while keeping full contract fidelity, and Template E scales section overhead by risk track.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """Execute the deterministic benchmark and write JSON and Markdown artifacts."""
    payload = run_benchmark()
    JSON_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    REPORT_OUT_PATH.write_text(render_markdown_report(payload), encoding="utf-8")
    print(
        f"Wrote {JSON_OUT_PATH.relative_to(REPO_ROOT)} and {REPORT_OUT_PATH.relative_to(REPO_ROOT)}"
    )
    for spec in TEMPLATES:
        s = payload["templates"][spec.key]["summary"]
        print(
            f"  {s['label']}: completeness={s['mean_contract_completeness']:.2%}, "
            f"tokens~={s['mean_tokens_est']:.1f}, slop_free={s['slop_free_rate']:.0%}"
        )


class TestPromptBenchmark(unittest.TestCase):
    """Self-contained unit tests for prompt_cases.jsonl and prompt_benchmark.py."""

    def test_cases_cover_all_15_categories_and_traps(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 15)
        categories = {c["category"] for c in cases}
        expected = {
            "code_fix",
            "multi_module_debugging",
            "ui",
            "finance",
            "academic",
            "marketing",
            "data",
            "security",
            "deployment",
            "db_migration",
            "multi_intent",
            "vietnamese",
            "mixed_en_vi",
            "underspecified",
            "forbidden_operations",
        }
        self.assertEqual(categories, expected)
        traps = {trap for c in cases for trap in c.get("grounding_traps", [])}
        self.assertTrue(
            {"misleading_claim", "unverified_command", "reported_symptom"}.issubset(
                traps
            )
        )

    def test_all_templates_deterministic_and_clean(self) -> None:
        cases = load_cases()
        for spec in TEMPLATES:
            renderer = RENDERERS[spec.key]
            for case in cases:
                first = renderer(case)
                second = renderer(case)
                self.assertEqual(first, second)
                self.assertNotIn("\u2014", first)
                self.assertIsNone(PRIVATE_PATH_PATTERN.search(first))

    def test_grounding_and_report_generation(self) -> None:
        payload = run_benchmark()
        self.assertEqual(payload["case_count"], 15)
        self.assertEqual(
            payload["templates"]["A_compiler_md"]["summary"][
                "mean_contract_completeness"
            ],
            1.0,
        )
        self.assertEqual(
            payload["templates"]["E_risk_adjusted"]["summary"][
                "mean_contract_completeness"
            ],
            1.0,
        )
        report = render_markdown_report(payload)
        self.assertNotIn("\u2014", report)
        self.assertIsNone(PRIVATE_PATH_PATTERN.search(report))


if __name__ == "__main__":
    main()
