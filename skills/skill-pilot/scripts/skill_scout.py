#!/usr/bin/env python3
"""Cross-plugin and multi-tier skill discovery helper for Skill Pilot.

Provides deterministic, zero-dependency indexing across:
- Tier 1: Active Antigravity and Codex skills (plugins, global, builtin, workspace)
- Tier 2: Local skill warehouses (skills_index.json or skills/*/SKILL.md)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile
import time
import tomllib
import unicodedata
import uuid
from typing import Any

__version__ = "3.1.1"

HOME = pathlib.Path.home()
_HERE = pathlib.Path(__file__).resolve()
if _HERE.parent.name == "scripts" and _HERE.parent.parent.name == "skill-pilot":
    SKILL_ROOT = _HERE.parent.parent
    _CANDIDATE_ROOT = SKILL_ROOT.parents[1] if len(_HERE.parents) >= 4 else SKILL_ROOT
    PLUGIN_ROOT = (
        _CANDIDATE_ROOT
        if (_CANDIDATE_ROOT / "plugin.json").is_file()
        or (_CANDIDATE_ROOT / ".codex-plugin" / "plugin.json").is_file()
        else SKILL_ROOT
    )
else:
    PLUGIN_ROOT = _HERE.parents[1]
    SKILL_ROOT = PLUGIN_ROOT / "skills" / "skill-pilot"
GEMINI_CONFIG_DIR = HOME / ".gemini" / "config"
PLUGINS_DIR = GEMINI_CONFIG_DIR / "plugins"
GLOBAL_SKILLS_DIR = GEMINI_CONFIG_DIR / "skills"
BUILTIN_SKILLS_DIR = HOME / ".gemini" / "antigravity" / "builtin" / "skills"
CONFIG_JSON_PATH = GEMINI_CONFIG_DIR / "config.json"

LOCAL_CONFIG_PATHS = tuple(
    dict.fromkeys(
        [
            PLUGIN_ROOT / ".skill-pilot.local.json",
            SKILL_ROOT / ".skill-pilot.local.json",
            GEMINI_CONFIG_DIR / "skill-pilot.local.json",
        ]
    )
)
DEFAULT_WAREHOUSES = (HOME / ".agents" / "warehouses" / "agentic-awesome-skills",)
ECC_WAREHOUSES = (HOME / ".gemini" / "antigravity" / "ecc",)
CODEX_DIR = HOME / ".codex"
CODEX_SKILLS_DIR = CODEX_DIR / "skills"
CODEX_INACTIVE_SKILLS_DIR = CODEX_DIR / "skills-inactive"
CODEX_CONFIG_PATH = CODEX_DIR / "config.toml"
CODEX_CACHE_DIR = CODEX_DIR / "plugins" / "cache"

SCRIPT_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ksh",
    ".csh",
    ".ps1",
    ".psm1",
    ".psd1",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".bat",
    ".cmd",
    ".rb",
    ".pl",
    ".php",
    ".vbs",
    ".exe",
    ".dll",
    ".jar",
    ".wasm",
    ".com",
    ".msi",
    ".pyw",
    ".vbe",
    ".wsf",
    ".hta",
    ".lnk",
    ".so",
    ".dylib",
    ".pyc",
}
_BINARY_MAGIC_PREFIXES = (
    b"\x7fELF",
    b"MZ",
    b"\x00asm",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
)
HEALTHY_ACTIVE_CEILING = 90
MAX_FRONTMATTER_BYTES = 64 * 1024
MAX_RULE_FILE_BYTES = 256 * 1024
MAX_WAREHOUSE_INDEX_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 10 * 1024 * 1024
MAX_SKILL_TOTAL_BYTES = 50 * 1024 * 1024
MAX_SKILL_ENTRIES = 500
MAX_INSPECT_DEPTH = 8
MAX_INTAKE_RULE_DEPTH = 3
MAX_INTAKE_RULE_FILES = 20
SKIP_WALK_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
SAFE_PROMOTE_RISKS = frozenset({"safe", "low"})
TIER_BONUS = {"active": 2.0, "warehouse": 0.0, "inactive": -0.5}
TIER_RANK = {"active": 0, "warehouse": 1, "inactive": 2}
MIN_SEARCH_RAW_SCORE = 1.1
SEARCH_RATIO_CUTOFF = 0.4
COPY_CHUNK_BYTES = 64 * 1024
_LAST_CONFIG_WARNING: str | None = None
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_INVISIBLE_SPOOF_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff\u00ad]"
)


def _sanitize_compact(value: Any, max_len: int = 120) -> str:
    """Strip ANSI escapes, control chars, invisible bidi/zero-width chars, newlines, and pipes."""
    text = _ANSI_RE.sub("", str(value))
    text = _INVISIBLE_SPOOF_RE.sub("", text)
    text = _CTRL_RE.sub(" ", text).replace("|", "/")
    text = re.sub(r"\s+", " ", text).strip()
    if max_len > 3 and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text[:max_len]


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _is_link_or_reparse(path: pathlib.Path) -> bool:
    """Return True if path is a symlink, Windows junction, or NTFS reparse point."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        if callable(is_junction) and is_junction(path):
            return True
        reparse_attr = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if reparse_attr:
            st = os.lstat(path)
            if (getattr(st, "st_file_attributes", 0) or 0) & reparse_attr:
                return True
    except OSError:
        return False
    return False


def _validate_relative_skill_path(
    root: pathlib.Path, rel_path: str
) -> pathlib.Path | None:
    """Resolve rel_path strictly inside root while rejecting symlinks and junctions."""
    raw = rel_path.strip()
    if not raw:
        return None
    if raw.startswith(("/", "\\")) or pathlib.PureWindowsPath(raw).is_absolute():
        return None
    parts = [p for p in re.split(r"[\\/]+", raw) if p]
    if not parts or ":" in parts[0] or any(part in (".", "..") for part in parts):
        return None
    try:
        root_real = root.resolve(strict=True)
    except OSError:
        return None

    cur = root
    for part in parts:
        cur = cur / part
        if _is_link_or_reparse(cur):
            return None
    try:
        src_real = cur.resolve(strict=True)
    except OSError:
        return None
    if (
        src_real == root_real
        or not src_real.is_relative_to(root_real)
        or not cur.is_dir()
        or _is_link_or_reparse(cur)
    ):
        return None
    skill_md = cur / "SKILL.md"
    if not skill_md.is_file() or _is_link_or_reparse(skill_md):
        return None
    return src_real


def _copy_fd_stream(
    src_fd: int, dst_path: pathlib.Path, total_bytes: int
) -> tuple[int, int]:
    """Stream src_fd into a new dst_path while enforcing file and tree byte budgets."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    dst_fd = os.open(dst_path, flags, 0o644)
    file_bytes = 0
    try:
        while True:
            chunk = os.read(src_fd, COPY_CHUNK_BYTES)
            if not chunk:
                break
            file_bytes += len(chunk)
            total_bytes += len(chunk)
            if file_bytes > MAX_SKILL_FILE_BYTES:
                raise ValueError(
                    f"File exceeds size limit ({MAX_SKILL_FILE_BYTES} bytes)"
                )
            if total_bytes > MAX_SKILL_TOTAL_BYTES:
                raise ValueError(
                    f"Skill exceeds total size limit ({MAX_SKILL_TOTAL_BYTES} bytes)"
                )
            view = memoryview(chunk)
            written = 0
            while written < len(view):
                n = os.write(dst_fd, view[written:])
                if n <= 0:
                    raise OSError("Short write copying skill file")
                written += n
    finally:
        os.close(dst_fd)
    return file_bytes, total_bytes


def _bounded_scandir(
    target: int | pathlib.Path,
    remaining_budget: int,
    *,
    skip_dir_names: frozenset[str] = frozenset(),
) -> tuple[list[os.DirEntry[str]], bool]:
    """Read directory entries up to remaining_budget before sorting to bound traversal."""
    collected: list[os.DirEntry[str]] = []
    overflow = False
    limit = max(remaining_budget, 0)
    with os.scandir(target) as it:
        for entry in it:
            if (
                skip_dir_names
                and entry.name in skip_dir_names
                and entry.is_dir(follow_symlinks=False)
                and not _is_link_or_reparse(pathlib.Path(entry.path))
            ):
                continue
            if len(collected) >= limit:
                overflow = True
                break
            collected.append(entry)
    if not overflow:
        collected.sort(key=lambda e: e.name)
    return collected, overflow


def _copy_skill_tree_safely(
    src_dir: pathlib.Path,
    stage_dir: pathlib.Path,
    *,
    allow_scripts: bool = False,
    max_depth: int = MAX_INSPECT_DEPTH,
) -> dict[str, int]:
    """Copy a validated skill tree safely without symlinks, special files, or unapproved scripts."""
    if _is_link_or_reparse(src_dir):
        raise ValueError(f"Source skill directory is a symlink or junction: {src_dir}")
    src_real = src_dir.resolve(strict=True)
    counts = {"files": 0, "bytes": 0, "entries": 0}
    use_posix_dir_fd = os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
    nonblock_flag = getattr(os, "O_NONBLOCK", 0)

    def _check_copied_shebang(dst_file: pathlib.Path, rel_path: str) -> None:
        if allow_scripts:
            return
        try:
            with dst_file.open("rb") as chk:
                head = chk.read(16)
                stripped = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
                if stripped.startswith(b"#!") or head.startswith(
                    _BINARY_MAGIC_PREFIXES
                ):
                    raise ValueError(
                        f"Unapproved script or binary detected during copy: {rel_path}"
                    )
        except OSError as exc:
            raise ValueError(f"Failed verifying staged file {rel_path}: {exc}") from exc

    def copy_posix(
        src_fd: int, dst_dir: pathlib.Path, rel_prefix: str = "", depth: int = 0
    ) -> None:
        remaining = MAX_SKILL_ENTRIES - counts["entries"]
        entries, overflow = _bounded_scandir(src_fd, remaining)
        if overflow:
            raise ValueError(f"Skill exceeds maximum entry limit ({MAX_SKILL_ENTRIES})")
        for entry in entries:
            counts["entries"] += 1
            if counts["entries"] > MAX_SKILL_ENTRIES:
                raise ValueError(
                    f"Skill exceeds maximum entry limit ({MAX_SKILL_ENTRIES})"
                )
            rel_path = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
            if entry.is_symlink():
                raise ValueError(f"Symlink not allowed inside skill: {rel_path}")
            lst = os.stat(entry.name, dir_fd=src_fd, follow_symlinks=False)
            if not (stat.S_ISDIR(lst.st_mode) or stat.S_ISREG(lst.st_mode)):
                raise ValueError(f"Unsupported non-regular file in skill: {rel_path}")
            child_fd = os.open(
                entry.name,
                os.O_RDONLY | os.O_NOFOLLOW | nonblock_flag,
                dir_fd=src_fd,
            )
            try:
                st = os.fstat(child_fd)
                if stat.S_ISDIR(st.st_mode):
                    if depth >= max_depth:
                        raise ValueError(
                            f"Skill exceeds maximum directory depth ({max_depth})"
                        )
                    sub_dst = dst_dir / entry.name
                    sub_dst.mkdir(parents=False, exist_ok=True)
                    copy_posix(child_fd, sub_dst, rel_path, depth + 1)
                elif stat.S_ISREG(st.st_mode):
                    if not allow_scripts and _is_script_or_executable_meta(
                        entry.name, rel_path, st.st_mode
                    ):
                        raise ValueError(
                            f"Unapproved script detected during copy: {rel_path}"
                        )
                    if st.st_size > MAX_SKILL_FILE_BYTES:
                        raise ValueError(f"File exceeds size limit: {rel_path}")
                    dst_file = dst_dir / entry.name
                    _, counts["bytes"] = _copy_fd_stream(
                        child_fd, dst_file, counts["bytes"]
                    )
                    _check_copied_shebang(dst_file, rel_path)
                    mode = stat.S_IMODE(st.st_mode) & 0o777
                    if mode:
                        os.chmod(dst_file, mode)
                    counts["files"] += 1
                else:
                    raise ValueError(
                        f"Unsupported non-regular file in skill: {rel_path}"
                    )
            finally:
                os.close(child_fd)

    def copy_windows(
        cur_src: pathlib.Path,
        dst_dir: pathlib.Path,
        rel_prefix: str = "",
        depth: int = 0,
    ) -> None:
        remaining = MAX_SKILL_ENTRIES - counts["entries"]
        entries, overflow = _bounded_scandir(cur_src, remaining)
        if overflow:
            raise ValueError(f"Skill exceeds maximum entry limit ({MAX_SKILL_ENTRIES})")
        for entry in entries:
            counts["entries"] += 1
            if counts["entries"] > MAX_SKILL_ENTRIES:
                raise ValueError(
                    f"Skill exceeds maximum entry limit ({MAX_SKILL_ENTRIES})"
                )
            rel_path = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
            entry_path = pathlib.Path(entry.path)
            if _is_link_or_reparse(entry_path):
                raise ValueError(
                    f"Symlink or junction not allowed inside skill: {rel_path}"
                )
            lst = os.lstat(entry_path)
            if stat.S_ISDIR(lst.st_mode):
                if depth >= max_depth:
                    raise ValueError(
                        f"Skill exceeds maximum directory depth ({max_depth})"
                    )
                if not entry_path.resolve(strict=True).is_relative_to(src_real):
                    raise ValueError(f"Directory escapes source root: {rel_path}")
                sub_dst = dst_dir / entry.name
                sub_dst.mkdir(parents=False, exist_ok=True)
                copy_windows(entry_path, sub_dst, rel_path, depth + 1)
            elif stat.S_ISREG(lst.st_mode):
                if not allow_scripts and _is_script_or_executable_meta(
                    entry.name, rel_path, lst.st_mode
                ):
                    raise ValueError(
                        f"Unapproved script detected during copy: {rel_path}"
                    )
                if lst.st_size > MAX_SKILL_FILE_BYTES:
                    raise ValueError(f"File exceeds size limit: {rel_path}")
                fd = os.open(entry_path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    fst = os.fstat(fd)
                    if not stat.S_ISREG(fst.st_mode):
                        raise ValueError(
                            f"Unsupported non-regular file in skill: {rel_path}"
                        )
                    if (lst.st_dev or lst.st_ino) and (
                        lst.st_dev,
                        lst.st_ino,
                    ) != (fst.st_dev, fst.st_ino):
                        raise OSError(
                            f"File modified during promotion copy: {rel_path}"
                        )
                    if _is_link_or_reparse(entry_path) or not entry_path.resolve(
                        strict=True
                    ).is_relative_to(src_real):
                        raise ValueError(f"Source file changed or escaped: {rel_path}")
                    dst_file = dst_dir / entry.name
                    _, counts["bytes"] = _copy_fd_stream(fd, dst_file, counts["bytes"])
                    _check_copied_shebang(dst_file, rel_path)
                    counts["files"] += 1
                finally:
                    os.close(fd)
            else:
                raise ValueError(f"Unsupported non-regular entry in skill: {rel_path}")

    if use_posix_dir_fd:
        dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
        root_fd = os.open(src_real, dir_flags)
        try:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise ValueError(f"Source is not a directory: {src_dir}")
            copy_posix(root_fd, stage_dir)
        finally:
            os.close(root_fd)
    else:
        copy_windows(src_real, stage_dir)

    staged_skill = stage_dir / "SKILL.md"
    if not staged_skill.is_file() or _is_link_or_reparse(staged_skill):
        raise ValueError("Staged skill copy is missing a valid SKILL.md")
    return counts


def _swap_staged_directory(
    stage_dir: pathlib.Path, dest_dir: pathlib.Path, *, overwrite: bool
) -> None:
    """Install stage_dir into dest_dir atomically with rollback if replacement fails."""
    if _is_link_or_reparse(dest_dir):
        raise PermissionError(f"Destination is a symlink or junction: {dest_dir}")
    if dest_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Destination already exists: {dest_dir}. Pass --overwrite to replace."
            )
        if (
            not dest_dir.is_dir()
            or not (dest_dir / "SKILL.md").is_file()
            or _is_link_or_reparse(dest_dir / "SKILL.md")
        ):
            raise ValueError(
                f"Refusing to overwrite non-skill directory (missing SKILL.md): {dest_dir}"
            )
        backup_dir = dest_dir.parent / (
            f".{dest_dir.name}.bak-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        os.replace(dest_dir, backup_dir)
        try:
            os.replace(stage_dir, dest_dir)
        except OSError as swap_exc:
            try:
                os.replace(backup_dir, dest_dir)
            except OSError as rollback_exc:
                raise OSError(
                    f"Promotion swap failed ({swap_exc}) and rollback failed ({rollback_exc}); backup retained at {backup_dir}"
                ) from swap_exc
            raise OSError(
                f"Promotion swap failed; existing skill restored: {swap_exc}"
            ) from swap_exc
        shutil.rmtree(backup_dir, ignore_errors=True)
    else:
        os.replace(stage_dir, dest_dir)


def _strip_jsonc_comments(raw: str) -> str:
    """Strip // and /* */ comments and trailing commas outside string literals."""
    no_comments: list[str] = []
    i = 0
    n = len(raw)
    in_string = False
    escape = False
    while i < n:
        ch = raw[i]
        if in_string:
            no_comments.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            no_comments.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "/":
            i += 2
            while i < n and raw[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "*":
            i += 2
            closed = False
            while i + 1 < n:
                if raw[i] == "*" and raw[i + 1] == "/":
                    i += 2
                    closed = True
                    break
                i += 1
            if not closed:
                raise ValueError("Unterminated block comment in JSONC")
            continue
        no_comments.append(ch)
        i += 1

    if in_string:
        raise ValueError("Unterminated string in JSONC")

    stripped = "".join(no_comments)
    out: list[str] = []
    in_string = False
    escape = False
    m = len(stripped)
    i = 0
    while i < m:
        ch = stripped[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < m and stripped[j] in " \t\r\n":
                j += 1
            if j < m and stripped[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _load_jsonc_checked(path: pathlib.Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
        data = json.loads(_strip_jsonc_comments(text))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, str(exc)
    if not isinstance(data, dict):
        return {}, "root JSON value is not an object"
    return data, None


def _load_jsonc(path: pathlib.Path) -> dict[str, Any]:
    data, _ = _load_jsonc_checked(path)
    return data


def _unquote_scalar(val: str) -> str:
    if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        inner = val[1:-1]
        return re.sub(
            r'\\(["\\nt])',
            lambda m: {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}[m.group(1)],
            inner,
        ).strip()
    if len(val) >= 2 and val.startswith("'") and val.endswith("'"):
        return val[1:-1].replace("''", "'").strip()
    return val.strip()


def parse_frontmatter_text(
    text: str, default_name: str, *, allow_fallback: bool = True
) -> dict[str, str]:
    """Parse bounded YAML frontmatter text using pure stdlib."""
    lines = text[:MAX_FRONTMATTER_BYTES].splitlines()
    fallback = {"name": default_name if allow_fallback else "", "description": ""}
    if not lines or lines[0].strip() != "---":
        return fallback

    fm_lines: list[str] = []
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        fm_lines.append(line)
    if not closed:
        return fallback

    result: dict[str, str] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            i += 1
            continue
        key = match.group(1).strip()
        val = match.group(2).strip()
        if val in (">", ">-", "|", "|-"):
            block: list[str] = []
            i += 1
            while i < len(fm_lines):
                nxt = fm_lines[i]
                if nxt and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
                i += 1
            joined = (
                " ".join(part for part in block if part)
                if val.startswith(">")
                else "\n".join(block).strip()
            )
            result[key] = joined.strip()
            continue
        result[key] = _unquote_scalar(val)
        i += 1

    if allow_fallback and not result.get("name"):
        result["name"] = default_name
    elif "name" not in result:
        result["name"] = ""
    if "description" not in result:
        result["description"] = ""
    return result


def parse_frontmatter(skill_md: pathlib.Path) -> dict[str, str]:
    """Parse bounded YAML frontmatter name and description using pure stdlib."""
    with skill_md.open("r", encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read(MAX_FRONTMATTER_BYTES)
    return parse_frontmatter_text(text, skill_md.parent.name, allow_fallback=True)


def _parse_plugin_states() -> tuple[set[str], set[str], str | None]:
    cfg, err = _load_jsonc_checked(CONFIG_JSON_PATH)
    plugins_cfg = cfg.get("plugins", {}) if isinstance(cfg, dict) else {}
    disabled: set[str] = set()
    explicitly_enabled: set[str] = set()
    if isinstance(plugins_cfg, dict):
        for pdir, state in plugins_cfg.items():
            if not isinstance(state, dict):
                continue
            enabled_val = state.get("enabled")
            if enabled_val is False:
                disabled.add(pdir)
            elif enabled_val is True:
                explicitly_enabled.add(pdir)
    return disabled, explicitly_enabled, err


def _disabled_plugin_dirs() -> set[str]:
    disabled, _, _ = _parse_plugin_states()
    return disabled


def _safe_resolved_str(path_str: str) -> str:
    if not path_str:
        return ""
    try:
        return str(pathlib.Path(path_str).expanduser().resolve())
    except OSError:
        return os.path.normcase(os.path.normpath(path_str))


def _skill_content_digest(skill_md_str: str) -> str | None:
    if not skill_md_str:
        return None
    skill_md = pathlib.Path(skill_md_str).expanduser()
    try:
        if not skill_md.is_file() or _is_link_or_reparse(skill_md):
            return None
        sdir = skill_md.parent
        if not sdir.is_dir() or _is_link_or_reparse(sdir):
            return None
    except OSError:
        return None
    scan = _scan_skill_dir_metadata(sdir, include_hidden_dirs=True)
    if (
        scan["symlinks_detected"]
        or scan["special_files_detected"]
        or scan["truncated"]
        or len(scan["files"]) > 50
    ):
        return None
    hasher = hashlib.sha256()
    for rel in scan["files"]:
        fpath = sdir / rel
        try:
            st = os.lstat(fpath)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FRONTMATTER_BYTES:
                return None
            data = fpath.read_bytes()
        except OSError:
            return None
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\x00")
        if rel.lower().endswith((".md", ".txt", ".json", ".py", ".sh")):
            data = data.replace(b"\r\n", b"\n")
        hasher.update(hashlib.sha256(data).digest())
    return hasher.hexdigest()


def _same_skill_identity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True only when two entries refer to the same canonical physical file."""
    path_a = _safe_resolved_str(str(a.get("skill_md_path") or ""))
    path_b = _safe_resolved_str(str(b.get("skill_md_path") or ""))
    return bool(path_a and path_b and path_a == path_b)


def _cached_skill_digest(
    item: dict[str, Any], digest_cache: dict[str, str | None]
) -> str | None:
    raw_path = str(item.get("skill_md_path") or "")
    key = _safe_resolved_str(raw_path) or raw_path
    if not key:
        return None
    if key not in digest_cache:
        digest_cache[key] = _skill_content_digest(raw_path)
    return digest_cache[key]


def _same_skill_content(
    a: dict[str, Any],
    b: dict[str, Any],
    digest_cache: dict[str, str | None],
) -> bool:
    """Return True when two entries share a verified identical tree digest."""
    digest_a = _cached_skill_digest(a, digest_cache)
    digest_b = _cached_skill_digest(b, digest_cache)
    return digest_a is not None and digest_b is not None and digest_a == digest_b


def _version_sort_key(path: pathlib.Path) -> tuple[tuple[int, ...], float]:
    nums = tuple(int(part) for part in re.findall(r"\d+", path.name))
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return nums, mtime


def collect_active_skills(
    workspace: str | None = None, harness: str = "antigravity"
) -> list[dict[str, Any]]:
    """Collect all Tier 1 active skills across plugins, global, builtin, and workspace."""
    global _LAST_CONFIG_WARNING
    skills: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    by_name: dict[str, list[dict[str, Any]]] = {}
    disabled_dirs, explicitly_enabled, config_err = _parse_plugin_states()
    _LAST_CONFIG_WARNING = config_err
    if config_err is not None:
        print(
            f"Warning: failed parsing {CONFIG_JSON_PATH} ({config_err}); omitting Antigravity plugins (fail-closed)",
            file=sys.stderr,
        )

    digest_cache: dict[str, str | None] = {}

    def register_item(item: dict[str, Any]) -> None:
        resolved = _safe_resolved_str(str(item.get("skill_md_path") or ""))
        if resolved and resolved in seen_paths:
            return
        if resolved:
            seen_paths.add(resolved)
        name = str(item.get("name") or "")
        item_copy = dict(item)
        siblings = by_name.get(name, [])
        same_identity_shadow = False
        for prev in siblings:
            if _same_skill_identity(prev, item_copy):
                same_identity_shadow = True
                continue
            if _same_skill_content(prev, item_copy, digest_cache):
                prev["duplicate_candidate"] = True
                item_copy["duplicate_candidate"] = True
            prev["name_collision"] = True
            item_copy["name_collision"] = True
        item_copy["shadowed"] = same_identity_shadow
        skills.append(item_copy)
        by_name.setdefault(name, []).append(item_copy)

    def add_skill(
        skill_md: pathlib.Path, source: str, tier: str, priority: int
    ) -> None:
        meta = parse_frontmatter(skill_md)
        register_item(
            {
                "name": meta["name"],
                "description": meta["description"],
                "source": source,
                "tier": tier,
                "priority": priority,
                "skill_md_path": str(skill_md),
            }
        )

    include_antigravity = harness in ("auto", "antigravity", "all")
    if workspace:
        ws_path = pathlib.Path(workspace).expanduser().resolve()
        workspace_roots = [ws_path]
        if ws_path.name.lower() == "workspaces" and ws_path.is_dir():
            workspace_roots.extend(
                sorted(path for path in ws_path.iterdir() if path.is_dir())
            )
        for root in workspace_roots:
            for dot_dir in (".agents", ".agent", "_agents", "_agent"):
                skills_root = root / dot_dir / "skills"
                if skills_root.is_dir():
                    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
                        add_skill(
                            skill_md, f"workspace:{root.name}", "tier1-workspace", 1
                        )

    if include_antigravity and GLOBAL_SKILLS_DIR.is_dir():
        for skill_md in sorted(GLOBAL_SKILLS_DIR.glob("*/SKILL.md")):
            add_skill(skill_md, "global:skills", "tier1-global", 2)

    if include_antigravity and config_err is None and PLUGINS_DIR.is_dir():
        for plugin_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()):
            manifest = _load_jsonc(plugin_dir / "plugin.json")
            if plugin_dir.name in disabled_dirs:
                continue
            if (
                manifest.get("disabled") is True
                and plugin_dir.name not in explicitly_enabled
            ):
                continue
            plugin_name = str(manifest.get("name") or plugin_dir.name)
            skills_dir = plugin_dir / "skills"
            if skills_dir.is_dir():
                for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
                    add_skill(skill_md, f"plugin:{plugin_name}", "tier1-plugin", 3)

    if include_antigravity and BUILTIN_SKILLS_DIR.is_dir():
        for skill_md in sorted(BUILTIN_SKILLS_DIR.glob("*/SKILL.md")):
            add_skill(skill_md, "builtin", "tier1-builtin", 4)

    if harness in ("auto", "codex", "all"):
        for codex_item in collect_codex_skills():
            register_item(codex_item)
    return skills


def _codex_plugin_sources(
    include_inactive: bool = False,
) -> list[tuple[str, pathlib.Path, bool]]:
    """Resolve installed Codex plugin paths and report whether each is enabled."""
    try:
        config = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []

    sources: list[tuple[str, pathlib.Path, bool]] = []
    marketplaces = config.get("marketplaces", {})
    plugins = config.get("plugins", {})
    if not isinstance(marketplaces, dict) or not isinstance(plugins, dict):
        return []
    for plugin_id, state in plugins.items():
        if not isinstance(state, dict) or "@" not in plugin_id:
            continue
        enabled = state.get("enabled") is True
        if not enabled and not include_inactive:
            continue
        plugin_name, marketplace_name = plugin_id.split("@", 1)
        marketplace = marketplaces.get(marketplace_name, {})
        local_source = (
            str(marketplace.get("source", "")) if isinstance(marketplace, dict) else ""
        )
        local_source = local_source.removeprefix("\\\\?\\")
        candidate_roots: list[pathlib.Path] = []
        if (
            isinstance(marketplace, dict)
            and marketplace.get("source_type") == "local"
            and local_source
        ):
            local_path = pathlib.Path(local_source)
            if local_path.is_dir():
                candidate_roots.append(local_path)
        cache_root = CODEX_CACHE_DIR / marketplace_name / plugin_name
        if cache_root.is_dir():
            version_dirs = sorted(
                (v for v in cache_root.iterdir() if v.is_dir()),
                key=_version_sort_key,
                reverse=True,
            )
            candidate_roots.extend(version_dirs)
        if candidate_roots:
            chosen_root = next(
                (
                    root
                    for root in candidate_roots
                    if any(root.glob("skills/*/SKILL.md"))
                ),
                candidate_roots[0],
            )
            sources.append((plugin_id, chosen_root, enabled))
    return sources


def collect_codex_skills(include_inactive: bool = False) -> list[dict[str, Any]]:
    """Collect Codex skills, optionally including disabled plugin skills as candidates."""
    skills: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add(skill_md: pathlib.Path, source: str, tier: str, priority: int) -> None:
        resolved = _safe_resolved_str(str(skill_md))
        if resolved and resolved in seen_paths:
            return
        if resolved:
            seen_paths.add(resolved)
        meta = parse_frontmatter(skill_md)
        skills.append(
            {
                "name": meta["name"],
                "description": meta["description"],
                "source": source,
                "tier": tier,
                "priority": priority,
                "shadowed": False,
                "skill_md_path": str(skill_md),
                "inactive": source.startswith(
                    ("codex-plugin-inactive:", "codex-skill-inactive")
                ),
            }
        )

    if CODEX_SKILLS_DIR.is_dir():
        for skill_md in sorted(CODEX_SKILLS_DIR.glob("*/SKILL.md")):
            add(skill_md, "codex:global-skills", "tier1-codex", 5)
    if include_inactive and CODEX_INACTIVE_SKILLS_DIR.is_dir():
        for skill_md in sorted(CODEX_INACTIVE_SKILLS_DIR.glob("*/SKILL.md")):
            add(skill_md, "codex-skill-inactive", "tier2-codex-inactive", 7)
    for plugin_id, plugin_root, enabled in _codex_plugin_sources(include_inactive):
        source = (
            f"codex-plugin:{plugin_id}"
            if enabled
            else f"codex-plugin-inactive:{plugin_id}"
        )
        for skill_md in sorted(plugin_root.glob("skills/*/SKILL.md")):
            add(
                skill_md,
                source,
                "tier1-codex-plugin" if enabled else "tier2-codex-inactive",
                6,
            )
    return skills


def _is_valid_warehouse(wh: pathlib.Path) -> bool:
    return (wh / "skills_index.json").is_file() or (wh / "skills").is_dir()


def _load_warehouse_records(wh: pathlib.Path) -> list[dict[str, Any]]:
    index_path = wh / "skills_index.json"
    if index_path.is_file():
        if _is_link_or_reparse(index_path):
            print(
                f"Warning: skipping symlinked warehouse index {index_path}",
                file=sys.stderr,
            )
            return []
        try:
            if index_path.stat().st_size > MAX_WAREHOUSE_INDEX_BYTES:
                print(
                    f"Warning: skipping oversized warehouse index {index_path}",
                    file=sys.stderr,
                )
                return []
            data = json.loads(index_path.read_text(encoding="utf-8-sig"))
            return (
                [rec for rec in data if isinstance(rec, dict)]
                if isinstance(data, list)
                else []
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"Warning: failed reading {index_path}: {exc}", file=sys.stderr)
            return []

    skills_root = wh / "skills"
    if not skills_root.is_dir() or _is_link_or_reparse(skills_root):
        return []
    records: list[dict[str, Any]] = []
    warehouse_name = wh.name.lower()
    skill_md_candidates: list[pathlib.Path] = []
    max_records = MAX_SKILL_ENTRIES * 4
    try:
        with os.scandir(skills_root) as entries:
            for entry in entries:
                if len(skill_md_candidates) >= max_records:
                    break
                try:
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                sub_dir = pathlib.Path(entry.path)
                skill_md = sub_dir / "SKILL.md"
                if (
                    _is_link_or_reparse(sub_dir)
                    or _is_link_or_reparse(skill_md)
                    or not skill_md.is_file()
                ):
                    continue
                skill_md_candidates.append(skill_md)
    except OSError:
        return []
    for skill_md in sorted(skill_md_candidates):
        meta = parse_frontmatter(skill_md)
        slug = skill_md.parent.name
        records.append(
            {
                "id": slug,
                "name": meta["name"] or slug,
                "category": warehouse_name,
                "risk": "unknown",
                "description": meta["description"],
                "tags": [warehouse_name],
                "path": f"skills/{slug}",
            }
        )
    return records


def _load_local_warehouse_paths() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for cfg_path in LOCAL_CONFIG_PATHS:
        data = _load_jsonc(cfg_path)
        raw = data.get("warehouses", []) if isinstance(data, dict) else []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.strip():
                    paths.append(pathlib.Path(entry.strip()).expanduser())
    return paths


def resolve_warehouses(cli_warehouse: str | None) -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    if cli_warehouse:
        paths.append(pathlib.Path(cli_warehouse).expanduser())
    env_val = os.environ.get("SKILL_PILOT_WAREHOUSES", "")
    if env_val:
        paths.extend(
            pathlib.Path(part.strip()).expanduser()
            for part in env_val.split(os.pathsep)
            if part.strip()
        )
    paths.extend(_load_local_warehouse_paths())
    valid_paths: list[pathlib.Path] = []
    for p in paths:
        if _is_valid_warehouse(p) and p not in valid_paths:
            valid_paths.append(p)
    for fallbacks in (DEFAULT_WAREHOUSES, ECC_WAREHOUSES):
        selected = next((path for path in fallbacks if _is_valid_warehouse(path)), None)
        if selected is not None and selected not in valid_paths:
            valid_paths.append(selected)
    return valid_paths


VI_NEGATION_RE = re.compile(
    r"\b(?:khong can|khong dung|khong su dung|khong muon|khong lam|khong phai|khong tinh|chu khong phai|tranh dung|tranh|bo qua|ngoai tru|thay vi|thay cho|dung dung|loai tru|loai bo|tru ra|khong)\b"
)
_VI_UNICODE_TRU_RE = re.compile(r"\btrừ(?:\s+ra)?\b")
_VI_PSEUDO_TRU_BEFORE_RE = re.compile(r"\b(?:phép|toán|bài\s+toán)\s*$")
_VI_PSEUDO_TRU_AFTER_RE = re.compile(r"^\s*khi\b")
EN_NEGATION_RE = re.compile(
    r"\b(?:do not use|don't use|dont use|never use|not using|do not|don't|dont|but not|without|avoid|exclude|excluding|instead of|rather than|except|not)\b"
)
_VI_NON_EXCLUSION_KHONG_BEFORE_RE = re.compile(
    r"\b(?:tai sao|lam sao|vi sao|khi nao|co the|sao|de|ma)\s*$"
)
_VI_NON_EXCLUSION_KHONG_AFTER_RE = re.compile(
    r"^\s*(?:chay duoc|duoc|bi loi|can thiet|hoat dong|chay|hieu|ro|biet)\b"
)
_EN_NON_EXCLUSION_AFTER_RE = re.compile(r"^\s*(?:know|understand|sure)\b")
_BOOL_NOT_CONTEXT_BEFORE_RE = re.compile(r"\b(?:sql|logical|boolean|bitwise|unary)\s*$")
_BOOL_NOT_CONTEXT_AFTER_RE = re.compile(
    r"^\s*(?:operators?|gates?|null|in|exists|like|between|equals?)\b"
)
GENERIC_ONLY_TOKENS = frozenset(
    {
        "audit",
        "design",
        "review",
        "check",
        "plan",
        "planning",
        "report",
        "reporting",
        "guide",
        "build",
        "schedule",
        "analysis",
        "analyze",
        "kiem",
        "tra",
        "ke",
        "hoach",
        "bao",
        "cao",
        "danh",
        "gia",
        "phan",
        "tich",
        "lam",
        "tao",
    }
)
EN_NO_RE = re.compile(r"\bno\b")
VI_CONTEXT_HINT_RE = re.compile(
    r"\b(?:lam|tao|cua|cho|phan|tich|bao|cao|tai|chinh|ngan|hang|binh|luan|khach|giao|dien|truy|van|thiet|ke|khong|dung|can|xau|dep)\b"
)
COMMAND_CANDIDATE_RE = re.compile(
    r"\b(?:uv run|python3?\s+-m\s+(?:unittest|pytest|py_compile|ruff|mypy)|pytest|ruff|mypy|npm\s+(?:run|test|install)|pnpm|yarn|bun\s+(?:run|test|install)|cargo\s+(?:test|check|build)|go\s+test|make|tox|poetry\s+run|dotnet\s+test|flutter\s+test)\b"
)
NEGATIVE_CMD_CONTEXT_RE = re.compile(
    r"(?:\b(?:never|do not|don't|dont|avoid|forbidden|prohibited|must not|not to|khong duoc|khong nen|khong|cam|dung|tranh)\s+(?:run|execute|use|chay|dung|lenh)\b|\b(?:never|do not|don't|dont|avoid|forbidden|prohibited|deprecated)\b)"
)
MUTATING_CMD_RE = re.compile(
    r"\b(?:deploy|publish|release|reset|drop|destroy|migrate|install|add|push)\b|rm\s+-rf|\bruff\s+format(?!\s+--check)\b"
)
CHECK_CMD_RE = re.compile(
    r"\b(?:test|unittest|pytest|lint|check|mypy|py_compile|vet|audit|ruff)\b"
)
BUILD_CMD_RE = re.compile(r"\b(?:build|compile|bundle|dist)\b")
SHELL_FENCE_LANGS = frozenset(
    {"", "sh", "bash", "zsh", "shell", "console", "pwsh", "powershell", "cmd", "text"}
)
STOP_WORDS = frozenset(
    {
        "make",
        "create",
        "build",
        "dung",
        "help",
        "please",
        "with",
        "for",
        "the",
        "and",
        "to",
        "of",
        "is",
        "in",
        "on",
        "my",
        "me",
        "it",
        "do",
        "be",
        "as",
        "at",
        "by",
        "or",
        "an",
        "we",
        "so",
        "if",
        "up",
        "are",
        "was",
        "were",
        "been",
        "has",
        "have",
        "had",
        "can",
        "could",
        "would",
        "should",
        "will",
        "this",
        "that",
        "these",
        "those",
        "from",
        "into",
        "about",
        "your",
        "our",
        "their",
        "how",
        "what",
        "when",
        "where",
        "which",
        "use",
        "using",
        "need",
        "want",
        "just",
        "only",
        "some",
        "any",
        "all",
        "lam",
        "tao",
        "giup",
        "cho",
        "cua",
        "theo",
        "doi",
        "gon",
        "mot",
        "hay",
        "chon",
        "phu",
        "hop",
        "nhat",
        "toi",
        "muon",
        "va",
        "la",
        "nhung",
        "khi",
        "cung",
        "nay",
        "voi",
        "tu",
        "ve",
        "ra",
        "vao",
        "thi",
        "nhu",
        "cac",
        "trang",
        "bai",
    }
)
QUERY_ALIASES = {
    "tai chinh": "finance financial",
    "ngan hang": "banking finance",
    "bao cao": "report reporting",
    "ke toan": "accounting",
    "nghien cuu": "research",
    "lap trinh": "programming code",
    "xac thuc": "authentication auth",
    "sua loi": "debug bug fix",
    "trinh bay": "presentation slides",
    "thuyet trinh": "presentation slides",
    "bai tap": "assignment coursework",
    "don gian hoa": "simplification simplify refactor",
    "toi uu": "optimization optimize",
    "truy van": "query sql",
    "truy van cham": "slow performance",
    "chay cham": "slow performance",
    "sql cham": "slow performance",
    "postgres cham": "slow performance",
    "hieu nang cham": "slow performance",
    "giao dien": "frontend ui design",
    "web ui": "frontend ui",
    "web app": "frontend ui",
    "web design": "design frontend ui",
    "web dashboard": "frontend ui dashboard",
    "lam web": "frontend ui",
    "web dep": "design frontend ui",
    "ui dep": "design frontend ui",
    "giao dien dep": "design frontend ui",
    "dashboard dep": "design frontend ui",
    "dashboard": "frontend ui dashboard",
    "chi tieu": "finance budget spending",
    "marketing": "marketing campaign",
    "binh luan": "comments social sentiment research analysis",
    "binh luan khach hang": "comments social sentiment research analysis",
    "comment tiktok": "comments social research analysis",
    "comment facebook": "comments social research analysis",
    "comment khach hang": "comments social sentiment research analysis",
    "phan tich": "analysis analyze",
    "phan tich thi truong": "analysis research market",
    "phan tich binh luan": "analysis sentiment social research",
    "phan tich comment": "comments social sentiment research analysis",
    "auth": "authentication",
    "bug": "debug",
    "debug": "debugging error recovery",
    "failing": "debugging error recovery",
    "plan": "planning",
    "break down": "planning task breakdown",
    "spreadsheet": "excel",
    "ty gia": "fx currency exchange hedging",
    "hoi doai": "fx foreign exchange currency",
    "ky han": "forward contracts hedging",
    "phong ngua": "hedging risk",
    "dong tien": "cash flow dcf",
    "chiet khau": "discounted dcf valuation",
    "tiep can": "accessibility wcag aria",
    "ban phim": "keyboard focus aria",
}


def _strip_accents_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return normalized.encode("ascii", "ignore").decode()


def tokenize(text: str) -> list[str]:
    norm = _strip_accents_lower(text)
    norm = re.sub(r"(?<![a-z0-9])c\+\+(?![a-z0-9])", " cpp ", norm)
    norm = re.sub(r"(?<![a-z0-9])c#(?![a-z0-9])", " csharp ", norm)
    norm = re.sub(r"\b([a-z0-9]+)'([a-z]+)\b", r"\1\2", norm)
    return [t for t in re.split(r"[^a-z0-9]+", norm) if len(t) >= 2]


def _stem(tok: str) -> str:
    if len(tok) > 5 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith("ed"):
        return tok[:-2]
    if len(tok) > 4 and tok.endswith("es") and not tok.endswith(("ss", "is", "us")):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "is", "us")):
        return tok[:-1]
    return tok


def _split_query_negations(query: str) -> tuple[str, str]:
    """Split a query into positive intent text and excluded negation clauses."""
    cleaned_query = re.sub(
        r"[\u200b-\u200f\u2060\ufeff\u00ad\u034f\U000e0000-\U000e007f]",
        "",
        unicodedata.normalize("NFKC", query),
    )
    pos_parts: list[str] = []
    neg_parts: list[str] = []
    coord_re = re.compile(
        r"(?i)\b(?:nhưng\s+cần|nhung\s+can|nhưng|nhung|chỉ\s+cần|chi\s+can|but\s+only|but|instead)\b"
    )
    # Mask quoted spans so literals like 'Explain "not docker"' are not split on sentence/coord boundaries.
    quoted_spans: list[str] = []

    def _mask_quote(m: re.Match[str]) -> str:
        idx = len(quoted_spans)
        quoted_spans.append(m.group(0))
        return f" __QSPAN_{idx}__ "

    masked_query = re.sub(
        r'"[^"]*"|(?<!\w)\'[^\']*\'(?!\w)', _mask_quote, cleaned_query
    )

    def _unmask(text: str) -> str:
        return re.sub(
            r"__QSPAN_(\d+)__",
            lambda m: quoted_spans[int(m.group(1))],
            text,
        ).strip()

    clauses: list[str] = []
    for sentence in re.split(r"[.!?;,\n]+", masked_query):
        clauses.extend(coord_re.split(sentence))
    for raw_clause in clauses:
        clause = raw_clause.strip()
        if not clause:
            continue
        raw_tokens = list(re.finditer(r"\S+", clause))
        norm_words: list[str] = []
        word_to_raw_idx: list[int] = []
        for raw_idx, tok_match in enumerate(raw_tokens):
            tok_sub = re.sub(r"__QSPAN_(\d+)__", r"qspan\1", tok_match.group(0))
            for w in re.findall(r"[a-z0-9']+", _strip_accents_lower(tok_sub)):
                norm_words.append(w)
                word_to_raw_idx.append(raw_idx)
        norm_clause = " ".join(norm_words)
        matches: list[re.Match[str]] = []
        for regex in (VI_NEGATION_RE, EN_NEGATION_RE):
            for m in regex.finditer(norm_clause):
                matched = m.group(0)
                if matched == "not" and (
                    _BOOL_NOT_CONTEXT_BEFORE_RE.search(norm_clause[: m.start()])
                    or _BOOL_NOT_CONTEXT_AFTER_RE.search(norm_clause[m.end() :])
                ):
                    continue
                if matched == "khong" and (
                    _VI_NON_EXCLUSION_KHONG_BEFORE_RE.search(norm_clause[: m.start()])
                    or _VI_NON_EXCLUSION_KHONG_AFTER_RE.search(norm_clause[m.end() :])
                ):
                    continue
                if matched in ("don't", "dont", "do not", "not") and (
                    _EN_NON_EXCLUSION_AFTER_RE.search(norm_clause[m.end() :])
                ):
                    continue
                matches.append(m)
                break
        if (
            re.search(r"\bno\b", norm_clause)
            and not re.search(r"\bnó\b", clause.lower())
            and not VI_CONTEXT_HINT_RE.search(norm_clause)
        ):
            m_no = EN_NO_RE.search(norm_clause)
            if m_no is not None:
                matches.append(m_no)
        clause_lower = clause.lower()
        for m_tru_u in _VI_UNICODE_TRU_RE.finditer(clause_lower):
            if _VI_PSEUDO_TRU_BEFORE_RE.search(
                clause_lower[: m_tru_u.start()]
            ) or _VI_PSEUDO_TRU_AFTER_RE.search(clause_lower[m_tru_u.end() :]):
                continue
            m_tru_n = re.search(r"\btru(?:\s+ra)?\b", norm_clause)
            if m_tru_n is not None:
                matches.append(m_tru_n)
                break
        if not matches:
            pos_parts.append(_unmask(clause))
            continue
        first = min(matches, key=lambda m: m.start())
        prefix_word_idx = len(norm_clause[: first.start()].split())
        if prefix_word_idx > 0 and prefix_word_idx < len(word_to_raw_idx):
            raw_cut = raw_tokens[word_to_raw_idx[prefix_word_idx]].start()
            pos_prefix_raw = _unmask(clause[:raw_cut])
            if pos_prefix_raw:
                pos_parts.append(pos_prefix_raw)
        neg_suffix = norm_clause[first.end() :].strip()
        if neg_suffix:
            neg_parts.append(neg_suffix)
    return " ".join(p for p in pos_parts if p), " ".join(neg_parts)


def _query_term_groups(query: str) -> tuple[list[str], list[str]]:
    """Return deduplicated direct query tokens and separate alias-expanded tokens."""
    tokens = tokenize(query)
    normalized = " ".join(tokens)
    direct = list(dict.fromkeys(tok for tok in tokens if tok not in STOP_WORDS))
    direct_set = set(direct)
    aliases_extra: list[str] = []
    if re.search(r"\bchậm\b", unicodedata.normalize("NFC", query.lower())):
        aliases_extra.extend(["slow", "performance"])
    for phrase, terms in QUERY_ALIASES.items():
        if f" {phrase} " in f" {normalized} ":
            aliases_extra.extend(terms.split())
    filtered_aliases = list(
        dict.fromkeys(tok for tok in aliases_extra if tok not in direct_set)
    )
    return direct, filtered_aliases


def query_terms(query: str) -> list[str]:
    """Expand common English and Vietnamese task terms without external services."""
    direct, alias_extra = _query_term_groups(query)
    return list(dict.fromkeys([*direct, *alias_extra]))


def score_record(
    query: str,
    q_tokens: list[str],
    name: str,
    category: str,
    tags: list[str],
    desc: str,
    excluded_tokens: set[str] | None = None,
    alias_tokens: list[str] | None = None,
) -> float:
    q_lower = query.lower().strip()
    name_l = name.lower()
    cat_l = category.lower()
    tags_l = " ".join(str(t).lower() for t in tags)
    desc_l = desc.lower()

    name_tokens = set(tokenize(name_l))
    cat_tokens = set(tokenize(cat_l))
    tag_tokens = set(tokenize(tags_l))
    desc_tokens = set(tokenize(desc_l))

    name_stems = {_stem(t) for t in name_tokens}
    cat_stems = {_stem(t) for t in cat_tokens}
    tag_stems = {_stem(t) for t in tag_tokens}
    desc_stems = {_stem(t) for t in desc_tokens}

    direct_list = list(q_tokens)
    q_fold = _strip_accents_lower(q_lower)
    if (
        any(
            phrase in q_fold
            for phrase in (
                "chay cham",
                "truy van cham",
                "sql cham",
                "postgres cham",
                "hieu nang cham",
            )
        )
        and "cham" in direct_list
        and name_l.startswith("cham-")
    ):
        direct_list = [tok for tok in direct_list if tok != "cham"]
    alias_list = (
        [t for t in alias_tokens if t not in set(direct_list)] if alias_tokens else []
    )
    all_q_set = set(direct_list) | set(alias_list)

    if excluded_tokens:
        if excluded_tokens & name_tokens:
            return 0.0
        if (excluded_tokens & (tag_tokens | desc_tokens)) and not (
            all_q_set & name_tokens
        ):
            return 0.0

    if "d3" in all_q_set and "d3" not in name_tokens | tag_tokens | desc_tokens:
        return 0.0

    score = 0.0
    if len(q_lower) >= 2:
        boundary_re = re.compile(rf"(?<![a-z0-9]){re.escape(q_lower)}(?![a-z0-9])")
        if q_lower == name_l:
            score += 25.0
        elif boundary_re.search(name_l):
            score += 12.0
        if boundary_re.search(desc_l):
            score += 6.0

    matched_direct = 0
    matched_any = 0
    for tok, weight, is_direct in [
        *((t, 1.0, True) for t in direct_list),
        *((t, 0.75, False) for t in alias_list),
    ]:
        st = _stem(tok)
        hit = False
        if tok in name_tokens:
            score += 6.0 * weight
            hit = True
        elif st in name_stems:
            score += 4.5 * weight
            hit = True
        if tok in cat_tokens:
            score += 3.5 * weight
            hit = True
        elif st in cat_stems:
            score += 2.5 * weight
            hit = True
        if tok in tag_tokens:
            score += 4.0 * weight
            hit = True
        elif st in tag_stems:
            score += 3.0 * weight
            hit = True
        if tok in desc_tokens:
            score += 2.0 * weight
            hit = True
        elif st in desc_stems:
            score += 1.2 * weight
            hit = True
        if hit:
            matched_any += 1
            if is_direct:
                matched_direct += 1

    if not matched_any and score == 0.0:
        return 0.0

    if direct_list:
        coverage = min(1.0, matched_direct / len(direct_list))
        score *= 0.5 + coverage

    has_primary_hit = bool(all_q_set & (name_tokens | tag_tokens))
    if len(direct_list) >= 3 and not has_primary_hit and score < 2.5:
        return 0.0
    if len(direct_list) >= 3:
        all_doc_tokens = name_tokens | cat_tokens | tag_tokens | desc_tokens
        all_doc_stems = name_stems | cat_stems | tag_stems | desc_stems
        matched_terms = [
            tok
            for tok in [*direct_list, *alias_list]
            if tok in all_doc_tokens or _stem(tok) in all_doc_stems
        ]
        if matched_terms and all(tok in GENERIC_ONLY_TOKENS for tok in matched_terms):
            return 0.0
    return round(score, 2)


def cmd_inventory(args: argparse.Namespace) -> int:
    skills = collect_active_skills(args.workspace, args.harness)
    config_warning = _LAST_CONFIG_WARNING
    active = [s for s in skills if not s["shadowed"]]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for s in active:
        by_source.setdefault(s["source"], []).append(s)

    if args.format == "summary":
        if config_warning:
            print(
                f"Warning: config:unparsed ({_sanitize_compact(config_warning, 100)})"
            )
        print(
            f"Active skills: {len(active)} (total discovered including shadowed: {len(skills)})"
        )
        for src, items in by_source.items():
            names = ", ".join(_sanitize_compact(item["name"], 60) for item in items)
            print(f"- {_sanitize_compact(src, 60)} ({len(items)}): {names}")
        return 0

    payload: dict[str, Any] = {
        "total_active": len(active),
        "by_source_counts": {k: len(v) for k, v in by_source.items()},
        "skills": active,
    }
    if config_warning:
        payload["config_warning"] = config_warning
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _discover_rule_files(
    root: pathlib.Path, targets: list[str]
) -> tuple[list[pathlib.Path], bool]:
    """Collect root, target-ancestor, and bounded nested instruction/rule files."""
    found: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    truncated = False
    rule_names = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

    def add_rule(candidate: pathlib.Path) -> None:
        nonlocal truncated
        if (
            candidate.is_file()
            and not _is_link_or_reparse(candidate)
            and candidate not in seen
        ):
            if len(found) >= MAX_INTAKE_RULE_FILES:
                truncated = True
                return
            seen.add(candidate)
            found.append(candidate)

    def collect_dir_rules(folder: pathlib.Path) -> None:
        for filename in rule_names:
            add_rule(folder / filename)
        rules_subdir = folder / ".agents" / "rules"
        if rules_subdir.is_dir() and not _is_link_or_reparse(rules_subdir):
            for md in sorted(rules_subdir.glob("*.md")):
                add_rule(md)

    collect_dir_rules(root)

    for raw_target in targets:
        try:
            tgt = pathlib.Path(raw_target).expanduser()
            resolved = (tgt if tgt.is_absolute() else root / tgt).resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_relative_to(root):
            continue
        start_dir = resolved if resolved.is_dir() else resolved.parent
        rel_parts = start_dir.relative_to(root).parts
        cur = root
        for part in rel_parts:
            cur = cur / part
            if _is_link_or_reparse(cur):
                break
            collect_dir_rules(cur)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        cur_dir = pathlib.Path(dirpath)
        rel = cur_dir.relative_to(root)
        depth = 0 if cur_dir == root else len(rel.parts)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_WALK_DIRS
            and not _is_link_or_reparse(cur_dir / d)
            and depth < MAX_INTAKE_RULE_DEPTH
        )
        for filename in rule_names:
            if filename in filenames:
                add_rule(cur_dir / filename)
        rules_subdir = cur_dir / ".agents" / "rules"
        if (
            depth < MAX_INTAKE_RULE_DEPTH
            and rules_subdir.is_dir()
            and not _is_link_or_reparse(rules_subdir)
        ):
            for md in sorted(rules_subdir.glob("*.md")):
                add_rule(md)
        if truncated:
            break

    return found, truncated


def _detect_js_package_manager(root: pathlib.Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm run"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lock").is_file() or (root / "bun.lockb").is_file():
        return "bun run"
    return "npm run"


COMMAND_SAFETY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shell_chaining_or_subshell", re.compile(r"(?:&&|\|\||;|\||\$\(|`)")),
    (
        "network_download",
        re.compile(r"\b(?:curl|wget|invoke-webrequest|iwr)\b", re.IGNORECASE),
    ),
    ("privilege_escalation", re.compile(r"\b(?:sudo|runas)\b", re.IGNORECASE)),
    ("global_config_mutation", re.compile(r"(?:--global|--system)\b", re.IGNORECASE)),
    (
        "encoded_payload",
        re.compile(
            r"(?:-(?:enc|encodedcommand)\b|\bbase64\s+(?:-d|--decode)\b|\b(?:invoke-expression|iex|eval)\b)",
            re.IGNORECASE,
        ),
    ),
)


def _command_safety_flags(command: str, definition: str = "") -> list[str]:
    combined = f"{command} {definition}".strip()
    return [name for name, pattern in COMMAND_SAFETY_RULES if pattern.search(combined)]


def _classify_command(command: str, definition: str = "") -> str:
    if _command_safety_flags(command, definition):
        return "risky"
    combined = f"{command} {definition}".lower()
    if MUTATING_CMD_RE.search(combined):
        return "mutating"
    if CHECK_CMD_RE.search(combined):
        return "check"
    if BUILD_CMD_RE.search(combined):
        return "build"
    return "other"


def _extract_rule_commands(content: str, rel_rule: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    in_fence = False
    in_html_comment = False
    fence_char = ""
    fence_len = 0
    fence_shell = False
    fence_negated = False
    prev_nonempty = ""

    def record(command: str, line_no: int) -> None:
        source_loc = f"{rel_rule}:{line_no}"
        key = (command, source_loc)
        if key not in seen:
            seen.add(key)
            flags = _command_safety_flags(command)
            entry: dict[str, object] = {
                "command": command,
                "source": source_loc,
                "origin": "rule_file",
                "kind": _classify_command(command),
                "verified": False,
            }
            if flags:
                entry["safety_flags"] = flags
            found.append(entry)

    for line_no, line in enumerate(content.splitlines(), start=1):
        if not in_fence:
            if in_html_comment:
                if "-->" in line:
                    in_html_comment = False
                continue
            line_no_html = re.sub(r"<!--.*?-->", "", line)
            if "<!--" in line_no_html:
                in_html_comment = True
                line_no_html = line_no_html.split("<!--", 1)[0]
            stripped_line = line_no_html.strip()
            fence_open = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line_no_html)
            if fence_open:
                marker = fence_open.group(1)
                fence_char = marker[0]
                fence_len = len(marker)
                fence_shell = fence_open.group(2).strip().lower() in SHELL_FENCE_LANGS
                fence_negated = bool(
                    NEGATIVE_CMD_CONTEXT_RE.search(_strip_accents_lower(prev_nonempty))
                )
                in_fence = True
                continue
            for match in re.finditer(r"`([^`\r\n]+)`", line_no_html):
                command = match.group(1).strip()
                if not COMMAND_CANDIDATE_RE.search(command):
                    continue
                clause_prefix = _strip_accents_lower(
                    re.split(r"[.!?\n;]", line_no_html[: match.start()])[-1]
                )
                clause_suffix = _strip_accents_lower(
                    re.split(r"[.!?\n;]", line_no_html[match.end() :])[0]
                )
                if NEGATIVE_CMD_CONTEXT_RE.search(
                    clause_prefix
                ) or NEGATIVE_CMD_CONTEXT_RE.search(clause_suffix):
                    continue
                record(command, line_no)
            if stripped_line:
                prev_nonempty = line_no_html
            continue

        close_re = re.match(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$", line)
        if close_re:
            in_fence = False
            prev_nonempty = ""
            continue
        if fence_shell and not fence_negated:
            cmd_line = re.sub(r"^\s*(?:\$|PS\s+[^>]*>)\s+", "", line).strip()
            if (
                cmd_line
                and not cmd_line.startswith("#")
                and COMMAND_CANDIDATE_RE.search(cmd_line)
            ):
                record(cmd_line, line_no)

    return found


def cmd_intake(args: argparse.Namespace) -> int:
    """Summarize local project metadata without running project commands."""
    raw_ws = str(args.workspace or "").strip()
    if not raw_ws:
        if getattr(args, "format", "json") == "compact":
            print("Workspace path must be non-empty", file=sys.stderr)
        else:
            print(
                json.dumps(
                    _error_payload(
                        "WORKSPACE_NOT_FOUND", "Workspace path must be non-empty"
                    )
                )
            )
        return 1
    root = pathlib.Path(raw_ws).expanduser().resolve()
    if not root.is_dir():
        if getattr(args, "format", "json") == "compact":
            print(f"Workspace not found: {root}", file=sys.stderr)
        else:
            print(
                json.dumps(
                    _error_payload(
                        "WORKSPACE_NOT_FOUND", f"Workspace not found: {root}"
                    )
                )
            )
        return 1
    raw_targets = getattr(args, "target", []) or []
    rule_paths, rules_truncated = _discover_rule_files(root, raw_targets)
    resolved_targets: list[pathlib.Path] = []
    for rt in raw_targets:
        try:
            tp = pathlib.Path(rt).expanduser()
            tr = (tp if tp.is_absolute() else root / tp).resolve(strict=True)
            if tr.is_relative_to(root):
                resolved_targets.append(tr)
        except OSError:
            continue

    rules: list[str] = []
    rule_details: list[dict[str, Any]] = []
    rule_injection_warnings: list[dict[str, Any]] = []
    candidates: list[dict[str, str]] = []
    seen_candidates: set[tuple[str, str]] = set()
    for path in rule_paths:
        rules.append(str(path))
        rel_rule = str(path.relative_to(root)).replace("\\", "/")
        anchor = (
            path.parent.parent.parent
            if path.parent.name == "rules" and path.parent.parent.name == ".agents"
            else path.parent
        )
        applicable = (not resolved_targets) or any(
            t.is_relative_to(anchor) for t in resolved_targets
        )
        scope = (
            "workspace_root"
            if anchor == root
            else ("target_ancestor" if applicable else "other_subproject")
        )
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
                content = fh.read(MAX_RULE_FILE_BYTES)
        except OSError:
            content = ""
        rule_signals = _detect_prompt_injection_signals(content) if content else []
        detail_entry: dict[str, Any] = {
            "path": str(path),
            "relative_path": rel_rule,
            "scope": scope,
            "applicable_to_target": applicable,
        }
        if rule_signals:
            detail_entry["prompt_injection_signals"] = rule_signals
            rule_injection_warnings.append({"file": rel_rule, "signals": rule_signals})
        rule_details.append(detail_entry)
        if not content:
            continue
        for cand in _extract_rule_commands(content, rel_rule):
            key = (cand["command"], cand["source"])
            if key not in seen_candidates:
                seen_candidates.add(key)
                candidates.append(cand)

    stack: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and not _is_link_or_reparse(pyproject):
        try:
            if pyproject.stat().st_size <= MAX_RULE_FILE_BYTES:
                project = tomllib.loads(pyproject.read_text(encoding="utf-8-sig")).get(
                    "project", {}
                )
                if isinstance(project, dict):
                    stack.append(
                        f"Python {project.get('requires-python', 'version unspecified')} ({pyproject})"
                    )
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            stack.append(f"Cannot parse {pyproject}: {exc}")
    package = root / "package.json"
    if package.is_file() and not _is_link_or_reparse(package):
        try:
            if package.stat().st_size <= MAX_RULE_FILE_BYTES:
                data = json.loads(package.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    stack.append(f"Node package: {package}")
                    scripts = data.get("scripts", {})
                    pm_prefix = _detect_js_package_manager(root)
                    if isinstance(scripts, dict):
                        for name, body in scripts.items():
                            command = f"{pm_prefix} {name}"
                            source_loc = f"package.json:scripts.{name}"
                            key = (command, source_loc)
                            if key not in seen_candidates:
                                seen_candidates.add(key)
                                flags = _command_safety_flags(command, str(body))
                                entry: dict[str, object] = {
                                    "command": command,
                                    "source": source_loc,
                                    "origin": "package_json",
                                    "kind": _classify_command(command, str(body)),
                                    "definition": str(body)[:80],
                                    "verified": False,
                                }
                                if flags:
                                    entry["safety_flags"] = flags
                                candidates.append(entry)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            stack.append(f"Cannot parse {package}: {exc}")

    result = {
        "workspace": str(root),
        "rules": rules,
        "rule_details": rule_details,
        "rules_truncated": rules_truncated,
        "prompt_injection_signals": rule_injection_warnings,
        "stack": stack,
        "command_candidates": candidates,
    }
    if args.format == "compact":
        print(f"Workspace: {_sanitize_compact(root, 160)}")
        for path_str in rules[:10]:
            print(f"Rule file (read before acting): {_sanitize_compact(path_str, 160)}")
        if rules_truncated or len(rules) > 10:
            print("Additional rule files omitted (limit reached)")
        for item in stack[:3]:
            print(f"Stack: {_sanitize_compact(item, 160)}")
        for warn in rule_injection_warnings[:5]:
            sigs = ", ".join(warn["signals"])
            print(
                f"Warning (prompt injection signal in {_sanitize_compact(warn['file'], 80)}): {sigs}"
            )
        for cand in candidates[:15]:
            cmd_safe = _sanitize_compact(cand["command"], 120)
            src_safe = _sanitize_compact(cand["source"], 80)
            kind = _sanitize_compact(cand.get("kind", "other"), 20)
            print(f"Command candidate (unverified, {kind}): {cmd_safe} [{src_safe}]")
        if len(candidates) > 15:
            print(f"Additional command candidates omitted: {len(candidates) - 15}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    pos_query, neg_query = _split_query_negations(query)
    if neg_query and not pos_query.strip():
        if args.format == "compact":
            print(
                "No positive search intent; specify desired capabilities alongside exclusions."
            )
        else:
            print(
                json.dumps(
                    _error_payload(
                        "INVALID_QUERY",
                        "No positive search intent after excluding negated terms",
                    )
                )
            )
        return 1
    score_query = pos_query if neg_query else (pos_query or query)
    direct_tokens, alias_tokens = _query_term_groups(score_query)
    all_pos = set(direct_tokens) | set(alias_tokens)
    neg_tokens = set(query_terms(neg_query)) if neg_query else set()
    if neg_tokens and not [t for t in direct_tokens if t not in neg_tokens]:
        direct_tokens = []
        alias_tokens = []
        excluded_tokens = neg_tokens
    else:
        excluded_tokens = neg_tokens - all_pos
    if not direct_tokens and not alias_tokens:
        msg = (
            "No positive search intent after excluding negated terms"
            if neg_query
            else "No searchable keywords in query"
        )
        if args.format == "compact":
            print(msg)
        else:
            print(json.dumps(_error_payload("INVALID_QUERY", msg)))
        return 1

    tier1_hits: list[dict[str, Any]] = []
    inactive_hits: list[dict[str, Any]] = []
    config_warning: str | None = None
    if args.include_active:
        for s in collect_active_skills(args.workspace, args.harness):
            if s["shadowed"] or s["name"] == "skill-pilot":
                continue
            raw_sc = score_record(
                score_query,
                direct_tokens,
                s["name"],
                "",
                [],
                s["description"],
                excluded_tokens=excluded_tokens,
                alias_tokens=alias_tokens,
            )
            if raw_sc >= MIN_SEARCH_RAW_SCORE:
                score = round(max(0.01, raw_sc + TIER_BONUS["active"]), 2)
                entry = {**s, "score": score}
                if getattr(args, "explain", False):
                    entry["score_breakdown"] = {
                        "raw_score": round(raw_sc, 2),
                        "tier_bonus": TIER_BONUS["active"],
                        "direct_tokens": direct_tokens,
                        "alias_tokens": alias_tokens,
                    }
                tier1_hits.append(entry)
        config_warning = _LAST_CONFIG_WARNING
        tier1_hits.sort(key=lambda x: x["score"], reverse=True)
    if args.harness in ("auto", "codex", "all"):
        for skill in collect_codex_skills(include_inactive=True):
            if not skill["inactive"]:
                continue
            raw_sc = score_record(
                score_query,
                direct_tokens,
                skill["name"],
                "",
                [],
                skill["description"],
                excluded_tokens=excluded_tokens,
                alias_tokens=alias_tokens,
            )
            if raw_sc >= MIN_SEARCH_RAW_SCORE:
                score = round(max(0.01, raw_sc + TIER_BONUS["inactive"]), 2)
                entry = {**skill, "score": score}
                if getattr(args, "explain", False):
                    entry["score_breakdown"] = {
                        "raw_score": round(raw_sc, 2),
                        "tier_bonus": TIER_BONUS["inactive"],
                        "direct_tokens": direct_tokens,
                        "alias_tokens": alias_tokens,
                    }
                inactive_hits.append(entry)
        inactive_hits.sort(key=lambda item: item["score"], reverse=True)

    tier2_hits: list[dict[str, Any]] = []
    warehouses = resolve_warehouses(args.warehouse)
    for wh in warehouses:
        records = _load_warehouse_records(wh)
        for rec in records:
            risk = str(rec.get("risk") or "unknown").strip().lower()
            if risk == "offensive" and not args.allow_risky:
                continue
            tags = rec.get("tags")
            rec_name = str(rec.get("name") or rec.get("id") or "").strip()
            raw_sc = score_record(
                score_query,
                direct_tokens,
                rec_name,
                str(rec.get("category") or ""),
                tags if isinstance(tags, list) else [],
                str(rec.get("description") or ""),
                excluded_tokens=excluded_tokens,
                alias_tokens=alias_tokens,
            )
            if raw_sc < MIN_SEARCH_RAW_SCORE:
                continue
            penalty = 0.9 if risk == "critical" else (0.95 if risk == "high" else 1.0)
            score = round(max(0.01, raw_sc * penalty + TIER_BONUS["warehouse"]), 2)
            rel_path = str(rec.get("path") or "")
            skill_dir = _validate_relative_skill_path(wh, rel_path)
            if skill_dir is None:
                continue
            skill_md = skill_dir / "SKILL.md"
            entry = {
                "id": rec.get("id"),
                "name": rec_name,
                "category": rec.get("category"),
                "risk": risk,
                "description": str(rec.get("description") or ""),
                "tags": rec.get("tags", []),
                "warehouse": str(wh),
                "skill_md_path": str(skill_md),
                "exists": True,
                "score": score,
            }
            if getattr(args, "explain", False):
                entry["score_breakdown"] = {
                    "raw_score": round(raw_sc, 2),
                    "risk_penalty": penalty,
                    "tier_bonus": TIER_BONUS["warehouse"],
                    "direct_tokens": direct_tokens,
                    "alias_tokens": alias_tokens,
                }
            tier2_hits.append(entry)
    tier2_hits.sort(key=lambda x: x["score"], reverse=True)

    by_identity: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    seen_skill_paths: set[str] = set()
    digest_cache: dict[str, str | None] = {}
    kept_entries: list[tuple[str, dict[str, Any]]] = []
    for label, matches in (
        ("active", tier1_hits),
        ("warehouse", tier2_hits),
        ("inactive", inactive_hits),
    ):
        for item in matches:
            resolved = _safe_resolved_str(str(item.get("skill_md_path") or ""))
            if resolved and resolved in seen_skill_paths:
                continue
            raw_name = str(item.get("name") or item.get("id") or "")
            identity = re.sub(r"\s+", " ", raw_name.strip().lower())
            if not identity:
                continue
            existing_group = by_identity.get(identity, [])
            if any(
                _same_skill_identity(prev_item, item) for _, prev_item in existing_group
            ):
                continue
            if resolved:
                seen_skill_paths.add(resolved)
            cur_source = str(item.get("source") or item.get("warehouse") or "")
            collapse_target: dict[str, Any] | None = None
            active_content_peers: list[dict[str, Any]] = []
            for prev_label, prev_item in existing_group:
                if not _same_skill_content(prev_item, item, digest_cache):
                    continue
                if prev_label == "active" and label == "active":
                    active_content_peers.append(prev_item)
                else:
                    collapse_target = prev_item
                    break
            if collapse_target is not None:
                collapse_target["duplicate_candidate"] = True
                collapse_target.setdefault("duplicate_candidates", []).append(
                    {
                        "tier": label,
                        "source": cur_source,
                        "skill_md_path": str(item.get("skill_md_path") or ""),
                    }
                )
                continue
            item_copy = dict(item)
            if active_content_peers:
                for prev_item in active_content_peers:
                    prev_item["duplicate_candidate"] = True
                    prev_item["name_collision"] = True
                item_copy["duplicate_candidate"] = True
                item_copy["name_collision"] = True
            elif existing_group:
                for _, prev_item in existing_group:
                    prev_item["name_collision"] = True
                item_copy["name_collision"] = True
            pair = (label, item_copy)
            existing_group.append(pair)
            by_identity[identity] = existing_group
            kept_entries.append(pair)

    tier1_hits = sorted(
        (item for label, item in kept_entries if label == "active"),
        key=lambda x: (-x["score"], str(x.get("name") or "")),
    )
    tier2_hits = sorted(
        (item for label, item in kept_entries if label == "warehouse"),
        key=lambda x: (-x["score"], str(x.get("name") or "")),
    )
    inactive_hits = sorted(
        (item for label, item in kept_entries if label == "inactive"),
        key=lambda x: (-x["score"], str(x.get("name") or "")),
    )
    ranked = sorted(
        kept_entries,
        key=lambda pair: (
            -pair[1]["score"],
            TIER_RANK[pair[0]],
            str(pair[1].get("name") or ""),
        ),
    )
    if ranked:
        min_keep = ranked[0][1]["score"] * SEARCH_RATIO_CUTOFF
        ranked = [pair for pair in ranked if pair[1]["score"] >= min_keep]

    # Do not echo recognizable instruction-override payloads from untrusted
    # warehouse indexes directly into the agent's search result context.
    for _label, item in kept_entries:
        signals = _detect_prompt_injection_signals(str(item.get("description") or ""))
        if signals:
            item["description"] = "[untrusted description withheld]"
            item["prompt_injection_signals"] = signals

    output: dict[str, Any] = {
        "query": query,
        "ranking_policy": "relevance_with_bounded_tier_bonus",
        "warehouses_scanned": [str(w) for w in warehouses],
        "ranked_matches": [
            {**item, "tier_label": label} for label, item in ranked[: args.limit]
        ],
        "tier1_active_matches": tier1_hits[: args.limit],
        "inactive_codex_skill_matches": inactive_hits[: args.limit],
        "tier2_warehouse_matches": tier2_hits[: args.limit],
    }
    if config_warning:
        output["config_warning"] = config_warning
    if args.format == "compact":
        print(f"Query: {_sanitize_compact(query, 160)}")
        wh_text = ", ".join(_sanitize_compact(w, 80) for w in warehouses) or "none"
        print(f"Warehouses: {wh_text}")
        if config_warning:
            print(
                f"Warning: config:unparsed ({_sanitize_compact(config_warning, 100)})"
            )
        for label, item in ranked[: args.limit]:
            name_safe = _sanitize_compact(item.get("name") or "", 64)
            path_safe = _sanitize_compact(item.get("skill_md_path") or "", 140)
            risk_part = (
                f" | risk:{_sanitize_compact(item['risk'], 24)}"
                if label == "warehouse"
                else ""
            )
            collision_part = ""
            if item.get("name_collision"):
                origin = (
                    item.get("source")
                    or pathlib.Path(str(item.get("warehouse") or "")).name
                )
                collision_part = f" | collision:{_sanitize_compact(origin, 48)}"
            desc_safe = _sanitize_compact(item.get("description") or "", 72)
            desc_part = f" | {desc_safe}" if desc_safe else ""
            print(
                f"{label} | {name_safe} | {item['score']}{risk_part}{collision_part} | {path_safe}{desc_part}"
            )
        if not ranked:
            print("No matches; try domain-specific synonyms.")
        return 0
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def _resolve_target_skill_dir(
    target: str, warehouse: str | None
) -> pathlib.Path | None:
    candidate = pathlib.Path(target).expanduser()
    if candidate.is_file() and candidate.name.upper() == "SKILL.MD":
        if _is_link_or_reparse(candidate) or _is_link_or_reparse(candidate.parent):
            return None
        return candidate.parent
    if candidate.is_dir() and (candidate / "SKILL.md").is_file():
        if _is_link_or_reparse(candidate) or _is_link_or_reparse(
            candidate / "SKILL.md"
        ):
            return None
        return candidate

    for s in collect_active_skills(harness="all"):
        if s["name"] == target:
            return pathlib.Path(s["skill_md_path"]).parent

    for skill in collect_codex_skills(include_inactive=True):
        if skill["name"] == target:
            return pathlib.Path(skill["skill_md_path"]).parent

    for wh in resolve_warehouses(warehouse):
        records = _load_warehouse_records(wh)
        for rec in records:
            if rec.get("id") == target or rec.get("name") == target:
                sdir = _validate_relative_skill_path(wh, str(rec.get("path") or ""))
                if sdir is not None:
                    return sdir
    return None


_INERT_SCRIPT_DIR_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
    }
)


def _is_script_or_executable_meta(
    file_name: str, rel: str, st_mode: int | None = None
) -> bool:
    lower_name = file_name.lower()
    suffix = pathlib.PurePosixPath(file_name).suffix.lower()
    rel_lower = rel.lower()
    in_scripts_dir = rel_lower.startswith("scripts/") or "/scripts/" in rel_lower
    if (
        suffix in SCRIPT_EXTENSIONS
        or (in_scripts_dir and suffix not in _INERT_SCRIPT_DIR_EXTENSIONS)
        or lower_name in {"makefile", "dockerfile"}
    ):
        return True
    return os.name != "nt" and st_mode is not None and bool(st_mode & 0o111)


def _is_script_or_executable(
    path: pathlib.Path, rel: str, st: os.stat_result | None = None
) -> bool:
    if st is None:
        try:
            st = os.lstat(path)
        except OSError:
            return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if _is_script_or_executable_meta(path.name, rel, st.st_mode):
        return True
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError:
        return False
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return False
        header = os.read(fd, 16)
        if header.lstrip(b"\xef\xbb\xbf").startswith(b"#!"):
            return True
        return header.startswith(_BINARY_MAGIC_PREFIXES)
    except OSError:
        return False
    finally:
        os.close(fd)


def _scan_skill_dir_metadata(
    sdir: pathlib.Path, *, include_hidden_dirs: bool = False
) -> dict[str, Any]:
    files: list[str] = []
    scripts: list[str] = []
    symlinks_detected: list[str] = []
    special_files_detected: list[str] = []
    truncated = False
    entries_seen = 0
    skip_dirs = frozenset() if include_hidden_dirs else SKIP_WALK_DIRS
    stack: list[tuple[pathlib.Path, int]] = [(sdir, 0)]
    while stack:
        cur_dir, depth = stack.pop()
        remaining = MAX_SKILL_ENTRIES - entries_seen
        try:
            entries, overflow = _bounded_scandir(
                cur_dir, remaining, skip_dir_names=skip_dirs
            )
        except OSError:
            rel_cur = (
                "."
                if cur_dir == sdir
                else str(cur_dir.relative_to(sdir)).replace("\\", "/")
            )
            special_files_detected.append(rel_cur)
            truncated = True
            break
        if overflow:
            truncated = True
            break
        child_dirs: list[tuple[pathlib.Path, int]] = []
        for entry in entries:
            entries_seen += 1
            if entries_seen > MAX_SKILL_ENTRIES:
                truncated = True
                break
            entry_path = pathlib.Path(entry.path)
            rel_item = str(entry_path.relative_to(sdir)).replace("\\", "/")
            if _is_link_or_reparse(entry_path):
                symlinks_detected.append(rel_item)
                continue
            try:
                st = os.lstat(entry_path)
            except OSError:
                special_files_detected.append(rel_item)
                continue
            if stat.S_ISDIR(st.st_mode):
                if depth < MAX_INSPECT_DEPTH:
                    child_dirs.append((entry_path, depth + 1))
                else:
                    truncated = True
                continue
            if not stat.S_ISREG(st.st_mode):
                special_files_detected.append(rel_item)
                continue
            files.append(rel_item)
            if _is_script_or_executable(entry_path, rel_item, st):
                scripts.append(rel_item)
        if truncated:
            break
        stack.extend(reversed(child_dirs))
    return {
        "files": files,
        "scripts": scripts,
        "symlinks_detected": symlinks_detected,
        "special_files_detected": special_files_detected,
        "truncated": truncated,
    }


def _error_payload(error_code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build a backward-compatible JSON error payload with a machine-readable error_code."""
    payload: dict[str, Any] = {"error_code": error_code, "error": message}
    payload.update(extra)
    return payload


def cmd_inspect(args: argparse.Namespace) -> int:
    sdir = _resolve_target_skill_dir(args.target, args.warehouse)
    if sdir is None:
        print(
            json.dumps(
                _error_payload("SKILL_NOT_FOUND", f"Skill not found: {args.target}")
            )
        )
        return 1

    skill_md = sdir / "SKILL.md"
    if _is_link_or_reparse(sdir) or _is_link_or_reparse(skill_md):
        print(
            json.dumps(
                _error_payload(
                    "SYMLINK_DETECTED", f"Refusing symlinked skill path: {sdir}"
                )
            )
        )
        return 1

    meta = parse_frontmatter(skill_md)
    with skill_md.open("r", encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read(MAX_SKILL_FILE_BYTES)
    lines = text.splitlines()

    scan = _scan_skill_dir_metadata(sdir)
    files = scan["files"]
    scripts = scan["scripts"]
    symlinks_detected = scan["symlinks_detected"]
    special_files_detected = scan["special_files_detected"]
    truncated = scan["truncated"]

    headings = [ln for ln in lines if ln.startswith("#")]
    injection_signals = _detect_prompt_injection_signals(text)
    reason_codes: list[str] = []
    if symlinks_detected or special_files_detected or truncated:
        reason_codes.append("blocked-links-or-special")
    if scripts:
        reason_codes.append("scripts-unreviewed")
    if injection_signals:
        reason_codes.append("injection-signals-detected")
    if not reason_codes:
        reason_codes.append("statically-inspected")
    evidence_state = reason_codes[0]
    trust_assessment = {
        "evidence_state": evidence_state,
        "reason_codes": reason_codes,
        "scripts_reviewed": False,
        "prompt_injection_signals": injection_signals,
    }
    if args.format == "compact":
        print(
            f"{_sanitize_compact(meta['name'], 64)} | {_sanitize_compact(skill_md, 140)}"
        )
        print(f"Description: {_sanitize_compact(meta['description'], 160)}")
        print(f"Trust: {', '.join(reason_codes)}")
        script_list = ", ".join(_sanitize_compact(s, 60) for s in scripts) or "none"
        print(f"Scripts (unreviewed metadata only): {script_list}")
        if injection_signals:
            print(f"Warning: prompt injection signals: {', '.join(injection_signals)}")
        if symlinks_detected:
            link_list = ", ".join(_sanitize_compact(s, 60) for s in symlinks_detected)
            print(f"Warning: symlinks/junctions detected: {link_list}")
        if special_files_detected:
            spec_list = ", ".join(
                _sanitize_compact(s, 60) for s in special_files_detected
            )
            print(f"Warning: special files detected: {spec_list}")
        if truncated:
            print("Warning: file scan truncated at safety budget limits")
        return 0
    payload = {
        "name": meta["name"],
        "description": meta["description"],
        "skill_dir": str(sdir),
        "skill_md_path": str(skill_md),
        "line_count": len(lines),
        "headings": headings[:30],
        "files": files[:50],
        "executable_or_script_files": scripts,
        "scripts_reviewed": False,
        "symlinks_detected": symlinks_detected,
        "special_files_detected": special_files_detected,
        "truncated": truncated,
        "trust_assessment": trust_assessment,
        "preview_lines": "\n".join(lines[: args.preview_lines]),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _detect_prompt_injection_signals(text: str) -> list[str]:
    """Detect common instruction-override and Trojan Source patterns inside skill markdown."""
    patterns = (
        (
            r"ignore\s+(?:all\s+)?previous\s+instructions",
            "ignore_previous_instructions",
        ),
        (r"override\s+system\s+prompt", "override_system_prompt"),
        (r"disregard\s+(?:all\s+)?safety", "disregard_safety"),
        (r"(?:curl|wget)\s+[^|\n]+\|\s*(?:sh|bash)", "piped_shell_download"),
        (r"powershell\s+[^\n]*-enc(?:odedcommand)?\b", "encoded_powershell"),
        (r"<\s*/?\s*system\s*>", "fake_system_tag"),
        (r"[\u202a-\u202e\u2066-\u2069]", "unicode_bidi_override"),
    )
    found: list[str] = []
    normalized = re.sub(
        r"[\u200b-\u200f\u2060\ufeff\u00ad\u034f\U000e0000-\U000e007f]",
        "",
        unicodedata.normalize("NFKC", text),
    ).lower()
    raw_lower = text.lower()
    for pat, label in patterns:
        target = raw_lower if label == "unicode_bidi_override" else normalized
        if re.search(pat, target):
            found.append(label)
    return found


LOCK_STALE_SECONDS = 300
LOCK_MALFORMED_GRACE_SECONDS = 5.0


class _LockError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _is_pid_alive(pid: Any) -> bool | None:
    """Return True if pid is a live local process, False if dead, None if indeterminate."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if pid == os.getpid():
        return True
    if os.name == "nt":
        if pid > 0xFFFFFFFF:
            return None
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited = 0x1000
            handle = kernel32.OpenProcess(process_query_limited, False, int(pid))
            if not handle:
                err = ctypes.get_last_error()
                if err == 5:  # ERROR_ACCESS_DENIED -> process exists
                    return True
                if err == 87:  # ERROR_INVALID_PARAMETER -> no such PID
                    return False
                return None
            try:
                exit_code = ctypes.c_uint32(0)
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == 259  # STILL_ACTIVE
                return None
            finally:
                kernel32.CloseHandle(handle)
        except OSError:
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


def _read_lock_metadata(lock_path: pathlib.Path) -> dict[str, Any]:
    """Read bounded advisory lock metadata without following symlinks."""
    if _is_link_or_reparse(lock_path):
        return {"symlink": True, "malformed": True}
    try:
        st = os.lstat(lock_path)
    except OSError:
        return {"age_seconds": 0.0, "malformed": True, "symlink": False}
    age = max(0.0, time.time() - st.st_mtime)
    base_meta: dict[str, Any] = {
        "age_seconds": round(age, 1),
        "symlink": False,
        "dev": st.st_dev,
        "ino": st.st_ino,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }
    try:
        open_flags = (
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        fd = os.open(lock_path, open_flags)
        try:
            fst = os.fstat(fd)
            if not stat.S_ISREG(fst.st_mode) or (fst.st_dev, fst.st_ino) != (
                st.st_dev,
                st.st_ino,
            ):
                return {**base_meta, "malformed": True}
            raw_bytes = os.read(fd, 4096)
        finally:
            os.close(fd)
        raw = raw_bytes.decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            pid_val = parsed.get("pid")
            tok_val = parsed.get("token")
            valid_schema = (
                isinstance(pid_val, int)
                and not isinstance(pid_val, bool)
                and pid_val > 0
                and isinstance(tok_val, str)
                and bool(tok_val)
            )
            return {
                **base_meta,
                "pid": pid_val if valid_schema else None,
                "token": tok_val if valid_schema else None,
                "created_at": parsed.get("created_at"),
                "malformed": not valid_schema,
            }
    except (OSError, json.JSONDecodeError, ValueError):
        return {**base_meta, "malformed": True}
    return {**base_meta, "malformed": True}


def _acquire_dest_lock(
    dest_root: pathlib.Path,
    dest_name: str,
    *,
    break_stale: bool = False,
    stale_seconds: int = LOCK_STALE_SECONDS,
) -> tuple[pathlib.Path, str]:
    """Acquire an exclusive advisory lockfile with owner token; never auto-reclaim without break_stale."""
    lock_path = dest_root / f".skill-pilot-{dest_name}.lock"
    token = uuid.uuid4().hex
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    for attempt in range(2):
        try:
            fd = os.open(lock_path, flags, 0o600)
            break
        except FileExistsError as exc:
            meta = _read_lock_metadata(lock_path)
            if meta.get("symlink"):
                raise _LockError(
                    "LOCK_SYMLINK",
                    f"Refusing symlinked destination lockfile: {lock_path}",
                ) from exc
            age = float(meta.get("age_seconds") or 0.0)
            pid = meta.get("pid")
            pid_alive = _is_pid_alive(pid)
            is_brand_new_empty = meta.get("size", 0) == 0 and age < 2.0
            is_reclaimable = not is_brand_new_empty and (
                age > stale_seconds
                or (meta.get("malformed") and age >= LOCK_MALFORMED_GRACE_SECONDS)
            )
            if attempt == 0 and break_stale and is_reclaimable:
                if pid_alive is True:
                    raise _LockError(
                        "LOCK_OWNER_ALIVE",
                        f"Refusing --break-stale-lock while owner process is still alive: {lock_path} "
                        f"(pid={pid}, age_seconds={age})",
                    ) from exc
                try:
                    if _is_link_or_reparse(lock_path):
                        raise _LockError(
                            "LOCK_SYMLINK",
                            f"Refusing symlinked destination lockfile: {lock_path}",
                        )
                    cur_st = os.lstat(lock_path)
                    if (
                        cur_st.st_dev,
                        cur_st.st_ino,
                        cur_st.st_mtime_ns,
                    ) != (meta.get("dev"), meta.get("ino"), meta.get("mtime_ns")):
                        raise _LockError(
                            "DEST_LOCKED",
                            f"Destination lockfile changed concurrently during break-stale check: {lock_path}",
                        )
                    lock_path.unlink(missing_ok=True)
                    continue
                except OSError:
                    pass
            raise _LockError(
                "DEST_LOCKED",
                f"Destination is locked by another promote operation: {lock_path} "
                f"(pid={pid}, age_seconds={age}); pass --break-stale-lock after confirming no active promote is running",
            ) from exc
    payload = json.dumps(
        {"pid": os.getpid(), "token": token, "created_at": time.time()}
    )
    try:
        os.write(fd, (payload + "\n").encode("utf-8"))
    except OSError:
        os.close(fd)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    else:
        os.close(fd)
    return lock_path, token


def _release_dest_lock(lock_path: pathlib.Path, token: str) -> None:
    """Release lock_path only if it is a regular file still owned by token."""
    if _is_link_or_reparse(lock_path) or not lock_path.is_file():
        return
    meta = _read_lock_metadata(lock_path)
    if meta.get("token") == token:
        for attempt in range(5):
            try:
                if _is_link_or_reparse(lock_path):
                    return
                cur_st = os.lstat(lock_path)
                if (cur_st.st_dev, cur_st.st_ino) == (
                    meta.get("dev"),
                    meta.get("ino"),
                ):
                    lock_path.unlink(missing_ok=True)
                return
            except PermissionError:
                if os.name == "nt" and attempt < 4:
                    time.sleep(0.01)
                    continue
                return
            except OSError:
                return


_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _validate_dest_name(dest_name: str) -> bool:
    if not dest_name or dest_name in (".", ".."):
        return False
    if dest_name.endswith((".", " ")):
        return False
    if "/" in dest_name or "\\" in dest_name or ":" in dest_name:
        return False
    if any(ord(ch) < 32 for ch in dest_name):
        return False
    if dest_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        return False
    return (
        pathlib.PureWindowsPath(dest_name).name == dest_name
        and pathlib.Path(dest_name).name == dest_name
    )


def cmd_promote(args: argparse.Namespace) -> int:
    if getattr(args, "force", False):
        print(
            json.dumps(
                _error_payload(
                    "DEPRECATED_FORCE_FLAG",
                    "--force is deprecated and rejected for safety; pass --overwrite to replace an existing skill and/or --allow-risky to acknowledge non-low risk",
                )
            )
        )
        return 1

    warehouses = resolve_warehouses(args.warehouse)
    matched_rec: dict[str, Any] | None = None
    matched_wh: pathlib.Path | None = None
    for wh in warehouses:
        records = _load_warehouse_records(wh)
        for rec in records:
            if rec.get("id") == args.skill_id or rec.get("name") == args.skill_id:
                matched_rec = rec
                matched_wh = wh
                break
        if matched_rec:
            break

    if matched_rec is None or matched_wh is None:
        print(
            json.dumps(
                _error_payload(
                    "SKILL_NOT_FOUND",
                    f"Skill '{args.skill_id}' not found in local warehouses",
                )
            )
        )
        return 1

    risk = str(matched_rec.get("risk") or "unknown").strip().lower()
    if risk not in SAFE_PROMOTE_RISKS and not args.allow_risky:
        print(
            json.dumps(
                _error_payload(
                    "RISK_ACK_REQUIRED",
                    f"Refusing to promote skill with risk '{risk}' without --allow-risky; inspect it first",
                    risk=risk,
                )
            )
        )
        return 1

    src_dir = _validate_relative_skill_path(
        matched_wh, str(matched_rec.get("path") or "")
    )
    if src_dir is None:
        print(
            json.dumps(
                _error_payload("INVALID_SOURCE_PATH", "Invalid skill source path")
            )
        )
        return 1

    scan = _scan_skill_dir_metadata(src_dir, include_hidden_dirs=True)
    if scan["symlinks_detected"]:
        print(
            json.dumps(
                _error_payload(
                    "SYMLINK_DETECTED",
                    f"Symlink or junction not allowed inside skill: {', '.join(scan['symlinks_detected'][:5])}",
                )
            )
        )
        return 1
    if scan["special_files_detected"]:
        print(
            json.dumps(
                _error_payload(
                    "SPECIAL_FILE_DETECTED",
                    f"Unsupported non-regular file in skill: {', '.join(scan['special_files_detected'][:5])}",
                )
            )
        )
        return 1
    if scan["truncated"]:
        print(
            json.dumps(
                _error_payload(
                    "BUDGET_EXCEEDED",
                    "Skill exceeds maximum depth or entry budget; refusing promotion",
                )
            )
        )
        return 1
    if scan["scripts"] and not args.allow_risky:
        print(
            json.dumps(
                _error_payload(
                    "SCRIPTS_UNREVIEWED",
                    f"Skill contains unreviewed scripts ({', '.join(scan['scripts'][:5])}); inspect them and pass --allow-risky",
                    scripts=scan["scripts"],
                )
            )
        )
        return 1

    skill_md_path = src_dir / "SKILL.md"
    if (
        skill_md_path.is_file()
        and not _is_link_or_reparse(skill_md_path)
        and not args.allow_risky
    ):
        try:
            with skill_md_path.open("r", encoding="utf-8-sig", errors="replace") as fh:
                md_text = fh.read(MAX_SKILL_FILE_BYTES)
        except OSError:
            md_text = ""
        inj_signals = _detect_prompt_injection_signals(md_text)
        if inj_signals:
            print(
                json.dumps(
                    _error_payload(
                        "PROMPT_INJECTION_DETECTED",
                        f"Skill SKILL.md contains prompt injection signals ({', '.join(inj_signals)}); inspect it and pass --allow-risky",
                        injection_signals=inj_signals,
                    )
                )
            )
            return 1

    dest_root = (
        pathlib.Path(args.dest).expanduser()
        if args.dest
        else (GLOBAL_SKILLS_DIR if args.target == "antigravity" else CODEX_SKILLS_DIR)
    )
    dest_name = str(matched_rec.get("id") or args.skill_id).strip()
    if not _validate_dest_name(dest_name):
        print(
            json.dumps(
                _error_payload("INVALID_DEST_NAME", "Invalid skill destination name")
            )
        )
        return 1

    if _is_link_or_reparse(dest_root):
        print(
            json.dumps(
                _error_payload(
                    "DEST_ESCAPES_ROOT", "Destination escapes skill directory"
                )
            )
        )
        return 1

    dest_dir = dest_root / dest_name
    if _is_link_or_reparse(dest_dir):
        print(
            json.dumps(
                _error_payload(
                    "DEST_ESCAPES_ROOT", "Destination escapes skill directory"
                )
            )
        )
        return 1

    resolved_dest = dest_dir.resolve()
    resolved_root = resolved_dest.parent
    if not dest_root.exists() and resolved_root != dest_root.resolve():
        resolved_root = dest_root.resolve()
    if resolved_dest == resolved_root or not resolved_dest.is_relative_to(
        resolved_root
    ):
        print(
            json.dumps(
                _error_payload(
                    "DEST_ESCAPES_ROOT", "Destination escapes skill directory"
                )
            )
        )
        return 1
    if (
        resolved_dest == src_dir
        or src_dir.is_relative_to(resolved_dest)
        or resolved_dest.is_relative_to(src_dir)
    ):
        print(
            json.dumps(
                _error_payload("SOURCE_DEST_OVERLAP", "Source and destination overlap")
            )
        )
        return 1

    if dest_dir.exists():
        if not args.overwrite:
            print(
                json.dumps(
                    _error_payload(
                        "DEST_EXISTS",
                        f"Destination already exists: {dest_dir}. Pass --overwrite to replace.",
                    )
                )
            )
            return 1
        if (
            not dest_dir.is_dir()
            or not (dest_dir / "SKILL.md").is_file()
            or _is_link_or_reparse(dest_dir / "SKILL.md")
        ):
            print(
                json.dumps(
                    _error_payload(
                        "DEST_NOT_SKILL_DIR",
                        f"Refusing to overwrite non-skill directory (missing SKILL.md): {dest_dir}",
                    )
                )
            )
            return 1

    if getattr(args, "dry_run", False):
        planned_bytes = 0
        for rel_file in scan["files"]:
            try:
                planned_bytes += (src_dir / rel_file).stat().st_size
            except OSError:
                pass
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "promoted": matched_rec.get("id"),
                    "risk": risk,
                    "would_overwrite": dest_dir.exists(),
                    "files_planned": len(scan["files"]),
                    "bytes_planned": planned_bytes,
                    "scripts_detected": scan["scripts"],
                    "install_to": str(dest_dir),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    dest_root.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(dest_root) or _is_link_or_reparse(dest_dir):
        print(
            json.dumps(
                _error_payload(
                    "DEST_ESCAPES_ROOT", "Destination escapes skill directory"
                )
            )
        )
        return 1

    try:
        lock_path, lock_token = _acquire_dest_lock(
            dest_root,
            dest_name,
            break_stale=getattr(args, "break_stale_lock", False),
        )
    except _LockError as exc:
        print(json.dumps(_error_payload(exc.error_code, str(exc))))
        return 1
    except (OSError, ValueError) as exc:
        print(json.dumps(_error_payload("DEST_LOCKED", str(exc))))
        return 1

    stage_dir = pathlib.Path(
        tempfile.mkdtemp(dir=dest_root, prefix=f".{dest_name}.stage-")
    )
    try:
        copy_stats = _copy_skill_tree_safely(
            src_dir, stage_dir, allow_scripts=args.allow_risky
        )
        _swap_staged_directory(stage_dir, dest_dir, overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        print(json.dumps(_error_payload("PROMOTE_FAILED", str(exc))))
        return 1
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        _release_dest_lock(lock_path, lock_token)

    active_count = len(
        [s for s in collect_active_skills(harness=args.target) if not s["shadowed"]]
    )
    tree_sha256 = _skill_content_digest(str(dest_dir / "SKILL.md"))
    print(
        json.dumps(
            {
                "promoted": matched_rec.get("id"),
                "risk": risk,
                "scripts_detected": scan["scripts"],
                "files_copied": copy_stats["files"],
                "bytes_copied": copy_stats["bytes"],
                "source": str(src_dir),
                "installed_to": str(dest_dir),
                "active_skills_total": active_count,
                "bloat_warning": active_count > HEALTHY_ACTIVE_CEILING,
                "install_receipt": {
                    "skill_id": matched_rec.get("id"),
                    "warehouse_name": matched_wh.name,
                    "risk": risk,
                    "evidence_state": (
                        "scripts-acknowledged"
                        if scan["scripts"]
                        else "statically-inspected"
                    ),
                    "tree_sha256": tree_sha256,
                    "files_copied": copy_stats["files"],
                    "bytes_copied": copy_stats["bytes"],
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_prune_check(args: argparse.Namespace) -> int:
    skills = collect_active_skills(None, args.harness)
    active = [s for s in skills if not s["shadowed"]]
    counts: dict[str, int] = {}
    for s in active:
        counts[s["source"]] = counts.get(s["source"], 0) + 1
    global_standalone = [s["name"] for s in active if s["source"] == "global:skills"]
    over_budget = len(active) > args.threshold
    print(
        json.dumps(
            {
                "active_skills_total": len(active),
                "healthy_ceiling": args.threshold,
                "status": "OVER_BUDGET" if over_budget else "HEALTHY",
                "counts_by_source": counts,
                "global_standalone_skills": global_standalone,
                "recommendation": (
                    "Active skill count exceeds healthy ceiling; consider removing unused skills from ~/.gemini/config/skills/ or disabling unused plugins."
                    if over_budget
                    else "Active skill count is lean; keep Tier 2 warehouse skills cold unless reused frequently."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run read-only environment, manifest, warehouse, and footprint diagnostics."""
    import platform

    _, _, antigravity_err = _parse_plugin_states()
    active = [
        s
        for s in collect_active_skills(args.workspace, args.harness)
        if not s["shadowed"]
    ]
    warehouses = resolve_warehouses(args.warehouse)
    metadata_chars = sum(
        len(str(s.get("name") or "")) + len(str(s.get("description") or ""))
        for s in active
    )
    manifest_versions: dict[str, str] = {}
    manifest_candidates = (
        ("plugin.json", PLUGIN_ROOT / "plugin.json"),
        (".codex-plugin/plugin.json", PLUGIN_ROOT / ".codex-plugin" / "plugin.json"),
        (
            ".agents/plugins/marketplace.json",
            PLUGIN_ROOT / ".agents" / "plugins" / "marketplace.json",
        ),
    )
    for label, mpath in manifest_candidates:
        if not mpath.is_file() or _is_link_or_reparse(mpath):
            manifest_versions[label] = "missing"
            continue
        try:
            mdata = json.loads(mpath.read_text(encoding="utf-8-sig"))
            ver: Any = None
            if isinstance(mdata, dict):
                ver = mdata.get("version")
                if (
                    not ver
                    and isinstance(mdata.get("plugins"), list)
                    and mdata["plugins"]
                ):
                    first_plug = mdata["plugins"][0]
                    if isinstance(first_plug, dict):
                        ver = first_plug.get("version")
            manifest_versions[label] = (
                ver.strip() if isinstance(ver, str) and ver.strip() else "invalid"
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            manifest_versions[label] = "invalid"

    distinct_versions = {
        v for v in manifest_versions.values() if v not in ("missing", "invalid")
    }
    manifest_versions_consistent = (
        bool(manifest_versions)
        and "missing" not in manifest_versions.values()
        and "invalid" not in manifest_versions.values()
        and len(distinct_versions) == 1
    )
    cli_matches_manifests = (
        manifest_versions_consistent and next(iter(distinct_versions)) == __version__
    )
    payload = {
        "cli_version": __version__,
        "manifest_versions": manifest_versions,
        "manifest_versions_consistent": manifest_versions_consistent,
        "cli_matches_manifests": cli_matches_manifests,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "antigravity_config_exists": CONFIG_JSON_PATH.is_file(),
        "antigravity_config_error": antigravity_err,
        "codex_config_exists": CODEX_CONFIG_PATH.is_file(),
        "warehouses_discovered": [str(w) for w in warehouses],
        "active_skills_total": len(active),
        "healthy_ceiling": HEALTHY_ACTIVE_CEILING,
        "metadata_chars": metadata_chars,
        "approx_metadata_tokens": round(metadata_chars / 4.0, 1),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate SKILL.md metadata constraints and relative markdown references."""
    sdir = _resolve_target_skill_dir(args.target, args.warehouse)
    if sdir is None:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_code": "SKILL_NOT_FOUND",
                    "errors": [f"Skill not found: {args.target}"],
                }
            )
        )
        return 1
    skill_md = sdir / "SKILL.md"
    if _is_link_or_reparse(sdir) or _is_link_or_reparse(skill_md):
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_code": "SYMLINK_DETECTED",
                    "errors": ["Symlinked skill directory"],
                }
            )
        )
        return 1
    try:
        open_flags = (
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        fd = os.open(skill_md, open_flags)
        try:
            fst = os.fstat(fd)
            if not stat.S_ISREG(fst.st_mode):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "error_code": "SPECIAL_FILE_DETECTED",
                            "errors": [f"SKILL.md is not a regular file: {skill_md}"],
                        }
                    )
                )
                return 1
            if fst.st_size > MAX_SKILL_FILE_BYTES:
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "error_code": "SKILL_MD_TOO_LARGE",
                            "errors": [
                                f"SKILL.md exceeds MAX_SKILL_FILE_BYTES ({fst.st_size} > {MAX_SKILL_FILE_BYTES})"
                            ],
                        }
                    )
                )
                return 1
            chunks: list[bytes] = []
            total_read = 0
            while True:
                chunk = os.read(fd, COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > MAX_SKILL_FILE_BYTES:
                    print(
                        json.dumps(
                            {
                                "valid": False,
                                "error_code": "SKILL_MD_TOO_LARGE",
                                "errors": [
                                    f"SKILL.md exceeds MAX_SKILL_FILE_BYTES ({total_read} > {MAX_SKILL_FILE_BYTES})"
                                ],
                            }
                        )
                    )
                    return 1
                chunks.append(chunk)
        finally:
            os.close(fd)
    except OSError:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_code": "SKILL_NOT_FOUND",
                    "errors": [f"SKILL.md unreadable: {skill_md}"],
                }
            )
        )
        return 1
    text = b"".join(chunks).decode("utf-8-sig", errors="replace")
    meta = parse_frontmatter_text(text, sdir.name, allow_fallback=False)
    errors: list[str] = []
    warnings: list[str] = []

    lines = text.splitlines()
    if (
        not lines
        or lines[0].strip() != "---"
        or "---" not in [ln.strip() for ln in lines[1:]]
    ):
        errors.append("Missing or unclosed YAML frontmatter delimiters")

    name = meta.get("name", "")
    if not name or len(name) > 64 or not re.fullmatch(r"[a-z0-9-]+", name):
        errors.append(
            f"Invalid skill name {name!r}: must match [a-z0-9-]+ and <= 64 chars"
        )
    elif name != sdir.name:
        warnings.append(
            f"Skill name {name!r} differs from directory name {sdir.name!r}"
        )

    desc = meta.get("description", "")
    if not desc.strip():
        errors.append("Description must be non-empty")
    elif len(desc) > 1024:
        warnings.append(f"Description exceeds 1024 chars ({len(desc)})")

    compat = meta.get("compatibility", "")
    if compat and len(compat) > 500:
        warnings.append(f"Compatibility exceeds 500 chars ({len(compat)})")

    sdir_resolved = sdir.resolve()
    for match in re.finditer(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        rel_target = match.group(1).strip()
        if rel_target.startswith(("http://", "https://", "mailto:")):
            continue
        rel_path = pathlib.Path(rel_target)
        if rel_path.is_absolute():
            errors.append(f"Absolute reference path not allowed: {rel_target}")
            continue
        candidate = sdir / rel_path
        has_link_segment = False
        probe = sdir
        for part in rel_path.parts:
            if part in ("", "."):
                continue
            probe = probe / part
            if _is_link_or_reparse(probe):
                has_link_segment = True
                break
        try:
            resolved_ref = candidate.resolve(strict=True)
        except OSError:
            errors.append(f"Missing relative reference: {rel_target}")
            continue
        if (
            has_link_segment
            or _is_link_or_reparse(candidate)
            or resolved_ref == sdir_resolved
            or not resolved_ref.is_relative_to(sdir_resolved)
        ):
            errors.append(f"Missing or escaping relative reference: {rel_target}")

    inject_signals = _detect_prompt_injection_signals(text)
    if inject_signals:
        warnings.append(f"Suspicious instruction patterns: {', '.join(inject_signals)}")

    valid = len(errors) == 0
    print(
        json.dumps(
            {
                "valid": valid,
                "skill_dir": str(sdir),
                "name": name,
                "errors": errors,
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if valid else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Skill Pilot multi-tier skill discovery tool"
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser(
        "inventory",
        help="List all active Tier 1 skills across plugins and global/builtin dirs",
    )
    inv.add_argument(
        "--workspace", help="Optional workspace root path to include .agents/skills"
    )
    inv.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    inv.add_argument("--format", choices=["json", "summary"], default="json")
    inv.set_defaults(func=cmd_inventory)

    intake = sub.add_parser(
        "intake", help="Read workspace rules and unverified command candidates"
    )
    intake.add_argument("--workspace", required=True)
    intake.add_argument(
        "--target",
        action="append",
        default=[],
        help="Optional target file or subdirectory inside workspace to prioritize ancestor rules",
    )
    intake.add_argument("--format", choices=["json", "compact"], default="compact")
    intake.set_defaults(func=cmd_intake)

    srch = sub.add_parser(
        "search", help="Search Tier 1 active skills and Tier 2 local warehouse"
    )
    srch.add_argument("query", nargs="+", help="Search keywords")
    srch.add_argument("--limit", type=positive_int, default=12)
    srch.add_argument("--workspace", help="Optional workspace root path")
    srch.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    srch.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    srch.add_argument("--include-active", action="store_true", default=True)
    srch.add_argument("--no-active", dest="include_active", action="store_false")
    srch.add_argument(
        "--allow-risky",
        action="store_true",
        help="Include skills marked risk=offensive",
    )
    srch.add_argument(
        "--explain",
        action="store_true",
        help="Include score_breakdown details in JSON search results",
    )
    srch.add_argument("--format", choices=["json", "compact"], default="json")
    srch.set_defaults(func=cmd_search)

    insp = sub.add_parser(
        "inspect", help="Inspect a skill's SKILL.md and check for executable scripts"
    )
    insp.add_argument("target", help="Skill ID/name or path to SKILL.md/folder")
    insp.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    insp.add_argument("--preview-lines", type=non_negative_int, default=60)
    insp.add_argument("--format", choices=["json", "compact"], default="json")
    insp.set_defaults(func=cmd_inspect)

    prom = sub.add_parser(
        "promote",
        help="Install a Tier 2 warehouse skill permanently to a harness skill directory",
    )
    prom.add_argument("skill_id", help="Skill ID or name in a local warehouse")
    prom.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    prom.add_argument("--dest", help="Override destination skills directory")
    prom.add_argument(
        "--target", choices=["antigravity", "codex"], default="antigravity"
    )
    prom.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing installed skill directory safely with rollback",
    )
    prom.add_argument(
        "--allow-risky",
        action="store_true",
        help="Acknowledge and promote skills whose risk is unknown, medium, high, critical, or offensive",
    )
    prom.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report planned promotion manifest without writing to destination",
    )
    prom.add_argument(
        "--break-stale-lock",
        action="store_true",
        help="Reclaim an expired or malformed destination lockfile before promoting",
    )
    prom.add_argument(
        "--force",
        action="store_true",
        help="Deprecated; rejected for safety. Use --overwrite and/or --allow-risky.",
    )
    prom.set_defaults(func=cmd_promote)

    prune = sub.add_parser(
        "prune-check",
        help="Check whether active skill count stays under healthy context ceiling",
    )
    prune.add_argument("--workspace", help="Optional workspace root path")
    prune.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    prune.add_argument("--threshold", type=int, default=HEALTHY_ACTIVE_CEILING)
    prune.set_defaults(func=cmd_prune_check)

    doc = sub.add_parser(
        "doctor",
        help="Run read-only environment, config, warehouse, and context footprint diagnostics",
    )
    doc.add_argument("--workspace", help="Optional workspace root path")
    doc.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    doc.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    doc.set_defaults(func=cmd_doctor)

    val = sub.add_parser(
        "validate",
        help="Validate SKILL.md metadata bounds and relative markdown references",
    )
    val.add_argument("target", help="Skill ID/name or path to SKILL.md/folder")
    val.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    val.set_defaults(func=cmd_validate)

    sess = sub.add_parser(
        "session",
        help="Initialize, update, revise, or inspect a structured discovery session",
    )
    sess.add_argument(
        "action",
        choices=["init", "update", "revise", "status", "spec"],
        help="Session action",
    )
    sess.add_argument("--session", required=True, help="Path to session JSON file")
    sess.add_argument("--request", default="", help="Initial user request (for init)")
    sess.add_argument(
        "--language", default="en", help="Session language (en, vi, mixed)"
    )
    sess.add_argument("--patch", help="Path to JSON patch file (for update/revise)")
    sess.add_argument("--note", default="Session updated", help="Revision note")
    sess.set_defaults(func=cmd_session)

    psearch = sub.add_parser(
        "plan-search",
        help="Run per-step skill discovery and gap detection for a structured plan",
    )
    psearch.add_argument("--plan", help="Path to JSON file containing plan_steps")
    psearch.add_argument(
        "--session", help="Path to session JSON file containing plan_steps"
    )
    psearch.add_argument("--limit", type=positive_int, default=3)
    psearch.add_argument("--workspace", help="Optional workspace root path")
    psearch.add_argument(
        "--harness",
        choices=["auto", "antigravity", "codex", "all"],
        default="antigravity",
    )
    psearch.add_argument(
        "--warehouse", help="Override path to a local skill warehouse directory"
    )
    psearch.add_argument("--include-active", action="store_true", default=True)
    psearch.add_argument("--no-active", dest="include_active", action="store_false")
    psearch.add_argument("--allow-risky", action="store_true")
    psearch.set_defaults(func=cmd_plan_search)

    return parser


def cmd_session(args: argparse.Namespace) -> int:
    import session_planner

    session_path = pathlib.Path(args.session)
    if args.action == "init":
        data = session_planner.init_session(args.request, language=args.language)
        session_planner.save_json_file(session_path, data)
    elif args.action in ("update", "revise"):
        patch = (
            session_planner.load_json_file(pathlib.Path(args.patch))
            if args.patch
            else {}
        )
        if args.action == "revise":
            patch["replace_plan"] = True
        data = session_planner.update_session_file_locked(
            session_path, patch, revision_note=args.note
        )
    elif args.action == "spec":
        data = session_planner.load_json_file(session_path)
        print(session_planner.render_specification(data, data.get("last_discovery")))
        return 0
    else:
        data = session_planner.load_json_file(session_path)

    out = {
        "session": data,
        "readiness": session_planner.compute_readiness(data),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_plan_search(args: argparse.Namespace) -> int:
    import session_planner

    if args.session:
        source = session_planner.load_json_file(pathlib.Path(args.session))
        readiness = session_planner.compute_readiness(source)
        if not readiness["ready_for_planning"]:
            print(
                json.dumps(
                    {
                        **_error_payload(
                            "DISCOVERY_BLOCKED_UNCONFIRMED_INTENT",
                            "Confirm intent and resolve blocking interview questions first.",
                        ),
                        "missing_for_planning": readiness["missing_for_planning"],
                    }
                )
            )
            return 1
        if not readiness["ready_for_discovery"]:
            print(
                json.dumps(
                    {
                        **_error_payload(
                            "DISCOVERY_BLOCKED_NOT_READY",
                            "Complete success criteria and a current, valid plan before discovery.",
                        ),
                        "missing_criteria": readiness["missing_criteria"],
                    }
                )
            )
            return 1
    elif args.plan:
        source = session_planner.load_json_file(pathlib.Path(args.plan))
    else:
        print(
            json.dumps(_error_payload("MISSING_PLAN", "Provide --plan or --session."))
        )
        return 1

    steps = source.get("plan_steps", []) if isinstance(source, dict) else source
    if not isinstance(steps, list) or not steps:
        print(json.dumps(_error_payload("EMPTY_PLAN", "Plan has no steps.")))
        return 1

    def _search_step(query: str, limit: int) -> int:
        step_args = argparse.Namespace(
            query=[query],
            limit=limit,
            workspace=args.workspace,
            harness=args.harness,
            warehouse=args.warehouse,
            include_active=args.include_active,
            allow_risky=args.allow_risky,
            explain=False,
            format="json",
        )
        return cmd_search(step_args)

    result = session_planner.run_plan_search(steps, _search_step, limit=args.limit)
    if args.session and isinstance(source, dict):
        session_planner.persist_discovery_to_session(
            pathlib.Path(args.session),
            str(source.get("session_id", "")),
            int(source.get("revision", 1)),
            result,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def main() -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
    ) as exc:
        print(json.dumps(_error_payload("CLI_EXECUTION_ERROR", str(exc))))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
