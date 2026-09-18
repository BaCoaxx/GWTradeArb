"""Offscreen GUI smoke. Skips if PySide6 cannot create a QApplication."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.gui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_window(tmp_path):
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(f"PySide6/Qt platform unavailable: {exc}")

    from gwtradearb.ui.window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "ui.sqlite")
    window.refresh_from_db()
    return app, window


def test_main_window_loads_empty_db(tmp_path):
    app, window = _make_window(tmp_path)
    assert "GWTradeArb" in window.windowTitle()
    assert window.table.columnCount() == 10
    assert window.lookback_spin.value() == 12
    assert window.lookback_spin.minimum() == 12
    window.lookback_spin.setValue(24)
    window.close()
    from gwtradearb.database import get_match_lookback_hours, open_db

    with open_db(tmp_path / "ui.sqlite") as conn:
        assert get_match_lookback_hours(conn) == 24
    assert app is not None


def test_dense_layout_headers_and_status_dots(tmp_path):
    app, window = _make_window(tmp_path)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QAbstractSpinBox,
        QStatusBar,
        QStyle,
        QStyleOptionSpinBox,
        QTabBar,
        QWidget,
    )

    from gwtradearb.ui.window import (
        COLUMNS,
        LOG_HEIGHT_PX,
        SOURCE_STATUS_GAP_PX,
        ArrowSpinBox,
        SourceStatusDot,
        SourceStatusIndicator,
    )

    headers = [
        window.table.horizontalHeaderItem(index).text()
        for index in range(window.table.columnCount())
    ]
    assert tuple(headers) == COLUMNS
    assert headers == [
        "Item",
        "Qty",
        "Seller",
        "Sell",
        "Buyer",
        "Buy",
        "Diff",
        "Src",
        "Detected",
        "Status",
    ]
    assert window.table.horizontalHeaderItem(1).toolTip() == "Quantity"
    assert window.table.horizontalHeaderItem(6).toolTip().startswith("Potential difference")

    assert window.log.maximumHeight() == LOG_HEIGHT_PX
    assert window.log.minimumHeight() == LOG_HEIGHT_PX
    assert window.detail.minimumHeight() >= 150
    assert window.table.minimumHeight() >= 200
    assert window.main_splitter.count() == 2
    assert window.main_splitter.sizes()[0] >= window.main_splitter.sizes()[1]
    assert window.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert isinstance(window.tabs, QTabBar)

    assert isinstance(window.lookback_spin, ArrowSpinBox)
    assert (
        window.lookback_spin.buttonSymbols()
        == QAbstractSpinBox.ButtonSymbols.UpDownArrows
    )
    window.lookback_spin.resize(130, 26)
    window.show()
    app.processEvents()
    opt = QStyleOptionSpinBox()
    window.lookback_spin.initStyleOption(opt)
    up_rect = window.lookback_spin.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        opt,
        QStyle.SubControl.SC_SpinBoxUp,
        window.lookback_spin,
    )
    down_rect = window.lookback_spin.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        opt,
        QStyle.SubControl.SC_SpinBoxDown,
        window.lookback_spin,
    )
    assert up_rect.width() >= 12
    assert down_rect.width() >= 12
    assert up_rect.height() >= 8
    assert down_rect.height() >= 8

    assert isinstance(window.decltype_badge, SourceStatusIndicator)
    assert isinstance(window.gwtoolbox_badge, SourceStatusIndicator)
    assert isinstance(window.decltype_badge.dot, SourceStatusDot)
    assert isinstance(window.gwtoolbox_badge.dot, SourceStatusDot)
    assert window.decltype_badge.label_text == "decltype:"
    assert window.gwtoolbox_badge.label_text == "gwtoolbox:"
    assert window.decltype_badge.caption.text() == "decltype:"
    assert window.gwtoolbox_badge.caption.text() == "gwtoolbox:"
    decltype_margins = window.decltype_badge.layout().contentsMargins()
    gwtoolbox_margins = window.gwtoolbox_badge.layout().contentsMargins()
    assert decltype_margins.left() >= 8
    assert decltype_margins.right() >= 8
    assert gwtoolbox_margins.left() >= 8
    assert gwtoolbox_margins.right() >= 8
    # Comfortable gap: each badge's outer padding plus an explicit spacer.
    assert decltype_margins.right() + gwtoolbox_margins.left() >= 16
    assert SOURCE_STATUS_GAP_PX >= 20
    gap = window.statusBar().findChild(QWidget, "source_status_gap")
    assert gap is not None
    assert gap.width() >= 20
    assert "Src" not in {
        child.text()
        for child in window.statusBar().findChildren(window.decltype_badge.caption.__class__)
        if child.text()
    }
    assert isinstance(window.statusBar(), QStatusBar)
    assert window.statusBar().isAncestorOf(window.decltype_badge)
    assert window.statusBar().isAncestorOf(window.gwtoolbox_badge)
    assert window.decltype_badge.toolTip() == "Decltype: Unknown"
    window._set_badge("decltype", True)
    window._set_badge("gwtoolbox", False)
    assert window.decltype_badge.toolTip() == "Decltype: Online"
    assert window.gwtoolbox_badge.toolTip() == "GWToolbox: Offline"
    assert "#16a34a" in window.decltype_badge.dot.styleSheet()
    assert "#dc2626" in window.gwtoolbox_badge.dot.styleSheet()

    shortcuts = {action.shortcut().toString() for action in window.actions()}
    assert "Ctrl+R" in shortcuts
    assert "Ctrl+T" in shortcuts
    assert "Ctrl+D" in shortcuts
    window.close()
    assert app is not None
