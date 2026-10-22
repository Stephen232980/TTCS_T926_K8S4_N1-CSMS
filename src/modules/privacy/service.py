from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.alerts.models import AlertEmail
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import LoginIpAttempt, Session, User
from src.modules.identity.security import verify_password
from src.modules.ocpp.admin_health_models import (
    OcppTelemetryBucket,
    SystemHealthSample,
)
from src.modules.privacy.default_policy import VERSION
from src.modules.privacy.models import (
    PrivacyJob,
    PrivacyPolicy,
    PrivacyRequest,
)
from src.modules.privacy.schemas import (
    AnonymizeUserResponse,
    LegalHoldResponse,
    PrivacyDecision,
    PrivacyReceipt,
    RetentionCleanupResponse,
    RetentionPoliciesResponse,
    RetentionPolicyItem,
)
from src.modules.reservations.models import HOLDS, Reservation
from src.modules.stations.models import StationCreateIdempotency
from src.modules.wallet.administration import dieu_chinh_vi
from src.modules.wallet.exceptions import WalletReconciliationError
from src.modules.wallet.models import Wallet
from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky


class PrivacyRetentionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_retention_policies(self) -> RetentionPoliciesResponse:
        now = datetime.now(UTC)

        cutoff_login = now - timedelta(days=settings.retention_login_attempts_days)
        cutoff_sessions = now - timedelta(days=settings.retention_expired_sessions_days)
        cutoff_idempotency = now - timedelta(days=settings.retention_idempotency_days)
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

        # Pending is unresolved evidence, regardless of its age.
        count_pending = 0

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
                policy_type="Tin nhắn OCPP chờ xử lý",
                retention_threshold=f"{settings.retention_pending_messages_days} ngày",
                description="Giữ lại để phục hồi/đối soát; chưa có policy xác nhận mồ côi",
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
            blocked_reason="Cleanup kỹ thuật nằm ngoài phạm vi AC gốc S-57",
        )

    async def run_retention_cleanup(
        self,
        actor_id: UUID | None = None,
        permission: str | None = None,
    ) -> RetentionCleanupResponse:
        # A time threshold is not approval to destroy evidence. Keep the worker
        # alive, but make both scheduled and manual calls safe until an approved
        # data-class policy and hold-aware batch executor are implemented.
        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="system.retention_cleanup_blocked",
            object_type="system",
            object_id="retention",
            data={"reason_code": "retention_policy_unavailable", "total_deleted": 0},
            permission=permission or "admin.privacy.manage",
        )
        await self.db.commit()
        return RetentionCleanupResponse(executed_at=datetime.now(UTC))

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
        await self.db.execute(text("SELECT pg_advisory_xact_lock(57170028)"))
        user = await self._lock_user(user_id)
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

        # The old direct endpoint cannot bypass request approval.
        raise HTTPException(
            409,
            "privacy_execution_unavailable: Dùng luồng yêu cầu đã duyệt; tài khoản chưa bị thay đổi",
        )

    async def _lock_user(self, user_id: UUID) -> User:
        user = await self.db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise HTTPException(404, "Tài khoản không tồn tại")
        return user

    async def create_request(
        self, user_id: UUID, password: str, reason: str
    ) -> PrivacyReceipt:
        user = await self._lock_user(user_id)
        now = datetime.now(UTC)
        if user.status != "active" or (user.locked_until and user.locked_until > now):
            raise HTTPException(403, "Xác thực lại không thành công")
        if not verify_password(user.password_hash, password):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.auth_max_failed_attempts:
                user.locked_until = now + timedelta(seconds=settings.auth_lock_seconds)
            await self.db.commit()
            raise HTTPException(403, "Xác thực lại không thành công")
        user.failed_login_count = 0
        user.locked_until = None
        request = await self.db.scalar(
            select(PrivacyRequest).where(
                PrivacyRequest.user_id == user_id,
                PrivacyRequest.status.in_(("pending", "approved")),
            )
        )
        if request is None:
            request = PrivacyRequest(user_id=user_id, reason=reason, status="pending")
            self.db.add(request)
            await self.db.flush()
            await ghi_nhat_ky(
                self.db,
                actor_id=user_id,
                action="privacy.request_created",
                object_type="privacy_request",
                object_id=str(request.id),
                data={"status": "pending"},
                permission="driver.privacy.request",
                actor_roles=["driver"],
            )
        receipt = await self._receipt(request)
        await self.db.commit()
        return receipt

    async def list_requests(self, user_id: UUID | None = None) -> list[PrivacyReceipt]:
        query = (
            select(PrivacyRequest)
            .order_by(PrivacyRequest.created_at.desc(), PrivacyRequest.id.desc())
            .limit(100)
        )
        if user_id is not None:
            query = query.where(PrivacyRequest.user_id == user_id)
        rows = (await self.db.scalars(query)).all()
        return [await self._receipt(row) for row in rows]

    async def review_request(
        self,
        request_id: UUID,
        payload: PrivacyDecision,
        actor_id: UUID,
        authorization: AuthorizationEvidence,
    ) -> PrivacyReceipt:
        request = await self.db.scalar(
            select(PrivacyRequest)
            .where(PrivacyRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if request is None:
            raise HTTPException(404, "Yêu cầu không tồn tại")
        if request.status != "pending":
            raise HTTPException(409, "Yêu cầu đã được duyệt hoặc từ chối")
        if request.user_id == actor_id:
            raise HTTPException(409, "Không được tự duyệt yêu cầu của mình")
        if payload.decision == "approved" and (
            payload.policy_version != VERSION
            or await self.db.get(PrivacyPolicy, VERSION) is None
        ):
            raise HTTPException(409, "Policy chưa được hỗ trợ hoặc chưa được duyệt")
        request.status = payload.decision
        request.decision_reason = payload.reason
        request.policy_version = payload.policy_version
        request.reviewer_id = actor_id
        request.reviewed_at = datetime.now(UTC)
        if payload.decision == "approved":
            self.db.add(PrivacyJob(request_id=request.id))
        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="privacy.request_reviewed",
            object_type="privacy_request",
            object_id=str(request.id),
            data={"status": payload.decision, "policy_version": payload.policy_version},
            permission=authorization.permission,
            actor_roles=authorization.roles,
        )
        receipt = await self._receipt(request)
        await self.db.commit()
        return receipt

    async def _receipt(self, request: PrivacyRequest) -> PrivacyReceipt:
        job = await self.db.scalar(
            select(PrivacyJob).where(PrivacyJob.request_id == request.id)
        )
        blockers = []
        if request.policy_version != VERSION and request.status == "approved":
            blockers.append("approved_data_class_policy_required")
        if request.status != "approved":
            blockers.append(
                "approval_required"
                if request.status == "pending"
                else "request_rejected"
            )
        held, _ = await self.check_legal_hold(request.user_id)
        if held:
            blockers.append("legal_hold_or_unsettled_charging")
        cable = await self.db.scalar(
            select(ChargingSession.id)
            .where(
                ChargingSession.driver_id == request.user_id,
                ChargingSession.connector_released_at.is_(None),
            )
            .limit(1)
        )
        if cable is not None:
            blockers.append("connector_release_required")
        booking = await self.db.scalar(
            select(Reservation.id)
            .where(
                Reservation.driver_id == request.user_id,
                (
                    Reservation.status.in_(HOLDS)
                    | Reservation.fee_decision.in_(("pending", "review"))
                ),
            )
            .limit(1)
        )
        if booking is not None:
            blockers.append("reservation_or_fee_pending")
        wallet = await self.db.scalar(
            select(Wallet).where(Wallet.driver_id == request.user_id)
        )
        if wallet is not None and wallet.balance_vnd != 0:
            blockers.append(
                "refund_required"
                if wallet.balance_vnd > 0
                else "debt_resolution_required"
            )
        return PrivacyReceipt(
            id=request.id,
            user_id=request.user_id,
            status=request.status,
            reason=request.reason,
            created_at=request.created_at,
            reviewed_at=request.reviewed_at,
            decision_reason=request.decision_reason,
            policy_version=request.policy_version,
            wallet_balance_vnd=wallet.balance_vnd if wallet is not None else None,
            blockers=[] if job and job.status == "completed" else blockers,
            execution_status=job.status if job else "blocked",
            checkpoint=job.checkpoint if job else 0,
            last_error=job.last_error if job else None,
            retained_data=[
                "financial_documents_minimum_10_years",
                "deidentified_operational_measurements",
            ],
        )

    async def enqueue_execution(
        self,
        request_id: UUID,
        actor_id: UUID,
        authorization: AuthorizationEvidence,
        reason: str,
        *,
        external_refund_confirmed: bool = False,
        expected_balance_vnd: int | None = None,
    ) -> PrivacyReceipt:
        # Match the worker's job -> request -> user -> wallet lock order.
        job = await self.db.scalar(
            select(PrivacyJob)
            .where(PrivacyJob.request_id == request_id)
            .with_for_update()
        )
        request = await self.db.scalar(
            select(PrivacyRequest)
            .where(PrivacyRequest.id == request_id)
            .with_for_update()
        )
        if request is None:
            raise HTTPException(404, "Yêu cầu không tồn tại")
        if (
            request.user_id == actor_id
            or request.status != "approved"
            or request.policy_version != VERSION
        ):
            raise HTTPException(409, "Yêu cầu chưa đủ điều kiện duyệt")
        if (
            job is None
            and await self.db.scalar(
                select(PrivacyJob.id).where(PrivacyJob.request_id == request_id)
            )
            is not None
        ):
            raise HTTPException(409, "Hồ sơ vừa được duyệt; tải lại yêu cầu")
        await self._lock_user(request.user_id)
        # Repeated submissions must not change money or requeue a running job.
        if job is not None and job.status in {"queued", "processing", "completed"}:
            return await self._receipt(request)
        wallet = await self.db.scalar(
            select(Wallet).where(Wallet.driver_id == request.user_id).with_for_update()
        )
        receipt = await self._receipt(request)
        remaining = [code for code in receipt.blockers if code != "refund_required"]
        if remaining:
            raise HTTPException(409, ", ".join(remaining))
        if wallet is not None and wallet.balance_vnd > 0:
            if not external_refund_confirmed:
                raise HTTPException(409, "refund_required")
            if expected_balance_vnd != wallet.balance_vnd:
                raise HTTPException(
                    409, "Số dư đã thay đổi; tải lại hồ sơ và xác nhận lại"
                )
            audit_id = uuid4()
            try:
                await dieu_chinh_vi(
                    self.db,
                    wallet_id=wallet.id,
                    actor_id=actor_id,
                    amount_vnd=-wallet.balance_vnd,
                    audit_id=audit_id,
                    reason=f"Xác nhận hoàn tiền bên ngoài: {reason}"[:500],
                )
            except WalletReconciliationError as error:
                raise HTTPException(
                    409, "Sổ cái và số dư chưa khớp; cần đối chiếu ví"
                ) from error
            await ghi_nhat_ky(
                self.db,
                actor_id=actor_id,
                action="privacy.external_refund_confirmed",
                object_type="user",
                object_id=str(request.user_id),
                data={
                    "reason": reason,
                    "amount_vnd": expected_balance_vnd,
                    "method": "external_manual",
                },
                permission=authorization.permission,
                actor_roles=authorization.roles,
            )
        if job is None:
            self.db.add(PrivacyJob(request_id=request_id))
        elif job.status == "needs_review":
            job.status = "queued"
            job.last_error = None
        await ghi_nhat_ky(
            self.db,
            actor_id=actor_id,
            action="privacy.execution_queued",
            object_type="privacy_request",
            object_id=str(request_id),
            data={"reason": reason, "policy_version": VERSION},
            permission=authorization.permission,
            actor_roles=authorization.roles,
        )
        await self.db.commit()
        return await self._receipt(request)
