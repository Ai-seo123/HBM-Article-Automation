from datetime import datetime, timezone
from typing import Optional, Tuple


def normalize_timestamp_to_date(raw_ts: str | datetime | None) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a timestamp (ISO-8601 string or datetime object), convert consistently
    to the application's local timezone, and extract (normalized_iso_timestamp, YYYY-MM-DD).

    Returns:
        (normalized_timestamp, YYYY-MM-DD) or (None, None) if parsing fails or input is empty.
    """
    if not raw_ts:
        return None, None

    if isinstance(raw_ts, str):
        cleaned = raw_ts.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            return None, None
    elif isinstance(raw_ts, datetime):
        dt = raw_ts
    else:
        return None, None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = dt.astimezone()
    normalized_ts = local_dt.isoformat()
    normalized_date = local_dt.strftime("%Y-%m-%d")
    return normalized_ts, normalized_date
