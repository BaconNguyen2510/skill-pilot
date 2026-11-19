"""Structured session state, observable readiness, and per-step plan-search for Skill Pilot."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import pathlib
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

    criteria = {
        "has_confirmed_goal": len(confirmed) > 0,
        "has_success_criteria": len(success) > 0,
        "no_blocking_unresolved_questions": len(unresolved) == 0,
        "assumptions_acknowledged": len(unack_assumptions) == 0,
        "has_plan_steps": len(plan_steps) > 0,
    }
    missing = [k for k, v in criteria.items() if not v]
    ready_for_planning = (
        criteria["has_confirmed_goal"]
        and criteria["no_blocking_unresolved_questions"]
        and criteria["assumptions_acknowledged"]
    )
    ready_for_discovery = ready_for_planning and criteria["has_plan_steps"]
    return {
        "criteria": criteria,
        "missing_criteria": missing,
        "ready_for_planning": ready_for_planning,
        "ready_for_discovery": ready_for_discovery,
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
        is_gap = len(verified_matches) == 0
        if is_gap:
            capability_gaps.append(
                {
                    "step_id": sid,
                    "title": title,
                    "query": query,
                    "reason": "No verified local skill matched this step.",
                }
            )

        step_results.append(
            {
                "step_id": sid,
                "title": title,
                "depends_on": step.get("depends_on", []),
                "query": query,
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


def save_json_file(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
