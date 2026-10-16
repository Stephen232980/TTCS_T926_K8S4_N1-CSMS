# S-42 / S-43 / S-44 — Hạn mức và chia công suất trạm

Phạm vi G1: cấu hình tải sạc của trạm, danh định từng đầu nối, chia đều có trần,
và chia lại theo phiên/trạng thái. Không bao gồm S-45 (khung giờ), đặt chỗ, hay
phụ tải tòa nhà. Hạn mức là ngân sách phần mềm; không thay thế bảo vệ điện.

## Hợp đồng và vận hành

Owner dùng mục **Công suất**. API owned bên dưới `/api/v1/owner/stations/{id}`:

| Method | Path | Kết quả |
| --- | --- | --- |
| GET | `/power-config` | Cấu hình và trạng thái hiện tại |
| PUT | `/power-config` | Lưu cấu hình có kiểm phiên bản; HTTP 200 |
| GET | `/allocations` | Mức yêu cầu/xác nhận/ngân sách giữ từng đầu nối |
| POST | `/power-control/enable` | HTTP 202; bootstrap rồi ready hoặc degraded |
| POST | `/power-control/disable` | HTTP 202; chỉ tắt hoàn toàn sau gỡ hồ sơ |

PUT nhận `version`, `limit_kw` chuỗi Decimal dương tối đa ba chữ số thập phân,
`connectors` gồm đúng các đầu nối đang đăng ký, mỗi mục `connector_id`, `rated_kw`.
Thêm `zero_limit_verified`, `offline_retention_verified` và `verification_note`
(tối đa 500 ký tự). POST nhận `{"version":1}`. Version 0 dùng cấu hình mới.
Danh định này là trần riêng của bộ chia tải; giá trị metadata `max_power_kw`
hiện có được dùng để điền ban đầu, không tự sửa metadata trụ.

Phản hồi chứa `version`, `state`, `issue`, `limit_kw` đã lưu,
`applied_limit_w` hoặc null nếu chưa xác minh, `total_rated_w`, `over_registered`,
và `connectors`: danh định, `desired_w`, `confirmed_w`, `reserved_w`,
`baseline_verified`, trạng thái OCPP. W dùng số nguyên, kW dùng chuỗi Decimal.
Đổi hạn mức chưa làm nó có hiệu lực ngay: khi đang điều khiển, hạn mức cũ giữ
nguyên đến khi kế hoạch mới được xác minh. Giao diện phân biệt dữ liệu nháp,
yêu cầu đã lưu và mức đã áp dụng; polling không thay dữ liệu đang nhập.

403 cho owner khác; 404 cho trạm không có/đã archive; 422 cho số hoặc danh sách
đầu nối sai; 409 `power_version_conflict`, `power_plan_in_progress`,
`power_commissioning_required`, `power_control_requires_no_open_sessions`.
Actor/audit, cấu hình và phiên bản ghi cùng transaction.

## Thuật toán và lỗi

Water-filling chia đều bằng W nguyên rồi giới hạn danh định; phần dư do làm
tròn xuống không được cấp vượt ngân sách. 30 kW với 7/22/22 kW cho
7/11.5/11.5 kW; 1 W với ba xe cho 0/0/0 W. Chỉ phiên có trạng thái Charging
cần tải; SuspendedEV/Finishing vẫn giữ nghiệp vụ chiếm đầu nối và tính phí cũ.

Trước enable phải không có phiên mở, có commissioning và đầy đủ danh định.
Worker kiểm `SmartCharging`, đơn vị Power/W và stack level >=1, cài
TxDefaultProfile 0 W cho mọi đầu nối rồi đọc GetCompositeSchedule.
Start qua app, Authorize và StartTransaction đều qua cùng gate. Trong lúc
chia lại, phiên mới có thể bắt đầu dưới baseline 0 W đã xác minh; không được
cấp thêm điện cho đến kế hoạch sau. Late rejection được lưu để driver thấy
`power_unavailable`, không tạo phiên giả transaction 0.

TxProfile gắn transactionId, stack 1; baseline stack 0. Profile ID cấp duy
nhất bởi DB, UUID lệnh và payload được lưu trước gửi. Giảm và xác minh trước
tăng; ACK đơn thuần không đủ. Composite phải là W và không có kỳ nào vượt yêu
cầu trong cửa sổ đọc 60 giây. Timeout/Rejected/mất mạng/protocol lỗi giữ ngân
sách chưa giải phóng, degraded, chặn start mới, lưu yêu cầu RemoteStop cho
phiên liên quan. ACK stop không giải phóng công suất. Offline vẫn giữ ngân sách.

Khóa advisory theo trạm ngăn hai worker cùng lập kế hoạch; row lock/version
ngăn ghi đè. Mỗi pha chạy tối đa 5 trụ song song, các đầu nối trên cùng trụ
vẫn gửi/xác minh tuần tự. Tất cả lệnh giảm và đối chiếu intent phải hoàn tất
trước pha tăng; giảm thất bại thì không chạy pha tăng. Trong pha tăng, khóa
cấu hình trạm bảo vệ kiểm tổng ngân sách và giữ chỗ W cùng transaction trước
gửi lệnh. Worker đợi các lệnh cùng pha kết thúc cả khi một lệnh gặp lỗi,
tránh nhả khóa trạm khi lệnh nền vẫn đang chạy.
Không giữ transaction DB trong khi chờ socket. Scan 1 giây,
debounce sự kiện 2 giây, khoảng cách kế hoạch tối thiểu 5 giây. Boot/Start/Stop/
Status kích hoạt generation mới; MeterValues không chạy bộ chia tải. Generation
cũ không tăng công suất sau sự kiện mới. Restart đối chiếu intents/budget đã
lưu và trạng thái trụ trước tăng. Disable chỉ khi không có phiên mở, cài 0 W
trước gỡ các profile CSMS; lỗi gỡ giữ gate an toàn để retry.

## Commissioning và giới hạn triển khai

1. Trên thiết bị/firmware cụ thể, thử baseline 0 W thực sự ngừng cấp điện và
   cho phép start/resume bằng TxProfile.
2. Thử rút mạng, dừng CSMS và khởi động lại trụ: hồ sơ không hết hạn, không tự
   cấp tải ngoài kế hoạch. Nếu thiết bị không giữ hồ sơ, không bật tính năng;
   phải dùng điều khiển tải cục bộ phù hợp.
3. Ghi thiết bị/firmware/kết quả, lưu hai xác nhận, enable rồi chờ ready. Các
   checkbox là chứng nhận của người vận hành, không phải tự kiểm chứng vật lý.
4. Chạy ca nhiều xe, đổi hạn mức, stop/resume, lỗi giữa giảm/tăng, reboot và
   phục hồi CSMS. Đối chiếu cả đồng hồ điện và composite/profile.

Kiến trúc hiện tại dùng registry socket trong một backend process. Khóa DB
không biến registry thành distributed registry; chưa hỗ trợ nhiều backend
process điều khiển cùng đội trụ. Phạm vi demo hiệu năng là 10 đầu nối;
cấu hình đo mặc định dùng 10 trụ ảo, mỗi trụ một đầu nối. Test S-44 đo từ lúc
ghi sự kiện SuspendedEV/StopTransaction tới khi trạng thái ready và tất cả mức mới đã được
xác minh, gồm scan/debounce/khoảng cách kế hoạch. Mỗi phản hồi OCPP mô phỏng
trễ 2 giây và test yêu cầu hoàn tất dưới 30 giây; đồng thời kiểm tổng W không
vượt hạn mức, giảm được xác minh trước tăng và không gửi lại mức không đổi.
Đây là worker thật với PostgreSQL và adapter phản hồi có độ trễ, không phải
phép đo WebSocket/staging hay thiết bị vật lý. Nếu nhiều đầu nối dùng chung
một trụ, hoặc phản hồi chậm hơn cấu hình đo, cần đo lại trước demo; không hứa
30 giây cho mọi topology/đội trụ lớn. Timeout mặc định 5 giây/lệnh, có thể chỉnh
tối đa 30 giây; không nới timeout hay ngưỡng 200 ms của MeterValues.
Không công bố p95/worst-case hay nghiệm thu thiết bị từ unit test.

Simulator điều khiển dùng Power.Active.Import và tích phân điện năng theo
profile thực tế; TxDefault 0 W được giữ sau Stop. CLI lưu hồ sơ nguyên tử trong
`.local/control-power-<hash-code>.json`, có thể đặt `--profile-store`. File này
là dữ liệu thiết bị mô phỏng, không commit. Một instance cho mỗi charger code.

## Migration và bằng chứng

Migration `a210021a2026` sau `f200020a2026`, thêm station_power,
connector_power và power_commands; không tự bật trạm và không sửa dữ liệu ví,
biểu giá hoặc phiên hiện có. Downgrade xóa cấu hình/budget/intent công suất:
phải tắt chia tải và kết thúc phiên trước khi downgrade môi trường thật.

| Story / rủi ro | Bằng chứng trong repository |
| --- | --- |
| S-42 số nguyên, owned, reload, audit, version | `tests/test_power.py` config/allocator/migration cases |
| S-43 giảm trước tăng, lỗi, offline, reboot, gate | `tests/test_power.py` worker and start-gate cases |
| S-43 công suất/điện năng thực trong simulator | `tests/test_control_simulator.py` real WebSocket profiles/restart |
| S-44 stop/suspend/resume, kế hoạch cũ, nhiều worker/no-op | `tests/test_power.py` reduction/stale-generation/advisory-lock cases |
| UI version, retry đúng trạm, polling và yêu cầu đã lưu | `StationPowerPage.test.tsx` |

Local HTTP + OCPP nghiệm thu ba phiên 5 kW trong hạn mức 15 kW, desktop
1366x768 và mobile 360x800. Đây là mô phỏng cục bộ, chưa phải staging/hardware.
Local HTTP + OCPP cũng đã mở 20 phiên đồng thời: tất cả request 200, phân bổ
20 x 1.5 kW = 30 kW; dừng một xe cho 19 x 1.578 kW = 29.982 kW. Chờ xác nhận
kế hoạch sau các request khoảng 7.5 giây; kế hoạch sau stop khoảng 5.8 giây
trên máy test. Một ca này không chứng minh p95/worst-case toàn đội trụ.
Đo hiệu năng lặp lại và commissioning thật cần evidence riêng trước nghiệm
thu story Done hoặc bật trên thiết bị thật.

Kiểm thử tối ưu demo 10 đầu nối ngày 14/10/2026 trên WSL/Linux + PostgreSQL 16:
83 test power/simulator đạt. Với phản hồi adapter trễ 2 giây/lệnh, từ sự kiện
đến ready mất 17.087 giây cho SuspendedEV và 17.029 giây cho StopTransaction,
tối đa 5 lệnh đồng thời. Sau khi một xe nhường tải: 9 x 3.333 kW = 29.997 kW
trong ngân sách 30 kW; kiểm tổng W tại mỗi lần áp profile, thứ tự giảm trước
tăng và kế hoạch không đổi không gửi lại profile đều đạt. Đây là số đo local
trong cấu hình kiểm thử trên, chưa phải số đo staging/hardware hay p95.

## Bổ sung S-43: SmartCharging cho demo staging

Script `scripts/staging_demo.py` hiện hỗ trợ `Core,Reservation,SmartCharging`,
khai báo đơn vị Power/W và stack tối đa 1. Nó nhận tập profile mà worker CSMS
phát: `TxDefaultProfile` stack 0 và `TxProfile` stack 1 gắn đúng transaction,
Absolute, một kỳ bắt đầu tại 0, không hết hạn. Profile khác bị Rejected thay vì
nhận ACK nhưng bỏ qua. GetCompositeSchedule trả giới hạn đang có hiệu lực theo W;
ClearChargingProfile lọc theo id/connector/purpose/stack và lưu kết quả.

Giới hạn đi vào `ConnectorState.offered_watts` và `meter_samples`: baseline 0 W
không tăng điện năng sau start; các khoảng trước/sau đổi profile được tích phân
riêng, StopTransaction chốt meterStop theo profile cuối. TxProfile cũ được bỏ
khi kết thúc phiên; baseline vẫn áp dụng cho xe mới. File `.power.private.json`
riêng từng trụ được ghi nguyên tử, fsync trước Accepted, quyền 0600. Restart chỉ
khôi phục TxProfile khi transaction còn khớp DB; file lỗi làm trụ từ chối boot.
Lỗi ghi file trả Rejected và giữ mức cũ. Đây là mô phỏng, không phải chứng nhận
thiết bị hoặc bảo vệ điện vật lý.

Phần Reservation từng được cập nhật riêng trên script đang mount cũng được
đưa vào repository: giữ chỗ đúng thẻ, lưu trạng thái, hết hạn/hủy và truyền
reservationId khi bắt đầu. Giữ RemoteStop → Finishing → rút súng riêng.
Không thay tên trạm, marker hoặc dữ liệu seed trong bản bổ sung này.

### Coverage Matrix cho bản bổ sung

| Phần bổ sung | Kiểm chứng |
|---|---|
| Capability, Set/GetComposite/Clear qua WebSocket thật | `tests/test_staging_demo_power.py` |
| Nhiều start dưới 0 W; sau cấp tải tổng 3 × 1 kW = 3 kW, điện năng tăng đúng; đổi profile/stop không mất đoạn đo | `test_real_wire_profiles_bound_multi_start_power_and_energy` |
| Restart thực của Charger.run giữ baseline và TxProfile đúng phiên; clear profile và xe mới trở về 0 W | `test_actual_demo_restart_restores_profiles_before_boot_and_start` |
| Sai transaction/đơn vị/stack/kiểu dữ liệu/thời hạn hoặc nhiều kỳ bị từ chối | Parametrized `test_unsupported_profiles_are_rejected_without_changing_baseline` |
| Ghi đĩa lỗi không ACK giả; file lưu lỗi từ chối boot | Persistence tests trong `test_staging_demo_power.py` |
| Giữ chỗ đúng thẻ và reservationId; không mất baseline | `test_reservation_ownership_survives_start_under_zero_baseline` |
| RemoteStop không tự coi đã rút súng | `tests/test_staging_demo_protocol.py` |
| Cập nhật đúng script đang mount, không seed; chặn khi có hoạt động hoặc chia tải đang bật | `tests/test_staging_demo_update.py` |

### Cập nhật runtime sau merge/deploy

Image backend mới không tự thay file `/demo/staging_demo.py` đang bind mount.
Sau review, merge và pipeline staging thành công, chạy:

```powershell
.\scripts\update-csms-staging-demo.ps1
```

Lệnh lấy script từ **image backend đang chạy**, kiểm tra namespace/manifest,
phiên mở/chờ rút súng, hold, start intent và power control đang bật, kiểm tra lại
ngay trước dừng. Có hoạt động thì từ chối. Cần hai cờ demo hiện có được bật;
lệnh không sửa cấu hình backend để vượt điều kiện này. Nó sao lưu script cũ,
dừng simulator êm, thay script đang mount, chạy lại bằng image hiện hành với
`seed=False`, chờ 20/20 online. Không ghi lại tài khoản, ví, tên trạm, hold hay
profile. Không dùng lệnh start/seed để cập nhật môi trường đã có dữ liệu.

Nếu startup chưa được xác nhận, giữ backup và báo lỗi để kiểm tra; không tự
kill phiên mới xuất hiện để rollback. Không tự triển khai chỉ vì PR được tạo.
Sau cập nhật vẫn cần nghiệm thu S-43 trên staging: kiểm baseline, ghi bằng chứng
mô phỏng trước bật chia tải; đo profile/composite/MeterValues với nhiều phiên,
các nhánh lỗi/offline/reboot. Jira chưa được chuyển Done bởi bản sửa local này.
