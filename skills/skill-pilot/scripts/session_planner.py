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
        "intent_confirmed": bool(session.get("intent_confirmed", False)),
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

    # Never let a no-op/partial plan patch revive a previously stale plan.
    if "plan_steps" in sanitized_patch and not isinstance(
        sanitized_patch["plan_steps"], list
    ):
        raise ValueError("plan_steps must be a list")

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
    new_steps = sanitized_patch.get("plan_steps", [])
    existing_steps = session.get("plan_steps", [])
    plan_reaffirmed = bool(new_steps) and (
        bool(sanitized_patch.get("replace_plan")) or not existing_steps
    )
    if material_changed and updated.get("plan_steps") and not plan_reaffirmed:
        updated["plan_stale"] = True
    elif plan_reaffirmed:
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
    invalid_step_indices = [
        index for index, step in enumerate(steps) if not isinstance(step, dict)
    ]
    ids = [
        str(step.get("id") or "").strip() if isinstance(step, dict) else ""
        for step in steps
    ]
    unique_ids = list(dict.fromkeys(sid for sid in ids if sid))
    id_set = set(unique_ids)
    duplicate_ids = sorted({sid for sid in ids if sid and ids.count(sid) > 1})
    missing_ids = [index for index, sid in enumerate(ids) if not sid]
    missing_deps: list[dict[str, str]] = []
    invalid_dependencies: list[str] = []
    dependents: dict[str, list[str]] = {sid: [] for sid in unique_ids}
    indegree = dict.fromkeys(unique_ids, 0)

    for step, sid in zip(steps, ids):
        if not isinstance(step, dict):
            continue
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
        or invalid_step_indices
        or invalid_dependencies
        or has_cycle
    )
    return {
        "valid": valid,
        "step_count": len(steps),
        "missing_dependencies": missing_deps,
        "duplicate_step_ids": duplicate_ids,
        "missing_step_id_indices": missing_ids,
        "invalid_step_indices": invalid_step_indices,
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
        "build",
        "create",
        "make",
        "use",
        "implement",
        "provide",
        "provides",
        "perform",
        "handle",
        "handles",
        "manage",
        "manages",
        "work",
        "works",
        "tool",
        "tools",
        "feature",
        "features",
        "capability",
        "capabilities",
        "tạo",
        "làm",
        "xây",
        "dựng",
        "viết",
        "thiết",
        "kế",
        "dùng",
        "cho",
        "hỗ",
        "trợ",
    }
)


MAX_CAPABILITY_MD_BYTES = 1024 * 1024
MAX_MARKDOWN_SOURCE_LINES = 8192


def _visible_skill_markdown(text: str) -> str | None:
    """Retain rendered prose; exclude fenced examples and hidden HTML comments.

    This is a bounded conservative source-evidence filter, not a full Markdown
    parser. A malformed/unclosed code fence remains inert through EOF.
    """
    fence_pattern = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
    fence_type: str | None = None
    fence_length = 0
    visible_lines: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number > MAX_MARKDOWN_SOURCE_LINES:
            return None
        marker = fence_pattern.match(line)
        if fence_type is not None:
            if (
                marker
                and marker.group(1)[0] == fence_type
                and len(marker.group(1)) >= fence_length
                and not marker.group(2).strip()
            ):
                fence_type = None
            continue
        if marker:
            opening = marker.group(1)
            if opening[0] == "`" and "`" in marker.group(2):
                # CommonMark rejects backticks in a backtick fence's info string.
                visible_lines.append(line)
                continue
            fence_type = opening[0]
            fence_length = len(opening)
            continue
        visible_lines.append(line)

    visible = "\n".join(visible_lines)
    return re.sub(r"<!--.*?(?:-->|\Z)", "", visible, flags=re.DOTALL)


def extract_skill_capabilities(skill_md_path: str | pathlib.Path) -> dict[str, Any]:
    """Bounded, non-following read of untrusted SKILL.md for evidence checks."""
    path = pathlib.Path(skill_md_path)
    unavailable: dict[str, Any] = {
        "readable": False,
        "headings": [],
        "lower_text": "",
        "statements": [],
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
    text = _visible_skill_markdown(payload.decode("utf-8", errors="replace"))
    if text is None:
        return unavailable
    # Keep sentence boundaries: flattening all visible source text loses denial scope.
    statements: list[str] = []
    for line in text.splitlines():
        for statement in re.split(r"(?<=[.!?;])\s+", line):
            if statement.strip():
                statements.append(statement.strip())
                if len(statements) > 4096:
                    return unavailable
    headings = [
        m.group(1).strip()
        for m in re.finditer(r"^#{1,3}\s+(.+)$", text, flags=re.MULTILINE)
    ]
    return {
        "readable": True,
        "headings": headings,
        "lower_text": re.sub(r"\s+", " ", text.lower()),
        "statements": statements,
    }


def _evidence_terms(text: str) -> set[str]:
    """Unicode-aware conservative content terms, not semantic equivalence."""
    return {
        token
        for token in re.findall(r"[^\W_]+", text.casefold())
        if len(token) >= 2 and token not in _EVIDENCE_STOPWORDS
    }


# Prefix cues scope to the capability *after* the cue. Suffix cues scope
# to the subject *before* the cue. Neither is semantic entailment.
_EVIDENCE_DENIAL_PREFIX = re.compile(
    r"\b(?:"
    r"(?:does|do|did)\s+not\s+(?:support|provide|implement|build|handle|allow)"
    r"|(?:doesn't|don't|didn't)\s+(?:support|provide|implement|build|handle|allow)"
    r"|(?:cannot|can't|unable\s+to)"
    r"|no\s+support\s+for"
    r"|not\s+(?:supported|implemented)\s*:"
    r"|(?:không|chưa)\s+(?:hỗ\s+trợ|cung\s+cấp|triển\s+khai|thể|có|được)"
    r")\b",
    re.IGNORECASE,
)
_EVIDENCE_DENIAL_SUFFIX = re.compile(
    r"\b(?:"
    r"(?:is|are|was|were)\s+(?:not\s+(?:supported|available|implemented|provided)"
    r"|unavailable|unsupported|out\s+of\s+scope)"
    r"|out\s+of\s+scope"
    r"|not\s+(?:supported|available|implemented)"
    r"|nằm\s+ngoài\s+phạm\s+vi"
    r"|chưa\s+(?:khả\s+dụng|được\s+(?:triển\s+khai|hỗ\s+trợ))"
    r"|không\s+khả\s+dụng"
    r")\b",
    re.IGNORECASE,
)
_EVIDENCE_CONTRAST = re.compile(r"\s+(?:but|however|nhưng)\s+", re.IGNORECASE)
_EVIDENCE_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+")


def _denies_step_capability(text: str, step_terms: set[str]) -> bool:
    """Conservative EN/VI cue-scope detector for explicit capability denials.

    Scope limits prevent an unrelated negative statement from vetoing a
    positive capability. Caller-provided labels do not override this check.
    """
    min_overlap = min(2, len(step_terms))

    def relevant(scope: str) -> bool:
        if not step_terms:
            return True
        return len(_evidence_terms(scope) & step_terms) >= min_overlap

    for statement in _EVIDENCE_SENTENCES.split(text):
        if not statement.strip():
            continue
        for cue in _EVIDENCE_DENIAL_PREFIX.finditer(statement):
            # "does not support GraphQL but supports React UI" denies only GraphQL.
            tail = _EVIDENCE_CONTRAST.split(statement[cue.end() :], maxsplit=1)[0]
            if relevant(tail):
                return True
        for cue in _EVIDENCE_DENIAL_SUFFIX.finditer(statement):
            # "React UI is planned but not implemented" retains the subject.
            if relevant(statement[: cue.start()]):
                return True
    return False


def verify_capability_evidence(
    evidence_text: str,
    matches: list[dict[str, Any]],
    *,
    step_text: str = "",
) -> dict[str, Any]:
    """Ground a quote/heading and require overlap with the specific plan step.

    This is a lexical sanity check, NOT proof of semantic capability fit.
    """
    cleaned = re.sub(r"\s+", " ", evidence_text.strip())
    if not cleaned or not matches:
        return {"verified": False, "matched_skill_id": None, "grounding_type": "none"}

    # Extract quoted spans if present, otherwise evaluate the whole cleaned evidence string
    quoted = [q.strip() for q in re.findall(r'"([^"]{12,})"', cleaned)]
    candidates = quoted or [cleaned]
    heading_probe = cleaned.strip().strip('`"').strip()
    heading_probe = re.sub(r"^#{1,3}\s+", "", heading_probe).casefold()
    step_terms = _evidence_terms(step_text)
    if step_text and not step_terms:
        return {"verified": False, "matched_skill_id": None, "grounding_type": "none"}
    if _denies_step_capability(cleaned, step_terms):
        return {"verified": False, "matched_skill_id": None, "grounding_type": "none"}

    for m in matches:
        md_path = m.get("skill_md_path")
        if not md_path:
            continue
        caps = extract_skill_capabilities(md_path)
        if not caps["readable"]:
            continue
        # A source contradicting the requested capability cannot establish
        # direct coverage, even if it also contains a positive quote/heading.
        if step_text and any(
            _denies_step_capability(statement, step_terms)
            for statement in caps["statements"]
        ):
            continue
        skill_id = str(m.get("id", "")).lower()
        for h in caps["headings"]:
            hl = h.lower()
            if (
                len(hl) >= 4
                and hl != skill_id
                and heading_probe == h.casefold()
                and (not step_text or step_terms & _evidence_terms(h))
                and not _denies_step_capability(h, step_terms)
            ):
                return {
                    "verified": True,
                    "matched_skill_id": m.get("id"),
                    "grounding_type": "exact_heading",
                }
        for cand in candidates:
            cl = cand.lower()
            if (
                len(cl) >= 12
                and cl != skill_id
                and cl in caps["lower_text"]
                and (not step_text or step_terms & _evidence_terms(cand))
                and not _denies_step_capability(cand, step_terms)
            ):
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

    if not dep_check["valid"]:
        # No search or capability claim is permissible for a malformed DAG.
        return {
            "dependency_validation": dep_check,
            "discovery_blocked": True,
            "steps": [],
            "capability_gaps": [],
            "total_steps": len(steps),
            "covered_steps": 0,
        }

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
            assessed["capability_evidence"],
            verified_matches,
            step_text=f"{title} {query}",
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
        "discovery_blocked": False,
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
        if pid > 0xFFFFFFFF:
            return None
        # PROCESS_QUERY is unnecessary: SYNCHRONIZE permits a zero-time wait.
        # ctypes defaults to C int, so explicitly type every pointer-sized HANDLE.
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            wait_process = kernel32.WaitForSingleObject
            wait_process.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait_process.restype = wintypes.DWORD
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL

            handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                error = ctypes.get_last_error()
                if error == 5:  # Protected process; treat as possibly alive.
                    return True
                if error == 87:  # ERROR_INVALID_PARAMETER (nonexistent PID).
                    return False
                return None
            try:
                state = wait_process(handle, 0)
                if state == 0x00000102:  # WAIT_TIMEOUT: still running.
                    return True
                if state == 0:  # WAIT_OBJECT_0: process terminated.
                    return False
                return None
            finally:
                close_handle(handle)
        except (OSError, AttributeError, TypeError):
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


def create_session_file_locked(
    session_path: pathlib.Path, data: dict[str, Any]
) -> None:
    """Never overwrite an existing session or its revision history during init."""
    with session_lock(session_path):
        if session_path.exists() or session_path.is_symlink():
            raise FileExistsError(f"Session already exists: {session_path}")
        save_json_file(session_path, data)


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
        if not compute_readiness(current)["ready_for_discovery"]:
            raise ValueError("Session no longer ready for discovery; results rejected.")
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

    lines.extend(["", "## 6. Dependency Order & Next Action"])
    plan_check = validate_plan_dependencies(session.get("plan_steps", []))
    if plan_check["valid"] and plan_check["execution_order"]:
        for index, sid in enumerate(plan_check["execution_order"], start=1):
            lines.append(f"{index}. `{sid}`")
    else:
        lines.append("- Plan dependency graph is incomplete or invalid.")

    if effective_discovery is None:
        missing = ", ".join(readiness["missing_criteria"]) or "outdated discovery"
        lines.append(
            f"> **BLOCKED:** Resolve {missing}; rerun discovery before any execution."
        )
    else:
        missing_fit = [
            step.get("step_id", "")
            for step in effective_discovery.get("steps", [])
            if step.get("coverage_level") != "direct"
        ]
        if missing_fit:
            lines.append(
                "> **REVIEW REQUIRED:** The following steps have unverified or "
                "partial skill coverage: " + ", ".join(missing_fit)
            )
        else:
            lines.append(
                "> **Handoff:** Reconfirm the approved requirements and constraints "
                "above; inspect each selected SKILL.md as untrusted data, execute "
                "the dependency-ordered steps only with existing authorization, "
                "then report observed acceptance-check outcomes. Exact text "
                "grounding does not prove semantic capability fit."
            )

    return "\n".join(lines) + "\n"
