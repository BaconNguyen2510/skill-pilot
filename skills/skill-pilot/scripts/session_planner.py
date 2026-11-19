"""Structured session state, observable readiness, and per-step plan-search for Skill Pilot."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import os
import pathlib
import tempfile
import time
import uuid
from typing import Any


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def compute_readiness(session: dict[str, Any]) -> dict[str, Any]:
    """Compute observable readiness criteria without inventing numerical confidence scores."""
    confirmed = session.get("confirmed_requirements", [])
    success = session.get("success_criteria", [])
    unresolved = [
        q for q in session.get("unresolved_questions", []) if not q.get("resolved")
    ]
    unack_assumptions = [
        a for a in session.get("assumptions", []) if not a.get("acknowledged")
    ]
    plan_steps = session.get("plan_steps", [])

    dep_check = validate_plan_dependencies(plan_steps)
    criteria = {
        "has_confirmed_goal": len(confirmed) > 0,
        "has_success_criteria": len(success) > 0,
        "no_blocking_unresolved_questions": len(unresolved) == 0,
        "assumptions_acknowledged": len(unack_assumptions) == 0,
        "has_plan_steps": len(plan_steps) > 0,
        "plan_dependencies_valid": dep_check["valid"] if plan_steps else False,
    }
    missing_for_planning = [
        k
        for k in (
            "has_confirmed_goal",
            "no_blocking_unresolved_questions",
            "assumptions_acknowledged",
        )
        if not criteria[k]
    ]
    missing_for_discovery = [k for k, v in criteria.items() if not v]
    ready_for_planning = len(missing_for_planning) == 0
    ready_for_discovery = (
        ready_for_planning
        and criteria["has_plan_steps"]
        and criteria["plan_dependencies_valid"]
    )
    return {
        "criteria": criteria,
        "missing_for_planning": missing_for_planning,
        "missing_criteria": missing_for_discovery,
        "ready_for_planning": ready_for_planning,
        "ready_for_discovery": ready_for_discovery,
        "plan_stale": bool(session.get("plan_stale", False)),
        "discovery_stale": bool(session.get("discovery_stale", False)),
        "unresolved_question_count": len(unresolved),
        "unacknowledged_assumption_count": len(unack_assumptions),
    }


def init_session(
    initial_request: str,
    *,
    language: str = "en",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create a new structured discovery session."""
    now = _utc_now()
    return {
        "schema_version": "3.0",
        "session_id": session_id or uuid.uuid4().hex[:12],
        "created_at": now,
        "updated_at": now,
        "revision": 1,
        "initial_request": initial_request.strip(),
        "language": language,
        "confirmed_requirements": [],
        "assumptions": [],
        "unresolved_questions": [],
        "decisions": [],
        "constraints": [],
        "success_criteria": [],
        "plan_steps": [],
        "revision_history": [
            {
                "revision": 1,
                "timestamp": now,
                "summary": "Session initialized",
            }
        ],
    }


def _merge_by_id(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in existing:
        key = str(item.get("id") or len(order))
        by_id[key] = copy.deepcopy(item)
        order.append(key)
    for item in incoming:
        key = str(item.get("id") or len(order))
        if key not in by_id:
            order.append(key)
        by_id[key] = copy.deepcopy(item)
    return [by_id[k] for k in order]


def update_session(
    session: dict[str, Any],
    patch: dict[str, Any],
    *,
    revision_note: str = "Session updated",
) -> dict[str, Any]:
    """Update session fields without silently losing prior history."""
    updated = copy.deepcopy(session)
    list_fields = (
        "confirmed_requirements",
        "assumptions",
        "unresolved_questions",
        "decisions",
        "constraints",
        "success_criteria",
        "plan_steps",
    )
    for field in list_fields:
        if field in patch and isinstance(patch[field], list):
            if patch.get("replace_plan") and field == "plan_steps":
                updated[field] = copy.deepcopy(patch[field])
            else:
                updated[field] = _merge_by_id(updated.get(field, []), patch[field])

    if patch.get("language"):
        updated["language"] = patch["language"]

    # Invalidate stale plan/discovery when requirements, constraints, or plan change
    req_changed = any(
        k in patch
        for k in ("confirmed_requirements", "constraints", "success_criteria")
    )
    if req_changed and "plan_steps" not in patch and updated.get("plan_steps"):
        updated["plan_stale"] = True
    elif "plan_steps" in patch:
        updated["plan_stale"] = False

    if req_changed or "plan_steps" in patch:
        updated["discovery_stale"] = True
        updated["last_discovery"] = None

    now = _utc_now()
    updated["updated_at"] = now
    updated["revision"] = int(updated.get("revision", 1)) + 1
    history = list(updated.get("revision_history", []))
    history.append(
        {
            "revision": updated["revision"],
            "timestamp": now,
            "summary": revision_note,
        }
    )
    updated["revision_history"] = history
    return updated


def validate_plan_dependencies(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate step IDs, missing dependencies, and cycles."""
    step_ids = {str(s.get("id", "")).strip() for s in steps if s.get("id")}
    missing_deps: list[dict[str, str]] = []
    adj: dict[str, list[str]] = {sid: [] for sid in step_ids}

    for step in steps:
        sid = str(step.get("id", "")).strip()
        for dep in step.get("depends_on", []):
            dep_id = str(dep).strip()
            if dep_id not in step_ids:
                missing_deps.append({"step_id": sid, "missing_dependency": dep_id})
            elif sid:
                adj[sid].append(dep_id)

    # Cycle detection via DFS
    state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done
    has_cycle = False

    def _dfs(node: str) -> None:
        nonlocal has_cycle
        state[node] = 1
        for nxt in adj.get(node, []):
            if state.get(nxt, 0) == 1:
                has_cycle = True
                return
            if state.get(nxt, 0) == 0:
                _dfs(nxt)
        state[node] = 2

    for sid in step_ids:
        if state.get(sid, 0) == 0:
            _dfs(sid)

    return {
        "valid": len(missing_deps) == 0 and not has_cycle,
        "step_count": len(steps),
        "missing_dependencies": missing_deps,
        "has_cycle": has_cycle,
    }


def normalize_step_coverage(step: dict[str, Any]) -> dict[str, Any]:
    """Validate host-assessed skill coverage; never promote ranking score to direct coverage."""
    raw_level = str(step.get("coverage_level", "unverified_fit")).lower()
    evidence = str(step.get("capability_evidence", "")).strip()
    uncovered = str(step.get("uncovered_capabilities", "")).strip()

    if raw_level == "direct" and not evidence:
        level = "unverified_fit"
    elif raw_level in ("direct", "partial", "none", "unverified_fit"):
        level = raw_level
    else:
        level = "unverified_fit"

    return {
        "coverage_level": level,
        "capability_evidence": evidence,
        "uncovered_capabilities": uncovered,
    }


def run_plan_search(
    steps: list[dict[str, Any]],
    search_fn: Any,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """Execute per-step skill discovery using the provided deterministic search callable."""
    dep_check = validate_plan_dependencies(steps)
    step_results: list[dict[str, Any]] = []
    capability_gaps: list[dict[str, Any]] = []

    for step in steps:
        sid = str(step.get("id", ""))
        title = str(step.get("title", ""))
        query = str(step.get("query") or title).strip()
        matches: list[dict[str, Any]] = []

        if query:
            buf = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = search_fn(query, limit)
            raw = buf.getvalue().strip()
            if rc == 0 and raw:
                payload = json.loads(raw)
                for m in payload.get("ranked_matches", []):
                    verified = bool(m.get("exists")) and bool(m.get("skill_md_path"))
                    matches.append(
                        {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "score": m.get("score"),
                            "risk": m.get("risk", "unknown"),
                            "tier_label": m.get("tier_label"),
                            "verified_on_disk": verified,
                            "skill_md_path": m.get("skill_md_path"),
                        }
                    )

        verified_matches = [m for m in matches if m.get("verified_on_disk")]
        assessed = normalize_step_coverage(step)
        if not verified_matches:
            coverage_level = "none"
        elif assessed["coverage_level"] in ("direct", "partial"):
            coverage_level = assessed["coverage_level"]
        else:
            # Score is a ranking signal only; without inspected SKILL.md evidence, fit is unverified.
            coverage_level = "unverified_fit"

        is_gap = coverage_level == "none"
        if coverage_level == "none":
            capability_gaps.append(
                {
                    "step_id": sid,
                    "title": title,
                    "query": query,
                    "coverage_level": "none",
                    "reason": "No verified local skill matched this step.",
                }
            )
        elif coverage_level == "partial":
            capability_gaps.append(
                {
                    "step_id": sid,
                    "title": title,
                    "query": query,
                    "coverage_level": "partial",
                    "reason": assessed["uncovered_capabilities"]
                    or "Partial coverage; specialized capability remains uncovered.",
                }
            )
        elif coverage_level == "unverified_fit":
            capability_gaps.append(
                {
                    "step_id": sid,
                    "title": title,
                    "query": query,
                    "coverage_level": "unverified_fit",
                    "reason": "Candidate(s) ranked on disk, but SKILL.md capability fit has not been verified yet.",
                }
            )

        step_results.append(
            {
                "step_id": sid,
                "title": title,
                "depends_on": step.get("depends_on", []),
                "query": query,
                "coverage_level": coverage_level,
                "capability_evidence": assessed["capability_evidence"],
                "uncovered_capabilities": assessed["uncovered_capabilities"],
                "matches": verified_matches,
                "unverified_candidates_filtered": len(matches) - len(verified_matches),
                "capability_gap": is_gap,
            }
        )

    return {
        "dependency_validation": dep_check,
        "steps": step_results,
        "capability_gaps": capability_gaps,
        "total_steps": len(steps),
        "covered_steps": len(steps) - len(capability_gaps),
    }


def load_json_file(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def session_lock(path: pathlib.Path, timeout_s: float = 5.0):
    """Cross-platform exclusive lockfile guard for concurrent session writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for session lock: {lock_path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(lock_path)


def save_json_file(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def update_session_file_locked(
    session_path: pathlib.Path,
    patch: dict[str, Any],
    *,
    revision_note: str = "Session updated",
) -> dict[str, Any]:
    """Update and atomically persist a session file under exclusive lock."""
    with session_lock(session_path):
        existing = load_json_file(session_path)
        data = update_session(existing, patch, revision_note=revision_note)
        save_json_file(session_path, data)
        return data


def persist_discovery_to_session(
    session_path: pathlib.Path,
    expected_session_id: str,
    expected_revision: int,
    discovery: dict[str, Any],
) -> dict[str, Any]:
    """Atomically persist discovery results under lock only if session_id and revision match."""
    with session_lock(session_path):
        current = load_json_file(session_path)
        if current.get("session_id") != expected_session_id:
            raise ValueError(
                f"Session identity mismatch: expected {expected_session_id}, got {current.get('session_id')}."
            )
        if int(current.get("revision", 0)) != int(expected_revision):
            raise ValueError(
                f"Session revision changed during discovery ({expected_revision} -> {current.get('revision')}); stale discovery rejected."
            )
        annotated = copy.deepcopy(discovery)
        annotated["for_revision"] = expected_revision
        current["last_discovery"] = annotated
        current["discovery_stale"] = False
        save_json_file(session_path, current)
        return current


def render_specification(
    session: dict[str, Any], discovery: dict[str, Any] | None = None
) -> str:
    """Render a structured Markdown specification and execution-ready workflow."""
    is_stale = bool(session.get("discovery_stale")) or bool(session.get("plan_stale"))
    if (
        discovery is not None
        and discovery.get("for_revision") is not None
        and int(discovery["for_revision"]) != int(session.get("revision", 1))
    ):
        is_stale = True
    effective_discovery = None if is_stale else discovery

    lines: list[str] = [
        f"# Project Specification: {session.get('initial_request', 'Untitled')}",
        "",
        f"- **Session ID:** `{session.get('session_id', 'unknown')}` (Revision {session.get('revision', 1)})",
        f"- **Language:** `{session.get('language', 'en')}`",
    ]
    if is_stale or effective_discovery is None:
        lines.extend(
            [
                "",
                "> **WARNING:** Discovery results are stale or missing for the current revision; run `plan-search --session <path>` before executing.",
            ]
        )
    lines.extend(["", "## 1. Confirmed Requirements"])
    for r in session.get("confirmed_requirements", []):
        lines.append(f"- `{r.get('id', '')}`: {r.get('text', '')}")
    if not session.get("confirmed_requirements"):
        lines.append("- *(None confirmed yet)*")

    lines.extend(["", "## 2. Acknowledged Assumptions"])
    for a in session.get("assumptions", []):
        ack = "acknowledged" if a.get("acknowledged") else "UNACKNOWLEDGED"
        lines.append(f"- `{a.get('id', '')}` ({ack}): {a.get('text', '')}")
    if not session.get("assumptions"):
        lines.append("- *(None)*")

    lines.extend(["", "## 3. Constraints & Acceptance Criteria"])
    for c in session.get("constraints", []):
        lines.append(f"- **Constraint** `{c.get('id', '')}`: {c.get('text', '')}")
    for s in session.get("success_criteria", []):
        lines.append(f"- **Acceptance** `{s.get('id', '')}`: {s.get('text', '')}")

    lines.extend(["", "## 4. Dependency-Aware Execution Plan & Verified Skills"])
    steps = (effective_discovery or {}).get("steps", [])
    if steps:
        for st in steps:
            deps = ", ".join(st.get("depends_on", [])) or "none"
            cov = str(st.get("coverage_level", "unknown")).upper()
            lines.append(
                f"### {st.get('step_id', '')}: {st.get('title', '')} [{cov}] (depends_on: {deps})"
            )
            if st.get("capability_evidence"):
                lines.append(
                    f"- **Capability Evidence:** {st.get('capability_evidence')}"
                )
            if st.get("uncovered_capabilities"):
                lines.append(
                    f"- **Uncovered Capabilities:** {st.get('uncovered_capabilities')}"
                )
            if st.get("capability_gap"):
                lines.append("- **Gap:** No verified local skill matched this step.")
            else:
                for m in st.get("matches", []):
                    lines.append(
                        f"- **Skill:** `{m.get('id')}` (ranking_score={m.get('score')}, risk={m.get('risk')}, path=`{m.get('skill_md_path')}`)"
                    )
    else:
        for st in session.get("plan_steps", []):
            deps = ", ".join(st.get("depends_on", [])) or "none"
            lines.append(
                f"- `{st.get('id', '')}`: {st.get('title', '')} (depends_on: {deps})"
            )

    gaps = (effective_discovery or {}).get("capability_gaps", [])
    lines.extend(["", "## 5. Uncovered Capability Gaps"])
    if gaps:
        for g in gaps:
            lines.append(
                f"- `{g.get('step_id')}` ({g.get('title')}): {g.get('reason')}"
            )
    else:
        lines.append("- *(None)*")

    return "\n".join(lines) + "\n"
