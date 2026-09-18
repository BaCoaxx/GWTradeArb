"""Background scan worker. Network I/O stays off the GUI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from gwtradearb.scan import run_scan_cycle


class ScanWorker(QObject):
    log_line = Signal(str)
    source_state = Signal(str, bool)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: str | Path) -> None:
        super().__init__()
        self._db_path = str(db_path)

    def run(self) -> None:
        try:
            result = run_scan_cycle(self._db_path, log=self.log_line.emit)
            for source, online in result.source_online.items():
                self.source_state.emit(source, online)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 — surface any scanner failure in the log
            self.failed.emit(f"{type(exc).__name__}: {exc}")
