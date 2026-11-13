"""Local chart files. No network renderer."""

from __future__ import annotations

from pathlib import Path


def write_daily_chart(rows: list[dict], path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 3.2))
    if not rows:
        axis.text(0.5, 0.5, "No incidents in the selected period", ha="center", va="center")
        axis.set_axis_off()
    else:
        axis.bar([row["event_date"] for row in rows], [row["incidents"] for row in rows], color="#1f4e79")
        axis.set_xlabel("Date")
        axis.set_ylabel("Incidents")
        axis.set_title("Calls for service by date")
        figure.autofmt_xdate()
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path
