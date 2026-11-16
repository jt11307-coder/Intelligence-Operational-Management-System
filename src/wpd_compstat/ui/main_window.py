"""Desktop shell. Figures come from the database; an empty database stays empty."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wpd_compstat.admin import confirm_profile, confirm_shifts, confirm_source_lists
from wpd_compstat.analysis import significant_incidents
from wpd_compstat.analysis.compare import compare_calls
from wpd_compstat.analysis.dashboard import AWAITING_TEXT, compstat_table, top_call_types
from wpd_compstat.analysis.dashboard import tiles as dashboard_tiles
from wpd_compstat.analysis.trends import developing_patterns
from wpd_compstat.analysis.divisions import division_report
from wpd_compstat.analysis.geo import hotspot_bins, location_points, repeat_streets
from wpd_compstat.analysis.patterns import detect_patterns
from wpd_compstat.analysis.recommend import draft_recommendations
from wpd_compstat.analysis.temporal import daily_counts, peak_hours, hour_counts, response_times, shift_summary
from wpd_compstat.analysis.traffic import weekly_verified_totals
from wpd_compstat.assignments import create_assignment, create_cycle, overdue_assignments, phase_for, transition
from wpd_compstat.backup import create_backup, list_backups
from wpd_compstat.classification.service import confirm_code
from wpd_compstat.db.seed import get_setting
from wpd_compstat.errors import AppError, sanitized_traceback
from wpd_compstat.import_engine.bulk import collect_pdfs, run_import, summary_text
from wpd_compstat.import_engine.call_log import CALL_LOG_PROFILE
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate
from wpd_compstat.quality import quality_summary
from wpd_compstat.reporting.charts import write_daily_chart
from wpd_compstat.reporting import export_csv, export_pdf, export_pptx, export_xlsx
from wpd_compstat.reporting.packet import build_compstat_packet
from wpd_compstat.search import incident_detail, search_incidents
from wpd_compstat.ui.drop_import import DropBox
from wpd_compstat.ui.theme import DARK, LIGHT

NAV = (
    ("Executive Dashboard", "dashboard"),
    ("Daily Briefing", "briefing"),
    ("COMPSTAT", "compstat"),
    ("Crime Analysis", "analysis"),
    ("Traffic Enforcement", "traffic"),
    ("Crash Analysis", "crashes"),
    ("Significant Incidents", "significant"),
    ("Geographic Intelligence", "geo"),
    ("Division Performance", "divisions"),
    ("Operational Assignments", "assignments"),
    ("Reports", "reports"),
    ("Incident Search", "search"),
    ("PDF Import", "import"),
    ("Data Quality", "quality"),
    ("Administration", "admin"),
    ("System Health", "health"),
)


class MainWindow(QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.setWindowTitle("WPD COMPSTAT Intelligence & Operational Management System")
        self.resize(1280, 800)
        self._pages = {}
        self._nav_buttons = {}
        self._build()
        self._apply_theme(self._saved_theme())
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self._check_idle)
        self._timer.start()
        self.show_page("dashboard")

    def _build(self) -> None:
        shell = QWidget()
        outer = QHBoxLayout(shell)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        title = QLabel("WPD COMPSTAT")
        title.setStyleSheet("color: white; font-size: 18px; font-weight: 600; background: transparent;")
        side.addWidget(title)
        for label, key in NAV:
            button = QPushButton(label)
            button.setProperty("class", "nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, name=key: self.show_page(name))
            side.addWidget(button)
            self._nav_buttons[key] = button
        side.addStretch(1)
        self.theme_button = QPushButton("Dark mode")
        self.theme_button.clicked.connect(self._toggle_theme)
        side.addWidget(self.theme_button)
        self.lock_button = QPushButton("Lock")
        self.lock_button.clicked.connect(self._manual_lock)
        side.addWidget(self.lock_button)
        sidebar.setFixedWidth(240)
        self.stack = QStackedWidget()
        builders = {
            "dashboard": self._dashboard,
            "briefing": self._briefing,
            "compstat": self._compstat,
            "analysis": self._analysis,
            "traffic": self._traffic,
            "crashes": self._crashes,
            "significant": self._significant,
            "geo": self._geo,
            "divisions": self._divisions,
            "assignments": self._assignments,
            "reports": self._reports,
            "search": self._search,
            "import": self._import,
            "quality": self._quality,
            "admin": self._admin,
            "health": self._health,
        }
        for key, _label in ((key, label) for label, key in NAV):
            page = builders[key]()
            self._pages[key] = page
            self.stack.addWidget(page)
        outer.addWidget(sidebar)
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        self.statusBar().showMessage("Offline. Official figures use imported records only.")

    def show_page(self, key: str) -> None:
        page = self._pages[key]
        label = next(text for text, name in NAV if name == key)
        self.stack.setCurrentWidget(page)
        for name, button in self._nav_buttons.items():
            button.setChecked(name == key)
        refresh = getattr(page, "refresh_page", None)
        if refresh:
            self.statusBar().showMessage(f"Loading {label}...")
            QApplication.processEvents()
            self._guard(refresh)
        self.statusBar().showMessage(f"Showing {label}. Offline. Official figures use imported records only.")

    def _check_idle(self) -> None:
        try:
            if self.session.timed_out():
                self.session.lock()
                self._manual_lock()
        except Exception:
            self.statusBar().showMessage("The session could not be checked.")

    def _manual_lock(self) -> None:
        if not self.session.locked:
            self.session.lock()
        from wpd_compstat.ui.login import LoginDialog

        dialog = LoginDialog(self.session)
        if not dialog.exec():
            self.close()
            return
        self.show_page("dashboard")

    def _saved_theme(self) -> str:
        path = self.session.paths.ui_preferences
        if not path.exists():
            return "light"
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("theme", "light")
        except json.JSONDecodeError:
            return "light"

    def _apply_theme(self, name: str) -> None:
        self.setStyleSheet(DARK if name == "dark" else LIGHT)
        self.theme_button.setText("Light mode" if name == "dark" else "Dark mode")
        self.session.paths.ui_preferences.write_text(json.dumps({"theme": name}), encoding="utf-8")

    def _toggle_theme(self) -> None:
        current = "dark" if "12171d" in self.styleSheet() else "light"
        self._apply_theme("light" if current == "dark" else "dark")

    def _guard(self, func) -> None:
        try:
            func()
        except AppError as exc:
            QMessageBox.warning(self, "WPD COMPSTAT", str(exc))
        except Exception as exc:
            self.session.logger.error("Unexpected error: %s", sanitized_traceback(exc))
            QMessageBox.warning(
                self,
                "WPD COMPSTAT",
                "Something went wrong on this page, so it may be incomplete. "
                "The technical details (no call details) were written to Logs\\application.log.",
            )

    def _dashboard(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll)
        page = outer
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.addWidget(_page_title("Executive Dashboard"))
        banner = QLabel("No call-log incidents have been imported. Official COMPSTAT figures are not estimates.")
        banner.setObjectName("banner")
        banner.setWordWrap(True)
        page.banner = banner
        layout.addWidget(banner)
        top = QHBoxLayout()
        period = _period_bar()
        page.period = period
        top.addWidget(period, 1)
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._fill_dashboard(page)))
        top.addWidget(button)
        layout.addLayout(top)
        page.period_note = QLabel()
        page.period_note.setObjectName("banner")
        page.period_note.setWordWrap(True)
        layout.addWidget(page.period_note)

        page.compstat_section = _section("COMPSTAT summary")
        layout.addWidget(page.compstat_section)
        page.compstat = _table(["Category", "This week", "Last week", "4-week average", "Change vs last week", "Year to date", "Flag", "Status"])
        layout.addWidget(page.compstat)

        page.patterns_section = _section(
            "Developing patterns",
            "Rule-based flags, not findings. Each line is one flag with its count. Addresses and call details stay in Crime Analysis.",
        )
        layout.addWidget(page.patterns_section)
        page.patterns = QLabel()
        page.patterns.setWordWrap(True)
        page.patterns.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(page.patterns)

        page.tiles_section = _section("This period at a glance")
        layout.addWidget(page.tiles_section)
        page.grid = QGridLayout()
        layout.addLayout(page.grid)

        page.types_section = _section("Top call types this period")
        layout.addWidget(page.types_section)
        page.types = _table(["Call type (IMC name)", "IMC code", "Calls", "Previous equal period", "Change"])
        layout.addWidget(page.types)

        page.compare_section = _section(
            "How this period compares",
            "Every comparison period has the same number of days as this period. A percentage is shown only when the "
            "comparison period has enough calls.",
        )
        layout.addWidget(page.compare_section)
        page.table = _table(["Comparison", "What it compares", "This period", "Comparison period", "Change", "Percent"])
        layout.addWidget(page.table)

        layout.addWidget(_section("Add new CAD PDFs", "Drag the daily CAD call-log PDFs or a folder onto the box, or click it to choose files."))
        page.drop_box = DropBox(self._import_dropped)
        layout.addWidget(page.drop_box)
        layout.addStretch(1)
        page.refresh_page = lambda: self._fill_dashboard(page)
        return page

    def _fill_dashboard(self, page: QWidget) -> None:
        start_text, end_text = page.period.iso()
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        conn = self.session.conn
        count = conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"]
        page.banner.setVisible(count == 0)
        result = dashboard_tiles(conn, start, end)
        period = result["period"]
        page.period_note.setText(period["note"] or "")
        page.period_note.setVisible(bool(period["note"]))
        days = period["days"]

        table = compstat_table(conn, end)
        week_start, week_end = table["week"]
        average_start, average_end = table["average_weeks"]
        page.compstat_section.explanation.setText(
            f"This week means the 7 complete days {week_start} to {week_end}; last week is the 7 days before that. "
            f"The 4-week average is the average week from {average_start} to {average_end}. Year to date runs from "
            f"{table['ytd_start']} to {week_end}. Flag says UP or DOWN when this week is at least double, or at most half, "
            f"the 4-week average and differs by at least {table['support']} calls (the Crime Analysis rule). "
            f"Rows marked \"{AWAITING_TEXT}\" show proposed counts that are not official until you confirm the rule."
        )
        _fill(page.compstat, [
            [
                row["label"], row["this_week"], row["last_week"], _blank(row["four_week_average"]),
                f"{row['change']:+d}", row["ytd"], row["flag"],
                "Counted" if row["status"] == "counted" else AWAITING_TEXT,
            ]
            for row in table["rows"]
        ])
        _fit(page.compstat)

        found = developing_patterns(conn, start, end)
        lines = []
        for title, key in (
            ("Emerging day over day", "emerging"),
            ("Volume flags (at least doubled versus the previous equal period)", "volume"),
            ("Repeat calls at the same address", "repeat"),
        ):
            lines.append(title + ":")
            lines.extend(f"  - {item['sentence']}" for item in found[key])
            if not found[key]:
                lines.append("  - None in this period.")
        page.patterns.setText("\n".join(lines))

        while page.grid.count():
            widget = page.grid.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        page.tiles_section.explanation.setText(
            f"Counts for {period['start']} to {period['end']} ({days} complete days). "
            f"\"Previous\" is the {days} days just before. A call can appear in more than one box."
        )
        for index, tile in enumerate(result["tiles"]):
            page.grid.addWidget(_tile_widget(tile, days), index // 3, index % 3)

        types = top_call_types(conn, start, end)
        page.types_section.explanation.setText(
            f"The most frequent call types in these {days} days, using the official IMC name when the call type is on the "
            f"IMC list. Previous equal period is the {days} days just before."
        )
        _fill(page.types, [
            [
                row["name"] + ("" if row["on_imc_list"] else " (not on the IMC list)"),
                row["code"] or "",
                row["count"],
                _blank(row["previous"]),
                "" if row["change"] is None else f"{row['change']:+d}",
            ]
            for row in types
        ])
        _fit(page.types)

        rows = compare_calls(conn, start, end)
        _fill(page.table, [
            [
                row["label"],
                row["description"],
                row["current"],
                _blank(row["baseline"]),
                _blank(row["absolute_change"]),
                f"{row['percent']:+.1f}%" if row["comparable"] else (row["reason"] or "Not shown"),
            ]
            for row in rows
        ])
        _fit(page.table)

    def _briefing(self) -> QWidget:
        page = self._text_page(
            "Daily Briefing",
            "A written briefing built from imported records for the dates you choose.",
            "Choose the dates above, then press \"Generate briefing\". Each briefing is recorded in the report history.",
        )
        button = QPushButton("Generate briefing")
        button.clicked.connect(lambda: self._guard(lambda: self._run_briefing(page)))
        page.actions.addWidget(button)
        return page

    def _run_briefing(self, page) -> None:
        start, end = page.period.iso()
        packet = build_compstat_packet(self.session, date.fromisoformat(start), date.fromisoformat(end))
        page.output.setPlainText(_packet_text(packet))

    def _compstat(self) -> QWidget:
        page = self._text_page(
            "COMPSTAT",
            "Starts a 14-day COMPSTAT cycle. Unresolved assignments carry forward. Completion is not effectiveness.",
            "Choose the start date above, then press \"Start 14-day cycle\".",
        )
        button = QPushButton("Start 14-day cycle")
        button.clicked.connect(lambda: self._guard(lambda: self._start_cycle(page)))
        page.actions.addWidget(button)
        return page

    def _start_cycle(self, page) -> None:
        start, _end = page.period.iso()
        cycle_id = create_cycle(self.session, date.fromisoformat(start))
        row = self.session.conn.execute("SELECT * FROM compstat_cycles WHERE id = ?", (cycle_id,)).fetchone()
        phase = phase_for(date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"]), date.fromisoformat(start))
        overdue = overdue_assignments(self.session.conn, start)
        page.output.setPlainText(
            f"Cycle {cycle_id}: {row['start_date']} through {row['end_date']}. Phase on the start date: {phase}.\n"
            f"Overdue unresolved assignments: {len(overdue)}."
        )

    def _analysis(self) -> QWidget:
        page = self._text_page(
            "Crime Analysis",
            "Every classifier category and every uploaded call type can flag when its count at least doubles and rises by at least 3. "
            "A repeat flag is the same call type at one address within 7 calendar days.",
            "Choose the dates above, then press \"Run analysis\". It saves the flags it finds and can take several seconds.",
        )
        button = QPushButton("Run analysis")
        button.clicked.connect(lambda: self._guard(lambda: self._run_analysis(page)))
        page.actions.addWidget(button)
        page.chart = QLabel()
        page.layout().addWidget(page.chart)
        return page

    def _run_analysis(self, page) -> None:
        start, end = page.period.iso()
        result = detect_patterns(self.session, start, end)
        created = draft_recommendations(self.session)
        counts = hour_counts(self.session.conn, start, end)
        peaks = peak_hours(counts)
        daily = daily_counts(self.session.conn, start, end)
        chart = write_daily_chart(daily, self.session.paths.working / "daily-calls.png")
        page.chart.setPixmap(QPixmap(str(chart)).scaledToWidth(640, Qt.TransformationMode.SmoothTransformation))
        lines = result["notes"] + [f"Patterns stored: {len(result['patterns'])}.", f"Draft recommendations created: {created}."]
        if result["patterns"]:
            placeholders = ",".join("?" for _ in result["patterns"])
            rows = self.session.conn.execute(
                f"SELECT name, explanation FROM patterns WHERE id IN ({placeholders}) ORDER BY name",
                tuple(result["patterns"]),
            ).fetchall()
            lines.extend(f"{row['name']}: {row['explanation']}" for row in rows)
        lines.append(f"Peak hours: {peaks.get('peaks') or peaks.get('reason')}.")
        page.output.setPlainText("\n".join(lines))

    def _traffic(self) -> QWidget:
        page = self._text_page(
            "Traffic Enforcement",
            "Weekly verified violations from imported traffic exports. Citation references are not verified violations. "
            "The weekly benchmark is configurable and defaults to 200.",
        )
        button = QPushButton("Show weekly verified totals")
        button.clicked.connect(lambda: self._guard(lambda: self._show_traffic(page)))
        page.actions.addWidget(button)
        page.refresh_page = lambda: self._show_traffic(page)
        return page

    def _show_traffic(self, page) -> None:
        start, end = page.period.iso()
        goal = int(get_setting(self.session.conn, "violation_weekly_goal", 200))
        rows = weekly_verified_totals(self.session.conn, start, end, goal)
        if not rows:
            page.output.setPlainText(
                "No traffic-export rows fall in this period. Verified violations come only from a traffic export, "
                "not from the CAD call-log PDFs."
            )
            return
        page.output.setPlainText("\n".join(
            f"{row['week']}: verified {row['verified_violations']} of {row['goal']}; "
            f"citation references {row['citation_references']} (not included)."
            for row in rows
        ))

    def _crashes(self) -> QWidget:
        page = self._text_page("Crash Analysis", "Accident counts for the dates you choose, with accident report numbers.")
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_crashes(page)))
        page.actions.addWidget(button)
        page.refresh_page = lambda: self._show_crashes(page)
        return page

    def _show_crashes(self, page) -> None:
        start, end = page.period.iso()
        result = dashboard_tiles(self.session.conn, date.fromisoformat(start), date.fromisoformat(end))
        wanted = {"accident_report", "accidents", "injury_accidents"}
        lines = [result["period"]["note"]] if result["period"]["note"] else []
        for tile in result["tiles"]:
            if tile["key"] in wanted:
                lines.append(f"{tile['label']}: {_tile_value(tile)}. {tile['description']}")
        page.output.setPlainText("\n\n".join(lines) or "No calls are imported for these dates.")

    def _significant(self) -> QWidget:
        page = self._text_page("Significant Incidents", "Only officially counted significant-event categories are listed.")
        button = QPushButton("Show the list")
        button.clicked.connect(lambda: self._guard(lambda: self._show_significant(page, open_list=True)))
        page.actions.addWidget(button)
        page.refresh_page = lambda: self._show_significant(page)
        return page

    def _show_significant(self, page, open_list: bool = False) -> None:
        start, end = page.period.iso()
        metric = significant_incidents(self.session.conn, start, end)
        if not metric.incident_ids:
            page.output.setPlainText(
                "No officially counted significant incidents in this period. Significant categories count only after "
                "you confirm their rules or accept a classification."
            )
            return
        page.output.setPlainText(f"Significant incidents: {metric.value}. Press \"Show the list\" to open them.")
        if open_list:
            self._show_incidents(metric.label, metric.incident_ids)

    def _geo(self) -> QWidget:
        page = self._text_page(
            "Geographic Intelligence", "Streets with the most calls in the dates you choose. No address is sent to a mapping service."
        )
        button = QPushButton("Refresh locations")
        button.clicked.connect(lambda: self._guard(lambda: self._show_geo(page)))
        page.actions.addWidget(button)
        page.refresh_page = lambda: self._show_geo(page)
        return page

    def _show_geo(self, page) -> None:
        start, end = page.period.iso()
        points = location_points(self.session.conn, start, end)
        bins = hotspot_bins(points["exact"])
        streets = repeat_streets(self.session.conn, start, end)
        page.output.setPlainText(
            f"Exact points: {len(points['exact'])}. Approximate points, excluded from hotspots: {len(points['approximate'])}.\n"
            f"Hotspot bins: {len(bins)}.\n"
            + "\n".join(f"{row['street']}: {row['incidents']}" for row in streets[:20])
            + ("\nNo street locations are stored." if not streets else "")
        )

    def _divisions(self) -> QWidget:
        page = self._text_page("Division Performance", "Workload for one unit in the dates you choose. Totals are workload, not a performance finding.")
        page.division = QComboBox()
        page.actions.addWidget(page.division, 1)
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_division(page)))
        page.actions.addWidget(button)

        def refresh_page() -> None:
            page.division.clear()
            for row in self.session.conn.execute("SELECT id, name, confirmed FROM divisions ORDER BY name"):
                suffix = "" if row["confirmed"] else " (unconfirmed)"
                page.division.addItem(row["name"] + suffix, row["id"])
            self._show_division(page)

        page.refresh_page = refresh_page
        return page

    def _show_division(self, page) -> None:
        start, end = page.period.iso()
        division_id = page.division.currentData()
        if division_id is None:
            page.output.setPlainText("No organizational units are configured.")
            return
        report = division_report(self.session.conn, int(division_id), start, end)
        lines = [
            report["qualification"],
            f"Incidents touching this unit: {report['incident_count']}.",
            report["rate_note"],
        ]
        for row in report["officer_contributions"]:
            lines.append(
                f"{row['officer']}: {row['incidents']} incidents, {row['assignment_rows']} officer-assignment rows."
            )
        page.output.setPlainText("\n".join(lines))

    def _assignments(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_page_title("Operational Assignments"))
        form = QFormLayout()
        page.title = QLineEdit()
        page.description = QLineEdit()
        form.addRow("Title", page.title)
        form.addRow("Description", page.description)
        layout.addLayout(form)
        create = QPushButton("Create proposed assignment")
        create.clicked.connect(lambda: self._guard(lambda: self._create_assignment(page)))
        layout.addWidget(create)
        page.table = _table(["Action", "Title", "Status", "Due"])
        layout.addWidget(page.table)
        page.refresh_page = lambda: self._load_assignments(page)
        return page

    def _create_assignment(self, page) -> None:
        create_assignment(self.session, page.title.text(), page.description.text())
        self._load_assignments(page)

    def _load_assignments(self, page) -> None:
        rows = self.session.conn.execute(
            "SELECT action_number, title, status, due_date FROM assignments ORDER BY action_number"
        ).fetchall()
        _fill(page.table, [[row["action_number"], row["title"], row["status"], row["due_date"] or ""] for row in rows])

    def _reports(self) -> QWidget:
        page = self._text_page(
            "Reports",
            "Exports a COMPSTAT packet. Exports include the generation time, period, and qualifications.",
            "Choose the dates above, then press PDF, Excel, CSV, or PowerPoint. The file is saved in the Reports folder.",
        )
        for label, kind in (("PDF", "pdf"), ("Excel", "xlsx"), ("CSV", "csv"), ("PowerPoint", "pptx")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, export_kind=kind, target=page: self._guard(lambda: self._export(target, export_kind)))
            page.actions.addWidget(button)
        return page

    def _export(self, page, kind: str) -> None:
        start, end = page.period.iso()
        packet = build_compstat_packet(self.session, date.fromisoformat(start), date.fromisoformat(end))
        folder = self.session.paths.reports
        stamp = self.session.stamp().replace(":", "")
        path = folder / f"compstat-{stamp}.{kind if kind != 'xlsx' else 'xlsx'}"
        if kind == "pdf":
            export_pdf(packet, path)
        elif kind == "xlsx":
            export_xlsx(packet, path)
        elif kind == "csv":
            export_csv(packet, path)
        else:
            export_pptx(packet, path.with_suffix(".pptx"))
            path = path.with_suffix(".pptx")
        page.output.setPlainText(f"Wrote {path}")

    def _search(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_page_title("Incident Search"))
        layout.addWidget(QLabel("Type a CAD number, a street, or narrative words, then press Search. Double-click a result to open it."))
        form = QFormLayout()
        page.cad = QLineEdit()
        page.street = QLineEdit()
        page.narrative = QLineEdit()
        form.addRow("CAD number", page.cad)
        form.addRow("Street", page.street)
        form.addRow("Narrative words", page.narrative)
        layout.addLayout(form)
        button = QPushButton("Search")
        button.clicked.connect(lambda: self._guard(lambda: self._run_search(page)))
        layout.addWidget(button)
        page.table = _table(["CAD", "Date", "Type", "Disposition", "Address"])
        page.table.itemDoubleClicked.connect(lambda _item: self._open_selected(page))
        layout.addWidget(page.table)
        page.results = []
        return page

    def _run_search(self, page) -> None:
        filters = {}
        if page.cad.text().strip():
            filters["cad_number"] = page.cad.text().strip()
        if page.street.text().strip():
            filters["street"] = page.street.text().strip()
        if page.narrative.text().strip():
            filters["narrative"] = page.narrative.text().strip()
        page.results = search_incidents(self.session, filters)
        _fill(page.table, [
            [row["cad_number"], row["event_date"] or "", row["call_type"] or "", row["disposition"] or "", row["raw_address"] or ""]
            for row in page.results
        ])

    def _open_selected(self, page) -> None:
        row = page.table.currentRow()
        if row < 0 or row >= len(page.results):
            return
        detail = incident_detail(self.session, page.results[row]["id"])
        self._show_detail(detail)

    def _import(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_page_title("PDF Import"))
        note = QLabel(
            "Imports use the active agency-confirmed CAD profile. Without one, the PDF is stored and no incidents are guessed."
        )
        note.setObjectName("banner")
        note.setWordWrap(True)
        layout.addWidget(note)
        page.drop_box = DropBox(self._import_dropped)
        layout.addWidget(page.drop_box)
        page.files = []
        page.list_label = QLabel("No files selected.")
        page.list_label.setWordWrap(True)
        layout.addWidget(page.list_label)
        choose = QPushButton("Select PDFs")
        choose.clicked.connect(lambda: self._choose_pdfs(page))
        layout.addWidget(choose)
        folder = QPushButton("Select a folder of PDFs (includes subfolders)")
        folder.clicked.connect(lambda: self._choose_folder(page))
        layout.addWidget(folder)
        run = QPushButton("Extract, validate, and commit")
        run.clicked.connect(lambda: self._guard(lambda: self._run_import(page)))
        layout.addWidget(run)
        page.output = QTextEdit()
        page.output.setReadOnly(True)
        page.output.setPlaceholderText("The counts from your last import appear here: new calls, updated calls, duplicates, and conflicts.")
        layout.addWidget(page.output)
        return page

    def _choose_pdfs(self, page) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "Select CAD PDFs", "", "PDF (*.pdf)")
        page.files = paths
        page.list_label.setText("\n".join(paths) if paths else "No files selected.")

    def _choose_folder(self, page) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder of CAD PDFs")
        if not folder:
            return
        page.files = [str(path) for path in sorted(Path(folder).rglob("*")) if path.suffix.casefold() == ".pdf"]
        page.list_label.setText("\n".join(page.files) if page.files else "No PDFs were found in that folder.")

    def _run_import(self, page) -> None:
        if not page.files:
            raise AppError("Select at least one PDF.")
        batch_id = stage_select(self.session, page.files)
        extracted = stage_extract(self.session, batch_id)
        validated = stage_validate(self.session, batch_id)
        committed = stage_commit(self.session, batch_id)
        page.output.setPlainText(json.dumps({"extract": extracted, "validate": validated, "commit": committed}, indent=2))

    def _import_dropped(self, paths: list[str]) -> dict | None:
        pdfs, rejected = collect_pdfs(paths)
        if not pdfs:
            QMessageBox.warning(
                self,
                "WPD COMPSTAT",
                "Only PDF files can be imported. Nothing was imported.\n\nNot PDFs: " + (", ".join(rejected) or "none"),
            )
            return None
        dialog = QProgressDialog("Starting the import...", "", 0, 1, self)
        dialog.setWindowTitle("Importing CAD PDFs")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()

        def progress(text: str, done: int, total: int) -> None:
            dialog.setMaximum(max(total, 1))
            dialog.setValue(done)
            dialog.setLabelText(text)
            QApplication.processEvents()

        try:
            totals = run_import(self.session, pdfs, progress)
        except AppError as exc:
            QMessageBox.warning(self, "WPD COMPSTAT", f"The import stopped and that batch was rolled back.\n\n{exc}")
            return None
        finally:
            dialog.close()
        text = summary_text(totals, rejected)
        self._pages["import"].output.setPlainText(text)
        self._guard(lambda: self._fill_dashboard(self._pages["dashboard"]))
        QMessageBox.information(self, "Import finished", text)
        return totals

    def _quality(self) -> QWidget:
        page = self._text_page("Data Quality", "Counts of records that need review. Corrections keep the prior value in the field history.")
        page.period.hide()
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_quality(page)))
        page.actions.addWidget(button)
        page.refresh_page = lambda: self._show_quality(page)
        return page

    def _show_quality(self, page) -> None:
        summary = quality_summary(self.session)
        page.output.setPlainText("\n".join(f"{key}: {value}" for key, value in summary.items()))

    def _admin(self) -> QWidget:
        page = self._text_page(
            "Administration",
            "Agency codes have no built-in meaning. Confirm a CAD profile only after checking it against a real export.",
        )
        page.period.hide()
        column = QVBoxLayout()
        page.actions.addLayout(column, 1)
        call_log = QPushButton("Confirm the Warwick CAD call-log profile (Selective Search / Dispatch Log)")
        call_log.clicked.connect(lambda: self._guard(self._confirm_call_log_profile))
        column.addWidget(call_log)
        profile = QPushButton("Confirm the generic labeled profile")
        profile.clicked.connect(lambda: self._guard(self._confirm_generic_profile))
        column.addWidget(profile)
        sources = QPushButton("Confirm starter call-source lists")
        sources.clicked.connect(lambda: self._guard(self._confirm_sources))
        column.addWidget(sources)
        shifts = QPushButton("Confirm the placeholder shift hours")
        shifts.clicked.connect(lambda: self._guard(self._confirm_shifts))
        column.addWidget(shifts)
        page.refresh_page = lambda: self._show_admin(page)
        return page

    def _show_admin(self, page) -> None:
        conn = self.session.conn
        rules = conn.execute(
            "SELECT confirmation, COUNT(*) AS n FROM classification_rules GROUP BY confirmation ORDER BY confirmation"
        ).fetchall()
        codes = conn.execute("SELECT code, status FROM agency_codes ORDER BY code").fetchall()
        profile = get_setting(conn, "active_profile_id", None)
        lines = [f"Active CAD profile: {profile or 'none confirmed'}."]
        lines.append(
            "Call-type rules: "
            + (", ".join(f"{row['n']} {row['confirmation'].replace('_', ' ')}" for row in rules) or "none")
            + ". Categories from unconfirmed rules show on the dashboard as \"awaiting your rule confirmation\"."
        )
        lines.append("Agency codes: " + (", ".join(f"{row['code']} ({row['status']})" for row in codes) or "none") + ".")
        page.output.setPlainText("\n\n".join(lines))

    def _confirm_call_log_profile(self) -> None:
        answer = QMessageBox.question(
            self,
            "WPD COMPSTAT",
            "Make the Warwick CAD call-log layout the active confirmed import profile?\n\n"
            "Confirm only after checking that imported calls match the printed call log.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        confirm_profile(self.session, CALL_LOG_PROFILE["id"])
        QMessageBox.information(self, "WPD COMPSTAT", "The Warwick CAD call-log profile is now the active confirmed profile.")

    def _confirm_generic_profile(self) -> None:
        confirm_profile(self.session, "generic-labeled-v1")
        QMessageBox.information(self, "WPD COMPSTAT", "The generic labeled profile is now the active confirmed profile.")

    def _confirm_sources(self) -> None:
        confirm_source_lists(
            self.session,
            get_setting(self.session.conn, "officer_initiated_sources", []),
            get_setting(self.session.conn, "citizen_sources", []),
        )

    def _confirm_shifts(self) -> None:
        confirm_shifts(self.session, get_setting(self.session.conn, "shifts", []))

    def _health(self) -> QWidget:
        page = self._text_page("System Health", "Data-quality counts and the backup list. Backups on this drive do not protect against loss of the drive.")
        page.period.hide()
        backup = QPushButton("Create backup")
        backup.clicked.connect(lambda: self._guard(lambda: self._backup(page)))
        page.actions.addWidget(backup)
        page.refresh_page = lambda: self._show_health(page)
        return page

    def _backup(self, page) -> None:
        result = create_backup(self.session, "Manual backup", "manual")
        page.output.setPlainText(json.dumps(result, indent=2))

    def _show_health(self, page) -> None:
        summary = quality_summary(self.session) if _can(self.session, "data_quality") else {}
        backups = list_backups(self.session) if _can(self.session, "backup") else []
        page.output.setPlainText(json.dumps({"quality": summary, "backups": backups}, default=str, indent=2))

    def _show_incidents(self, title: str, ids: list[int]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        table = _table(["CAD", "Date", "Type", "Disposition"])
        if not ids:
            layout.addWidget(QLabel("No supporting incidents."))
        else:
            rows = self.session.conn.execute(
                f"SELECT id, cad_number, event_date, call_type, disposition FROM incidents WHERE id IN ({','.join('?' for _ in ids)})",
                tuple(ids),
            ).fetchall()
            _fill(table, [[row["cad_number"], row["event_date"] or "", row["call_type"] or "", row["disposition"] or ""] for row in rows])
            table.itemDoubleClicked.connect(
                lambda _item, records=list(rows): self._show_detail(incident_detail(self.session, records[table.currentRow()]["id"]))
            )
        layout.addWidget(table)
        dialog.resize(720, 420)
        dialog.exec()

    def _show_detail(self, detail: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(detail["cad_number"])
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(detail, indent=2, default=str))
        layout.addWidget(text)
        dialog.resize(760, 560)
        dialog.exec()

    def _text_page(self, title: str, subtitle: str, hint: str = "") -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_page_title(title))
        note = QLabel(subtitle)
        note.setWordWrap(True)
        layout.addWidget(note)
        period = _period_bar()
        page.period = period
        layout.addWidget(period)
        page.actions = QHBoxLayout()
        layout.addLayout(page.actions)
        page.output = QTextEdit()
        page.output.setReadOnly(True)
        page.output.setPlaceholderText(hint)
        layout.addWidget(page.output)
        return page


def _page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("pageTitle")
    return label


def _section(text: str, explanation: str = "") -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 12, 0, 0)
    heading = QLabel(text)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    widget.explanation = QLabel(explanation)
    widget.explanation.setWordWrap(True)
    widget.explanation.setObjectName("explanation")
    layout.addWidget(widget.explanation)
    return widget


def _period_bar() -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    start = QDateEdit()
    end = QDateEdit()
    for control in (start, end):
        control.setCalendarPopup(True)
        control.setDisplayFormat("yyyy-MM-dd")
    today = QDate.currentDate()
    end.setDate(today)
    start.setDate(today.addDays(-13))
    layout.addWidget(QLabel("From"))
    layout.addWidget(start)
    layout.addWidget(QLabel("through"))
    layout.addWidget(end)
    layout.addStretch(1)

    def iso() -> tuple[str, str]:
        return start.date().toString("yyyy-MM-dd"), end.date().toString("yyyy-MM-dd")

    widget.iso = iso
    return widget


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    return table


def _fill(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            table.setItem(row_index, column, QTableWidgetItem("" if value is None else str(value)))


def _tile_value(tile: dict) -> str:
    if tile["status"] == "awaiting":
        return f"{tile['value']} proposed ({AWAITING_TEXT.lower()})"
    return str(tile["value"])


def _tile_widget(tile: dict, days: int) -> QFrame:
    frame = QFrame()
    frame.setObjectName("tile")
    frame.setProperty("awaiting", tile["status"] == "awaiting")
    layout = QVBoxLayout(frame)
    title = QLabel(tile["label"])
    title.setObjectName("tileTitle")
    layout.addWidget(title)
    value = QLabel(str(tile["value"]))
    value.setObjectName("tileValue")
    layout.addWidget(value)
    if tile["status"] == "awaiting":
        status = QLabel(f"{AWAITING_TEXT}. This is the proposed count, not an official count.")
        status.setObjectName("tileAwaiting")
        status.setWordWrap(True)
        layout.addWidget(status)
    description = QLabel(tile["description"])
    description.setWordWrap(True)
    description.setObjectName("explanation")
    layout.addWidget(description)
    if tile.get("previous") is not None:
        change = tile["value"] - tile["previous"]
        layout.addWidget(QLabel(f"Previous {days} days: {tile['previous']} ({change:+d})"))
    return frame


def _fit(table: QTableWidget) -> None:
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    table.resizeRowsToContents()
    height = (
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().length()
        + table.frameWidth() * 2
        + table.horizontalScrollBar().sizeHint().height()
    )
    table.setMinimumHeight(min(height, 640))
    table.setMaximumHeight(min(height, 640))


def _blank(value) -> str:
    return "" if value is None else str(value)


def _packet_text(packet) -> str:
    lines = [packet.title, packet.period, packet.generated_at, ""]
    lines.extend(packet.qualifications)
    for section in packet.sections:
        lines.append("")
        lines.append(section.title)
        lines.extend(section.prose)
    return "\n".join(lines)


def _can(session, permission: str) -> bool:
    from wpd_compstat.security.permissions import has_permission

    return session.user is not None and has_permission(session.user["role"], permission)
