"""Read-only traffic-export import. A citation reference is not a verified violation."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook

from wpd_compstat.errors import ValidationError
from wpd_compstat.security.crypto import seal_file

_COLUMNS = {
    "occurred_at",
    "officer_name",
    "shift_name",
    "division_name",
    "location_text",
    "duty_type",
    "directed",
    "stops",
    "citation_references",
    "verified_violations",
    "warnings",
    "dui",
}


def import_traffic_export(session, path: Path, column_map: dict[str, str]) -> dict:
    session.require("traffic_import")
    path = Path(path)
    before = path.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    before_mtime = path.stat().st_mtime_ns
    rows, warnings = _read_rows(path, column_map)
    after_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if after_hash != before_hash or path.stat().st_mtime_ns != before_mtime:
        raise ValidationError("The source workbook changed while it was being read. Nothing was imported.")
    verified_column = "verified_violations" in set(column_map.values())
    status = "explicit_verified_column" if verified_column else "references_not_counted"
    if not verified_column:
        warnings.append(
            "No verified-violation column was mapped. Citation references were stored and were not counted as verified violations."
        )
    relative = f"Imports/traffic/{before_hash}.bin.enc"
    seal_file(session.paths.root / relative, session.dek, before)
    cursor = session.conn.execute(
        """
        INSERT INTO traffic_imports(
            original_filename, sha256, imported_at, imported_by, row_count, mapping_json,
            warnings_json, counting_rule_status, stored_relative_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            path.name,
            before_hash,
            session.stamp(),
            session.user["id"],
            len(rows),
            json.dumps(column_map),
            json.dumps(warnings),
            status,
            relative,
        ),
    )
    import_id = int(cursor.lastrowid)
    for row in rows:
        session.conn.execute(
            """
            INSERT INTO traffic_activity(
                import_id, occurred_at, officer_name, shift_name, division_name, location_text,
                duty_type, directed, stops, citation_references, verified_violations, warnings, dui
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                row.get("occurred_at"),
                row.get("officer_name"),
                row.get("shift_name"),
                row.get("division_name"),
                row.get("location_text"),
                row.get("duty_type") or "unknown",
                int(bool(row.get("directed"))),
                _int(row.get("stops")),
                _int(row.get("citation_references")),
                _int(row.get("verified_violations")) if verified_column else 0,
                _int(row.get("warnings")),
                _int(row.get("dui")),
            ),
        )
    session.audit("traffic_import", entity_type="traffic_import", entity_id=import_id)
    return {"id": import_id, "rows": len(rows), "warnings": warnings, "counting_rule_status": status}


def weekly_verified_totals(conn, start: str, end: str, goal: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT occurred_at, verified_violations, citation_references, warnings, stops, dui, directed
        FROM traffic_activity
        WHERE occurred_at IS NOT NULL AND occurred_at >= ? AND occurred_at <= ?
        """,
        (start, end + "T23:59:59" if len(end) == 10 else end),
    ).fetchall()
    weeks: dict[str, dict] = {}
    for row in rows:
        week = row["occurred_at"][:10]
        from datetime import date

        day = date.fromisoformat(week)
        key = f"{day.isocalendar().year}-W{day.isocalendar().week:02d}"
        bucket = weeks.setdefault(
            key,
            {"week": key, "verified_violations": 0, "citation_references": 0, "warnings": 0, "stops": 0, "dui": 0},
        )
        bucket["verified_violations"] += int(row["verified_violations"] or 0)
        bucket["citation_references"] += int(row["citation_references"] or 0)
        bucket["warnings"] += int(row["warnings"] or 0)
        bucket["stops"] += int(row["stops"] or 0)
        bucket["dui"] += int(row["dui"] or 0)
    for bucket in weeks.values():
        bucket["goal"] = goal
        bucket["goal_met"] = bucket["verified_violations"] >= goal
        bucket["note"] = "Citation references are not included in the verified-violation total."
    return [weeks[key] for key in sorted(weeks)]


def _read_rows(path: Path, column_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    unknown = set(column_map.values()) - _COLUMNS
    if unknown:
        raise ValidationError("The column map contains an unknown field.")
    if path.suffix.casefold() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            source_rows = list(reader)
    elif path.suffix.casefold() == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            iterator = sheet.iter_rows(values_only=True)
            headers = [str(cell).strip() if cell is not None else "" for cell in next(iterator)]
            source_rows = []
            for values in iterator:
                source_rows.append({headers[index]: values[index] for index in range(len(headers))})
        finally:
            workbook.close()
    else:
        raise ValidationError("Traffic imports must be CSV or XLSX.")
    warnings = []
    mapped = []
    for source in source_rows:
        item = {}
        for source_name, target in column_map.items():
            item[target] = source.get(source_name)
        if item.get("verified_violations") in (None, "") and "verified_violations" in column_map.values():
            item["verified_violations"] = 0
        mapped.append(item)
    return mapped, warnings


def _int(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
