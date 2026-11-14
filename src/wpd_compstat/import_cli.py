"""Bulk CAD PDF import from a command prompt, one batch per folder, through the same staged pipeline as the window.

Usage (with the program closed):
    python -m wpd_compstat.import_cli --root "E:\\WPD COMPSTAT" --user jthomas "E:\\PDFs for Updating the Program"

The password is typed at the prompt and is never stored or echoed.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import pymupdf

from wpd_compstat.admin import confirm_profile
from wpd_compstat.errors import AppError
from wpd_compstat.import_engine.call_log import CALL_LOG_PROFILE, TITLE_RANGE
from wpd_compstat.import_engine.dates import parse_date
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate
from wpd_compstat.paths import use_install_temp
from wpd_compstat.session import Session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wpd-compstat-import")
    parser.add_argument("--root", required=True, help="The WPD COMPSTAT installation folder")
    parser.add_argument("--user", required=True, help="Administrator or analyst username")
    parser.add_argument("folder", help="Folder of CAD PDFs; subfolders are included")
    parser.add_argument(
        "--confirm-call-log-profile",
        action="store_true",
        help="Ask to make the Warwick CAD call-log layout the active confirmed profile before importing",
    )
    args = parser.parse_args(argv)
    session = Session(Path(args.root))
    use_install_temp(session.paths)
    if session.state() != "ready":
        print("This installation is not set up. Open WPD COMPSTAT once and finish first-run setup.", file=sys.stderr)
        return 2
    if session.paths.db_working.exists():
        print(
            "WPD COMPSTAT is open, or its last session did not close cleanly. Close the program "
            "(or open and close it once to recover the session), then run the import again.",
            file=sys.stderr,
        )
        return 2
    groups = _groups(Path(args.folder))
    if not groups:
        print("No PDFs were found in that folder.", file=sys.stderr)
        return 2
    password = getpass.getpass(f"Password for {args.user}: ")
    try:
        session.unlock(args.user, password)
    except AppError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        password = None
    try:
        if not _profile_ready(session, args.confirm_call_log_profile):
            return 4
        for label, files in groups:
            print(f"\n== {label}: {len(files)} PDF(s)")
            batch_id = stage_select(session, files)
            stage_extract(session, batch_id)
            stage_validate(session, batch_id)
            summary = stage_commit(session, batch_id)
            for item in summary["files"]:
                print(
                    f"  {item['filename']}: pages={item['pages']} call_lines={item.get('call_lines')} "
                    f"extracted={item['extracted']} new={item['new_incidents']} updated={item.get('existing_updated')} "
                    f"duplicates={item.get('duplicates_skipped')} exceptions={item.get('exceptions')} "
                    f"parse_errors={item.get('parsing_errors')}"
                )
            print(
                f"  batch {batch_id}: new={summary['new_incidents']} updated={summary['existing_updated']} "
                f"duplicates={summary['duplicates_skipped']} conflicts={summary['conflicting_records']} "
                f"exceptions={summary['exceptions']} database_total={summary['final_incident_count']}"
            )
        print("\nIncidents in the database by month:")
        for row in session.conn.execute(
            """
            SELECT substr(event_date, 1, 7) AS month, COUNT(*) AS n
            FROM incidents WHERE excluded = 0 GROUP BY month ORDER BY month
            """
        ):
            print(f"  {row['month']}: {row['n']}")
    finally:
        session.close()
    return 0


def _profile_ready(session: Session, may_confirm: bool) -> bool:
    active = session.setting("active_profile_id")
    row = session.conn.execute("SELECT confirmation FROM cad_profiles WHERE id = ?", (CALL_LOG_PROFILE["id"],)).fetchone()
    if active == CALL_LOG_PROFILE["id"] and row is not None and row["confirmation"] == "agency_confirmed":
        return True
    if not may_confirm:
        print(
            "The Warwick CAD call-log profile is not the active confirmed profile. Confirm it under "
            "Administration, or run again with --confirm-call-log-profile.",
            file=sys.stderr,
        )
        return False
    answer = input(f"Type YES to make '{CALL_LOG_PROFILE['name']}' the active confirmed import profile: ")
    if answer.strip() != "YES":
        print("The profile was not confirmed. Nothing was imported.", file=sys.stderr)
        return False
    confirm_profile(session, CALL_LOG_PROFILE["id"])
    return True


def _groups(folder: Path) -> list[tuple[str, list[Path]]]:
    """One batch per folder, ordered by the latest date each folder covers; files inside a batch follow their printed range."""
    by_folder: dict[Path, list[tuple[tuple, Path]]] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.casefold() == ".pdf":
            by_folder.setdefault(path.parent, []).append((_range_key(path), path))
    ordered = []
    for parent, items in by_folder.items():
        items.sort()
        label = parent.name if parent != folder else folder.name
        latest_end = max(key[1] for key, _path in items)
        ordered.append((latest_end, label, [path for _key, path in items]))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [(label, files) for _key, label, files in ordered]


def _range_key(path: Path) -> tuple:
    try:
        document = pymupdf.open(path)
        try:
            first = document[0].get_text("text") if document.page_count else ""
        finally:
            document.close()
    except Exception:
        return ("9999-12-31", "9999-12-31", path.name)
    match = TITLE_RANGE.search(first)
    if not match:
        return ("9999-12-31", "9999-12-31", path.name)
    return (parse_date(match.group(1), "MDY") or "9999-12-31", parse_date(match.group(2), "MDY") or "9999-12-31", path.name)


if __name__ == "__main__":
    raise SystemExit(main())
