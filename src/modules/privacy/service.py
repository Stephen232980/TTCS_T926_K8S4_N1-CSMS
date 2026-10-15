from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.alerts.models import AlertEmail
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession, PendingChargingMessage
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import LoginIpAttempt, Role, Session, User, UserRole
from src.modules.ocpp.admin_health_models import (
    OcppTelemetryBucket,
    SystemHealthSample,
)
from src.modules.privacy.schemas import (
    AnonymizeUserResponse,
    LegalHoldResponse,
    RetentionCleanupResponse,
    RetentionPoliciesResponse,
    RetentionPolicyItem,
)
from src.modules.stations.models import StationCreateIdempotency
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky


def _extract_rowcount(result: Any) -> int:
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount) if rowcount is not None and rowcount > 0 else 0


class PrivacyRetentionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_retention_policies(self) -> RetentionPoliciesResponse:
        now = datetime.now(UTC)

        cutoff_login = now - timedelta(days=settings.retention_login_attempts_days)
        cutoff_sessions = now - timedelta(days=settings.retention_expired_sessions_days)
        cutoff_idempotency = now - timedelta(days=settings.retention_idempotency_days)
        cutoff_pending = now - timedelta(days=settings.retention_pending_messages_days)
        cutoff_telemetry = now - timedelta(hours=settings.retention_telemetry_hours)
        cutoff_emails = now - timedelta(days=settings.retention_sent_alert_emails_days)
        cutoff_health = now - timedelta(days=settings.retention_health_samples_days)

        count_login = (
            await self.db.scalar(
                select(func.count(LoginIpAttempt.ip_address)).where(
                    (
                        LoginIpAttempt.locked_until.is_(None)
                        | (LoginIpAttempt.locked_until < now)
                    )
                    & (LoginIpAttempt.updated_at < cutoff_login)
                )
            )
            or 0
        )

        count_sessions = (
            await self.db.scalar(
                select(func.count(Session.id)).where(
                    Session.revoked_at.is_not(None)
                    & (Session.revoked_at < cutoff_sessions)
                )
            )
            or 0
        )

        count_idempotency = (
            await self.db.scalar(
                select(func.count(StationCreateIdempotency.idempotency_key)).where(
                    StationCreateIdempotency.created_at < cutoff_idempotency
                )
            )
            or 0
        )

        count_pending = (
            await self.db.scalar(
                select(func.count(PendingChargingMessage.id)).where(
                    PendingChargingMessage.received_at < cutoff_pending
                )
            )
            or 0
        )

        count_telemetry = (
            await self.db.scalar(
                select(func.count(OcppTelemetryBucket.timestamp)).where(
                    OcppTelemetryBucket.timestamp < cutoff_telemetry
                )
            )
            or 0
        )

        count_emails = (
            await self.db.scalar(
                select(func.count(AlertEmail.id)).where(
                    (AlertEmail.status == "sent")
                    & AlertEmail.sent_at.is_not(None)
                    & (AlertEmail.sent_at < cutoff_emails)
                )
            )
            or 0
        )

        count_health = (
            await self.db.scalar(
                select(func.count(SystemHealthSample.timestamp)).where(
                    SystemHealthSample.timestamp < cutoff_health
                )
            )
            or 0
        )

        items = [
            RetentionPolicyItem(
                table_name="login_ip_attempts",
                policy_type="Bản ghi khóa IP đăng nhập sai",
                retention_threshold=f"{settings.retention_login_attempts_days} ngày",
                description="Dọn dẹp các lần thử đăng nhập thất bại đã hết thời hạn khóa",
                eligible_count=count_login,
            ),
            RetentionPolicyItem(
                table_name="sessions",
                policy_type="Phiên đăng nhập web đã thu hồi",
                retention_threshold=f"{settings.retention_expired_sessions_days} ngày",
                description="Dọn dẹp phiên đăng nhập đã bị hủy hoặc hết hạn",
                eligible_count=count_sessions,
            ),
            RetentionPolicyItem(
                table_name="station_create_idempotency",
                policy_type="Khóa chống trùng lặp tạo trạm",
                retention_threshold=f"{settings.retention_idempotency_days} ngày",
                description="Dọn dẹp các khóa idempotency tạo trạm quá hạn",
                eligible_count=count_idempotency,
            ),
            RetentionPolicyItem(
                table_name="charging_pending_messages",
                policy_type="Tin nhắn OCPP chờ xử lý mồ côi",
                retention_threshold=f"{settings.retention_pending_messages_days} ngày",
                description="Dọn dẹp các tin nhắn OCPP pending quá hạn không giải quyết",
                eligible_count=count_pending,
            ),
            RetentionPolicyItem(
                table_name="ocpp_telemetry_buckets",
                policy_type="Mẫu đo lường telemetry OCPP",
                retention_threshold=f"{settings.retention_telemetry_hours} giờ",
                description="Dọn dẹp telemetry ngoài cửa sổ giám sát",
                eligible_count=count_telemetry,
            ),
            RetentionPolicyItem(
                table_name="alert_emails",
                policy_type="Email cảnh báo đã gửi thành công",
                retention_threshold=f"{settings.retention_sent_alert_emails_days} ngày",
                description="Dọn dẹp nhật ký email outbox đã gửi thành công",
                eligible_count=count_emails,
            ),
            RetentionPolicyItem(
                table_name="system_health_samples",
                policy_type="Mẫu đo sức khỏe hệ thống",
                retention_threshold=f"{settings.retention_health_samples_days} ngày",
                description="Dọn dẹp các mẫu đo sức khỏe hệ thống ngoài chu kỳ phân tích",
                eligible_count=count_health,
            ),
        ]

        return RetentionPoliciesResponse(
            policies=items,
            auto_cleanup_interval_seconds=settings.retention_cleanup_interval_seconds,
            checked_at=now,
        )

    async def run_retention_cleanup(
        self,
        actor_id: UUID | None = None,
        permission: str | None = None,
    ) -> RetentionCleanupResponse:
        now = datetime.now(UTC)

        cutoff_login = now - timedelta(days=settings.retention_login_attempts_days)
        cutoff_sessions = now - timedelta(days=settings.retention_expired_sessions_days)
        cutoff_idempotency = now - timedelta(days=settings.retention_idempotency_days)
        cutoff_pending = now - timedelta(days=settings.retention_pending_messages_days)
        cutoff_telemetry = now - timedelta(hours=settings.retention_telemetry_hours)
        cutoff_emails = now - timedelta(days=settings.retention_sent_alert_emails_days)
        cutoff_health = now - timedelta(days=settings.retention_health_samples_days)

        res_login = await self.db.execute(
            delete(LoginIpAttempt).where(
                (
                    LoginIpAttempt.locked_until.is_(None)
                    | (LoginIpAttempt.locked_until < now)
                )
                & (LoginIpAttempt.updated_at < cutoff_login)
            )
        )
        del_login = _extract_rowcount(res_login)

        res_sess = await self.db.execute(
            delete(Session).where(
                Session.revoked_at.is_not(None) & (Session.revoked_at < cutoff_sessions)
            )
        )
        del_sess = _extract_rowcount(res_sess)

        res_idemp = await self.db.execute(
            delete(StationCreateIdempotency).where(
                StationCreateIdempotency.created_at < cutoff_idempotency
            )
        )
        del_idemp = _extract_rowcount(res_idemp)

        res_pend = await self.db.execute(
            delete(PendingChargingMessage).where(
                PendingChargingMessage.received_at < cutoff_pending
            )
        )
        del_pend = _extract_rowcount(res_pend)

        res_telem = await self.db.execute(
            delete(OcppTelemetryBucket).where(
                OcppTelemetryBucket.timestamp < cutoff_telemetry
            )
        )
        del_telem = _extract_rowcount(res_telem)

        res_emails = await self.db.execute(
            delete(AlertEmail).where(
                (AlertEmail.status == "sent")
                & AlertEmail.sent_at.is_not(None)
                & (AlertEmail.sent_at < cutoff_emails)
            )
        )
        del_emails = _extract_rowcount(res_emails)

        res_health = await self.db.execute(
            delete(SystemHealthSample).where(
                SystemHealthSample.timestamp < cutoff_health
            )
        )
        del_health = _extract_rowcount(res_health)

        total = (
            del_login
            + del_sess
            + del_idemp
            + del_pend
            + del_telem
            + del_emails
            + del_health
        )

        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="system.retention_cleanup",
            object_type="system",
            object_id="retention",
            data={
                "deleted_login_attempts": del_login,
                "deleted_expired_sessions": del_sess,
                "deleted_idempotency_keys": del_idemp,
                "deleted_pending_messages": del_pend,
                "deleted_telemetry_buckets": del_telem,
                "deleted_sent_alert_emails": del_emails,
                "deleted_health_samples": del_health,
                "total_deleted": total,
            },
            permission=permission or "admin.privacy.manage",
        )
        await self.db.commit()

        return RetentionCleanupResponse(
            executed_at=now,
            deleted_login_attempts=del_login,
            deleted_expired_sessions=del_sess,
            deleted_idempotency_keys=del_idemp,
            deleted_pending_messages=del_pend,
            deleted_telemetry_buckets=del_telem,
            deleted_sent_alert_emails=del_emails,
            deleted_health_samples=del_health,
            total_deleted=total,
        )

    async def check_legal_hold(self, user_id: UUID) -> tuple[bool, str | None]:
        active_session = await self.db.scalar(
            select(ChargingSession.id)
            .where(
                ChargingSession.driver_id == user_id,
                (
                    ChargingSession.ended_at.is_(None)
                    | ChargingSession.settlement_completed_at.is_(None)
                ),
            )
            .limit(1)
        )
        if active_session:
            return (
                True,
                "Người dùng đang có phiên sạc đang hoạt động hoặc chưa hoàn tất quyết toán",
            )

        hold_log = await self.db.scalar(
            select(AuditLog)
            .where(
                AuditLog.object_type == "user",
                AuditLog.object_id == str(user_id),
                AuditLog.action == "privacy.legal_hold",
            )
            .order_by(AuditLog.occurred_at.desc())
            .limit(1)
        )
        if (
            hold_log
            and isinstance(hold_log.data, dict)
            and hold_log.data.get("hold") is True
        ):
            reason = str(
                hold_log.data.get("reason", "Tài khoản đang bị tạm giữ pháp lý")
            )
            return True, reason

        return False, None

    async def set_legal_hold(
        self,
        user_id: UUID,
        hold: bool,
        reason: str,
        actor_id: UUID,
        authorization: AuthorizationEvidence | None = None,
    ) -> LegalHoldResponse:
        user = await self.db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "Tài khoản không tồn tại")
        if user.status == "anonymized":
            raise HTTPException(
                409, "Không thể thay đổi tạm giữ của tài khoản đã ẩn danh"
            )

        now = datetime.now(UTC)
        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="privacy.legal_hold",
            object_type="user",
            object_id=str(user_id),
            data={"hold": hold, "reason": reason},
            permission=authorization.permission
            if authorization
            else "admin.privacy.manage",
            actor_roles=list(authorization.roles) if authorization else None,
        )
        await self.db.commit()

        return LegalHoldResponse(
            user_id=user_id,
            legal_hold=hold,
            reason=reason if hold else None,
            updated_at=now,
        )

    async def anonymize_user(
        self,
        user_id: UUID,
        actor_id: UUID,
        reason: str,
        confirm_phrase: str,
        actor_roles: frozenset[str] = frozenset(),
        authorization: AuthorizationEvidence | None = None,
    ) -> AnonymizeUserResponse:
        if confirm_phrase.strip() != "CONFIRM_ANONYMIZE":
            raise HTTPException(
                422,
                "Xác nhận không đúng. Vui lòng nhập chính xác 'CONFIRM_ANONYMIZE'",
            )

        user = await self.db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise HTTPException(404, "Tài khoản không tồn tại")
        if user.status == "anonymized":
            raise HTTPException(409, "Tài khoản đã được ẩn danh trước đó")
        if user_id == actor_id and "admin" in actor_roles:
            raise HTTPException(409, "Quản trị viên không thể tự ẩn danh chính mình")

        # Check if user is the last active admin
        is_admin = await self.db.scalar(
            select(Role.code)
            .join(UserRole)
            .where(UserRole.user_id == user_id, Role.code == "admin")
        )
        if is_admin is not None and user.status == "active":
            other = await self.db.scalar(
                select(User.id)
                .join(UserRole)
                .join(Role)
                .where(
                    User.status == "active",
                    Role.code == "admin",
                    User.id != user_id,
                )
                .limit(1)
            )
            if other is None:
                raise HTTPException(409, "Phải giữ ít nhất một quản trị viên hoạt động")

        is_held, hold_reason = await self.check_legal_hold(user_id)
        if is_held:
            raise HTTPException(
                409,
                f"Tài khoản đang bị tạm giữ pháp lý hoặc có phiên sạc chưa kết thúc: {hold_reason}",
            )

        now = datetime.now(UTC)
        original_email = user.email
        domain = original_email.split("@")[-1] if "@" in original_email else "local"
        anonymized_email = f"anonymized_{user.id.hex[:12]}@deleted.local"

        user.email = anonymized_email
        user.password_hash = "ANONYMIZED_DISABLED_PASSWORD_HASH"
        user.status = "anonymized"
        user.failed_login_count = 0
        user.locked_until = None
        user.updated_at = now

        # Revoke all active web sessions
        await self.db.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )

        # Remove role assignments
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))

        # Count preserved financial and charging records (preserving foreign keys & immutable audit)
        invoices_count = (
            await self.db.scalar(
                select(func.count(Invoice.id)).where(Invoice.driver_id == user_id)
            )
            or 0
        )
        sessions_count = (
            await self.db.scalar(
                select(func.count(ChargingSession.id)).where(
                    ChargingSession.driver_id == user_id
                )
            )
            or 0
        )
        ledger_count = (
            await self.db.scalar(
                select(func.count(WalletLedger.id))
                .join(Wallet, Wallet.id == WalletLedger.wallet_id)
                .where(Wallet.driver_id == user_id)
            )
            or 0
        )

        preserved = {
            "invoices": invoices_count,
            "charging_sessions": sessions_count,
            "wallet_ledger_entries": ledger_count,
        }

        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="privacy.anonymize",
            object_type="user",
            object_id=str(user_id),
            data={
                "reason": reason,
                "anonymized_email": anonymized_email,
                "original_email_domain": domain,
                "preserved_records": preserved,
            },
            permission=authorization.permission
            if authorization
            else "admin.privacy.manage",
            actor_roles=list(authorization.roles)
            if authorization
            else list(actor_roles),
        )

        await self.db.commit()

        return AnonymizeUserResponse(
            user_id=user_id,
            anonymized_email=anonymized_email,
            status="anonymized",
            anonymized_at=now,
            preserved_financial_records=preserved,
        )
