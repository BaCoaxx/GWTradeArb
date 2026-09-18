#!/usr/bin/env python3
"""Build a platform-native GWTradeArb archive with PyInstaller.

This script never cross-compiles and never mislabels an archive:
- Linux x64  → dist/GWTradeArb-Linux-x64.tar.gz
- Windows x64 → dist/GWTradeArb-Windows-x64.zip

Run it on the OS you intend to ship. GitHub Actions (linux-latest and
windows-latest) is the supported way to produce the Windows zip.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SPEC = ROOT / "packaging" / "gwtradearb.spec"
APP_NAME = "GWTradeArb"
REPO_URL = "https://github.com/BaCoaxx/GWTradeArb"

ARCHIVE_README = """GWTradeArb
==========

Public Kamadan trade-chat scanner (fetch → parse → compare → display).
It does not automate Guild Wars, send whispers, or store game credentials.

Run:
  Windows:  double-click GWTradeArb.exe  (or run it from cmd)
  Linux:    ./GWTradeArb

CLI examples:
  GWTradeArb --help
  GWTradeArb --version
  GWTradeArb --scan
  GWTradeArb --stats

SQLite data is stored in your user-data folder, not next to this binary:
  Linux:   ~/.local/share/gwtradearb/gwtradearb.sqlite
  Windows: %APPDATA%\\\\gwtradearb\\\\gwtradearb.sqlite

Override with --db PATH or the GWTRADEARB_DB environment variable.

Source, license, and documentation:
  {repo}
"""


def _archive_name() -> str:
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise SystemExit(
            f"Refusing to label an x64 archive on machine={platform.machine()!r}."
        )
    if sys.platform.startswith("linux"):
        return "GWTradeArb-Linux-x64.tar.gz"
    if sys.platform == "win32":
        return "GWTradeArb-Windows-x64.zip"
    raise SystemExit(
        f"Unsupported platform {sys.platform!r}. Build on Linux x64 or Windows x64."
    )


def _write_bundle_docs(staged: Path) -> None:
    (staged / "README.txt").write_text(
        ARCHIVE_README.format(repo=REPO_URL), encoding="utf-8"
    )
    license_src = ROOT / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, staged / "LICENSE.txt")


def _pack(staged: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    if dest.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(dest, "w:gz") as archive:
            archive.add(staged, arcname=APP_NAME)
        return
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in staged.rglob("*"):
            if path.is_file():
                archive.write(path, Path(APP_NAME) / path.relative_to(staged))


def main() -> int:
    dest = DIST / _archive_name()
    DIST.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    staged = DIST / APP_NAME
    if not staged.exists():
        raise SystemExit(f"PyInstaller did not produce {staged}")
    _write_bundle_docs(staged)
    _pack(staged, dest)
    print(f"Wrote {dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
