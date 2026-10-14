"""Exact per-segment VND rounding shared by billing callers (T-71)."""

from decimal import Decimal


def tien_dong(energy_wh: int | Decimal, price_vnd_per_kwh: int) -> int:
    """Return Wh * VND/kWh / 1000 rounded half up to whole VND.

    Decimal Wh preserves the current T-70/T-73 contract; this function does
    not round energy. Integer arithmetic avoids float and Decimal-context
    precision loss, including for very large readings.
    """
    if isinstance(energy_wh, bool) or not isinstance(energy_wh, (int, Decimal)):
        raise TypeError("energy_wh must be int or Decimal, not bool or float")
    if isinstance(price_vnd_per_kwh, bool) or not isinstance(price_vnd_per_kwh, int):
        raise TypeError("price_vnd_per_kwh must be int, not bool or float")

    if isinstance(energy_wh, Decimal):
        if not energy_wh.is_finite():
            raise ValueError("energy_wh must be finite")
        numerator, denominator = energy_wh.as_integer_ratio()
    else:
        numerator, denominator = energy_wh, 1

    numerator *= price_vnd_per_kwh
    denominator *= 1000
    whole, remainder = divmod(abs(numerator), denominator)
    amount = whole + int(2 * remainder >= denominator)
    return -amount if numerator < 0 else amount
