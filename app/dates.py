"""Issue dates, cut-offs and period anchors."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


LONDON = ZoneInfo("Europe/London")
SCHEDULE_HOUR = 19
SCHEDULE_MINUTE = 37


def london_now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(LONDON)


def schedule_window_open(now: dt.datetime) -> bool:
    """Return true for Sunday after the schedule time or a delayed Monday run."""

    local = london_now(now)
    if local.weekday() == 6:
        return (local.hour, local.minute, local.second) >= (SCHEDULE_HOUR, SCHEDULE_MINUTE, 0)
    # GitHub may start a scheduled workflow late. Keep the Sunday issue alive
    # through Monday so a delayed run does not silently skip the edition.
    return local.weekday() == 0


def last_completed_sunday(now: dt.datetime | dt.date | None = None) -> dt.date:
    """Return the issue Sunday whose scheduled run has completed."""

    if isinstance(now, dt.datetime):
        local = london_now(now)
        date_value = local.date()
        if local.weekday() == 6 and (local.hour, local.minute) < (SCHEDULE_HOUR, SCHEDULE_MINUTE):
            date_value -= dt.timedelta(days=7)
    elif isinstance(now, dt.date):
        date_value = now
    else:
        local = london_now()
        date_value = local.date()
        if local.weekday() == 6 and (local.hour, local.minute) < (SCHEDULE_HOUR, SCHEDULE_MINUTE):
            date_value -= dt.timedelta(days=7)
    return date_value - dt.timedelta(days=(date_value.weekday() + 1) % 7)


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Expected YYYY-MM-DD, got {value!r}") from exc


def period_anchor(asof: dt.date, period: str) -> dt.date:
    if period == "1D":
        return asof - dt.timedelta(days=1)
    if period == "1W":
        return asof - dt.timedelta(days=7)
    if period == "1M":
        return asof - dt.timedelta(days=30)
    if period == "YTD":
        return dt.date(asof.year - 1, 12, 31)
    if period == "1Y":
        return asof - dt.timedelta(days=365)
    if period == "5Y":
        return asof - dt.timedelta(days=365 * 5)
    raise ValueError(f"Unknown period: {period}")


PERIODS = ("1D", "1W", "1M", "YTD", "1Y", "5Y")
