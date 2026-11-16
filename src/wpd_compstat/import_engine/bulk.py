"""Import any mix of dropped PDFs and folders: one staged batch per folder, oldest coverage first."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pymupdf

from wpd_compstat.import_engine.call_log import TITLE_RANGE
from wpd_compstat.import_engine.dates import parse_date
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate

TOTAL_KEYS = ("new_incidents", "existing_updated", "duplicates_skipped", "conflicting_records", "exceptions")
STAGES = ("Storing", "Reading", "Checking", "Saving")


def collect_pdfs(items: Iterable[str | Path]) -> tuple[list[Path], list[str]]:
    """PDFs from the dropped files and folders (subfolders included), and the names of everything else."""
    pdfs: list[Path] = []
    rejected: list[str] = []
    seen: set[Path] = set()

    def keep(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            pdfs.append(path)

    for item in items:
        path = Path(item)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.casefold() == ".pdf":
                    keep(child)
        elif path.is_file() and path.suffix.casefold() == ".pdf":
            keep(path)
        else:
            rejected.append(path.name or str(path))
    return pdfs, rejected


def group_batches(pdfs: Iterable[Path]) -> list[tuple[str, list[Path]]]:
    """One batch per folder, ordered by the latest date each folder covers; files inside a batch follow their printed range."""
    by_folder: dict[Path, list[tuple[tuple, Path]]] = {}
    for path in pdfs:
        by_folder.setdefault(path.parent, []).append((_range_key(path), path))
    ordered = []
    for parent, items in by_folder.items():
        items.sort()
        label = parent.name or str(parent)
        latest_end = max(key[1] for key, _path in items)
        ordered.append((latest_end, label, [path for _key, path in items]))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [(label, files) for _key, label, files in ordered]


def run_import(
    session,
    pdfs: list[Path],
    progress: Callable[[str, int, int], None] | None = None,
) -> dict:
    """Run every batch through select, extract, validate, and commit. Each commit is its own transaction."""
    batches = group_batches(pdfs)
    steps = len(batches) * len(STAGES)
    totals = {key: 0 for key in TOTAL_KEYS}
    totals.update({"files": len(pdfs), "batches": len(batches), "final_incident_count": None})
    done = 0

    def step(text: str) -> None:
        nonlocal done
        if progress is not None:
            progress(text, done, steps)
        done += 1

    for index, (label, files) in enumerate(batches, start=1):
        prefix = f"Batch {index} of {len(batches)} ({label}, {len(files)} PDF{'s' if len(files) != 1 else ''})"
        step(f"{prefix}: storing the PDFs")
        batch_id = stage_select(session, files)
        step(f"{prefix}: reading the calls")
        stage_extract(session, batch_id)
        step(f"{prefix}: checking for duplicates and conflicts")
        stage_validate(session, batch_id)
        step(f"{prefix}: saving")
        summary = stage_commit(session, batch_id)
        for key in TOTAL_KEYS:
            totals[key] += int(summary.get(key) or 0)
        totals["final_incident_count"] = summary.get("final_incident_count")
    if progress is not None:
        progress("Import finished.", steps, steps)
    return totals


def summary_text(totals: dict, rejected: list[str] | None = None) -> str:
    lines = [
        f"Imported {totals['files']} PDF{'s' if totals['files'] != 1 else ''}.",
        f"New calls: {totals['new_incidents']}",
        f"Updated calls: {totals['existing_updated']}",
        f"Duplicates skipped: {totals['duplicates_skipped']}",
        f"Conflicts for review: {totals['conflicting_records']}",
    ]
    if totals.get("exceptions"):
        lines.append(f"Exceptions for review: {totals['exceptions']}")
    if totals.get("final_incident_count") is not None:
        lines.append(f"Calls in the database: {totals['final_incident_count']}")
    if rejected:
        lines.append(f"Not imported because they are not PDFs: {', '.join(rejected)}")
    return "\n".join(lines)


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
