import asyncio
import warnings
from hashlib import sha256
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import undefer

from src.modules.identity.authorization import allow_roles, build_actor_scope
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import Station
from src.modules.stations.repository import StationRepository
from src.modules.stations.router import DatabaseSession
from src.modules.stations.schemas import StationResponse

router = APIRouter(
    prefix="/api/v1/stations",
    tags=["station-photos"],
    dependencies=[Depends(authorize_request)],
)
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def normalize_photo(data: bytes, mime: str) -> tuple[bytes, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != FORMATS[mime]:
                    raise ValueError("invalid_station_photo")
                # A station cover is static. Decode only the first frame of an
                # animated WebP/PNG rather than rejecting a supported image.
                image.seek(0)
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("station_photo_dimensions_too_large")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Fresh pixels exclude EXIF/GPS, filenames and embedded metadata.
                transparent = "A" in oriented.getbands() or "transparency" in image.info
                clean = Image.new("RGBA" if transparent else "RGB", oriented.size)
                clean.paste(oriented.convert(clean.mode))
                output = BytesIO()
                if transparent:
                    clean.save(output, format="PNG")
                else:
                    clean.save(output, format="JPEG", quality=85)
                normalized = output.getvalue()
                if len(normalized) > MAX_BYTES:
                    raise ValueError("station_photo_too_large")
                return normalized, "image/png" if transparent else "image/jpeg"
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("invalid_station_photo") from error


async def station_for_photo(
    station_id: UUID,
    actor: CurrentActorDependency,
    db: DatabaseSession,
    *,
    lock: bool = False,
    load: bool = False,
) -> Station:
    try:
        station = await StationRepository(db).get_station_by_id(
            station_id, build_actor_scope(actor)
        )
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    statement = select(Station).where(Station.id == station.id)
    if lock:
        statement = statement.with_for_update()
    if load:
        statement = statement.options(undefer(Station.photo_data))
    result = await db.scalar(statement.execution_options(populate_existing=True))
    if result is None:
        raise HTTPException(404, "resource_not_found")
    return result


@router.put("/{station_id}/photo", response_model=StationResponse)
@allow_roles("station_owner")
async def put_photo(
    station_id: UUID,
    request: Request,
    actor: CurrentActorDependency,
    db: DatabaseSession,
) -> StationResponse:
    # Check ownership before reading or decoding the upload.
    await station_for_photo(station_id, actor, db)
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in FORMATS:
        raise HTTPException(415, "unsupported_station_photo_type")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "station_photo_too_large")
        data.extend(chunk)
    try:
        normalized, mime = await asyncio.to_thread(normalize_photo, bytes(data), mime)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    station = await station_for_photo(station_id, actor, db, lock=True)
    station.photo_data = normalized
    station.photo_mime = mime
    station.photo_digest = sha256(normalized).hexdigest()
    await db.flush()
    await db.refresh(station)
    return StationResponse.model_validate(station)


@router.get("/{station_id}/photo")
@allow_roles("station_owner", "operator", "admin")
async def get_photo(
    station_id: UUID,
    actor: CurrentActorDependency,
    db: DatabaseSession,
) -> Response:
    station = await station_for_photo(station_id, actor, db, load=True)
    if station.photo_data is None:
        raise HTTPException(404, "station_photo_not_found")
    return Response(
        content=station.photo_data,
        media_type=station.photo_mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{station_id}/photo", status_code=204)
@allow_roles("station_owner")
async def delete_photo(
    station_id: UUID,
    actor: CurrentActorDependency,
    db: DatabaseSession,
) -> Response:
    station = await station_for_photo(station_id, actor, db, lock=True)
    station.photo_data = None
    station.photo_mime = None
    station.photo_digest = None
    await db.flush()
    return Response(status_code=204)
