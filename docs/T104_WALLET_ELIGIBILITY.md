# T-104 — Kiểm số dư trước khi bắt đầu sạc

## Contract

`src.modules.wallet.eligibility.du_so_du_de_sac(session, *, driver_id, station_id, now=None)` trả `ChargingEligibility` gồm:

- `allowed`: đạt ngưỡng hay không.
- `reason`: `wallet_low`, `wallet_missing`, `wallet_locked`, `tariff_unavailable`, hoặc `None` khi đạt.
- `balance_vnd`, `minimum_balance_vnd`: số nguyên đồng; có thể rỗng khi dữ liệu cần thiết không khả dụng.
- `tariff_id`: phiên bản hiệu lực đã dùng, hoặc rỗng khi dùng dự phòng.

Hàm chỉ đọc; không tạo ví, không giữ tiền, không ghi sổ cái, không commit hoặc rollback transaction của người gọi. Trạm không tồn tại dùng lỗi `TariffNotFoundError` của T-68. `now` phải có timezone; mặc định lấy thời điểm UTC hiện tại và T-68 chuyển sang ngày địa phương của trạm.

## Quy tắc

- Có biểu giá hiệu lực: `CHARGING_MINIMUM_KWH × max(energy_rate_vnd_per_kwh)` trong các khung của phiên bản đó. Không cộng dự phòng.
- Chưa có biểu giá hiệu lực (kể cả chỉ có phiên bản tương lai): dùng `WALLET_RESERVE_VND`.
- Biểu giá đã có nhưng không có khung: từ chối với `tariff_unavailable`, không coi như chưa có biểu giá.
- Ví active có số dư không âm và bằng hoặc trên ngưỡng thì đạt. Số dư âm luôn bị từ chối, kể cả giá điện/ngưỡng bằng 0.
- Ví thiếu hoặc khóa bị từ chối; không thay đổi dữ liệu để khắc phục trong hàm kiểm.
- Hai tham số dùng chung toàn hệ thống, mặc định 5 kWh và 10.000 đồng; Compose truyền cấu hình tới app.

## Phạm vi

T-105 sẽ gọi hàm tại Authorize, StartTransaction và API bắt đầu sạc. T-106 hiển thị lý do/ngưỡng và nút nạp. Kết quả là snapshot, không phải bảo đảm số dư cho một lần bắt đầu trong tương lai; bên gọi cần kiểm lại tại thời điểm sử dụng. Không cache kết quả chấp nhận.

## Kiểm tra

`pytest tests/test_wallet_eligibility.py -q` dùng PostgreSQL đã migrate. Phủ các ca biên ngưỡng, nợ, dự phòng, nhiều khung, phiên bản cũ/tương lai, phạm vi trạm, ranh ngày địa phương, cấu hình khác mặc định, biểu giá miễn phí, ví thiếu/khóa và biểu giá thiếu khung. Các ca biên kiểm số dư không đổi và không tạo sổ cái.

Đây chưa phải bằng chứng hoàn thành toàn bộ S-38 hoặc kiểm tra staging.
