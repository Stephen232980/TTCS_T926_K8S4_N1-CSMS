# S-29 / T-65 — Kiểm tra khung giờ biểu giá

`src.modules.pricing.bands.kiem_khung_gio` là hàm thuần, không đọc DB.
Nhận danh sách `BandInput(start_min, end_min, energy_rate_vnd_per_kwh, label)`;
trả danh sách cùng kiểu đã tách vắt đêm và sắp xếp theo giờ bắt đầu.
Không thay đổi đầu vào. Thời gian là phút trong ngày địa phương của trạm.

- Bắt đầu: 0–1439; kết thúc: 0–1440. 1440 là 24:00, chỉ dùng ở cuối.
- Hai mốc bằng nhau bị từ chối; biểu giá cả ngày dùng 0–1440.
- 22:00–02:00 tách thành 00:00–02:00 và 22:00–24:00, giữ giá/nhãn.
- 22:00–00:00 chỉ sinh 22:00–24:00, không sinh đoạn rỗng.
- Giá là đồng nguyên không âm trong phạm vi BIGINT; không nhận bool/float.
- Các khung phải phủ kín 24 giờ đúng một lần, kể cả khi giá giống nhau.

Lỗi `TariffBandsError.issues` chứa `code`, `message`, `input_indices`
(chỉ số dòng đầu vào từ 0), `start_min`, `end_min`. Lỗi giờ/giá/nhãn
được trả trước kiểm phủ kín để tránh báo khoảng hở do dữ liệu không hợp lệ.
Lỗi phủ kín chỉ rõ tất cả khoảng hở/chồng, ví dụ `Khoảng hở 06:00–07:00`.

T-61/T-66 có thể chuyển lỗi thành HTTP 422 có vị trí dòng. T-66 chỉ ghi
Tariff/TariffBand sau khi hàm thành công, trong cùng giao dịch với guard T-68.
T-65 chưa thêm endpoint, form hoặc migration; chưa hoàn thành toàn bộ S-29.

Kiểm tra: `pytest tests/test_tariff_bands.py -q`. Các ca bao phủ ba khung,
chồng, hở, vắt đêm, mốc bằng nhau/ngoài ngày, khung thừa, dữ liệu tiền sai,
giữ nhãn/giá, đầu vào bất biến và nhiều khoảng lỗi. Không cần PostgreSQL
cho các test này; conftest chung vẫn yêu cầu DATABASE_URL có cú pháp hợp lệ.
