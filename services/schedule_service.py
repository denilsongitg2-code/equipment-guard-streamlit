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
