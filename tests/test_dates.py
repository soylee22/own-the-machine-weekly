import datetime as dt

from app.dates import last_completed_sunday, schedule_window_open


def test_schedule_uses_london_dst_and_delayed_monday_window():
    before = dt.datetime(2026, 3, 29, 18, 36, tzinfo=dt.timezone.utc)
    after = dt.datetime(2026, 3, 29, 18, 37, tzinfo=dt.timezone.utc)
    monday = dt.datetime(2026, 3, 30, 12, 0, tzinfo=dt.timezone.utc)
    tuesday = dt.datetime(2026, 3, 31, 12, 0, tzinfo=dt.timezone.utc)
    assert not schedule_window_open(before)
    assert schedule_window_open(after)
    assert schedule_window_open(monday)
    assert not schedule_window_open(tuesday)


def test_last_completed_sunday_does_not_use_monday_partial_data():
    monday = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)
    sunday_before_schedule = dt.datetime(2026, 9, 20, 18, 0, tzinfo=dt.timezone.utc)
    sunday_after_schedule = dt.datetime(2026, 9, 20, 19, 40, tzinfo=dt.timezone.utc)
    assert last_completed_sunday(monday) == dt.date(2026, 9, 20)
    assert last_completed_sunday(sunday_before_schedule) == dt.date(2026, 9, 13)
    assert last_completed_sunday(sunday_after_schedule) == dt.date(2026, 9, 20)
