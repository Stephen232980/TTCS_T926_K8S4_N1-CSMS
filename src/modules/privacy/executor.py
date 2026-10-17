"""Checkpointed execution; SQL rechecks approval and live financial gates."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.config import settings


def executor_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, hide_parameters=True)


async def execute_job(engine: AsyncEngine, job_id: UUID) -> int:
    async with engine.connect() as connection:
        locked = await connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:id,0))"),
            {"id": str(job_id)},
        )
        await connection.commit()
        if not locked:
            return -1
        try:
            checkpoint = int(
                await connection.scalar(
                    text("SELECT checkpoint FROM privacy_jobs WHERE id=:id"),
                    {"id": job_id},
                )
                or 0
            )
            await connection.commit()
            while checkpoint < 3:
                checkpoint = int(
                    await connection.scalar(
                        text("SELECT privacy_private.execute_stage(:id)"),
                        {"id": job_id},
                    )
                    or 0
                )
                await connection.commit()
            return checkpoint
        except Exception as exc:
            await connection.rollback()
            diag = getattr(getattr(exc, "orig", None), "diag", None)
            code = getattr(diag, "message_primary", "execution_failed")
            safe_codes = {
                "wallet_refund_or_debt_required",
                "charging_or_cable_open",
                "remote_start_open",
                "reservation_or_fee_open",
                "topup_open",
                "legal_hold",
                "non_driver_obligations",
                "financial_reference_requires_review",
                "subject_not_active",
                "subject_collision",
            }
            if code not in safe_codes:
                code = "execution_failed"
            await connection.execute(
                text(
                    "UPDATE privacy_jobs SET status='needs_review',last_error=:code,updated_at=clock_timestamp() WHERE id=:id AND checkpoint<3"
                ),
                {"id": job_id, "code": code},
            )
            await connection.commit()
            raise
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:id,0))"),
                {"id": str(job_id)},
            )
            await connection.commit()
