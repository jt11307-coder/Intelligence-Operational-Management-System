"""Temporal summaries. Peaks are withheld when support is too small."""

from __future__ import annotations

import numpy as np
import pandas as pd

from wpd_compstat.db.seed import get_setting


def hour_counts(conn, start: str, end: str) -> list[int]:
    rows = conn.execute(
        """
        SELECT event_time FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ? AND event_time IS NOT NULL
        """,
        (start, end),
    ).fetchall()
    counts = [0] * 24
    for row in rows:
        counts[int(row["event_time"][:2])] += 1
    return counts


def peak_hours(counts: list[int], min_support: int = 5) -> dict:
    array = np.array(counts, dtype=float)
    method = "Hours at or above the mean plus two standard deviations, with a minimum count."
    if float(array.sum()) < min_support:
        return {"peaks": [], "method": method, "reason": "Not enough timed incidents to identify a peak."}
    mean = float(array.mean())
    std = float(array.std())
    threshold = mean + (2 * std)
    peaks = [hour for hour, count in enumerate(counts) if count >= threshold and count >= min_support]
    if not peaks:
        return {
            "peaks": [],
            "method": method,
            "reason": "No hour reaches both the statistical threshold and the minimum count.",
            "mean": round(mean, 2),
            "std": round(std, 2),
        }
    return {"peaks": peaks, "method": method, "reason": None, "mean": round(mean, 2), "threshold": round(threshold, 2)}


def daily_counts(conn, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT event_date, id FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
        """,
        (start, end),
    ).fetchall()
    frame = pd.DataFrame([{"event_date": row["event_date"], "id": row["id"]} for row in rows])
    if frame.empty:
        return []
    grouped = frame.groupby("event_date", as_index=False).size()
    grouped = grouped.rename(columns={"size": "incidents"})
    return grouped.to_dict("records")


def weekday_counts(conn, start: str, end: str) -> list[dict]:
    frame_rows = daily_counts(conn, start, end)
    if not frame_rows:
        return []
    frame = pd.DataFrame(frame_rows)
    frame["weekday"] = pd.to_datetime(frame["event_date"]).dt.day_name()
    grouped = frame.groupby("weekday", as_index=False)["incidents"].sum()
    return grouped.to_dict("records")


def shift_for_time(event_time: str | None, shifts: list[dict]) -> str | None:
    if not event_time:
        return None
    minutes = int(event_time[:2]) * 60 + int(event_time[3:5])
    for shift in shifts:
        start = _minutes(shift["start"])
        end = _minutes(shift["end"])
        if start == end:
            continue
        if start < end and start <= minutes < end:
            return shift["name"]
        if start > end and (minutes >= start or minutes < end):
            return shift["name"]
    return None


def shift_summary(conn, start: str, end: str) -> dict:
    if not get_setting(conn, "shifts_confirmed", False):
        return {
            "available": False,
            "qualification": "Shift hours have not been confirmed by an administrator.",
            "counts": [],
        }
    shifts = get_setting(conn, "shifts", [])
    rows = conn.execute(
        """
        SELECT event_time FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
        """,
        (start, end),
    ).fetchall()
    counts = {shift["name"]: 0 for shift in shifts}
    undocumented = 0
    for row in rows:
        name = shift_for_time(row["event_time"], shifts)
        if name is None:
            undocumented += 1
        else:
            counts[name] += 1
    return {
        "available": True,
        "qualification": "Shift hours are the administrator-confirmed schedule.",
        "counts": [{"shift": name, "incidents": count} for name, count in counts.items()],
        "time_not_documented": undocumented,
    }


def response_times(conn, start: str, end: str) -> dict:
    rows = conn.execute(
        """
        SELECT dispatch_time, arrival_time FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
        """,
        (start, end),
    ).fetchall()
    samples = []
    excluded = 0
    undocumented = 0
    for row in rows:
        if not row["dispatch_time"] or not row["arrival_time"]:
            undocumented += 1
            continue
        elapsed = _minutes(row["arrival_time"]) - _minutes(row["dispatch_time"])
        if elapsed < 0:
            excluded += 1
            continue
        samples.append(elapsed)
    average = round(sum(samples) / len(samples), 1) if samples else None
    return {
        "average_minutes": average,
        "samples": len(samples),
        "excluded_nonsequential": excluded,
        "not_documented": undocumented,
        "qualification": "Overnight spans are not inferred. A clear or arrival time earlier than dispatch is excluded, not treated as zero or as the next day.",
    }


def _minutes(value: str) -> int:
    hour, minute, *_ = value.split(":")
    return int(hour) * 60 + int(minute)
