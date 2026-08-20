from __future__ import annotations

from datetime import date, timedelta

SEND_WEEKDAYS = {2, 4}  # quarta=2, sexta=4


def next_send_date(base: date | None = None) -> date:
    d = base or date.today()
    for offset in range(0, 8):
        candidate = d + timedelta(days=offset)
        if candidate.weekday() in SEND_WEEKDAYS:
            return candidate
    return d


def add_business_days(start: date, days: int = 15) -> date:
    """SLA operacional: conta segunda a sexta. Feriados entram numa fase posterior."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def business_days_remaining(start: date, end: date) -> int:
    if start == end:
        return 0
    step = 1 if end > start else -1
    current = start
    total = 0
    while current != end:
        current += timedelta(days=step)
        if current.weekday() < 5:
            total += step
    return total
