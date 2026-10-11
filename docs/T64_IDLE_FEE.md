# S-28 / T-64 — Tính phí chiếm trụ

Hàm thuần `src.modules.billing.idle_fee.tinh_phi_chiem_tru` nhận
`idle_since`, `session_end`, `grace_minutes`, `idle_rate_vnd_per_minute`;
trả tuple `(số phút tính phí, thành tiền đồng nguyên)`.

Trừ ân hạn trước, làm tròn lên phần thời gian còn lại theo phút, rồi nhân
đơn giá nguyên đồng/phút. Phép tính dùng microsecond nguyên, không dùng float.
Không có `idle_since`, chưa hết ân hạn hoặc đúng bằng ân hạn thì trả `(0, 0)`.
Ví dụ chiếm trụ 35 phút 20 giây, ân hạn 5 phút, giá 200 đồng/phút:
phần tính phí là 30 phút 20 giây → 31 phút → 6.200 đồng.

Các thời điểm phải có múi giờ; tính thời lượng theo UTC. Thời điểm kết thúc
lấy từ StopTransaction, không phải lúc rút súng. Thời gian kết thúc trước
idle_since và số phút/đơn giá âm bị từ chối bằng ValueError; float/bool cho
tham số số nguyên bị từ chối bằng TypeError. Đơn giá 0 vẫn trả số phút tính phí.

| Tiêu chí | Bằng chứng |
| --- | --- |
| Không chiếm trụ, trước/bằng ân hạn, 30 phút, 30 phút 20 giây, ân hạn 0 | Bảy ca `test_required_table` |
| Vượt ân hạn 1 microsecond tính 1 phút | Ca thứ bảy trong bảng |
| Qua nửa đêm và khác offset | `test_offsets_and_midnight_use_actual_elapsed_time` |
| Tiền nguyên chính xác, dữ liệu sai | Test số lớn, đơn giá 0, kiểu sai, số âm, thời gian đảo/ngây thơ |

Chạy `pytest tests/test_t64_idle_fee.py -q`. Không đọc database; conftest
chung vẫn yêu cầu DATABASE_URL có cú pháp hợp lệ.

T-64 không thêm idle_since (T-63), không nối lập hoá đơn (T-80) và không
chứng minh toàn bộ S-28 đã Done. T-63 cung cấp khoảng chiếm trụ cần tính;
T-80 truyền thời điểm StopTransaction và dữ liệu biểu giá vào hàm này.
