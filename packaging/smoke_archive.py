#!/usr/bin/env python3
"""Smoke-test a native GWTradeArb archive on the current OS.

Extracts the archive, runs --help / --version / --stats against a temp DB.
Does not open the GUI. Does not talk to Guild Wars.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def _archive_path() -> Path:
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise SystemExit(f"Smoke is x64-only; this host is {platform.machine()!r}.")
    if sys.platform.startswith("linux"):
        path = DIST / "GWTradeArb-Linux-x64.tar.gz"
    elif sys.platform == "win32":
        path = DIST / "GWTradeArb-Windows-x64.zip"
    else:
        raise SystemExit(f"No smoke archive defined for {sys.platform!r}.")
    if not path.is_file():
        raise SystemExit(f"Missing archive: {path}")
    return path


def _extract(archive: Path, dest: Path) -> Path:
    if archive.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(archive, "r:gz") as tar:
            try:
                tar.extractall(dest, filter="data")
            except TypeError:
                tar.extractall(dest)
    else:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    binary_name = "GWTradeArb.exe" if sys.platform == "win32" else "GWTradeArb"
    matches = [path for path in dest.rglob(binary_name) if path.is_file()]
    if not matches:
        raise SystemExit(f"No {binary_name} file found inside {archive.name}")
    binary = matches[0]
    if sys.platform != "win32":
        binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def _run(binary: Path, args: list[str], *, db: Path | None = None) -> str:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    cmd = [str(binary), *args]
    if db is not None:
        cmd.extend(["--db", str(db)])
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise SystemExit(
            f"{' '.join(cmd)} exited {completed.returncode}\n{output}"
        )
    return output


def main() -> int:
    archive = _archive_path()
    with tempfile.TemporaryDirectory(prefix="gwtradearb-smoke-") as raw:
        tmp = Path(raw)
        binary = _extract(archive, tmp / "extract")
        help_text = _run(binary, ["--help"])
        if "gwtradearb" not in help_text.lower():
            raise SystemExit("--help did not mention gwtradearb")
        version_text = _run(binary, ["--version"])
        if "GWTradeArb" not in version_text:
            raise SystemExit(f"--version unexpected: {version_text!r}")
        db = tmp / "smoke.sqlite"
        stats_text = _run(binary, ["--stats"], db=db)
        if "scans=" not in stats_text:
            raise SystemExit(f"--stats unexpected: {stats_text!r}")
        print(f"smoke ok: {archive.name}")
        print(version_text.strip())
        print(stats_text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
