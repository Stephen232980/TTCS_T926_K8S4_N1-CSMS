# T-77 / S-32 — Bảng đáp án và phép tính độc lập

Ngày chuẩn bị: 11/10/2026. Người làm: Hoàng Hữu Đạt. Người review: Đào Minh Tâm. Codex hỗ trợ chuẩn bị phép tính; Ngày tính tay và ngày review: 11/10/2026 (theo thông tin người dùng cung cấp).

Đây là bảng đối chiếu theo công thức nghiệp vụ, không dùng hàm tính tiền CSMS để sinh đáp án. Đào Minh Tâm đã xác nhận T-77 trong chat ngày 11/10/2026. Người viết phần tính tiền đã được hỗ trợ trong cùng chat; tính độc lập về công thức không thay thế yêu cầu độc lập về người.

## Nguồn và các đầu vào bổ sung

Backlog CSMS.xlsx, S-32 yêu cầu ít nhất 12 ca và đối chiếu từng đồng. Bảng phân công Chia_viec_Sprint_4-5_cap_nhat.xlsx yêu cầu kế hoạch 16 ca; người dùng đã xác nhận backlog chỉ yêu cầu tối thiểu 12 và yêu cầu mở rộng độ phủ. Sheet Ca kiểm thử S-32 chỉ mô tả KT-01–KT-03, KT-04–KT-16 là placeholder vì thiếu Backlog_CSMS_refined_S4-5.xlsx. Giữ nguyên ý nghĩa ba ca đầu. 19 ca sau là bộ bổ sung theo yêu cầu người dùng để phủ AC; mọi ngày, đơn giá và số đo bổ sung là dữ liệu thử, không phải mức giá kinh doanh hoặc đề bài gốc đã được phê duyệt.

## Công thức và cấu trúc

- Thời gian ISO-8601 có offset; mặc định timezone Asia/Ho_Chi_Minh (+07:00), KT-20 dùng America/Los_Angeles (−07:00 tại ngày thử). Ngày biểu giá là ngày địa phương, không phải ngày UTC. 00:00 ngày 11/10 tương ứng 17:00 UTC ngày 10/10.
- Khung giờ [từ, đến). Nội suy chỉ số tích lũy tại ranh trong cặp số đo kề ranh: E(t)=E(a)+(E(b)-E(a))×(t-a)/(b-a). Làm tròn nửa lên chỉ số Wh tại ranh; Wh đoạn bằng hiệu hai chỉ số đã làm tròn. Không làm tròn riêng mỗi delta. Bộ ca dùng số đo biên nguyên Wh.
- Tiền đoạn = làm tròn nửa lên(Wh đoạn × đồng/kWh / 1000); tổng điện = cộng tiền từng đoạn. Không gộp Wh rồi làm tròn tiền một lần. Đoạn 0 giây hoặc 0 Wh không sinh dòng.
- Phút idle = ceil(max(0, thời gian idle tính bằng giây - ân hạn×60)/60). Không idle thì 0 phút. Một phút bắt đầu tính trọn phút; không tăng điện năng giả trong lúc idle.
- Dùng khoảng idle cuối đã ghi nhận tới Stop. Qua ngày: ân hạn trừ một lần từ giá lúc idle bắt đầu; mỗi phút tính phí dùng giá tại đầu phút. KT-16 kiểm phạm vi T-80 này; phần sau Stop tới rút súng của S-28 chưa được nghiệm thu.
- Cờ nội suy true nếu ranh đầu/cuối đoạn cần suy từ số đo; dữ liệu trong đoạn không tạo thêm dòng nếu vẫn cùng khung/ngày. KT-16 có số đo tại nửa đêm nên false.

Biểu giá A (10/10): 00–06: 2000; 06–22: 3000; 22–24: 2000 đ/kWh, idle 200 đ/phút, grace 5 phút. AB thêm 11/10: 2500/3500/2500, idle 300, grace 5. R dùng 2500 cho cả ba khung, nhãn vẫn khác; idle 200, grace 5. ABC dùng A ngày 10/10, giá B ngày 11/10 và kế thừa B ngày 12/10 (effective_from vẫn 11/10, không tạo phiên bản mới).

JSON là dữ liệu đầu vào/expected cố định cho T-78; Excel chứa công thức số học để kiểm tra và dễ đọc. Không xuất lại JSON expected từ kết quả hàm sản phẩm hoặc từ Excel sau khi sửa đầu vào. Thay đổi đề bài/đáp án cần review, cập nhật đồng thời cả hai tệp và phiên bản.

## Tổng đáp án

| Ca | Điện (đ) | Idle (đ) | Tổng (đ) | Đề bài |
|---|---:|---:|---:|---|
| KT-01 | 6000 | 0 | 6000 | Mot khung, khong chiem tru |
| KT-02 | 45000 | 0 | 45000 | 21:30–23:30, ranh 22:00 |
| KT-03 | 22500 | 0 | 22500 | Qua ngay, doi bieu gia |
| KT-04 | 2000 | 0 | 2000 | Bat dau dung ranh 22:00 |
| KT-05 | 3000 | 0 | 3000 | Ket thuc dung ranh 22:00 |
| KT-06 | 3000 | 0 | 3000 | Cat ranh 06:00 |
| KT-07 | 52000 | 0 | 52000 | Ba khung, hai ranh |
| KT-08 | 3600 | 0 | 3600 | So do thua, doc theo cap ke nhau |
| KT-09 | 13 | 0 | 13 | Noi suy .5 Wh, bao toan tong |
| KT-10 | 3 | 0 | 3 | Tien tai diem nua dong |
| KT-11 | 6 | 0 | 6 | Lam tron moi doan roi cong |
| KT-12 | 0 | 0 | 0 | Khong tang dien nang |
| KT-13 | 3000 | 1000 | 4000 | Chiem tru vuot an han 5 phut |
| KT-14 | 3000 | 0 | 3000 | Chiem tru dung an han |
| KT-15 | 3000 | 200 | 3200 | Vuot an han mot giay |
| KT-16 | 2000 | 4300 | 6300 | Chiem tru qua ngay, an han mot lan |
| KT-17 | 3000 | 0 | 3000 | Idle dưới ân hạn |
| KT-18 | 3000 | 200 | 3200 | Đúng một phút sau ân hạn |
| KT-19 | 80500 | 0 | 80500 | 26 giờ, ba ngày và giá hiệu lực kế thừa |
| KT-20 | 22500 | 0 | 22500 | Múi giờ trạm khác UTC+7 |
| KT-21 | 2 | 0 | 2 | Đoạn ranh 0 Wh được bỏ, phiên vẫn có Wh |
| KT-22 | 3000 | 1000 | 4000 | Nhiều khoảng idle, chỉ thu khoảng cuối |

## Phép tính từng ca

### KT-01 — Mot khung, khong chiem tru

Mo ta nguon; dau vao so duoc bo sung.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 3000 Wh.

3000 - 1000 = 2000 Wh; 2000 × 3000 / 1000 = 6000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 2000 | 3000 | Ban ngay | false | 6000 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 6000 đ.

### KT-02 — 21:30–23:30, ranh 22:00

Mo ta nguon; dau vao so duoc bo sung.

Phiên 2026-10-10T21:30:00+07:00 → 2026-10-10T23:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T21:30:00+07:00 = 0 Wh; 2026-10-10T23:30:00+07:00 = 20000 Wh.

Ranh: 0 + 20000 × 30/120 = 5000 Wh; đoạn sau 20000 - 5000 = 15000 Wh; tiền 15000 + 30000 = 45000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 21:30:00 | 2026-10-10T22:00:00+07:00 | 5000 | 3000 | Ban ngay | true | 15000 |
| 2026-10-10 | 22:00:00 | 2026-10-10T23:30:00+07:00 | 15000 | 2000 | Dem muon | true | 30000 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 45000 đ.

### KT-03 — Qua ngay, doi bieu gia

Mo ta nguon; dau vao so duoc bo sung.

Phiên 2026-10-10T23:00:00+07:00 → 2026-10-11T01:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá AB. Số đo: 2026-10-10T23:00:00+07:00 = 0 Wh; 2026-10-11T01:00:00+07:00 = 10000 Wh.

Nửa đêm: 10000 × 60/120 = 5000 Wh; 5000 × 2000/1000 + 5000 × 2500/1000 = 22500 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 23:00:00 | 2026-10-11T00:00:00+07:00 | 5000 | 2000 | Dem muon | true | 10000 |
| 2026-10-11 | 00:00:00 | 2026-10-11T01:00:00+07:00 | 5000 | 2500 | Dem som | true | 12500 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 22500 đ.

### KT-04 — Bat dau dung ranh 22:00

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T22:00:00+07:00 → 2026-10-10T23:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T22:00:00+07:00 = 0 Wh; 2026-10-10T23:00:00+07:00 = 1000 Wh.

22:00 thuộc khung đêm muộn [22:00,24:00); 1000 × 2000/1000 = 2000 đ; không có đoạn 0 giây.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 22:00:00 | 2026-10-10T23:00:00+07:00 | 1000 | 2000 | Dem muon | false | 2000 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 2000 đ.

### KT-05 — Ket thuc dung ranh 22:00

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T21:00:00+07:00 → 2026-10-10T22:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T21:00:00+07:00 = 0 Wh; 2026-10-10T22:00:00+07:00 = 1000 Wh.

Khoảng [21:00,22:00) chỉ thuộc ban ngày: 1000 × 3000/1000 = 3000 đ; không sinh đoạn sau Stop.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 21:00:00 | 2026-10-10T22:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3000 đ.

### KT-06 — Cat ranh 06:00

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T05:30:00+07:00 → 2026-10-10T06:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T05:30:00+07:00 = 0 Wh; 2026-10-10T06:30:00+07:00 = 1200 Wh.

1200 × 30/60 = 600 Wh mỗi đoạn; 1200 + 1800 = 3000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 05:30:00 | 2026-10-10T06:00:00+07:00 | 600 | 2000 | Dem som | true | 1200 |
| 2026-10-10 | 06:00:00 | 2026-10-10T06:30:00+07:00 | 600 | 3000 | Ban ngay | true | 1800 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3000 đ.

### KT-07 — Ba khung, hai ranh

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T05:00:00+07:00 → 2026-10-10T23:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T05:00:00+07:00 = 0 Wh; 2026-10-10T23:00:00+07:00 = 18000 Wh.

18000/18 = 1000 Wh/giờ; chỉ số tại 06:00 = 1000, tại 22:00 = 17000; ΔWh = 1000,16000,1000; tiền 2000 + 48000 + 2000 = 52000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 05:00:00 | 2026-10-10T06:00:00+07:00 | 1000 | 2000 | Dem som | true | 2000 |
| 2026-10-10 | 06:00:00 | 2026-10-10T22:00:00+07:00 | 16000 | 3000 | Ban ngay | true | 48000 |
| 2026-10-10 | 22:00:00 | 2026-10-10T23:00:00+07:00 | 1000 | 2000 | Dem muon | true | 2000 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 52000 đ.

### KT-08 — So do thua, doc theo cap ke nhau

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T21:30:00+07:00 → 2026-10-10T22:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T21:30:00+07:00 = 0 Wh; 2026-10-10T21:50:00+07:00 = 300 Wh; 2026-10-10T22:30:00+07:00 = 1500 Wh.

Ranh thuộc cặp 21:50–22:30: 300 + (1500-300) × 10/40 = 600 Wh; ΔWh = 600,900; tiền 1800 + 1800 = 3600 đ. Không nội suy đều cả phiên.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 21:30:00 | 2026-10-10T22:00:00+07:00 | 600 | 3000 | Ban ngay | true | 1800 |
| 2026-10-10 | 22:00:00 | 2026-10-10T22:30:00+07:00 | 900 | 2000 | Dem muon | true | 1800 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3600 đ.

### KT-09 — Noi suy .5 Wh, bao toan tong

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T21:30:00+07:00 → 2026-10-10T22:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T21:30:00+07:00 = 100 Wh; 2026-10-10T22:30:00+07:00 = 105 Wh.

Chỉ số ranh 100 + 5 × 30/60 = 102.5 → 103 Wh; ΔWh = 103-100 = 3 và 105-103 = 2; tiền 9 + 4 = 13 đ. Không làm tròn riêng hai delta thành 3+3.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 21:30:00 | 2026-10-10T22:00:00+07:00 | 3 | 3000 | Ban ngay | true | 9 |
| 2026-10-10 | 22:00:00 | 2026-10-10T22:30:00+07:00 | 2 | 2000 | Dem muon | true | 4 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 13 đ.

### KT-10 — Tien tai diem nua dong

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T23:00:00+07:00 → 2026-10-10T23:01:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá R. Số đo: 2026-10-10T23:00:00+07:00 = 0 Wh; 2026-10-10T23:01:00+07:00 = 1 Wh.

1 × 2500/1000 = 2.5 → 3 đ (nửa lên).

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 23:00:00 | 2026-10-10T23:01:00+07:00 | 1 | 2500 | Dem muon | false | 3 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3 đ.

### KT-11 — Lam tron moi doan roi cong

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T21:30:00+07:00 → 2026-10-10T22:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá R. Số đo: 2026-10-10T21:30:00+07:00 = 0 Wh; 2026-10-10T22:30:00+07:00 = 2 Wh.

Chỉ số ranh 1 Wh; hai đoạn nhãn khác nhau dù cùng giá; mỗi đoạn 1 × 2500/1000 = 2.5 → 3 đ; tổng 6 đ, không phải 5 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 21:30:00 | 2026-10-10T22:00:00+07:00 | 1 | 2500 | Ban ngay | true | 3 |
| 2026-10-10 | 22:00:00 | 2026-10-10T22:30:00+07:00 | 1 | 2500 | Dem muon | true | 3 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 6 đ.

### KT-12 — Khong tang dien nang

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 42 Wh; 2026-10-10T11:00:00+07:00 = 42 Wh.

42 - 42 = 0 Wh; không sinh dòng điện 0 Wh; không chiếm trụ nên tổng 0 đ. Là ca tính tiền 0, không phải ca thiếu biểu giá hoặc cần xem xét.


Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 0 đ.

### KT-13 — Chiem tru vuot an han 5 phut

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:50:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Điện 3000 đ; idle 600 giây - 300 giây ân hạn = 300 giây; ceil(300/60)=5 phút; 5 × 200=1000 đ; tổng 4000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:50:00+07:00; 600 giây; grace 5 phút; phút thu 5; phí 1000 đ. Tổng 4000 đ.

### KT-14 — Chiem tru dung an han

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:55:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Idle 300 giây = ân hạn 300 giây; max(0,300-300)=0; phí 0 đ; tổng 3000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:55:00+07:00; 300 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3000 đ.

### KT-15 — Vuot an han mot giay

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:54:59+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Idle 301 giây - 300 = 1 giây; ceil(1/60)=1 phút; 1 × 200=200 đ; tổng 3200 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:54:59+07:00; 301 giây; grace 5 phút; phút thu 1; phí 200 đ. Tổng 3200 đ.

### KT-16 — Chiem tru qua ngay, an han mot lan

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T23:00:00+07:00 → 2026-10-11T00:10:20+07:00; múi giờ Asia/Ho_Chi_Minh, giá AB. Số đo: 2026-10-10T23:00:00+07:00 = 0 Wh; 2026-10-10T23:50:00+07:00 = 1000 Wh; 2026-10-11T00:00:00+07:00 = 1000 Wh; 2026-10-11T00:10:20+07:00 = 1000 Wh.

Điện 1000 ×2000/1000=2000 đ; sau 23:50 chỉ số đứng yên, đoạn ngày mới 0 Wh không sinh dòng. Idle 1220-300=920 giây; ceil(920/60)=16 phút. Bắt đầu thu 23:55: 5 phút bắt đầu ngày cũ ×200=1000; 11 phút bắt đầu ngày mới ×300=3300; idle 4300; tổng 6300 đ. Không cấp lại ân hạn hoặc làm tròn tổng Wh.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 23:00:00 | 2026-10-11T00:00:00+07:00 | 1000 | 2000 | Dem muon | false | 2000 |

Idle bắt đầu: 2026-10-10T23:50:00+07:00; 1220 giây; grace 5 phút; phút thu 16; phí 4300 đ. Tổng 6300 đ.

### KT-17 — Idle dưới ân hạn

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:56:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Idle 240 giây < grace 300 giây; thời gian thu max(0,240-300)=0; phí 0, tổng 3000 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:56:00+07:00; 240 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 3000 đ.

### KT-18 — Đúng một phút sau ân hạn

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:54:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Idle 360-300=60 giây; ceil(60/60)=1, không tính 2 phút; phí 200, tổng 3200 đ.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:54:00+07:00; 360 giây; grace 5 phút; phút thu 1; phí 200 đ. Tổng 3200 đ.

### KT-19 — 26 giờ, ba ngày và giá hiệu lực kế thừa

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T23:00:00+07:00 → 2026-10-12T01:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá ABC. Số đo: 2026-10-10T23:00:00+07:00 = 0 Wh; 2026-10-12T01:00:00+07:00 = 26000 Wh.

26000/26=1000 Wh/giờ. Chỉ số ranh lần lượt 1000,7000,23000,25000. Tiền 2000+15000+56000+5000+2500=80500 đ; ngày 12/10 kế thừa phiên bản hiệu lực 11/10, không tạo phiên bản mới.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 23:00:00 | 2026-10-11T00:00:00+07:00 | 1000 | 2000 | Dem muon | true | 2000 |
| 2026-10-11 | 00:00:00 | 2026-10-11T06:00:00+07:00 | 6000 | 2500 | Dem som | true | 15000 |
| 2026-10-11 | 06:00:00 | 2026-10-11T22:00:00+07:00 | 16000 | 3500 | Ban ngay | true | 56000 |
| 2026-10-11 | 22:00:00 | 2026-10-12T00:00:00+07:00 | 2000 | 2500 | Dem muon | true | 5000 |
| 2026-10-12 | 00:00:00 | 2026-10-12T01:00:00+07:00 | 1000 | 2500 | Dem som | true | 2500 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 80500 đ.

### KT-20 — Múi giờ trạm khác UTC+7

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T23:00:00-07:00 → 2026-10-11T01:00:00-07:00; múi giờ America/Los_Angeles, giá AB. Số đo: 2026-10-10T23:00:00-07:00 = 0 Wh; 2026-10-11T01:00:00-07:00 = 10000 Wh.

Trạm America/Los_Angeles ngày này UTC−7: phiên 06:00–08:00 UTC ngày 11/10; nửa đêm trạm là 07:00 UTC. Mỗi đoạn 5000 Wh; 10000+12500=22500 đ. Cắt theo UTC hoặc UTC+7 sẽ sai ngày/giá.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 23:00:00 | 2026-10-11T00:00:00-07:00 | 5000 | 2000 | Dem muon | true | 10000 |
| 2026-10-11 | 00:00:00 | 2026-10-11T01:00:00-07:00 | 5000 | 2500 | Dem som | true | 12500 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 22500 đ.

### KT-21 — Đoạn ranh 0 Wh được bỏ, phiên vẫn có Wh

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T21:30:00+07:00 → 2026-10-10T22:30:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T21:30:00+07:00 = 0 Wh; 2026-10-10T21:59:00+07:00 = 0 Wh; 2026-10-10T22:30:00+07:00 = 1 Wh.

Ranh 22:00: 0+(1-0)×1/31=1/31 Wh → 0 Wh. Đoạn trước ranh 0-0=0 Wh không sinh dòng; đoạn sau 1-0=1 Wh, tiền 2 đ; tổng Wh vẫn là 1.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 22:00:00 | 2026-10-10T22:30:00+07:00 | 1 | 2000 | Dem muon | true | 2 |

Idle bắt đầu: không có; 0 giây; grace 5 phút; phút thu 0; phí 0 đ. Tổng 2 đ.

### KT-22 — Nhiều khoảng idle, chỉ thu khoảng cuối

Ca bổ sung được người dùng yêu cầu để phủ AC; không phải đề bài refinement gốc.

Phiên 2026-10-10T10:00:00+07:00 → 2026-10-10T11:00:00+07:00; múi giờ Asia/Ho_Chi_Minh, giá A. Số đo: 2026-10-10T10:00:00+07:00 = 0 Wh; 2026-10-10T10:10:00+07:00 = 400 Wh; 2026-10-10T10:20:00+07:00 = 400 Wh; 2026-10-10T10:50:00+07:00 = 1000 Wh; 2026-10-10T11:00:00+07:00 = 1000 Wh.

Idle cũ 10:10–10:20 kết thúc bằng Charging, không cộng vào phí cuối. Idle cuối 10:50–11:00: (600-300)/60=5 phút; 1000 đ. Điện 3000; tổng 4000 đ. Phạm vi chỉ khoảng cuối theo T-63/T-80, không nghiệm thu mọi khoảng idle của S-28.

| Ngày | Từ | Đến | Wh | Giá (đ/kWh) | Nhãn | Nội suy | Tiền (đ) |
|---|---|---|---:|---:|---|---|---:|
| 2026-10-10 | 10:00:00 | 2026-10-10T11:00:00+07:00 | 1000 | 3000 | Ban ngay | false | 3000 |

Idle bắt đầu: 2026-10-10T10:50:00+07:00; 600 giây; grace 5 phút; phút thu 5; phí 1000 đ. Tổng 4000 đ.

## Độ phủ bổ sung theo yêu cầu

KT-17: idle dưới ân hạn. KT-18: đúng một phút sau ân hạn. KT-19: phiên 26 giờ chia ba ngày, gồm ngày kế thừa giá hiệu lực. KT-20: America/Los_Angeles để phát hiện cắt ngày theo UTC/UTC+7 cố định. KT-21: đoạn nội suy 0 Wh phải bỏ, tổng phiên vẫn có Wh. KT-22: nhiều khoảng idle, chỉ tính khoảng cuối theo phạm vi T-63/T-80. Bộ 22 ca vượt mức tối thiểu 12 của backlog; không dùng số lượng để thay thế kiểm chứng kết quả.

## Sử dụng để triển khai và nghiệm thu T-77

1. Người được giao T-77, không viết T-73/T-75, tự đối chiếu đề bài và phép tính trước khi đọc mã sản phẩm. Có thể sử dụng giấy hoặc máy tính cầm tay, không dùng mã CSMS sinh đáp án.
2. Đối chiếu các đầu vào bổ sung ba ca đầu và 19 ca bổ sung đã được người dùng yêu cầu. Nếu tìm được file refinement gốc, so sánh rồi thay đề bài tương ứng; không tuyên bố đây là các đề bài gốc.
3. Ghi human_calculator, human_calculation_date, human_reviewer và acceptance_status từng ca; người làm Hoàng Hữu Đạt, người review Đào Minh Tâm đã được phân công; ngày tính/ngày review là 11/10/2026 theo người dùng cung cấp; T-77 được Đào Minh Tâm xác nhận trong chat ngày 11/10/2026. Tên phân công không đồng nghĩa đã ký duyệt.
4. Kiểm tra từng đoạn, Wh bảo toàn, tiền nguyên đồng, phí idle và tổng. Xác nhận cả ca làm tròn KT-09/10/11, không chỉ tổng cuối.
5. Chốt phiên bản JSON cố định rồi để T-78 đọc qua tests Python. Assertion phải nêu case ID, đoạn/field, đáp án, kết quả và chênh lệch. T-78 kiểm mutation làm tròn, thời gian CI dưới một phút; không thuộc bằng chứng đã thực hiện của gói T-77 này.

Hai ca NL-01/NL-02 không lập hóa đơn thuộc T-80, không tính vào 22 ca trên. KT-12 vẫn là ca tính tiền hợp lệ có kết quả 0 đồng; lập hóa đơn/settlement 0 là phạm vi T-80/T-102.
