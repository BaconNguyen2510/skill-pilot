#!/usr/bin/env python3
"""Compatibility wrapper delegating to skills/skill-pilot/scripts/skill_scout.py."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_CANONICAL = (
    pathlib.Path(__file__).resolve().parents[1]
    / "skills"
    / "skill-pilot"
    / "scripts"
    / "skill_scout.py"
)
_SPEC = importlib.util.spec_from_file_location("_skill_scout_canonical", _CANONICAL)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

if __name__ == "__main__":
    raise SystemExit(_MOD.main())
sys.modules[__name__] = _MOD
