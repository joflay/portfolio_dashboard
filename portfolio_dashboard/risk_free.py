from __future__ import annotations

import csv
from pathlib import Path


def load_risk_free_rates(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}

    rates: dict[str, float] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            day = (row.get("Date") or "").strip()
            if not day:
                continue
            rate = _float(row.get("risk_free_rate"))
            if rate is None:
                percent = _float(row.get("risk_free_rate_percent"))
                rate = percent / 100 if percent is not None else None
            if rate is not None:
                rates[day[:10]] = rate
    return dict(sorted(rates.items()))


def latest_rate_on_or_before(rates: dict[str, float], day: str) -> float | None:
    latest: float | None = None
    for rate_day, rate in rates.items():
        if rate_day > day:
            break
        latest = rate
    return latest


def _float(value: str | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except ValueError:
        return None
