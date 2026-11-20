"""Build reproducible, allowlisted Skill Pilot v4 beta plugin ZIP and checksum.

Never package arbitrary git-tracked files, sealed evaluation, logs, or .git.
Full source + benchmarks remain available from the GitHub release's source ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = "4.0.0-beta.1"
PACKAGE_FILES = frozenset(
    {
        "plugin.json",
        ".codex-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        "README.md",
        "LICENSE",
        "scripts/skill_scout.py",
        "assets/logo.svg",
    }
)
PACKAGE_PREFIX = "skills/skill-pilot/"


def read_versions() -> tuple[str, str, str]:
    plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    codex = json.loads(
        (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    market = json.loads(
        (ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    )
    return (
        plugin["version"],
        codex["version"],
        market["plugins"][0]["version"],
    )


def package_paths() -> list[pathlib.Path]:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, timeout=20
    )
    paths = []
    for raw in tracked.decode("utf-8").split("\x00"):
        if not raw:
            continue
        if raw not in PACKAGE_FILES and not raw.startswith(PACKAGE_PREFIX):
            continue
        file = ROOT / raw
        if not file.is_file() or file.is_symlink():
            raise ValueError(f"Package file missing or unsafe: {raw}")
        paths.append(file)
    if not PACKAGE_FILES.issubset(
        {str(p.relative_to(ROOT)).replace("\\", "/") for p in paths}
    ):
        raise ValueError("Required plugin package files missing from git index")
    return sorted(paths, key=lambda p: p.as_posix())


def build(output: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    if read_versions() != (VERSION, VERSION, VERSION):
        raise ValueError("Beta plugin versions do not match the package version")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"skill-pilot-v{VERSION}-plugin.zip"
    checksum = output / "SHA256SUMS"
    if archive.exists() or checksum.exists():
        raise FileExistsError("Beta package artifacts already exist")
    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as bundle:
        for file in package_paths():
            relative = file.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"skill-pilot/{relative}", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "dist")
    args = parser.parse_args()
    archive, checksum = build(args.output)
    print(f"Package: {archive.name} ({archive.stat().st_size} bytes)")
    print(f"Checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
