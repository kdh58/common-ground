"""Display-only timestamp formatting; gathering schedule text is not a timestamp."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FALLBACK_TIMEZONE = 'America/New_York'


def timestamp_display(value):
    """Readable, labeled prototype fallback until the browser detects its zone.

    Require an explicit UTC offset: never guess a timezone for naive/invalid data.
    Return plain strings for Jinja autoescaping, never trusted HTML.
    """
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            return None
        utc = instant.astimezone(timezone.utc)
        local = utc.astimezone(ZoneInfo(FALLBACK_TIMEZONE))
        hour = local.hour % 12 or 12
        month = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[local.month - 1]
        period = 'AM' if local.hour < 12 else 'PM'
        return {
            'iso': utc.isoformat(timespec='seconds'),
            'label': (f'{month} {local.day}, {local.year} · {hour}:{local.minute:02d} '
                      f'{period} {local.tzname()} ({FALLBACK_TIMEZONE}; fallback)'),
        }
    except (ValueError, OverflowError):
        return None
