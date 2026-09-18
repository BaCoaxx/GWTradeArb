"""Main window: opportunities table, scan controls, stats, and technical log."""

from __future__ import annotations

import sys
import time
import webbrowser
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPainter, QPolygon
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyleOptionSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from gwtradearb import __version__
from gwtradearb.database import (
    DEFAULT_MATCH_LOOKBACK_HOURS,
    MAX_MATCH_LOOKBACK_HOURS,
    MIN_MATCH_LOOKBACK_HOURS,
    default_db_path,
    get_match_lookback_hours,
    get_setting,
    list_opportunity_details,
    open_db,
    set_match_lookback_hours,
    set_setting,
    set_status,
    stats,
)
from gwtradearb.display import (
    SCAN_INTERVALS,
    SOURCE_HOME_URLS,
    SOURCE_LABELS,
    format_detected,
    format_gold,
    format_sources,
    row_matches_filters,
)
from gwtradearb.ui.worker import ScanWorker

COLUMNS = (
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
)

COLUMN_HEADER_TIPS = (
    "Item",
    "Quantity",
    "Seller",
    "Sell price",
    "Buyer",
    "Buy price",
    "Potential difference (chat-price spread, not profit)",
    "Source",
    "Detected",
    "Status",
)

TAB_STATUSES = (
    ("Active", "new"),
    ("Traded", "traded"),
    ("Dismissed", "dismissed"),
    ("Expired", "expired"),
)

# Technical log stays a short strip so the table and listings keep the height.
LOG_HEIGHT_PX = 80
# Horizontal gap between labeled source badges so they do not read as Src 🟢🟢.
SOURCE_STATUS_GAP_PX = 28

APP_STYLESHEET = """
QMainWindow { background: #f3f4f6; }
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    spacing: 6px;
    padding: 3px 8px;
}
QToolBar QLabel { color: #4b5563; }
QPushButton {
    padding: 4px 10px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #ffffff;
}
QPushButton:hover { background: #f9fafb; border-color: #9ca3af; }
QPushButton:pressed { background: #e5e7eb; }
QPushButton:disabled { color: #9ca3af; }
QLineEdit, QComboBox {
    padding: 3px 6px;
    min-height: 22px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #ffffff;
}
/* Fusion + a padded QSpinBox rule collapses PE_IndicatorSpinUp/Down into a
   1px smear (thin black bars on Linux). Keep buttons sized and unpadded. */
QSpinBox {
    padding: 1px 2px 1px 6px;
    min-height: 24px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #ffffff;
}
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    border-left: 1px solid #d1d5db;
    background: #f3f4f6;
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 3px;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 3px;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    gridline-color: #e5e7eb;
    font-size: 12px;
    selection-background-color: #dbeafe;
    selection-color: #111827;
    border: 1px solid #e5e7eb;
}
QHeaderView::section {
    background: #eef2f7;
    color: #374151;
    padding: 4px 6px;
    border: none;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #d1d5db;
    font-size: 11px;
    font-weight: 600;
}
QTabBar::tab {
    padding: 5px 12px;
    background: #e5e7eb;
    border: 1px solid #d1d5db;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #ffffff; font-weight: 600; }
QGroupBox {
    font-size: 11px;
    font-weight: 600;
    color: #4b5563;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    margin-top: 8px;
    padding: 6px 8px 4px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    font-size: 12px;
}
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    font-size: 11px;
}
"""


class ArrowSpinBox(QSpinBox):
    """Fusion-safe spinbox: stylesheet-sized buttons plus painted triangles.

    Qt's stylesheet style often leaves PE_IndicatorSpinUp/Down as a 1px line
    (or omits the icon-theme glyph). Always draw clear up/down arrows.
    """

    _ARROW = QColor("#374151")
    _ARROW_DISABLED = QColor("#9ca3af")
    _BUTTON_WIDTH = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._ARROW if self.isEnabled() else self._ARROW_DISABLED
        for subcontrol, up in (
            (QStyle.SubControl.SC_SpinBoxUp, True),
            (QStyle.SubControl.SC_SpinBoxDown, False),
        ):
            rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox, opt, subcontrol, self
            )
            if rect.width() < 8 or rect.height() < 6:
                rect = self._fallback_button_rect(up)
            self._paint_arrow(painter, rect, up=up, color=color)
        painter.end()

    def _fallback_button_rect(self, up: bool) -> QRect:
        inner = self.rect().adjusted(1, 1, -1, -1)
        width = self._BUTTON_WIDTH
        height = max(8, inner.height() // 2)
        left = inner.right() - width + 1
        top = inner.top() if up else inner.bottom() - height + 1
        return QRect(left, top, width, height)

    @staticmethod
    def _paint_arrow(painter: QPainter, rect: QRect, *, up: bool, color: QColor) -> None:
        box = rect.adjusted(5, 3, -5, -3)
        if box.width() < 6:
            box.setWidth(6)
            box.moveLeft(rect.center().x() - 3)
        if box.height() < 4:
            box.setHeight(4)
            box.moveTop(rect.center().y() - 2)
        mid_x = box.center().x()
        if up:
            points = QPolygon(
                [
                    QPoint(mid_x, box.top()),
                    QPoint(box.left(), box.bottom()),
                    QPoint(box.right(), box.bottom()),
                ]
            )
        else:
            points = QPolygon(
                [
                    QPoint(box.left(), box.top()),
                    QPoint(box.right(), box.top()),
                    QPoint(mid_x, box.bottom()),
                ]
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(points)


class SourceStatusDot(QLabel):
    """Compact filled circle: green online, red offline, gray unknown."""

    _COLORS = {None: "#9ca3af", True: "#16a34a", False: "#dc2626"}

    def __init__(self, source: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = source
        self._online: bool | None = None
        self.setFixedSize(12, 12)
        self.setObjectName(f"{source}_status_dot")
        self.setAccessibleName(SOURCE_LABELS.get(source, source))
        self.set_state(None)

    def set_state(self, online: bool | None) -> None:
        self._online = online
        label = SOURCE_LABELS.get(self.source, self.source)
        if online is None:
            state = "Unknown"
        elif online:
            state = "Online"
        else:
            state = "Offline"
        self.setToolTip(f"{label}: {state}")
        color = self._COLORS[online]
        self.setStyleSheet(
            f"QLabel {{ background-color: {color}; border-radius: 6px; }}"
        )


class SourceStatusIndicator(QWidget):
    """Labeled source badge: `decltype: ●` with comfortable outer padding."""

    def __init__(self, source: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = source
        self.setObjectName(f"{source}_status")
        self.setAccessibleName(SOURCE_LABELS.get(source, source))
        self.caption = QLabel(f"{source}:")
        self.caption.setObjectName(f"{source}_status_caption")
        self.caption.setStyleSheet("color: #4b5563;")
        self.dot = SourceStatusDot(source)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(6)
        layout.addWidget(self.caption)
        layout.addWidget(self.dot)
        self.set_state(None)

    def set_state(self, online: bool | None) -> None:
        self.dot.set_state(online)
        self.setToolTip(self.dot.toolTip())

    @property
    def label_text(self) -> str:
        return self.caption.text()


class NumericTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is None:
            return True
        if right is None:
            return False
        try:
            return left < right
        except TypeError:
            return str(left) < str(right)


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self.db_path = Path(db_path) if db_path else default_db_path()
        self._rows: list[dict] = []
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._scan_busy = False

        self.setWindowTitle(f"GWTradeArb {__version__}")
        self.setStyleSheet(APP_STYLESHEET)
        self._restore_size()
        self._build()
        self._load_interval_setting()
        self._load_lookback_setting()
        self.refresh_from_db()
        self._append_log(
            "Ready. Scrape → parse → display only; never automates Guild Wars. "
            "potential_difference is a chat-price spread, not profit."
        )

    def _restore_size(self) -> None:
        width, height = 1180, 740
        try:
            with open_db(self.db_path) as conn:
                width = int(get_setting(conn, "ui_window_width", str(width)) or width)
                height = int(get_setting(conn, "ui_window_height", str(height)) or height)
        except (TypeError, ValueError, OSError):
            pass
        self.resize(max(960, width), max(600, height))

    def _build(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.scan_btn = QPushButton("Scan Now")
        self.scan_btn.clicked.connect(self.start_scan)
        toolbar.addWidget(self.scan_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_from_db)
        toolbar.addWidget(refresh_btn)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Auto-scan: "))
        self.interval_combo = QComboBox()
        for label, seconds in SCAN_INTERVALS:
            self.interval_combo.addItem(label, seconds)
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        toolbar.addWidget(self.interval_combo)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Match lookback: "))
        self.lookback_spin = ArrowSpinBox()
        self.lookback_spin.setRange(MIN_MATCH_LOOKBACK_HOURS, MAX_MATCH_LOOKBACK_HOURS)
        self.lookback_spin.setValue(DEFAULT_MATCH_LOOKBACK_HOURS)
        self.lookback_spin.setSuffix(" hours")
        self.lookback_spin.setToolTip(
            "Rematch local SQLite listings whose chat timestamp is within this "
            "many hours. Default 12; longer windows are allowed. Live APIs are "
            "not paginated, so older rows come from history already stored here."
        )
        self.lookback_spin.setMinimumWidth(128)
        self.lookback_spin.setFixedHeight(26)
        self.lookback_spin.valueChanged.connect(self._on_lookback_changed)
        toolbar.addWidget(self.lookback_spin)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(120)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        toolbar.addWidget(self.progress)

        traded_btn = QPushButton("Mark as Traded")
        traded_btn.clicked.connect(lambda: self._mark_selected("traded"))
        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.clicked.connect(lambda: self._mark_selected("dismissed"))

        filter_bar = QHBoxLayout()
        self.item_filter = QLineEdit()
        self.item_filter.setPlaceholderText("Filter item / player…")
        self.item_filter.textChanged.connect(self._apply_filters)
        self.source_filter = QComboBox()
        self.source_filter.addItem("All sources", "all")
        self.source_filter.addItem("Decltype", "decltype")
        self.source_filter.addItem("GWToolbox", "gwtoolbox")
        self.source_filter.currentIndexChanged.connect(self._apply_filters)
        self.min_diff = QLineEdit()
        self.min_diff.setPlaceholderText("Min spread")
        self.min_diff.setMaximumWidth(110)
        self.min_diff.editingFinished.connect(self._apply_filters)
        filter_bar.addWidget(QLabel("Item"))
        filter_bar.addWidget(self.item_filter, 2)
        filter_bar.addWidget(QLabel("Source"))
        filter_bar.addWidget(self.source_filter)
        filter_bar.addWidget(QLabel("Min spread"))
        filter_bar.addWidget(self.min_diff)
        filter_bar.addStretch(1)
        filter_bar.addWidget(traded_btn)
        filter_bar.addWidget(dismiss_btn)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for title, _status in TAB_STATUSES:
            self.tabs.addTab(title)
        self.tabs.currentChanged.connect(self.refresh_from_db)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setShowGrid(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setMinimumHeight(200)
        self._configure_columns()
        self.table.itemSelectionChanged.connect(self._show_detail)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(150)
        self.detail.setPlaceholderText("Select a row to view original listing messages.")
        open_decl = QPushButton("Open Decltype")
        open_decl.clicked.connect(lambda: self._open_source("decltype"))
        open_gwt = QPushButton("Open GWToolbox")
        open_gwt.clicked.connect(lambda: self._open_source("gwtoolbox"))
        detail_header = QHBoxLayout()
        detail_header.addWidget(QLabel("Original listings"))
        detail_header.addStretch(1)
        detail_header.addWidget(open_decl)
        detail_header.addWidget(open_gwt)
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addLayout(detail_header)
        detail_layout.addWidget(self.detail)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(detail_box)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 200])
        self.main_splitter = splitter

        stats_box = QGroupBox("Statistics")
        stats_form = QHBoxLayout(stats_box)
        stats_form.setContentsMargins(8, 2, 8, 2)
        self.stat_found = QLabel("Found: 0")
        self.stat_active = QLabel("Active: 0")
        self.stat_traded = QLabel("Traded: 0")
        self.stat_dismissed = QLabel("Dismissed: 0")
        self.stat_scans = QLabel("Scans: 0")
        for widget in (
            self.stat_found,
            self.stat_active,
            self.stat_traded,
            self.stat_dismissed,
            self.stat_scans,
        ):
            stats_form.addWidget(widget)
        stats_form.addStretch(1)
        note = QLabel("No profit total — listings may vanish; trade by hand.")
        note.setStyleSheet("color: palette(mid);")
        stats_form.addWidget(note)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setPlaceholderText("Technical scanner log")
        self.log.setFixedHeight(LOG_HEIGHT_PX)
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addLayout(filter_bar)
        layout.addWidget(self.tabs)
        layout.addWidget(splitter, 1)
        layout.addWidget(stats_box)
        layout.addWidget(QLabel("Technical log"))
        layout.addWidget(self.log)
        self.setCentralWidget(center)

        status = QStatusBar()
        status.showMessage(
            "Scrape, parse, and display only. Never automates Guild Wars, whispers, or trades."
        )
        self.decltype_badge = SourceStatusIndicator("decltype")
        self.gwtoolbox_badge = SourceStatusIndicator("gwtoolbox")
        status.addPermanentWidget(self.decltype_badge)
        status_gap = QWidget()
        status_gap.setFixedWidth(SOURCE_STATUS_GAP_PX)
        status_gap.setObjectName("source_status_gap")
        status.addPermanentWidget(status_gap)
        status.addPermanentWidget(self.gwtoolbox_badge)
        self.setStatusBar(status)

        scan_action = QAction("Scan Now", self)
        scan_action.setShortcut(QKeySequence("Ctrl+R"))
        scan_action.triggered.connect(self.start_scan)
        self.addAction(scan_action)
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(self.refresh_from_db)
        self.addAction(refresh_action)
        traded_action = QAction("Mark Traded", self)
        traded_action.setShortcut(QKeySequence("Ctrl+T"))
        traded_action.triggered.connect(lambda: self._mark_selected("traded"))
        self.addAction(traded_action)
        dismiss_action = QAction("Dismiss", self)
        dismiss_action.setShortcut(QKeySequence("Ctrl+D"))
        dismiss_action.triggered.connect(lambda: self._mark_selected("dismissed"))
        self.addAction(dismiss_action)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.start_scan)

    def _current_status(self) -> str:
        index = self.tabs.currentIndex()
        if 0 <= index < len(TAB_STATUSES):
            return TAB_STATUSES[index][1]
        return "new"

    def _load_interval_setting(self) -> None:
        seconds = 0
        try:
            with open_db(self.db_path) as conn:
                raw = get_setting(conn, "scan_interval_seconds", "0") or "0"
                seconds = int(raw)
        except (TypeError, ValueError, OSError):
            seconds = 0
        idx = 0
        for i, (_label, value) in enumerate(SCAN_INTERVALS):
            if value == seconds:
                idx = i
                break
        self.interval_combo.blockSignals(True)
        self.interval_combo.setCurrentIndex(idx)
        self.interval_combo.blockSignals(False)
        self._apply_timer(seconds)

    def _load_lookback_setting(self) -> None:
        hours = DEFAULT_MATCH_LOOKBACK_HOURS
        try:
            with open_db(self.db_path) as conn:
                hours = get_match_lookback_hours(conn)
        except OSError:
            hours = DEFAULT_MATCH_LOOKBACK_HOURS
        self.lookback_spin.blockSignals(True)
        self.lookback_spin.setValue(hours)
        self.lookback_spin.blockSignals(False)

    def _on_lookback_changed(self, hours: int) -> None:
        try:
            with open_db(self.db_path) as conn:
                stored = set_match_lookback_hours(conn, hours)
        except OSError as exc:
            self._append_log(f"Could not save lookback: {exc}")
            return
        self._append_log(
            f"Match lookback set to {stored} hours "
            "(rematch from local SQLite; live feeds are not paginated)."
        )

    def _on_interval_changed(self) -> None:
        seconds = int(self.interval_combo.currentData() or 0)
        try:
            with open_db(self.db_path) as conn:
                set_setting(conn, "scan_interval_seconds", str(seconds))
        except OSError as exc:
            self._append_log(f"Could not save interval: {exc}")
        self._apply_timer(seconds)

    def _apply_timer(self, seconds: int) -> None:
        if seconds <= 0:
            self._timer.stop()
        else:
            self._timer.start(seconds * 1000)

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _configure_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setMinimumSectionSize(44)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        compact = {1, 3, 5, 6, 7, 8, 9}
        for index in range(len(COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.ResizeToContents
                if index in compact
                else QHeaderView.ResizeMode.Stretch
            )
            header.setSectionResizeMode(index, mode)
            tip = COLUMN_HEADER_TIPS[index]
            item = self.table.horizontalHeaderItem(index)
            if item is not None:
                item.setToolTip(tip)

    def _set_badge(self, source: str, online: bool | None) -> None:
        widget = self.decltype_badge if source == "decltype" else self.gwtoolbox_badge
        widget.set_state(online)

    def start_scan(self) -> None:
        if self._scan_busy:
            return
        self._scan_busy = True
        self.scan_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("Scanning public JSON…")

        self._thread = QThread()
        self._worker = ScanWorker(self.db_path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self._append_log)
        self._worker.source_state.connect(self._set_badge)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.failed.connect(self._on_scan_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_scan_finished(self, result) -> None:
        self._scan_busy = False
        self.scan_btn.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        persist = getattr(result, "persist", {}) or {}
        n = persist.get("opportunities", len(getattr(result, "opportunities", []) or []))
        self.statusBar().showMessage(
            f"Scan complete. {n} potential opportunities this pass "
            "(chat-price spread, not profit)."
        )
        self.refresh_from_db()

    def _on_scan_failed(self, message: str) -> None:
        self._scan_busy = False
        self.scan_btn.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._append_log(f"Scan failed: {message}")
        self.statusBar().showMessage("Scan failed — see technical log.")
        self.refresh_from_db()

    def refresh_from_db(self) -> None:
        try:
            with open_db(self.db_path) as conn:
                self._rows = list_opportunity_details(conn, self._current_status())
                payload = stats(conn)
        except OSError as exc:
            self._append_log(f"Database error: {exc}")
            self._rows = []
            payload = {
                "opportunities": 0,
                "new": 0,
                "traded": 0,
                "dismissed": 0,
                "scans": 0,
            }
        self.stat_found.setText(f"Found: {payload.get('opportunities', 0)}")
        self.stat_active.setText(f"Active: {payload.get('new', 0)}")
        self.stat_traded.setText(f"Traded: {payload.get('traded', 0)}")
        self.stat_dismissed.setText(f"Dismissed: {payload.get('dismissed', 0)}")
        self.stat_scans.setText(f"Scans: {payload.get('scans', 0)}")
        self._apply_filters()

    def _min_difference(self) -> Decimal | None:
        text = self.min_diff.text().strip().lower().replace(",", "")
        if not text:
            return None
        if text.endswith("k"):
            text = text[:-1].strip()
            try:
                return Decimal(text) * 1000
            except InvalidOperation:
                return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    def _apply_filters(self) -> None:
        source = self.source_filter.currentData() or "all"
        query = self.item_filter.text()
        minimum = self._min_difference()
        visible = [
            row
            for row in self._rows
            if row_matches_filters(
                row, item_query=query, source=source, min_difference=minimum
            )
        ]
        self._fill_table(visible)

    def _fill_table(self, rows: list[dict]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            qty = row.get("quantity")
            unit = row.get("quantity_unit") or ""
            qty_text = f"{qty} {unit}".strip()
            values = [
                (str(row.get("item_canonical") or ""), str(row.get("item_canonical") or "")),
                (qty_text, int(qty or 0)),
                (str(row.get("seller") or ""), str(row.get("seller") or "")),
                (format_gold(row.get("sell_price")), _as_decimal(row.get("sell_price"))),
                (str(row.get("buyer") or ""), str(row.get("buyer") or "")),
                (format_gold(row.get("buy_price")), _as_decimal(row.get("buy_price"))),
                (
                    "+" + format_gold(row.get("potential_difference")),
                    _as_decimal(row.get("potential_difference")),
                ),
                (format_sources(row.get("sources")), format_sources(row.get("sources"))),
                (format_detected(row.get("detected_at_unix_s")), int(row.get("detected_at_unix_s") or 0)),
                (str(row.get("status") or ""), str(row.get("status") or "")),
            ]
            for column, (text, sort_key) in enumerate(values):
                item = NumericTableItem(text)
                item.setData(Qt.ItemDataRole.UserRole, sort_key)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole + 1, row.get("opportunity_key"))
                self.table.setItem(index, column, item)
        self.table.setSortingEnabled(True)
        self._configure_columns()
        if self.table.rowCount():
            self.table.selectRow(0)
        else:
            self.detail.clear()

    def _selected_key(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        first = self.table.item(row, 0)
        if first is None:
            return None
        key = first.data(Qt.ItemDataRole.UserRole + 1)
        return str(key) if key else None

    def _selected_row(self) -> dict | None:
        key = self._selected_key()
        if not key:
            return None
        for row in self._rows:
            if row.get("opportunity_key") == key:
                return row
        return None

    def _show_detail(self) -> None:
        row = self._selected_row()
        if not row:
            self.detail.clear()
            return
        wts_url = SOURCE_HOME_URLS.get(str(row.get("wts_source") or ""), "")
        wtb_url = SOURCE_HOME_URLS.get(str(row.get("wtb_source") or ""), "")
        lines = [
            f"Item: {row.get('item_canonical')}   qty {row.get('quantity')} {row.get('quantity_unit')}",
            f"potential_difference: {format_gold(row.get('potential_difference'))} "
            "(chat-price spread, not guaranteed profit)",
            f"Sources: {format_sources(row.get('sources'))}",
            "",
            "WTS (seller)",
            f"  Player: {row.get('wts_player') or row.get('seller')}",
            f"  Source: {SOURCE_LABELS.get(str(row.get('wts_source') or ''), row.get('wts_source'))}  {wts_url}",
            f"  When: {format_detected(row.get('wts_listing_ts') or row.get('wts_timestamp_unix_s'))}",
            f"  Span: {row.get('wts_span') or '—'}",
            f"  Message: {row.get('wts_message') or '—'}",
            "",
            "WTB (buyer)",
            f"  Player: {row.get('wtb_player') or row.get('buyer')}",
            f"  Source: {SOURCE_LABELS.get(str(row.get('wtb_source') or ''), row.get('wtb_source'))}  {wtb_url}",
            f"  When: {format_detected(row.get('wtb_listing_ts') or row.get('wtb_timestamp_unix_s'))}",
            f"  Span: {row.get('wtb_span') or '—'}",
            f"  Message: {row.get('wtb_message') or '—'}",
            "",
            "Trade by hand in Guild Wars. This app never sends whispers.",
        ]
        self.detail.setPlainText("\n".join(str(line) for line in lines))

    def _mark_selected(self, status: str) -> None:
        key = self._selected_key()
        if not key:
            QMessageBox.information(self, "GWTradeArb", "Select an opportunity first.")
            return
        try:
            with open_db(self.db_path) as conn:
                set_status(conn, key, status, now_unix_s=int(time.time()))
        except (KeyError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "GWTradeArb", str(exc))
            return
        self._append_log(f"Marked {key[:12]}… as {status}")
        self.refresh_from_db()

    def _open_source(self, source: str) -> None:
        url = SOURCE_HOME_URLS.get(source)
        if not url:
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            webbrowser.open(url)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            with open_db(self.db_path) as conn:
                set_setting(conn, "ui_window_width", str(self.width()))
                set_setting(conn, "ui_window_height", str(self.height()))
        except OSError:
            pass
        super().closeEvent(event)


def _as_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def run_gui(db_path: str | Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("GWTradeArb")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow(db_path)
    window.show()
    return app.exec()
