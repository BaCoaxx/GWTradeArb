"""Main window: opportunities table, scan controls, stats, and technical log."""

from __future__ import annotations

import sys
import time
import webbrowser
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
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
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
    "Quantity",
    "Seller",
    "Sell Price",
    "Buyer",
    "Buy Price",
    "Potential Difference",
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
        width, height = 1100, 720
        try:
            with open_db(self.db_path) as conn:
                width = int(get_setting(conn, "ui_window_width", str(width)) or width)
                height = int(get_setting(conn, "ui_window_height", str(height)) or height)
        except (TypeError, ValueError, OSError):
            pass
        self.resize(max(800, width), max(560, height))

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
        self.lookback_spin = QSpinBox()
        self.lookback_spin.setRange(MIN_MATCH_LOOKBACK_HOURS, MAX_MATCH_LOOKBACK_HOURS)
        self.lookback_spin.setValue(DEFAULT_MATCH_LOOKBACK_HOURS)
        self.lookback_spin.setSuffix(" hours")
        self.lookback_spin.setToolTip(
            "Rematch local SQLite listings whose chat timestamp is within this "
            "many hours. Default 12; longer windows are allowed. Live APIs are "
            "not paginated, so older rows come from history already stored here."
        )
        self.lookback_spin.setMinimumWidth(120)
        self.lookback_spin.valueChanged.connect(self._on_lookback_changed)
        toolbar.addWidget(self.lookback_spin)

        toolbar.addSeparator()
        self.decltype_badge = QLabel("Decltype: —")
        self.gwtoolbox_badge = QLabel("GWToolbox: —")
        toolbar.addWidget(self.decltype_badge)
        toolbar.addWidget(self.gwtoolbox_badge)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(160)
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
        self.min_diff.setPlaceholderText("Min potential_difference")
        self.min_diff.setMaximumWidth(180)
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

        self.tabs = QTabWidget()
        for title, _status in TAB_STATUSES:
            self.tabs.addTab(QWidget(), title)
        self.tabs.currentChanged.connect(self.refresh_from_db)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_detail)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
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
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        stats_box = QGroupBox("Statistics")
        stats_form = QHBoxLayout(stats_box)
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

        center = QWidget()
        layout = QVBoxLayout(center)
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

    def _set_badge(self, source: str, online: bool | None) -> None:
        label = SOURCE_LABELS.get(source, source)
        widget = self.decltype_badge if source == "decltype" else self.gwtoolbox_badge
        if online is None:
            widget.setText(f"{label}: —")
        elif online:
            widget.setText(f"{label}: Online")
        else:
            widget.setText(f"{label}: Offline")

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
    window = MainWindow(db_path)
    window.show()
    return app.exec()
