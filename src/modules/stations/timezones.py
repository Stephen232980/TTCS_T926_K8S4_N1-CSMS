from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_STATION_TIMEZONE = "Asia/Ho_Chi_Minh"


def validate_station_timezone(value: str) -> str:
    """Validate an IANA key without changing its identity or using a UTC offset."""
    value = value.strip()
    if not value or len(value) > 64:
        raise ValueError("Múi giờ phải là tên IANA hợp lệ")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Múi giờ phải là tên IANA hợp lệ") from error
    return value
