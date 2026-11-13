"""Offline location summaries. Coordinates are used only when a source says what they are."""

from __future__ import annotations

import csv
from pathlib import Path

from wpd_compstat.errors import ValidationError


def import_geocode_reference(session, path: Path, source_name: str) -> dict:
    session.require("configure")
    if not source_name.strip():
        raise ValidationError("Name the offline reference. Coordinates are not downloaded.")
    accepted = 0
    rejected = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"address", "latitude", "longitude", "quality"}
        if not reader.fieldnames or not required <= {name.strip().casefold() for name in reader.fieldnames}:
            raise ValidationError("The reference needs address, latitude, longitude, and quality columns.")
        fields = {name.casefold(): name for name in reader.fieldnames}
        for row in reader:
            quality = (row.get(fields["quality"]) or "").strip().casefold()
            address = " ".join((row.get(fields["address"]) or "").upper().split())
            try:
                latitude = float(row.get(fields["latitude"]) or "")
                longitude = float(row.get(fields["longitude"]) or "")
            except ValueError:
                rejected += 1
                continue
            if quality not in {"exact", "approximate"} or not address:
                rejected += 1
                continue
            session.conn.execute(
                """
                INSERT INTO geocode_reference(address_key, latitude, longitude, quality, source_name, imported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(address_key) DO UPDATE SET
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    quality = excluded.quality,
                    source_name = excluded.source_name,
                    imported_at = excluded.imported_at
                WHERE geocode_reference.quality != 'exact' OR excluded.quality = 'exact'
                """,
                (address, latitude, longitude, quality, source_name.strip(), session.stamp()),
            )
            accepted += 1
    from wpd_compstat.import_engine.pipeline import _apply_geocode_reference

    _apply_geocode_reference(session.conn)
    session.audit("import_geocode_reference", detail=f"accepted={accepted}")
    return {"accepted": accepted, "rejected": rejected}


def location_points(conn, start: str, end: str) -> dict:
    rows = conn.execute(
        """
        SELECT i.id, i.cad_number, l.latitude, l.longitude, l.coord_quality, l.raw_address
        FROM incidents i
        JOIN locations l ON l.id = i.location_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND l.latitude IS NOT NULL AND l.longitude IS NOT NULL
        """,
        (start, end),
    ).fetchall()
    exact = [dict(row) for row in rows if row["coord_quality"] == "exact"]
    approximate = [dict(row) for row in rows if row["coord_quality"] == "approximate"]
    return {
        "exact": exact,
        "approximate": approximate,
        "qualification": "Approximate coordinates are listed separately and are excluded from hotspot counts.",
    }


def hotspot_bins(points: list[dict], minimum: int = 3) -> list[dict]:
    bins: dict[tuple[int, int], int] = {}
    for point in points:
        lat_bin = round(float(point["latitude"]) / 0.0025)
        lon_bin = round(float(point["longitude"]) / 0.0025)
        bins[(lat_bin, lon_bin)] = bins.get((lat_bin, lon_bin), 0) + 1
    return [
        {
            "latitude_bin": lat,
            "longitude_bin": lon,
            "count": count,
            "method": "Count of exact coordinates in a grid of about 250 meters. This is not a smoothed heatmap.",
        }
        for (lat, lon), count in sorted(bins.items())
        if count >= minimum
    ]


def repeat_streets(conn, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.street AS street, COUNT(DISTINCT i.id) AS incidents
        FROM incidents i
        JOIN locations l ON l.id = i.location_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND l.street IS NOT NULL AND TRIM(l.street) != ''
        GROUP BY l.street
        ORDER BY incidents DESC, street
        """,
        (start, end),
    ).fetchall()
    return [dict(row) for row in rows]
