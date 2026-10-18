# Gói thuê bao tháng

## Quy tắc

- Chủ trạm tạo gói cho trạm thuộc quyền sở hữu; mỗi gói có phí tháng và biểu
  giá điện theo khung giờ riêng. Khung giá phải phủ kín ngày, không chồng lấn.
- Tài xế trả trước phí tháng từ ví khi đăng ký. Mỗi tài xế chỉ có một gói đang
  hiệu lực hoặc đang nợ phí tại một trạm.
- Chu kỳ là một tháng lịch UTC kể từ lúc thanh toán; ngày cuối tháng được chốt
  vào ngày cuối cùng của tháng kế tiếp. Ví dụ ngày 31/01 gia hạn ngày cuối
  tháng 02.
- Worker thử gia hạn mỗi phút. Nếu ví khóa hoặc không đủ tiền, gói chuyển
  `past_due`, không áp dụng giá ưu đãi sau khi hết kỳ đã thanh toán và được
  thử thu lại mỗi ngày. Khi nạp đủ tiền, kỳ mới bắt đầu tại thời điểm thu
  thành công.
- Hủy gói ngăn lần gia hạn kế tiếp; quyền lợi còn hiệu lực hết kỳ đã thanh
  toán. Ngừng bán gói chỉ chặn đăng ký mới, không tự hủy các gói hiện hành.
- Biểu giá thuê bao chỉ thay giá điện. Phí chiếm trụ vẫn lấy theo biểu giá
  thường của trạm. Hóa đơn giữ `subscription_plan_id` trên từng dòng điện để
  chỉ rõ nguồn giá.
- Phí thuê bao là bút toán `subscription_debit` riêng, âm, tham chiếu gói
  thuê bao và được ghi cùng giao dịch cập nhật số dư. Đăng ký/gia hạn thất bại
  không ghi bút toán.

## API

Owner, chỉ `station_owner` sở hữu trạm, quyền `owner.subscription.manage`:

- `POST /api/v1/owner/stations/{station_id}/subscription-plans` tạo gói.
- `GET /api/v1/owner/stations/{station_id}/subscription-plans` liệt kê gói.
- `POST /api/v1/owner/stations/{station_id}/subscription-plans/{plan_id}/deactivate`
  ngừng bán gói.

Ví dụ request tạo gói:

```json
{
  "name": "Thành viên tháng",
  "monthly_fee_vnd": 200000,
  "bands": [
    {
      "start_min": 0,
      "end_min": 1440,
      "energy_rate_vnd_per_kwh": 2200,
      "label": "Cả ngày"
    }
  ]
}
```

Driver, chỉ tài khoản `driver`:

- `GET /api/v1/driver/subscriptions/plans?station_id={uuid}` xem gói đang bán.
- `POST /api/v1/driver/subscriptions/plans/{plan_id}` đăng ký và thu phí tháng
  ngay; `402` nếu ví không đủ, `409` nếu đã có quyền lợi còn hiệu lực.
- `GET /api/v1/driver/subscriptions` xem các gói còn hiệu lực.
- `DELETE /api/v1/driver/subscriptions/{subscription_id}` hủy gia hạn.

Tiền trong API được trả dưới dạng chuỗi VND. Thời gian trả theo ISO 8601 có
múi giờ. API dùng cookie session và kiểm tra vai trò ở backend.

## Hóa đơn

Khi bắt đầu phiên sạc trong kỳ đã thanh toán, giá năng lượng dùng các khung
của gói đó cho toàn bộ phiên. Dòng năng lượng chứa `subscription_plan_id`;
dòng phí chiếm trụ tiếp tục tham chiếu biểu giá trạm. Giá và phí được chụp vào
hóa đơn bất biến, không bị thay đổi nếu gói ngừng bán sau đó.
