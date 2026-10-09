# S-26 — Bộ trụ ảo trong Docker Compose và CI

Tài liệu này ghi nhận triển khai S-26. Backlog yêu cầu một lệnh khởi động 20
trụ ảo, CI chạy kịch bản sau mỗi thay đổi và chặn Pull Request khi phát hiện
sai lệch dữ liệu phiên sạc. Phụ thuộc S-21 đã được merge vào `main`.

## Coverage Matrix

| AC/NFR | Triển khai S-26 | Bằng chứng PASS |
| --- | --- | --- |
| Compose khởi động đúng số trụ | Profile `simulator` dùng `SIMULATOR_COUNT`, mặc định 20; seed tạo `SIM-001` đến `SIM-020`, đầu nối và thẻ thử riêng | `simulator-verify` xác nhận đủ code đã cấu hình đang `connected`, `boot_accepted`, `online` |
| Trụ chạy luồng phục hồi | Mỗi client Boot, Authorize, StartTransaction, Status, MeterValues, ngắt–nối lại theo seed cố định, replay Start/Stop và dừng phiên | Báo cáo chứa transaction ID duy nhất, ít nhất một reconnect, meter stop 3500 Wh và 2,5 kWh cho từng trụ |
| CI chặn Pull Request | Job `simulator-scenario` chạy sau `quality`; job `Build Docker image` bắt buộc trên `main` dùng `always()` và thất bại nếu quality hoặc simulator không thành công | Simulator thất bại làm required check `Build Docker image` thất bại thay vì bị skip, chặn merge; deployment staging chờ simulator |
| CI có log/artifact | CI lưu `docker-compose.log`, trạng thái service và báo cáo JSON | Artifact `s26-simulator-evidence` xuất hiện cả khi kịch bản thất bại |
| Đổi phiên bản simulator không làm sửa phần khác | Compose truyền `SIMULATOR_OCPP_VERSION=2.1.0` và `SIMULATOR_WEBSOCKETS_VERSION=15.0.1` từ K-01 vào một build/image tag dùng chung | Đổi tag/phiên bản tại Compose, không sửa client, seed hoặc verifier |
| NFR: hoàn tất dưới năm phút | CI đặt `timeout-minutes: 5`; verifier từ chối báo cáo có thời lượng từ 300 giây | `elapsed_seconds` trong báo cáo nhỏ hơn 300 |

## Thành phần

`simulator-seed` chỉ tạo hoặc cập nhật dữ liệu có tiền tố simulator: user thử,
trạm, trụ, connector, thẻ và ví tài xế. Trạm simulator được đặt giá
`1.000 VND/kWh`; mỗi ví có ít nhất `charging_minimum_kwh × giá + wallet_reserve_vnd`
theo cấu hình ứng dụng. Chạy seed lại sẽ sửa giá trạm và bù ví chưa đủ ngưỡng,
ghi khoản bù qua API nạp tay nội bộ để giữ sổ cái bất biến; số dư cao hơn yêu
cầu không bị giảm. Seed dùng tài khoản quản trị local-only cho khoản nạp và
không thay đổi dữ liệu có mã khác tiền tố đã cấu hình.

`simulator` kết nối tới `ws://app:8000`, dùng subprotocol `ocpp1.6` và chỉ ghi
báo cáo không có id tag vào `.local/simulator-reports`. Service chờ seed hoàn
tất; seed chờ API `health/ready`, do đó simulator không thử kết nối trước khi
migration và app sẵn sàng.

Mỗi lần chạy simulator tạo `run_id` mới, lưu marker của process và marker trong
thư mục báo cáo. Báo cáo JSON được thay thế nguyên tử; healthcheck chỉ đạt khi
báo cáo khớp cả hai marker. Verifier từ chối báo cáo của lần chạy trước.

`simulator-verify` chỉ bắt đầu sau khi simulator đã có báo cáo của lần chạy hiện tại. Nó kiểm tra API
kết nối bằng tài khoản operator local-only và đối chiếu trực tiếp PostgreSQL
để nêu rõ mã trụ, `transactionId`, meter stop hoặc kWh khác mong đợi.

## Chạy local

1. Mở Docker Desktop và chờ Docker Engine chạy.
2. Tạo `.env` từ `.env.example`. Đặt `SIMULATOR_OPERATOR_PASSWORD` thành giá
   trị chỉ dùng local.
3. Từ thư mục gốc repository, chạy:

   ```powershell
   docker compose --profile simulator up --build -d
   ```

4. Theo dõi verifier:

   ```powershell
   docker compose --profile simulator logs -f simulator-verify
   ```

   Thành công khi có dòng `S-26 verified 20/20 online chargers and sessions.`
   và container `simulator-verify` có exit code `0`.

5. Màn hình **Giám sát trụ** của operator local-only hiển thị các mã simulator
   đang online trong thời gian `SIMULATOR_HOLD_SECONDS` (mặc định 45 giây).

Để chạy số lượng khác, thay `SIMULATOR_COUNT`. Code và tag được sinh ổn định từ
`SIMULATOR_CODE_PREFIX`, `SIMULATOR_TAG_PREFIX` và `SIMULATOR_RANDOM_SEED`.
Không đặt tiền tố trùng với trụ thật. Lệnh `docker compose down` giữ volume;
không cần dùng `down -v` để chạy lại kịch bản.

Trước khi chạy lại, dùng `docker compose --profile simulator down`, rồi chạy
lại lệnh `up` ở trên để seed, client và verifier cùng khởi động lại. Báo cáo
cũ có thể giữ nguyên trong thư mục; chúng không được dùng cho lần chạy mới.
Khi không bật profile simulator, không cần `SIMULATOR_OPERATOR_PASSWORD`;
khi bật profile, seed và verifier sẽ báo lỗi nếu mật khẩu trống.

StartTransaction phát lại với cùng message ID dùng cache bền vững của
dispatcher (bao gồm hash của toàn bộ action/payload), không nhận diện bằng
đuôi thẻ. Một bản tin mới phải đi qua xác thực riêng.

## CI và failure output

CI dùng 20 mã `SIM-CI-001` đến `SIM-CI-020`, môi trường PostgreSQL riêng và
seed cố định `2600`. Job chạy sau unit/integration test. Khi lỗi, artifact có
log Compose, trạng thái các service và báo cáo simulator để reviewer kiểm tra.

Ruleset đang bảo vệ `main` bắt buộc `Build Docker image`. Job build chờ cả
quality và simulator, luôn chạy bước kiểm tra kết quả dependencies và thất
bại khi một dependency thất bại, bị skip hoặc bị hủy. Không chỉ thêm `needs`:
một required job bị skip có thể được GitHub xem là đạt. Cách này chặn merge
khi simulator lỗi mà không cần quyền sửa ruleset. Quản trị repository có thể
thêm riêng `Verify 20 OCPP virtual chargers` (GitHub Actions) vào required
status checks để hiển thị điều kiện S-26 trực tiếp.
Khi nâng simulator, chỉ đổi hai biến phiên bản S-26 trong Compose; Dockerfile,
client, seed và verifier dùng lại nguyên trạng.

Ví dụ thông tin lỗi có thể đọc được:

```text
charger SIM-CI-004 is missing session 42
charger SIM-CI-011 meter stop expected 3500 Wh, actual 3000
charger SIM-CI-017 energy expected 2.5 kWh, actual 2.0
```

Không đưa `.env`, mật khẩu, URL database, id tag hoặc dữ liệu người dùng vào
artifact. Kịch bản dùng dữ liệu local/CI và không thay thế kiểm thử tải mạng
hay staging production.
