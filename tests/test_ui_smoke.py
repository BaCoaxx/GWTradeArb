"""Offscreen GUI smoke. Skips if PySide6 cannot create a QApplication."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.gui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_loads_empty_db(tmp_path):
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(f"PySide6/Qt platform unavailable: {exc}")

    from gwtradearb.ui.window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "ui.sqlite")
    window.refresh_from_db()
    assert "GWTradeArb" in window.windowTitle()
    assert window.table.columnCount() == 10
    window.close()
    assert app is not None
