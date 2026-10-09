from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.modules.stations.schemas import (
    ChargePointCodeAvailabilityQuery,
    ChargePointCreateRequest,
    StationCreateRequest,
    StationListQuery,
    StationUpdateRequest,
)


def test_charge_point_codes_are_normalized_consistently() -> None:
    availability = ChargePointCodeAvailabilityQuery(code="  cp-q1-001  ")
    creation = ChargePointCreateRequest(code="  cp-q1-001  ", connector_count=2)

    assert availability.code == "cp-q1-001"
    assert creation.code == "cp-q1-001"


def valid_create_payload() -> dict[str, object]:
    return {
        "name": "Trạm Quận 1",
        "address": "123 Nguyễn Huệ, Quận 1",
        "latitude": 10.7731,
        "longitude": 106.7032,
    }


def test_station_create_request_normalizes_valid_payload() -> None:
    payload = valid_create_payload()
    payload["name"] = "  Trạm Quận 1  "
    payload["address"] = "  123 Nguyễn Huệ, Quận 1  "

    request = StationCreateRequest.model_validate(payload)

    assert request.name == "Trạm Quận 1"
    assert request.address == "123 Nguyễn Huệ, Quận 1"
    assert request.latitude == Decimal("10.7731")
    assert request.longitude == Decimal("106.7032")


def test_station_price_is_optional_and_station_scoped() -> None:
    payload = valid_create_payload()
    payload["price_vnd_per_kwh"] = "1200.50"

    request = StationCreateRequest.model_validate(payload)

    assert request.price_vnd_per_kwh == Decimal("1200.50")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "   "),
        ("address", "   "),
        ("latitude", -90.000001),
        ("latitude", 90.000001),
        ("longitude", -180.000001),
        ("longitude", 180.000001),
        ("price_vnd_per_kwh", 0),
        ("price_vnd_per_kwh", -1),
    ],
)
def test_station_create_request_rejects_invalid_fields(
    field: str,
    value: object,
) -> None:
    payload = valid_create_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        StationCreateRequest.model_validate(payload)


def test_station_create_request_rejects_owner_id_from_client() -> None:
    payload = valid_create_payload()
    payload["owner_id"] = "00000000-0000-0000-0000-000000000001"

    with pytest.raises(ValidationError):
        StationCreateRequest.model_validate(payload)


def test_station_update_request_accepts_partial_payload() -> None:
    request = StationUpdateRequest.model_validate(
        {
            "name": "  Trạm trung tâm  ",
        }
    )

    assert request.name == "Trạm trung tâm"
    assert request.model_fields_set == {"name"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"owner_id": "00000000-0000-0000-0000-000000000001"},
        {"status": "active"},
    ],
)
def test_station_update_request_rejects_invalid_payload(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StationUpdateRequest.model_validate(payload)


def test_station_list_query_uses_defaults() -> None:
    query = StationListQuery()

    assert query.page == 1
    assert query.page_size == 20
    assert query.status is None
    assert query.search is None


@pytest.mark.parametrize(
    "payload",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"status": "broken"},
        {"search": "x" * 101},
    ],
)
def test_station_list_query_rejects_invalid_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StationListQuery.model_validate(payload)
