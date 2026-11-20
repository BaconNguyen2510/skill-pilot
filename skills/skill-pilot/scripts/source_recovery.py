"""Fail-closed, read-only source recovery contract for Skill Pilot v4.

No network requests, scraping, authentication or skill execution occur here.
The caller is responsible for reporting an actual source-access observation.
"""

from __future__ import annotations

import re
from typing import Any, Callable

SOURCE_STATES = frozenset(
    {
        "403",
        "404",
        "login_wall",
        "deleted",
        "timeout",
        "rate_limit",
        "blocked",
        "unsupported",
        "unknown",
    }
)
KINDS = frozenset({"video", "article", "image", "document", "other"})
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\x22']+")
DEFAULT_CAPABILITIES = {
    "video": "video media content analysis transcript marketing idea",
    "article": "article research summarization source evaluation",
    "image": "image visual analysis design review",
    "document": "document review content analysis summarization",
    "other": "content analysis research evaluation",
}
DEFAULT_SOURCE_REQUEST = {
    "video": "Could you share the video, caption/transcript, screenshots or a short scene summary?",
    "article": "Could you provide the article text, a saved copy, or relevant excerpts?",
    "image": "Could you upload the image or describe the key visible details?",
    "document": "Could you upload the document or paste the relevant section?",
    "other": "Could you share the relevant content or a brief summary of it?",
}


def redact_urls(text: str) -> str:
    """Prevent accidental echoing of private or token-bearing source URLs."""
    return URL_RE.sub("[source URL omitted]", text)


def bounded_text(value: str, *, label: str, maximum: int = 2000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{label} is empty, too long, or contains NUL")
    return normalized


def make_recovery_plan(
    *,
    goal: str,
    source_status: str,
    kind: str,
    goal_ambiguous: bool = False,
    material_provided: bool = False,
    skill_query: str | None = None,
    discover: Callable[[str, int], tuple[str, list[dict[str, Any]], str]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Produce a bounded recovery decision with truthful discovery provenance.

    discover returns (status, candidates, reason); it may only perform local,
    read-only skill discovery and must not fetch the remote source.
    """
    goal = bounded_text(goal, label="goal")
    if source_status not in SOURCE_STATES:
        raise ValueError("Invalid source status")
    if kind not in KINDS:
        raise ValueError("Invalid source kind")
    if not 1 <= limit <= 10:
        raise ValueError("Recovery skill limit must be between 1 and 10")

    safe_goal = redact_urls(goal)
    result: dict[str, Any] = {
        "original_goal": safe_goal,
        "goal_preserved": not goal_ambiguous,
        "source_status": source_status,
        "source_status_provenance": "caller_reported_not_verified_by_recovery_cli",
        "source_content_fetched": False,
        "content_basis": "user_supplied_material" if material_provided else "none",
        "external_retries": 0,
        "access_control_bypassed": False,
        "skill_discovery": {
            "status": "not_attempted",
            "reason": "",
            "candidates": [],
        },
    }

    if goal_ambiguous:
        result["decision"] = "ask_one_goal_question"
        result["next_action"] = "What would you like me to do with this material?"
        result["skill_discovery"]["reason"] = "User goal not yet established"
        return result

    if material_provided:
        result["decision"] = "continue_from_user_material"
        result["next_action"] = (
            "Analyze the user-provided material for the original goal; "
            "do not claim to have inspected the blocked original URL."
        )
        result["skill_discovery"]["reason"] = (
            "Relevant source material already provided; recovery lookup not required"
        )
        return result

    query = (
        bounded_text(skill_query, label="skill query", maximum=300)
        if skill_query is not None
        else DEFAULT_CAPABILITIES[kind]
    )
    if URL_RE.search(query):
        raise ValueError("Search by capability, not the inaccessible source URL")
    result["skill_discovery"]["query"] = query

    if discover is None:
        result["skill_discovery"].update(
            {
                "status": "unavailable",
                "reason": "No local skill-discovery provider configured",
            }
        )
    else:
        try:
            status, matches, reason = discover(query, limit)
            if status not in {"completed", "unavailable"}:
                raise ValueError("Unknown discovery status")
            if not isinstance(matches, list):
                raise ValueError("Skill discovery returned invalid candidates")
            # Candidate availability is not evidence that tools were invoked.
            safe_matches = [
                {
                    "id": str(item.get("id") or "")[:160],
                    "name": str(item.get("name") or "")[:160],
                    "tier": str(item.get("tier_label") or "")[:40],
                    "skill_md_path": str(item.get("skill_md_path") or "")[:1024],
                    "exists": item.get("exists") is True,
                    "requires_inspection": True,
                }
                for item in matches[:limit]
                if isinstance(item, dict)
            ]
            result["skill_discovery"] = {
                "status": status,
                "query": query,
                "reason": redact_urls(str(reason))[:500],
                "candidates": safe_matches,
            }
        except (OSError, ValueError, TypeError) as exc:
            result["skill_discovery"] = {
                "status": "unavailable",
                "query": query,
                "reason": f"Read-only skill lookup failed: {type(exc).__name__}",
                "candidates": [],
            }

    result["decision"] = "request_missing_source_material"
    result["next_action"] = DEFAULT_SOURCE_REQUEST[kind]
    result["evaluation_criteria"] = (
        "Analyze the original goal using only content actually obtained; "
        "evaluate fit, feasibility, benefits and risks if relevant."
    )
    return result
