"""Structured session state, observable readiness, and per-step plan-search for Skill Pilot."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import os
import pathlib
import re
import stat
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
        "intent_confirmed": bool(session.get("intent_confirmed", True)),
        "has_success_criteria": len(success) > 0,
        "no_blocking_unresolved_questions": len(unresolved) == 0,
        "assumptions_acknowledged": len(unack_assumptions) == 0,
        "has_plan_steps": len(plan_steps) > 0,
        "plan_dependencies_valid": dep_check["valid"] if plan_steps else False,
        "plan_current": not bool(session.get("plan_stale", False)),
    }
    missing_for_planning = [
        k
        for k in (
            "has_confirmed_goal",
            "intent_confirmed",
            "no_blocking_unresolved_questions",
            "assumptions_acknowledged",
        )
        if not criteria[k]
    ]
    missing_for_discovery = [k for k, v in criteria.items() if not v]
    ready_for_planning = len(missing_for_planning) == 0
    ready_for_discovery = all(criteria.values())
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
        "intent_confirmed": False,
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


_GUESS_SOURCES = frozenset({"agent_guess", "guess", "inferred", "assumption"})


def update_session(
    session: dict[str, Any],
    patch: dict[str, Any],
    *,
    revision_note: str = "Session updated",
) -> dict[str, Any]:
    """Update session fields without silently losing prior history."""
    updated = copy.deepcopy(session)
    sanitized_patch = copy.deepcopy(patch)
    # Route agent guesses out of confirmed_requirements into unacknowledged assumptions
    if isinstance(sanitized_patch.get("confirmed_requirements"), list):
        kept_reqs: list[dict[str, Any]] = []
        demoted: list[dict[str, Any]] = list(sanitized_patch.get("assumptions") or [])
        for req in sanitized_patch["confirmed_requirements"]:
            src = str(req.get("source", "")).strip().lower()
            if src in _GUESS_SOURCES:
                demoted.append(
                    {
                        "id": req.get("id") or f"guess-{len(demoted) + 1}",
                        "text": req.get("text", ""),
                        "source": src,
                        "acknowledged": False,
                    }
                )
            else:
                kept_reqs.append(req)
        sanitized_patch["confirmed_requirements"] = kept_reqs
        if demoted:
            sanitized_patch["assumptions"] = demoted

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
        if field in sanitized_patch and isinstance(sanitized_patch[field], list):
            if sanitized_patch.get("replace_plan") and field == "plan_steps":
                updated[field] = copy.deepcopy(sanitized_patch[field])
            else:
                updated[field] = _merge_by_id(
                    updated.get(field, []), sanitized_patch[field]
                )

    if "intent_confirmed" in sanitized_patch:
        updated["intent_confirmed"] = bool(sanitized_patch["intent_confirmed"])

    if sanitized_patch.get("language"):
        updated["language"] = sanitized_patch["language"]

    # Every material interview change invalidates recommendations from an older intent.
    # A new plan in the same patch is treated as a deliberate replacement.
    material_changed = any(
        field in sanitized_patch
        for field in (
            "intent_confirmed",
            "confirmed_requirements",
            "assumptions",
            "unresolved_questions",
            "decisions",
            "constraints",
            "success_criteria",
            "language",
        )
    )
    plan_updated = "plan_steps" in sanitized_patch
    if material_changed and not plan_updated and updated.get("plan_steps"):
        updated["plan_stale"] = True
    elif plan_updated:
        updated["plan_stale"] = False

    if material_changed or plan_updated:
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
    """Validate unique IDs and dependencies; return stable topological order."""
    ids = [str(step.get("id") or "").strip() for step in steps]
    unique_ids = list(dict.fromkeys(sid for sid in ids if sid))
    id_set = set(unique_ids)
    duplicate_ids = sorted({sid for sid in ids if sid and ids.count(sid) > 1})
    missing_ids = [index for index, sid in enumerate(ids) if not sid]
    missing_deps: list[dict[str, str]] = []
    invalid_dependencies: list[str] = []
    dependents: dict[str, list[str]] = {sid: [] for sid in unique_ids}
    indegree = dict.fromkeys(unique_ids, 0)

    for step, sid in zip(steps, ids):
        dependencies = step.get("depends_on", [])
        if not isinstance(dependencies, list):
            invalid_dependencies.append(sid or "(missing id)")
            continue
        for dep in dict.fromkeys(str(item).strip() for item in dependencies):
            if dep not in id_set:
                missing_deps.append({"step_id": sid, "missing_dependency": dep})
            elif sid:
                dependents[dep].append(sid)
                indegree[sid] += 1

    queue = [sid for sid in unique_ids if indegree[sid] == 0]
    order: list[str] = []
    index = 0
    while index < len(queue):
        current = queue[index]
        index += 1
        order.append(current)
        for child in dependents[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    has_cycle = len(order) != len(unique_ids)
    valid = not (
        missing_deps
        or duplicate_ids
        or missing_ids
        or invalid_dependencies
        or has_cycle
    )
    return {
        "valid": valid,
        "step_count": len(steps),
        "missing_dependencies": missing_deps,
        "duplicate_step_ids": duplicate_ids,
        "missing_step_id_indices": missing_ids,
        "invalid_dependencies": invalid_dependencies,
        "has_cycle": has_cycle,
        "execution_order": order if valid else [],
    }


_EVIDENCE_STOPWORDS = frozenset(
    {
        "skill",
        "skills",
        "covers",
        "cover",
        "supports",
        "support",
        "based",
        "using",
        "with",
        "from",
        "this",
        "that",
        "step",
        "task",
        "the",
        "and",
        "for",
    }
)


MAX_CAPABILITY_MD_BYTES = 1024 * 1024


def extract_skill_capabilities(skill_md_path: str | pathlib.Path) -> dict[str, Any]:
    """Bounded, non-following read of untrusted SKILL.md for evidence checks."""
    path = pathlib.Path(skill_md_path)
    unavailable: dict[str, Any] = {
        "readable": False,
        "headings": [],
        "lower_text": "",
    }
    junction = getattr(os.path, "isjunction", None)
    try:
        for item in (path, *path.parents):
            if item.is_symlink() or (callable(junction) and junction(item)):
                return unavailable
        entry = os.lstat(path)
        if not stat.S_ISREG(entry.st_mode) or entry.st_size > MAX_CAPABILITY_MD_BYTES:
            return unavailable
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > MAX_CAPABILITY_MD_BYTES
                or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                return unavailable
            payload = os.read(fd, MAX_CAPABILITY_MD_BYTES + 1)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return unavailable
    if len(payload) > MAX_CAPABILITY_MD_BYTES:
        return unavailable
    text = payload.decode("utf-8", errors="replace")
    headings = [
        m.group(1).strip()
        for m in re.finditer(r"^#{1,3}\s+(.+)$", text, flags=re.MULTILINE)
    ]
    return {
        "readable": True,
        "headings": headings,
        "lower_text": re.sub(r"\s+", " ", text.lower()),
    }


def verify_capability_evidence(
    evidence_text: str, matches: list[dict[str, Any]]
) -> dict[str, Any]:
    """Verify capability_evidence via exact quoted passage or exact SKILL.md heading match."""
    cleaned = re.sub(r"\s+", " ", evidence_text.strip())
    if not cleaned or not matches:
        return {"verified": False, "matched_skill_id": None, "grounding_type": "none"}

    # Extract quoted spans if present, otherwise evaluate the whole cleaned evidence string
    quoted = [q.strip() for q in re.findall(r'"([^"]{12,})"', cleaned)]
    candidates = quoted or [cleaned]
    lower_cleaned = cleaned.lower()

    for m in matches:
        md_path = m.get("skill_md_path")
        if not md_path:
            continue
        caps = extract_skill_capabilities(md_path)
        if not caps["readable"]:
            continue
        skill_id = str(m.get("id", "")).lower()
        for h in caps["headings"]:
            hl = h.lower()
            if len(hl) >= 4 and hl != skill_id and hl in lower_cleaned:
                return {
                    "verified": True,
                    "matched_skill_id": m.get("id"),
                    "grounding_type": "exact_heading",
                }
        for cand in candidates:
            cl = cand.lower()
            if len(cl) >= 12 and cl != skill_id and cl in caps["lower_text"]:
                return {
                    "verified": True,
                    "matched_skill_id": m.get("id"),
                    "grounding_type": "exact_quote",
                }
    return {"verified": False, "matched_skill_id": None, "grounding_type": "none"}


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

    ordered_steps = steps
    if dep_check["valid"]:
        by_id = {str(step["id"]): step for step in steps}
        ordered_steps = [by_id[sid] for sid in dep_check["execution_order"]]

    for step in ordered_steps:
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
                    verified = (
                        bool(m.get("exists"))
                        and bool(m.get("skill_md_path"))
                        and extract_skill_capabilities(str(m["skill_md_path"]))[
                            "readable"
                        ]
                    )
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
        ev_check = verify_capability_evidence(
            assessed["capability_evidence"], verified_matches
        )
        if not verified_matches:
            coverage_level = "none"
        elif assessed["coverage_level"] == "direct":
            coverage_level = "direct" if ev_check["verified"] else "unverified_fit"
        elif assessed["coverage_level"] == "partial":
            coverage_level = (
                "partial" if assessed["uncovered_capabilities"] else "unverified_fit"
            )
        else:
            # Score is a ranking signal only; without inspected SKILL.md evidence, fit is unverified.
            coverage_level = "unverified_fit"

        is_gap = coverage_level != "direct"
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
                "evidence_verified": ev_check["verified"],
                "grounding_type": ev_check["grounding_type"],
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
        "covered_steps": sum(not item["capability_gap"] for item in step_results),
    }


def load_json_file(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _session_lock_pid_alive(pid: int | None) -> bool | None:
    """Conservative process liveness probe: unknown never means safe to steal."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                error = ctypes.get_last_error()
                if error == 5:  # Access denied: process may still be alive.
                    return True
                if error == 87:  # Invalid PID on Windows.
                    return False
                return None
            try:
                code = ctypes.c_uint32(0)
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == 259  # STILL_ACTIVE
                return None
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, AttributeError):
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _session_lock_metadata(lock_path: pathlib.Path) -> dict[str, Any]:
    """Read regular-file lock metadata, rejecting links and file replacement."""
    entry = os.lstat(lock_path)
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(f"Refusing non-regular session lock: {lock_path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(lock_path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (entry.st_dev, entry.st_ino):
            raise ValueError(f"Session lock changed while inspecting: {lock_path}")
        raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
    finally:
        os.close(fd)

    pid: int | None = None
    token: str | None = None
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            candidate = value.get("pid")
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                pid = candidate
            token_value = value.get("token")
            if isinstance(token_value, str) and token_value:
                token = token_value
        elif isinstance(value, int) and not isinstance(value, bool):
            pid = value  # Older session locks stored the PID only.
    except json.JSONDecodeError:
        pass

    return {
        "dev": entry.st_dev,
        "ino": entry.st_ino,
        "mtime_ns": entry.st_mtime_ns,
        "age_seconds": max(0.0, time.time() - entry.st_mtime),
        "pid": pid,
        "token": token,
    }


@contextlib.contextmanager
def session_lock(
    path: pathlib.Path,
    timeout_s: float = 5.0,
    stale_after_s: float = 60.0,
):
    """Exclusive cross-platform lock; never reclaim a known-live owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_s
    token = uuid.uuid4().hex
    while True:
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            flags |= getattr(os, "O_BINARY", 0)
            fd = os.open(lock_path, flags, 0o600)
            try:
                payload = (
                    json.dumps({"pid": os.getpid(), "token": token}) + "\n"
                ).encode("utf-8")
                while payload:
                    payload = payload[os.write(fd, payload) :]
                os.fsync(fd)
            except Exception:
                os.close(fd)
                with contextlib.suppress(FileNotFoundError):
                    lock_path.unlink()
                raise
            else:
                os.close(fd)
            break
        except FileExistsError:
            try:
                meta = _session_lock_metadata(lock_path)
            except FileNotFoundError:
                continue
            if meta["age_seconds"] >= stale_after_s:
                alive = _session_lock_pid_alive(meta["pid"])
                if alive is False or meta["pid"] is None:
                    try:
                        current = os.lstat(lock_path)
                        if (
                            current.st_dev,
                            current.st_ino,
                            current.st_mtime_ns,
                        ) == (meta["dev"], meta["ino"], meta["mtime_ns"]):
                            lock_path.unlink()
                            continue
                    except FileNotFoundError:
                        continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for session lock: {lock_path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        # Another process may have replaced our path; never delete its lock.
        with contextlib.suppress(FileNotFoundError):
            meta = _session_lock_metadata(lock_path)
            if meta["token"] == token and meta["pid"] == os.getpid():
                current = os.lstat(lock_path)
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_mtime_ns,
                ) == (meta["dev"], meta["ino"], meta["mtime_ns"]):
                    lock_path.unlink()


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
    readiness = compute_readiness(session)
    is_stale = (
        bool(session.get("discovery_stale")) or not readiness["ready_for_discovery"]
    )
    # Unversioned discovery is untrusted even if its content appears plausible.
    if discovery is not None and discovery.get("for_revision") != session.get(
        "revision", 1
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
            if cov != "DIRECT":
                lines.append(
                    f"- **Coverage gap:** {cov}; do not treat ranked candidates as verified capability."
                )
            for m in st.get("matches", []):
                label = "Verified skill" if cov == "DIRECT" else "Ranked candidate"
                lines.append(
                    f"- **{label}:** `{m.get('id')}` (ranking_score={m.get('score')}, risk={m.get('risk')}, path=`{m.get('skill_md_path')}`)"
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
