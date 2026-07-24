"""Daily reporting windows for the admin dashboard.

Orders are stored with UTC `created_at`. The vendor thinks in local days, so
these helpers translate a business-local calendar day into the UTC half-open
interval [start, end) used to query Mongo. The offset is fixed (Nigeria/WAT has
no daylight saving), so no tz database is required.
"""

from datetime import date, datetime, time, timedelta, timezone

from flask import current_app


def business_tz():
    """The reporting timezone as a fixed-offset tzinfo."""
    hours = current_app.config.get('REPORT_TZ_OFFSET_HOURS', 1)
    return timezone(timedelta(hours=hours))


def today():
    """Today's date in the business timezone (not the server's)."""
    return datetime.now(business_tz()).date()


def parse_day(value):
    """A 'YYYY-MM-DD' string to a date, falling back to today on anything bad.

    Never returns a future day - the dashboard can't report on days that
    haven't happened.
    """
    tz_today = today()
    if not value:
        return tz_today
    try:
        day = date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return tz_today
    return min(day, tz_today)


def day_window_utc(day):
    """UTC [start, end) datetimes bounding one business-local calendar day."""
    tz = business_tz()
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def neighbours(day):
    """(prev_day, next_day_or_None) for navigation; next is None if day is today."""
    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    return prev_day, (next_day if next_day <= today() else None)
