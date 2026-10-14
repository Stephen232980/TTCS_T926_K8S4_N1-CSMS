# T-80 / S-33 — Lập hoá đơn từ phiên sạc

PR #116 được sửa bằng commit bổ sung, giữ lịch sử của thành viên. Nghiệp vụ
`lap_hoa_don` chuyển vào `src.modules.billing.invoicing`; phép nhân giá cố định
và bản in minh hoạ trong simulator được gỡ. Simulator tiếp tục chỉ gửi/kiểm chứng OCPP.

## Hợp đồng để T-81 tích hợp

```python
from src.modules.billing.invoicing import lap_hoa_don
from src.platform.database.session import SessionFactory


async def build_invoice(session_id: int):
    async with SessionFactory() as db, db.begin():
        result = await lap_hoa_don(db, session_id)
        # Commit cả kết quả thành công lẫn review_reasons của trường hợp từ chối.
    return result
```

`lap_hoa_don(db, session_id)` nhận session DB của caller, không tự commit.
`InvoiceResult` gồm `status`, `invoice` và `reason`:

- `ready`: hoá đơn mới hoặc snapshot đã lưu cho phiên; đọc các dòng bằng `invoice.id`.
- `pending`: phiên chưa kết thúc; không gắn lý do review vĩnh viễn.
- `needs_review`: phiên đã có lý do cần xem xét hoặc dữ liệu không thể lập hoá đơn.
  Không trả tiền tạm. Lý do mới được lưu vào `charging_sessions.review_reasons`,
  caller cần commit để màn hình T-82 đọc được.
- Phiên không tồn tại: `InvoiceSessionNotFoundError`.
- Lỗi DB/kỹ thuật: propagate để caller rollback/retry, không chuyển thành thanh toán thành công.

T-81 gọi sau khi giao dịch StopTransaction đã commit; không thêm tính tiền vào
đường trả lời OCPP trong T-80. T-102 sở hữu trừ ví và đặt `settlement_*`.
Hàm này không tạo ledger, trừ ví hay đánh dấu hoàn tất thanh toán.

## Dữ liệu và tính tiền

Đọc phiên, tài xế, quan hệ trạm/đầu nối, timezone và dữ liệu đo đã lưu. Chọn chuỗi
`Energy.Active.Import.Register`, phase rỗng, location `Outlet`, unit `Wh` theo
T-40; các chỉ số đầu/cuối từ StartTransaction/StopTransaction làm hai mốc biên.
Không cộng số đo tổng với từng pha, không nhân lại 1000 với dữ liệu đã chuẩn hoá.
Số đo trùng biên nhưng khác giá trị, không hữu hạn, âm, giảm hoặc sai đơn vị bị từ chối.

Chọn phiên bản T-68 hiệu lực theo từng ngày địa phương, kiểm khung phủ kín 24 giờ
bằng T-65, gọi `chia_doan` thật (T-70/T-73, làm tròn T-71). Không có giá mặc định.
Khoảng kết thúc đúng nửa đêm không yêu cầu giá của ngày tiếp theo. Lưu Wh Decimal,
đơn giá/thành tiền nguyên đồng, cờ nội suy và UUID phiên bản vào từng dòng.
Tổng bằng tổng dòng đã làm tròn, không tính lại từ tổng kWh. Từ chối tổng vượt BIGINT.
Phiên không tiêu thụ có thể có hoá đơn tổng 0; vẫn không đặt dấu settlement.

## Quyết định phí chiếm trụ trong phần bổ sung

Người dùng đã uỷ quyền chốt quy tắc trong phiên triển khai T-80 ngày 11/10/2026.
Dùng khoảng cuối `idle_since` mà T-63 đang lưu tới `StopTransaction`, gọi T-64:

1. Lấy ân hạn từ biểu giá hiệu lực tại `idle_since`, trừ một lần cho cả khoảng.
2. Phần còn lại làm tròn lên theo phút một lần. Mỗi phút bắt đầu dùng mức phí của
   phiên bản hiệu lực tại thời điểm đầu phút, theo ngày địa phương của trạm.
3. Nhóm các phút cùng ngày thành dòng snapshot; không làm tròn thêm hay áp lại
   ân hạn khi cắt ngày. Một phút bắt đầu trước nửa đêm có thể kết thúc ở ngày sau.

Ví dụ 35 phút 20 giây, ân hạn 5 phút, 200 đồng/phút: 31 phút × 200 = 6.200 đồng.
Khoảng 23:59:30–00:01:00, ân hạn 0: hai phút bắt đầu, một theo giá ngày cũ,
một theo giá ngày mới. Không dùng giờ chạy job để tính thêm thời gian.

Đây là phạm vi có dữ liệu tại lúc đóng phiên. T-80 không tự suy ra các khoảng idle
trước đã bị T-63 xoá khi Charging, và không thu phần Finishing sau StopTransaction.
Phần tới lúc rút súng trong AC gốc S-28 cần luồng ghi nhận/hạch toán riêng; chưa
nghiệm thu toàn bộ S-28 hoặc tự đổi schema một hoá đơn bất biến mỗi phiên.

## Transaction và chống trùng

Khoá phiên rồi trạm, lấy biểu giá đã khoá từ `danh_dau_bieu_gia_da_dung` trước
khi sao chép dữ liệu. Giữ khoá tới cuối transaction của caller. Unique T-79 theo
phiên là lớp bảo vệ DB; caller thứ hai chờ khoá và đọc snapshot đã commit.
Savepoint bảo đảm lỗi validation/ghi dòng không để lại header, dòng hoặc dấu
`used_at` dở dang. Sau lỗi nghiệp vụ, ghi lý do review ngoài savepoint.
Rollback transaction ngoài cũng rollback toàn bộ hoá đơn và dấu dùng biểu giá.
Không UPDATE/DELETE snapshot, không tắt trigger bất biến.

## Coverage và điều kiện nghiệm thu

| AC/NFR | Bằng chứng T-80 |
| --- | --- |
| Đọc phiên và giá thực, lưu diễn giải từng đoạn | Test một khung, ranh 22h, hai phiên bản qua nửa đêm, timezone khác UTC; đọc snapshot qua API T-82 |
| Giá cũ không đổi khi có phiên bản mới | Retry trả cùng ID/dòng/tổng; guard chặn sửa phiên bản đã dùng |
| Phiên cần xem xét/thiếu giá không có tiền tạm | NL-01/NL-02, commit rồi đọc lại lý do trên phiên |
| Tiền nguyên chính xác, không float | Decimal phần lẻ, làm tròn từng dòng, context nhỏ, zero, BIGINT overflow |
| Phí đã ghi nhận tới StopTransaction | T-64: ân hạn, ceil, qua ngày đổi giá nhưng không thêm phút/ân hạn |
| Không trùng và ghi nhất quán | Hai worker PostgreSQL thật; xác nhận chờ bằng pg_blocking_pids; rollback ngoài và lỗi INSERT dòng |
| Hợp đồng số đo T-40 | OCPP Wh/kWh tới DB tới hoá đơn; bỏ qua measurand/phase/location khác, từ chối sai đơn vị/biên/số lùi |

Không có API/migration mới. Test không dùng mock bộ tính tiền và không sửa trigger.
Chạy `pytest tests/test_t80_invoicing.py -q`, rồi lint/format/mypy và full backend
trên PostgreSQL sạch; hai gate latency chạy riêng trên Linux như CI.

Các con số kỳ vọng trong test là regression của implementation, không thay thế
tệp đáp án độc lập `dap_an_tay` có người/ngày tính của T-77. Tài liệu refinement
nhận được chưa có tệp đó; chưa tuyên bố đạt dependency nghiệm thu T-77/S-32.
T-81 còn phải nối StopTransaction/job; PR này không chứng minh luồng tự lập hoá đơn
trên staging, Jira Done hay toàn bộ S-33 đã hoàn tất.
