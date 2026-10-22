"""Integer-watt, equal-share water filling; no database or device I/O."""

from collections.abc import Mapping
from uuid import UUID


def allocate_watts(budget: int, demands: Mapping[UUID, int]) -> dict[UUID, int]:
    if type(budget) is not int or budget < 0:
        raise ValueError("Budget must be nonnegative integer watts")
    if any(type(value) is not int or value < 0 for value in demands.values()):
        raise ValueError("Demands must be nonnegative integer watts")
    result = {key: 0 for key in demands}
    remaining = {key: value for key, value in demands.items() if value}
    while remaining and budget:
        share = budget // len(remaining)
        if not share:
            break  # Leave indivisible watts unused; never round above budget.
        capped = [key for key, value in remaining.items() if value <= share]
        if capped:
            for key in capped:
                value = remaining.pop(key)
                result[key] = value
                budget -= value
        else:
            for key in remaining:
                result[key] = share
            break
    return result
