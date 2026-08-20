from pathlib import Path
import sys
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.schedule_service import next_send_date


def test_wednesday_is_send_day():
    assert next_send_date(date(2026, 8, 19)) == date(2026, 8, 19)


def test_thursday_goes_to_friday():
    assert next_send_date(date(2026, 8, 20)) == date(2026, 8, 21)


def test_saturday_goes_to_wednesday():
    assert next_send_date(date(2026, 8, 22)) == date(2026, 8, 26)

from services.schedule_service import add_business_days


def test_fifteen_business_days():
    assert add_business_days(date(2026, 8, 21), 15) == date(2026, 9, 11)
