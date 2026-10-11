"""S-33 / T-83: Integration tests for immutable, deduplicated, and tamper-resistant invoices.

Ba test tích hợp theo mẫu T-29:
1. Lập hoá đơn hai lần cho một phiên thì một hoá đơn (Idempotency & Deduplication).
2. Đổi biểu giá sau đó thì hoá đơn cũ không đổi (Tariff snapshot immutability).
3. UPDATE hoặc DELETE bằng tài khoản ứng dụng bị từ chối (Database-level mutation protection).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.entrypoints.http import app
from src.modules.billing.closure import chot_phien
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.pricing.models import Tariff
from src.modules.pricing.service import (
    TariffImmutableError,
    kiem_bieu_gia_co_the_sua,
)
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_t80_invoicing import STAMP, lines, seed, tariff

db_session = isolated_session


async def test_t83_lap_hoa_don_hai_lan_cho_mot_phien_thi_mot_hoa_don(db_session):
    """Test 1: Lập hoá đơn hai lần cho một phiên thì một hoá đơn.

    Xác minh:
    - Gọi lập hoá đơn lần 1: tạo thành công 1 hoá đơn kèm các dòng diễn giải.
    - Gọi lập hoá đơn lần 2 qua lap_hoa_don: trả về cùng snapshot đã lưu, cùng ID.
    - Gọi chot_phien cho phiên này: tái sử dụng snapshot đã có, không tạo bản ghi mới.
    - SELECT COUNT(*) trên bảng invoices cho phiên sạc này chính xác bằng 1.
    - Số lượng dòng trong invoice_lines không bị nhân đôi.
    - API tài xế (GET /api/v1/driver/charging/sessions/{id}/invoice và /api/v1/driver/invoices)
      trả về đúng 1 hoá đơn ở trạng thái 'ready' với số tiền và dòng nguyên vẹn.
    """
    charging, station, driver, version = await seed(
        db_session,
        stamp=STAMP,
        duration=timedelta(hours=1),
        first=1000,
        last=6000,  # 5 kWh consumed
        with_tariff=True,
    )
    session_id = charging.id

    # Lập hoá đơn lần 1
    first_result = await lap_hoa_don(db_session, session_id)
    assert first_result.status == "ready"
    assert first_result.invoice is not None
    original_invoice_id = first_result.invoice.id
    original_total_vnd = first_result.invoice.total_vnd
    assert original_total_vnd == 15000  # 5 kWh * 3000 đ/kWh

    original_lines = await lines(db_session, first_result.invoice)
    assert len(original_lines) == 1
    original_line_ids = [line.id for line in original_lines]

    # Lập hoá đơn lần 2 bằng lap_hoa_don
    second_result = await lap_hoa_don(db_session, session_id)
    assert second_result.status == "ready"
    assert second_result.invoice is not None
    assert second_result.invoice.id == original_invoice_id
    assert second_result.invoice.total_vnd == original_total_vnd

    # Gọi chot_phien (luồng closure của T-81) cho cùng phiên sạc
    closure_result = await chot_phien(session_id, db=db_session)
    assert closure_result.status == "ready"
    assert closure_result.invoice is not None
    assert closure_result.invoice.id == original_invoice_id

    # Xác minh cấp Database: chỉ tồn tại duy nhất 1 bản ghi Invoice cho session_id
    invoice_count = await db_session.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.session_id == session_id)
    )
    assert invoice_count == 1

    # Xác minh các dòng hoá đơn không bị nhân bản
    current_lines = await lines(db_session, second_result.invoice)
    assert len(current_lines) == 1
    assert [line.id for line in current_lines] == original_line_ids

    # Xác minh qua API tài xế theo đúng hợp đồng T-82 và giao diện DriverInvoicePage
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver.id, roles=frozenset({"driver"})
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Tra cứu hoá đơn chi tiết theo phiên sạc
            detail_res = await client.get(
                f"/api/v1/driver/charging/sessions/{session_id}/invoice"
            )
            assert detail_res.status_code == 200
            detail_data = detail_res.json()
            assert detail_data["status"] == "ready"
            assert detail_data["invoice_id"] == str(original_invoice_id)
            assert detail_data["total_vnd"] == "15000"
            assert len(detail_data["lines"]) == 1
            assert Decimal(detail_data["lines"][0]["energy_kwh"]) == Decimal("5.0")
            assert detail_data["lines"][0]["rate_vnd"] == "3000"
            assert detail_data["lines"][0]["amount_vnd"] == "15000"

            # Danh sách hoá đơn của tài xế
            list_res = await client.get("/api/v1/driver/invoices")
            assert list_res.status_code == 200
            items = list_res.json()["items"]
            matching_items = [it for it in items if it["session_id"] == session_id]
            assert len(matching_items) == 1
            assert matching_items[0]["status"] == "ready"
            assert matching_items[0]["total_vnd"] == "15000"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi(db_session):
    """Test 2: Đổi biểu giá sau đó thì hoá đơn cũ không đổi.

    Xác minh:
    - Phiên 1 (Session 1) sạc và lập hoá đơn với Biểu giá A (Tariff A: 3.000 đ/kWh, idle 200 đ/phút).
    - Biểu giá A được đánh dấu used_at và không thể sửa đổi (TariffImmutableError).
    - Trạm sau đó ban hành Biểu giá B mới (Tariff B: 8.000 đ/kWh, idle 1.000 đ/phút).
    - Lập hoá đơn lại hoặc truy vấn Session 1: hoá đơn cũ giữ nguyên 100% snapshot
      (tổng tiền, đơn giá từng dòng và tariff_id vẫn là Biểu giá A).
    - API tài xế vẫn trả về nguyên vẹn hoá đơn ban đầu.
    - Phiên 2 mới (Session 2) tại cùng trạm thuộc thời điểm Biểu giá B sẽ nhận giá mới 8.000 đ/kWh.
    """
    # 1. Khởi tạo phiên 1 và Biểu giá A (3.000 đ/kWh)
    session_1, station, driver, tariff_a = await seed(
        db_session,
        stamp=STAMP,
        duration=timedelta(hours=1),
        first=0,
        last=10000,  # 10 kWh -> 30.000 đ
        with_tariff=True,
    )
    assert tariff_a is not None

    res_1 = await lap_hoa_don(db_session, session_1.id)
    assert res_1.status == "ready"
    assert res_1.invoice.total_vnd == 30000

    lines_1 = await lines(db_session, res_1.invoice)
    assert len(lines_1) == 1
    assert lines_1[0].rate_vnd == 3000
    assert lines_1[0].amount_vnd == 30000
    assert lines_1[0].tariff_id == tariff_a.id

    # 2. Xác nhận Biểu giá A đã bị khoá bất biến, không thể sửa
    with pytest.raises(TariffImmutableError):
        await kiem_bieu_gia_co_the_sua(
            db_session, station_id=station.id, tariff_id=tariff_a.id
        )

    # 3. Tạo Biểu giá B mới cho trạm (ngày hôm sau, giá 8.000 đ/kWh, idle 1.000 đ/phút)
    next_day = date(2026, 10, 11)
    tariff_b = await tariff(
        db_session,
        station,
        day=next_day,
        bands=[(0, 1440, 8000, "Giá mới toàn ngày")],
        idle=1000,
        grace=0,
    )

    # 4. Tái lập hoá đơn Session 1: xác nhận hoá đơn cũ không hề bị tính lại
    recheck_res_1 = await lap_hoa_don(db_session, session_1.id)
    assert recheck_res_1.invoice.id == res_1.invoice.id
    assert recheck_res_1.invoice.total_vnd == 30000  # Không đổi thành 80.000 đ!

    recheck_lines_1 = await lines(db_session, recheck_res_1.invoice)
    assert len(recheck_lines_1) == 1
    assert recheck_lines_1[0].rate_vnd == 3000  # Vẫn là đơn giá 3.000 đ/kWh của Biểu giá A
    assert recheck_lines_1[0].amount_vnd == 30000
    assert recheck_lines_1[0].tariff_id == tariff_a.id  # Không bị trỏ sang tariff_b.id

    # 5. Xác minh qua API tài xế cho Session 1
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver.id, roles=frozenset({"driver"})
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            api_res = await client.get(
                f"/api/v1/driver/charging/sessions/{session_1.id}/invoice"
            )
            assert api_res.status_code == 200
            data = api_res.json()
            assert data["total_vnd"] == "30000"
            assert data["lines"][0]["rate_vnd"] == "3000"
            assert data["lines"][0]["amount_vnd"] == "30000"
            assert data["lines"][0]["tariff_id"] == str(tariff_a.id)
    finally:
        app.dependency_overrides.pop(get_current_actor, None)

    # 6. Xác minh một phiên mới (Session 2) thuộc ngày có Biểu giá B nhận đúng giá mới
    session_2_stamp = datetime(2026, 10, 11, 2, 0, tzinfo=UTC)
    session_2, _, _, _ = await seed(
        db_session,
        stamp=session_2_stamp,
        duration=timedelta(hours=1),
        first=0,
        last=10000,  # 10 kWh
        with_tariff=False,
    )
    session_2.charge_point_id = session_1.charge_point_id
    session_2.connector_id = session_1.connector_id
    session_2.driver_id = driver.id
    await db_session.flush()

    res_2 = await lap_hoa_don(db_session, session_2.id)
    assert res_2.status == "ready"
    assert res_2.invoice.total_vnd == 80000  # 10 kWh * 8000 đ/kWh theo Biểu giá B

    lines_2 = await lines(db_session, res_2.invoice)
    assert len(lines_2) == 1
    assert lines_2[0].rate_vnd == 8000
    assert lines_2[0].tariff_id == tariff_b.id

    # Khẳng định lại lần cuối: Session 1 vẫn không thay đổi
    db_session.expire_all()
    saved_invoice_1 = await db_session.get(Invoice, res_1.invoice.id)
    assert saved_invoice_1.total_vnd == 30000


async def test_t83_update_hoac_delete_bang_tai_khoan_ung_dung_bi_tu_choi(db_session):
    """Test 3: UPDATE hoặc DELETE bằng tài khoản ứng dụng bị từ chối.

    Xác minh:
    - Bảng invoices và invoice_lines có trigger chặn UPDATE, DELETE, TRUNCATE.
    - Mọi câu lệnh sửa/xoá thông qua session/kết nối của ứng dụng đều bị PostgreSQL từ chối
      với lỗi 'invoice evidence is append-only'.
    - Kiểm tra vai trò runtime app role theo scripts/grant_invoice_evidence.sql:
      SELECT/INSERT được phép, nhưng UPDATE/DELETE/TRUNCATE bị từ chối quyền.
    - Ràng buộc khoá ngoại FK RESTRICT ngăn chặn xoá charging_sessions, stations, users, tariffs
      khi đang có hoá đơn tham chiếu.
    - Dữ liệu hoá đơn nguyên vẹn tuyệt đối sau các nỗ lực sửa/xoá bất thành.
    """
    charging, station, driver, version = await seed(db_session)
    result = await lap_hoa_don(db_session, charging.id)
    assert result.status == "ready"
    invoice = result.invoice
    invoice_line = (await lines(db_session, invoice))[0]

    # 1. Kiểm tra Trigger ngăn chặn UPDATE / DELETE / TRUNCATE
    mutation_statements = [
        f"UPDATE invoices SET total_vnd=0 WHERE id='{invoice.id}'",
        f"DELETE FROM invoices WHERE id='{invoice.id}'",
        "TRUNCATE invoices CASCADE",
        f"UPDATE invoice_lines SET amount_vnd=0 WHERE id='{invoice_line.id}'",
        f"DELETE FROM invoice_lines WHERE id='{invoice_line.id}'",
        "TRUNCATE invoice_lines",
    ]

    for stmt in mutation_statements:
        with pytest.raises(DBAPIError, match="invoice evidence is append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text(stmt))

    # 2. Kiểm tra vai trò runtime ứng dụng theo scripts/grant_invoice_evidence.sql
    role = "invoice_app_test_" + uuid4().hex
    await db_session.execute(
        text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOINHERIT')
    )
    script_path = Path("scripts/grant_invoice_evidence.sql")
    if script_path.exists():
        script_content = script_path.read_text(encoding="utf-8")
        for stmt in (
            "\n".join(s for s in script_content.splitlines() if not s.startswith(("--", "\\")))
            .replace(':"app_role"', f'"{role}"')
            .split(";")
        ):
            if stmt.strip() and stmt.strip() not in ("BEGIN", "COMMIT"):
                await db_session.execute(text(stmt))

        # Chuyển sang app role
        await db_session.execute(text(f'SET LOCAL ROLE "{role}"'))

        # SELECT thành công dưới quyền app role
        app_read_total = await db_session.scalar(
            select(Invoice.total_vnd).where(Invoice.id == invoice.id)
        )
        assert app_read_total == invoice.total_vnd

        # UPDATE / DELETE dưới quyền app role bị từ chối
        for table in ("invoices", "invoice_lines"):
            with pytest.raises(DBAPIError):
                async with db_session.begin_nested():
                    await db_session.execute(text(f"UPDATE {table} SET id=id"))

            with pytest.raises(DBAPIError):
                async with db_session.begin_nested():
                    await db_session.execute(text(f"DELETE FROM {table}"))

        await db_session.execute(text("RESET ROLE"))

    # 3. Kiểm tra bảo vệ toàn vẹn tham chiếu khoá ngoại (Foreign Key RESTRICT)
    # Không thể xoá các thực thể cha đang được hoá đơn hoặc dòng hoá đơn tham chiếu
    fk_deletions = [
        ("charging_sessions", "id", charging.id),
        ("stations", "id", station.id),
        ("users", "id", driver.id),
        ("tariffs", "id", version.id),
    ]

    for table, column, target_id in fk_deletions:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"DELETE FROM {table} WHERE {column}=:target_id"),
                    {"target_id": target_id},
                )

    # 4. Xác nhận dữ liệu hoá đơn vẫn nguyên vẹn sau toàn bộ các thao tác trên
    db_session.expire_all()
    surviving_invoice = await db_session.get(Invoice, invoice.id)
    assert surviving_invoice is not None
    assert surviving_invoice.total_vnd == invoice.total_vnd
    surviving_lines = await lines(db_session, surviving_invoice)
    assert len(surviving_lines) == 1
    assert surviving_lines[0].id == invoice_line.id
