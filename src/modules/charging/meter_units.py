"""Canonical OCPP samples: normalize once on ingestion, not on reads.

Energy.Active.Import.Register is an absolute counter in Wh. Stored samples
are already canonical; billing must use their value directly and compute
counter differences, never sum absolute counters.
"""

from decimal import Decimal, InvalidOperation

from src.modules.charging.payloads import SamplePayload

UNITS: dict[str, tuple[str, dict[str, Decimal]]] = {
    "Energy.Active.Import.Register": ("Wh", {"Wh": Decimal(1), "kWh": Decimal(1000)}),
    "Power.Active.Import": ("W", {"W": Decimal(1), "kW": Decimal(1000)}),
    "Power.Offered": ("W", {"W": Decimal(1), "kW": Decimal(1000)}),
    "Current.Import": ("A", {"A": Decimal(1)}),
    "Voltage": ("V", {"V": Decimal(1)}),
    "SoC": ("Percent", {"Percent": Decimal(1)}),
    "Frequency": ("Hertz", {"Hertz": Decimal(1)}),
    "Temperature": ("Celsius", {"Celsius": Decimal(1), "Celcius": Decimal(1)}),
}


def numeric_sample(sample: SamplePayload) -> tuple[Decimal, str] | None:
    supported = UNITS.get(sample.measurand)
    if supported is None or sample.format != "Raw":
        return None
    unit, conversions = supported
    factor = conversions.get(sample.unit or unit)
    if factor is None:
        return None
    try:
        value = Decimal(sample.value) * factor
        if not value.is_finite() or abs(value) >= Decimal("1e18"):
            return None
        return value.quantize(Decimal("0.000001")), unit
    except InvalidOperation:
        return None
