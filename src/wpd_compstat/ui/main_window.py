"""Desktop shell. Figures come from the database; an empty database stays empty."""

from __future__ import annotations

import json
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wpd_compstat.admin import confirm_profile, confirm_shifts, confirm_source_lists
from wpd_compstat.analysis import dashboard_metrics
from wpd_compstat.analysis.compare import compare_calls
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
from wpd_compstat.errors import AppError
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate
from wpd_compstat.quality import quality_summary
from wpd_compstat.reporting.charts import write_daily_chart
from wpd_compstat.reporting import export_csv, export_pdf, export_pptx, export_xlsx
from wpd_compstat.reporting.packet import build_compstat_packet
from wpd_compstat.search import incident_detail, search_incidents
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
        self.stack.setCurrentWidget(page)
        for name, button in self._nav_buttons.items():
            button.setChecked(name == key)
        refresh = getattr(page, "refresh_page", None)
        if refresh:
            try:
                refresh()
            except AppError as exc:
                QMessageBox.warning(self, "WPD COMPSTAT", str(exc))

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

    def _dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Executive Dashboard"))
        banner = QLabel(
            "No call-log incidents have been imported. Official COMPSTAT figures are not estimates."
        )
        banner.setObjectName("banner")
        banner.setWordWrap(True)
        page.banner = banner
        layout.addWidget(banner)
        period = _period_bar()
        page.period = period
        layout.addWidget(period)
        grid = QGridLayout()
        page.grid = grid
        layout.addLayout(grid)
        page.table = _table(["Comparison", "Current", "Baseline", "Absolute change", "Percent"])
        layout.addWidget(page.table)
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._fill_dashboard(page)))
        layout.addWidget(button)

        def refresh_page() -> None:
            self._fill_dashboard(page)

        page.refresh_page = refresh_page
        return page

    def _fill_dashboard(self, page: QWidget) -> None:
        start, end = page.period.iso()
        count = self.session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"]
        page.banner.setVisible(count == 0)
        while page.grid.count():
            item = page.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        metrics = dashboard_metrics(self.session.conn, start, end)
        for index, metric in enumerate(metrics):
            button = QPushButton(_metric_text(metric))
            button.setEnabled(metric.available)
            button.clicked.connect(lambda _checked=False, item=metric: self._show_incidents(item.label, item.incident_ids))
            page.grid.addWidget(button, index // 3, index % 3)
        rows = compare_calls(self.session.conn, date.fromisoformat(start), date.fromisoformat(end))
        _fill(page.table, [
            [
                row["label"],
                _blank(row["current"]),
                _blank(row["baseline"]),
                _blank(row["absolute_change"]),
                _blank(row["percent"]) if row["comparable"] else "Not shown",
            ]
            for row in rows
        ])

    def _briefing(self) -> QWidget:
        page = self._text_page("Daily briefing", "Generate a briefing from imported records.")
        button = QPushButton("Generate briefing")
        button.clicked.connect(lambda: self._guard(lambda: self._run_briefing(page)))
        page.layout().addWidget(button)
        return page

    def _run_briefing(self, page) -> None:
        start, end = page.period.iso()
        packet = build_compstat_packet(self.session, date.fromisoformat(start), date.fromisoformat(end))
        page.output.setPlainText(_packet_text(packet))

    def _compstat(self) -> QWidget:
        page = self._text_page("COMPSTAT cycle", "Unresolved assignments carry forward. Completion is not effectiveness.")
        button = QPushButton("Start 14-day cycle")
        button.clicked.connect(lambda: self._guard(lambda: self._start_cycle(page)))
        page.layout().addWidget(button)
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
        page = self._text_page("Crime analysis", "Patterns use official counts and repeat-call locations.")
        button = QPushButton("Run analysis")
        button.clicked.connect(lambda: self._guard(lambda: self._run_analysis(page)))
        page.layout().addWidget(button)
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
        lines.append(f"Peak hours: {peaks.get('peaks') or peaks.get('reason')}.")
        page.output.setPlainText("\n".join(lines))

    def _traffic(self) -> QWidget:
        page = self._text_page(
            "Traffic enforcement",
            "Citation references are not verified violations. The weekly benchmark is configurable and defaults to 200.",
        )
        button = QPushButton("Show weekly verified totals")
        button.clicked.connect(lambda: self._guard(lambda: self._show_traffic(page)))
        page.layout().addWidget(button)
        return page

    def _show_traffic(self, page) -> None:
        start, end = page.period.iso()
        goal = int(get_setting(self.session.conn, "violation_weekly_goal", 200))
        rows = weekly_verified_totals(self.session.conn, start, end, goal)
        if not rows:
            page.output.setPlainText("No traffic-export rows fall in this period.")
            return
        page.output.setPlainText("\n".join(
            f"{row['week']}: verified {row['verified_violations']} of {row['goal']}; "
            f"citation references {row['citation_references']} (not included)."
            for row in rows
        ))

    def _crashes(self) -> QWidget:
        page = self._text_page("Crash analysis", "Accident totals use officially counted classifications only.")
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_crashes(page)))
        page.layout().addWidget(button)
        page.refresh_page = lambda: self._show_crashes(page)
        return page

    def _show_crashes(self, page) -> None:
        start, end = page.period.iso()
        metrics = {item.metric_id: item for item in dashboard_metrics(self.session.conn, start, end)}
        page.output.setPlainText(
            f"Accidents: {metrics['accidents'].value}.\n"
            f"Injury accidents: {metrics['injury_accidents'].value}.\n"
            "Unconfirmed starter rules are not included."
        )

    def _significant(self) -> QWidget:
        page = self._text_page("Significant incidents", "Only officially counted significant-event categories are listed.")
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_significant(page)))
        page.layout().addWidget(button)
        return page

    def _show_significant(self, page) -> None:
        start, end = page.period.iso()
        metric = next(item for item in dashboard_metrics(self.session.conn, start, end) if item.metric_id == "significant_incidents")
        if not metric.incident_ids:
            page.output.setPlainText("No officially counted significant incidents in this period.")
            return
        self._show_incidents(metric.label, metric.incident_ids)
        page.output.setPlainText(f"Significant incidents: {metric.value}.")

    def _geo(self) -> QWidget:
        page = self._text_page("Geographic intelligence", "No address is sent to a mapping service.")
        button = QPushButton("Refresh locations")
        button.clicked.connect(lambda: self._guard(lambda: self._show_geo(page)))
        page.layout().addWidget(button)
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
        page = self._text_page("Division performance", "Totals are workload, not a performance finding.")
        page.division = QComboBox()
        page.layout().insertWidget(2, page.division)
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_division(page)))
        page.layout().addWidget(button)

        def refresh_page() -> None:
            page.division.clear()
            for row in self.session.conn.execute("SELECT id, name, confirmed FROM divisions ORDER BY name"):
                suffix = "" if row["confirmed"] else " (unconfirmed)"
                page.division.addItem(row["name"] + suffix, row["id"])

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
        layout.addWidget(QLabel("Operational assignments"))
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
        page = self._text_page("Reports", "Exports include the generation time, period, and qualifications.")
        row = QHBoxLayout()
        for label, kind in (("PDF", "pdf"), ("Excel", "xlsx"), ("CSV", "csv"), ("PowerPoint", "pptx")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, export_kind=kind, target=page: self._guard(lambda: self._export(target, export_kind)))
            row.addWidget(button)
        page.layout().addLayout(row)
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
        layout.addWidget(QLabel("Incident search"))
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
        layout.addWidget(QLabel("PDF import"))
        note = QLabel(
            "Imports use the active agency-confirmed CAD profile. Without one, the PDF is stored and no incidents are guessed."
        )
        note.setObjectName("banner")
        note.setWordWrap(True)
        layout.addWidget(note)
        page.files = []
        page.list_label = QLabel("No files selected.")
        page.list_label.setWordWrap(True)
        layout.addWidget(page.list_label)
        choose = QPushButton("Select PDFs")
        choose.clicked.connect(lambda: self._choose_pdfs(page))
        layout.addWidget(choose)
        run = QPushButton("Extract, validate, and commit")
        run.clicked.connect(lambda: self._guard(lambda: self._run_import(page)))
        layout.addWidget(run)
        page.output = QTextEdit()
        page.output.setReadOnly(True)
        layout.addWidget(page.output)
        return page

    def _choose_pdfs(self, page) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "Select CAD PDFs", "", "PDF (*.pdf)")
        page.files = paths
        page.list_label.setText("\n".join(paths) if paths else "No files selected.")

    def _run_import(self, page) -> None:
        if not page.files:
            raise AppError("Select at least one PDF.")
        batch_id = stage_select(self.session, page.files)
        extracted = stage_extract(self.session, batch_id)
        validated = stage_validate(self.session, batch_id)
        committed = stage_commit(self.session, batch_id)
        page.output.setPlainText(json.dumps({"extract": extracted, "validate": validated, "commit": committed}, indent=2))

    def _quality(self) -> QWidget:
        page = self._text_page("Data quality", "Corrections keep the prior value in the field history.")
        button = QPushButton("Refresh")
        button.clicked.connect(lambda: self._guard(lambda: self._show_quality(page)))
        page.layout().addWidget(button)
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
        profile = QPushButton("Confirm the generic labeled profile")
        profile.clicked.connect(lambda: self._guard(self._confirm_generic_profile))
        page.layout().addWidget(profile)
        sources = QPushButton("Confirm starter call-source lists")
        sources.clicked.connect(lambda: self._guard(self._confirm_sources))
        page.layout().addWidget(sources)
        shifts = QPushButton("Confirm the placeholder shift hours")
        shifts.clicked.connect(lambda: self._guard(self._confirm_shifts))
        page.layout().addWidget(shifts)
        return page

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
        page = self._text_page("System health", "Backups on this drive do not protect against loss of the drive.")
        backup = QPushButton("Create backup")
        backup.clicked.connect(lambda: self._guard(lambda: self._backup(page)))
        page.layout().addWidget(backup)
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

    def _text_page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(title))
        note = QLabel(subtitle)
        note.setWordWrap(True)
        layout.addWidget(note)
        period = _period_bar()
        page.period = period
        layout.addWidget(period)
        page.output = QTextEdit()
        page.output.setReadOnly(True)
        layout.addWidget(page.output)
        return page


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


def _metric_text(metric) -> str:
    if not metric.available:
        return f"{metric.label}\nNot available"
    return f"{metric.label}\n{metric.value}"


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
