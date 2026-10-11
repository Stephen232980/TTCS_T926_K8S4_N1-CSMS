import os
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor
from src.modules.stations.photo_router import MAX_BYTES, normalize_photo
from tests.test_charge_point_creation import (
    charge_point_api_client,
    create_owner,
    create_station,
    owner_actor,
)


def picture() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), "green").save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_metadata_round_trip_and_locked_code(db_session: AsyncSession) -> None:
    owner = await create_owner(db_session, "owner-metadata")
    station = await create_station(db_session, owner=owner)
    body = {
        "code": f"META-{uuid4()}",
        "name": "Trụ sân trước",
        "connector_count": 2,
        "connectors": [
            {
                "connector_number": 1,
                "connector_type": "Type 2",
                "current_type": "AC",
                "max_power_kw": "22",
                "voltage": "400",
                "amperage": "32",
            },
            {
                "connector_number": 2,
                "connector_type": "CCS2",
                "current_type": "DC",
                "max_power_kw": "60",
            },
        ],
    }
    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        created = await client.post(
            f"/api/v1/stations/{station.id}/charge-points", json=body
        )
        assert created.status_code == 201
        cp = created.json()
        assert cp["name"] == body["name"]
        assert cp["connectors"][0]["voltage"] == "400"
        assert cp["connectors"][1]["current_type"] == "DC"
        # Existing code-lock behavior must not lock editable metadata.
        from sqlalchemy import func, select

        from src.modules.stations.models import ChargePoint

        entity = await db_session.scalar(
            select(ChargePoint).where(ChargePoint.code == body["code"])
        )
        assert entity is not None
        entity.code_locked_at = func.now()
        await db_session.flush()
        changed = await client.patch(
            f"/api/v1/charge-points/{cp['id']}",
            json={
                "name": "Tên mới",
                "connectors": [{"connector_number": 1, "voltage": None}],
            },
        )
        assert changed.status_code == 200
        assert changed.json()["connectors"][0]["voltage"] is None
        assert changed.json()["connectors"][0]["max_power_kw"] == "22.000"
        locked = await client.patch(
            f"/api/v1/charge-points/{cp['id']}", json={"code": "CHANGED"}
        )
        assert locked.status_code == 409
        invalid = await client.patch(
            f"/api/v1/charge-points/{cp['id']}",
            json={
                "name": "Must not save",
                "connectors": [{"connector_number": 3, "amperage": 16}],
            },
        )
        assert invalid.status_code == 422
        listed = await client.get(f"/api/v1/stations/{station.id}/charge-points")
        assert listed.json()["items"][0]["name"] == "Tên mới"
        denied_field = await client.patch(
            f"/api/v1/charge-points/{cp['id']}", json={"vendor": "Fake"}
        )
        assert denied_field.status_code == 422
    other = await create_owner(db_session, "metadata-other")
    async with charge_point_api_client(db_session, owner_actor(other.id)) as client:
        response = await client.patch(
            f"/api/v1/charge-points/{cp['id']}", json={"name": "Other"}
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_photo_replace_read_delete_scope_and_invalid_upload(
    db_session: AsyncSession,
) -> None:
    owner = await create_owner(db_session, "photo-owner")
    station = await create_station(db_session, owner=owner)
    url = f"/api/v1/stations/{station.id}/photo"
    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        assert (await client.get(url)).status_code == 404
        uploaded = await client.put(
            url, content=picture(), headers={"Content-Type": "image/jpeg"}
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["photo_url"].startswith(url + "?v=")
        fetched = await client.get(uploaded.json()["photo_url"])
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == "image/jpeg"
        with Image.open(BytesIO(fetched.content)) as image:
            assert image.size == (12, 8)
        assert (
            await client.put(
                url, content=b"svg", headers={"Content-Type": "image/svg+xml"}
            )
        ).status_code == 415
        assert (
            await client.put(url, content=b"bad", headers={"Content-Type": "image/png"})
        ).status_code == 422
        assert (
            await client.put(
                url,
                content=b"x" * (MAX_BYTES + 1),
                headers={"Content-Type": "image/png"},
            )
        ).status_code == 413
        assert (await client.get(url)).content == fetched.content
    other = await create_owner(db_session, "photo-other")
    async with charge_point_api_client(db_session, owner_actor(other.id)) as client:
        assert (await client.get(url)).status_code == 403
        assert (
            await client.put(
                url, content=picture(), headers={"Content-Type": "image/jpeg"}
            )
        ).status_code == 403
        assert (await client.delete(url)).status_code == 403
    async with charge_point_api_client(
        db_session, CurrentActor(user_id=owner.id, roles=frozenset({"operator"}))
    ) as client:
        assert (
            await client.get(url.replace("/api/v1/", "/api/v1/ops/"))
        ).status_code == 200
        station_response = await client.get(f"/api/v1/ops/stations/{station.id}")
        photo_url = station_response.json()["photo_url"]
        assert photo_url.startswith(f"/api/v1/ops/stations/{station.id}/photo")
        assert (await client.get(photo_url)).status_code == 200
        assert (await client.delete(url)).status_code == 403
    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        replacement = BytesIO()
        Image.new("RGB", (8, 12), "blue").save(replacement, format="PNG")
        changed = await client.put(
            url, content=replacement.getvalue(), headers={"Content-Type": "image/png"}
        )
        assert changed.json()["photo_url"] != uploaded.json()["photo_url"]
        assert (await client.delete(url)).status_code == 204
        assert (await client.get(url)).status_code == 404
        assert (await client.get(f"/api/v1/stations/{station.id}")).json()[
            "photo_url"
        ] is None


def test_animated_webp_becomes_static_cover() -> None:
    payload = BytesIO()
    Image.new("RGB", (16, 16), "red").save(
        payload,
        format="WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (16, 16), "blue")],
        duration=100,
        loop=0,
    )
    with Image.open(BytesIO(payload.getvalue())) as source:
        assert source.n_frames == 2
    normalized, mime = normalize_photo(payload.getvalue(), "image/webp")
    assert mime == "image/jpeg"
    with Image.open(BytesIO(normalized)) as cover:
        assert getattr(cover, "n_frames", 1) == 1
        red, _, blue = cover.getpixel((0, 0))
        assert red > blue


def test_supported_photo_between_old_and_new_upload_limits() -> None:
    payload = BytesIO()
    Image.frombytes("RGB", (1600, 1200), os.urandom(1600 * 1200 * 3)).save(
        payload, format="PNG"
    )
    assert 5 * 1024 * 1024 < len(payload.getvalue()) < MAX_BYTES
    normalized, mime = normalize_photo(payload.getvalue(), "image/png")
    assert len(normalized) < MAX_BYTES
    assert mime == "image/jpeg"


def test_photo_metadata_is_removed() -> None:
    image = Image.new("RGB", (3, 2), "red")
    exif = Image.Exif()
    exif[270] = "private metadata"
    payload = BytesIO()
    image.save(payload, format="JPEG", exif=exif)
    normalized, mime = normalize_photo(payload.getvalue(), "image/jpeg")
    assert mime == "image/jpeg"
    with Image.open(BytesIO(normalized)) as cleaned:
        assert not cleaned.getexif()


def test_phone_photo_orientation_is_preserved_without_exif() -> None:
    image = Image.new("RGB", (3, 2), "red")
    exif = Image.Exif()
    exif[274] = 6
    payload = BytesIO()
    image.save(payload, format="JPEG", exif=exif)
    normalized, _ = normalize_photo(payload.getvalue(), "image/jpeg")
    with Image.open(BytesIO(normalized)) as cleaned:
        assert cleaned.size == (2, 3)
        assert not cleaned.getexif()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configuration",
    [
        [{"connector_number": 1}, {"connector_number": 1}],
        [{"connector_number": 1}],
        [{"connector_number": 1, "max_power_kw": 0}, {"connector_number": 2}],
        [{"connector_number": 1, "voltage": -230}, {"connector_number": 2}],
        [{"connector_number": 1, "current_type": "UNKNOWN"}, {"connector_number": 2}],
        [{"connector_number": 1, "amperage": "1.234"}, {"connector_number": 2}],
    ],
)
async def test_invalid_connector_configuration_is_rejected(
    db_session: AsyncSession,
    configuration: list[dict[str, object]],
) -> None:
    owner = await create_owner(db_session, "invalid-metadata")
    station = await create_station(db_session, owner=owner)
    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.post(
            f"/api/v1/stations/{station.id}/charge-points",
            json={
                "code": f"INVALID-{uuid4()}",
                "connector_count": 2,
                "connectors": configuration,
            },
        )
        assert response.status_code == 422
        assert (
            await client.get(f"/api/v1/stations/{station.id}/charge-points")
        ).json()["total"] == 0
