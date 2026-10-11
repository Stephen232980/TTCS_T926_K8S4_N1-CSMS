# S-34 / T-68 — Tra và bảo vệ phiên bản biểu giá

## Hợp đồng dùng chung

Module `src.modules.pricing.service` cung cấp:

- `lay_bieu_gia_hieu_luc(session, station_id=..., ngay=...)`: trả `Tariff | None`, chọn phiên bản có ngày hiệu lực lớn nhất không vượt ngày cần tra. `date` được hiểu là ngày địa phương của trạm; `datetime` phải có múi giờ và được chuyển sang múi giờ trạm. Trước phiên bản đầu trả None; không tự chọn phiên bản tương lai hay biểu giá trạm khác. Trạm không tồn tại báo `TariffNotFoundError`. Các khung giờ nằm trong bảng TariffBand; hàm này chỉ chọn phiên bản, không tính tiền.
- `kiem_ngay_hieu_luc(...)`: T-61/T-66/T-69 gọi chung trước INSERT/UPDATE trong cùng giao dịch. Phiên bản đầu phải có hiệu lực hôm nay theo giờ trạm; phiên bản sau phải từ ngày mai. Trùng ngày phiên bản chờ báo `TariffDuplicateDateError`. Ngày sai báo `TariffEffectiveDateError`.
- `kiem_bieu_gia_co_the_sua(...)`: trả phiên bản đã khóa để người gọi sửa; từ chối phiên bản đã tới ngày hiệu lực hoặc có `used_at`. Áp dụng khi sửa cả ngày, mức phí, ân hạn và từng khung giờ. Khi đổi ngày, gọi thêm hàm kiểm ngày với `exclude_tariff_id` là phiên bản đang sửa; chính hàm kiểm ngày cũng gọi guard bất biến, không cho bypass bằng tham số này.
- `danh_dau_bieu_gia_da_dung(...)`: khóa phiên bản và ghi `used_at` lần đầu, gọi lại giữ nguyên dấu. T-79 phải dùng trong cùng giao dịch tạo hóa đơn, trước khi sao chép dữ liệu biểu giá đã khóa vào dòng hóa đơn. Helper chưa tạo hóa đơn.

Tất cả hàm không tự commit/rollback. Caller kiểm tra quyền và sở hữu trạm ở endpoint, rồi commit hoặc rollback giao dịch. `now` chỉ dành cho clock nội bộ/test, không nhận thời gian giả từ request. Timestamp không có múi giờ bị từ chối; `effective_from` chỉ nhận date, không nhận datetime.

## Khóa và cách tích hợp

Các nhánh ghi khóa trạm trước, biểu giá sau, giữ khóa tới cuối giao dịch. Nhờ đó hai yêu cầu tạo phiên bản đầu cùng lúc không cùng nhận kết quả "chưa có biểu giá". Guard đọc lại dữ liệu ORM sau khi chờ khóa để thấy dấu đã dùng mới commit. Dùng READ COMMITTED như cấu hình hiện tại; giao dịch nhiều trạm phải khóa theo thứ tự UUID thống nhất.

```python
from src.modules.pricing.service import kiem_ngay_hieu_luc

async with session.begin():
    await kiem_ngay_hieu_luc(
        session, station_id=station_id, effective_from=requested_date
    )
    # T-61/T-66 INSERT Tariff và các TariffBand đã kiểm tra trong giao dịch này.
```

Không INSERT/UPDATE ngoài giao dịch vừa kiểm; không sửa trực tiếp biểu giá/khung mà bỏ guard; không xóa phiên bản lịch sử hoặc xóa `used_at`. Unique theo trạm/ngày của T-59 vẫn là lớp bảo vệ database. T-65 chịu trách nhiệm kiểm phủ kín/chồng lấn khung; T-68 không thay thế hàm đó.

Đối với T-79/T-81: lấy dữ liệu từ phiên bản mà `danh_dau_bieu_gia_da_dung` trả về sau khi đã khóa, rồi sao chép mức phí/khung vào hóa đơn trong giao dịch này. Nếu lập hóa đơn thất bại thì rollback cả dấu. Khi có schema hóa đơn, cần test tích hợp thật cho liên kết hóa đơn–biểu giá; hiện repo chưa có bảng hóa đơn nên chưa chứng minh được luồng đó. Không coi helper là hoàn tất T-79 hay AC liên kết hóa đơn toàn hệ thống.

## Migration và nghiệm thu

`c100011a2026` nối `b090010a2026`, thêm `tariffs.used_at` nullable, không đổi ngày/giá/dữ liệu phiên bản cũ. Giá trị NULL ở biểu giá cũ phù hợp repo hiện chưa có hóa đơn; nếu tích hợp môi trường đã có hóa đơn ngoài repo, phải backfill từ hóa đơn trước khi mở chỉnh sửa.

Downgrade giữ các phiên bản và giá nhưng xóa dấu đã dùng. Sau downgrade/upgrade lại, phải khôi phục dấu từ hóa đơn trước khi cho phép sửa; không dùng downgrade này trên môi trường cần giữ bằng chứng mà chưa có kế hoạch phục hồi.

`tests/test_effective_tariffs.py` kiểm tra ranh ngày, UTC so với giờ trạm, DST, phiên bản đầu/sau, trùng ngày, bất biến, dùng nhầm trạm, marker/rollback, dữ liệu ORM cũ, hai kết nối tranh tạo phiên bản và ghi nhận sử dụng trước chỉnh sửa. Ca commit/migration dùng database riêng `t68_<uuid>`, cần CREATEDB. Không chạy trên demo/staging. T-61 và T-69 chưa có API trong repo; các task đó phải gọi đúng helper và bổ sung test endpoint/quyền của mình.
