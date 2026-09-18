"""PyInstaller entry point. Does not automate Guild Wars."""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            continue
    from gwtradearb.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
