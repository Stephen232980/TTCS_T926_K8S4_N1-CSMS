# Tài liệu bàn giao Story S-59: Tối ưu thông báo khi phiên sạc kết thúc hoặc bị dừng

- **Mã Story**: `S-59`
- **Tiêu đề**: Tối ưu màn thông báo khi phiên sạc kết thúc hoặc bị dừng
- **Nhánh triển khai**: `feature/S-59-driver-charging-notification`
- **Tài liệu tham chiếu**: `.local/project-inputs/Backlog CSMS.xlsx`, `docs/BACKLOG_DELIVERY_GUIDE.md`

---

## 1. Mục tiêu và phạm vi

Story S-59 tập trung nâng cao trải nghiệm tài xế khi sạc xe, đảm bảo tài xế nhận biết kịp thời các thay đổi trạng thái quan trọng của phiên sạc mà không cần phải nhìn chằm chằm vào màn hình điện thoại:
1. **Thông báo dừng sạc / Chờ rút súng (Stop / Idle)**: Phát thông báo khi phiên sạc dừng và chuyển sang trạng thái chờ rút cáp sạc (`awaiting_unplug`), cảnh báo tránh phát sinh phí đỗ xe / phí chiếm chỗ quá giờ.
2. **Thông báo sự cố phiên sạc (Fault / Anomaly)**: Phát hiện cờ `needs_attention: true` trong phiên sạc, cảnh báo người dùng kiểm tra trụ/súng sạc hoặc liên hệ hỗ trợ kỹ thuật.
3. **Thông báo hoàn tất sạc & xuất hóa đơn (Invoice / Released)**: Khi rút súng sạc thành công, phiên kết thúc hoàn toàn, thông báo hoàn tất phiên sạc kèm nút điều hướng nhanh `#driver-invoice-${sessionId}` tới trang chi tiết hóa đơn.
4. **Hỗ trợ Web Notification trình duyệt**: Cung cấp banner xin quyền nhận thông báo trình duyệt để tài xế vẫn nhận được thông báo khi chuyển sang ứng dụng hoặc tab khác.
5. **Chống trùng lặp (Deduplication) & Tự đóng (Auto-dismiss)**: Thông báo tự biến mất sau 8 giây, có nút đóng thủ công và không gửi thông báo trùng lặp cho cùng một trạng thái phiên.

*Phạm vi loại trừ (Out-of-scope)*: Gửi tin nhắn SMS / Push Notification từ server qua nhà mạng / cổng ngoài (thuộc các backlog cổng thông báo 67 riêng).

---

## 2. Coverage Matrix

| AC/NFR | Hành vi cần có | Backend | Frontend | Kiểm chứng / Test | Trạng thái |
|---|---|:---:|:---:|---|:---:|
| **AC-1: Thông báo dừng sạc (Stop/Idle)** | Khi phiên sạc chuyển từ đang sạc (`session`) sang chờ rút súng (`awaiting_unplug`), hiển thị Toast và Browser Notification thông báo dừng sạc, cảnh báo phí chiếm chỗ | Có sẵn (SSE `awaiting_unplug`) | Đã triển khai | `DriverCharging.test.tsx` test 1: Hiển thị toast "Đã dừng sạc — Vui lòng rút súng" | `PASS` |
| **AC-2: Thông báo sự cố bất thường (Fault)** | Khi phiên sạc có `needs_attention: true`, hiển thị Toast cảnh báo đỏ và Browser Notification với mức cảnh báo khẩn | Có sẵn (`needs_attention`) | Đã triển khai | `DriverCharging.test.tsx` test 2: Hiển thị toast "Phiên sạc gặp sự cố bất thường" | `PASS` |
| **AC-3: Thông báo hoàn tất & hóa đơn (Invoice)** | Khi rút súng thành công (`awaiting_unplug` -> null), hiển thị thông báo hoàn tất kèm link `#driver-invoice-${id}` tới hóa đơn | Có sẵn (Session kết thúc) | Đã triển khai | `DriverCharging.test.tsx` test 3: Toast "Phiên sạc hoàn tất" + link hóa đơn | `PASS` |
| **AC-4: Web Notification API** | Hiển thị banner cho phép tài xế bật quyền nhận thông báo trình duyệt, gọi `Notification` khi có quyền | N/A | Đã triển khai | `DriverCharging.test.tsx` test 3: Kiểm tra mock `Notification` được khởi tạo đúng payload | `PASS` |
| **AC-5: Tự đóng & Accessibility** | Toast có nút đóng tay, tự đóng sau 8s, hỗ trợ ARIA live regions (`polite` / `assertive`), role `status` / `alert` | N/A | Đã triển khai | `DriverCharging.test.tsx` test 4: `advanceTimersByTimeAsync(8000)` xóa toast tự động | `PASS` |
| **NFR: Trải nghiệm & Độ trơn tru** | CSS animation trượt nhẹ, màu sắc thương hiệu hài hòa, responsive trên mobile/desktop | N/A | Đã triển khai | `frontend/src/features/driver/driver.css` | `PASS` |

---

## 3. Kiến trúc và các file thay đổi

### 3.1. Dịch vụ thông báo và Helper
- **`frontend/src/features/driver/driverNotificationService.ts`**:
  - Định nghĩa kiểu dữ liệu `DriverNotificationType` (`stop` | `idle` | `fault` | `invoice`).
  - Định nghĩa cấu trúc `DriverNotificationItem`.
  - Cung cấp hàm `emitBrowserNotification(title, options)` an toàn với SSR và trình duyệt không hỗ trợ.

### 3.2. Thành phần Toast thông báo
- **`frontend/src/features/driver/DriverNotificationToast.tsx`**:
  - `DriverNotificationToastContainer`: Vùng chứa nổi (`fixed`) cố định ở góc trên màn hình, hỗ trợ hiển thị danh sách thông báo nổi mà không che khuất thao tác người dùng.
  - `DriverToast`: Thẻ thông báo cụ thể kèm icon trực quan (`Icon name="charger" | "settings" | "report"`), tiêu đề, nội dung, nút hành động (ví dụ: "Xem hóa đơn") và nút đóng (`close`). Tích hợp `setTimeout` 8.000ms tự động dọn dẹp.

### 3.3. Tích hợp màn hình theo dõi phiên sạc tài xế
- **`frontend/src/features/driver/DriverCharging.tsx`**:
  - Quản lý state danh sách `notifications`.
  - Theo dõi biến động phiên sạc qua `previousSessionRef`:
    - `live -> awaiting`: Kích hoạt thông báo dừng sạc & nhắc rút cáp.
    - `live/awaiting -> cleared`: Kích hoạt thông báo hoàn tất phiên sạc & xuất hóa đơn.
    - `needs_attention: false -> true`: Kích hoạt cảnh báo bất thường / lỗi sạc.
  - Banner xin cấp quyền `Notification.requestPermission()` khi trạng thái là `default`.
  - Hiển thị `DriverNotificationToastContainer` trên đầu màn hình.

### 3.4. Định kiểu giao diện CSS
- **`frontend/src/features/driver/driver.css`**:
  - `.driver-toast-container`: Vị trí neo `top: 16px`, căn giữa trên mobile hoặc góc phải trên desktop, `z-index: 1000`.
  - `.driver-toast`: Glassmorphism nhẹ, bo góc 12px, bóng đổ mềm mại, animation `driver-toast-in`.
  - Các biến thể màu sắc:
    - `.driver-toast-stop`: Accent xanh dương (#0e7490).
    - `.driver-toast-idle`: Cảnh báo vàng hổ phách (#b45309).
    - `.driver-toast-fault`: Lỗi đỏ tươi (#b91c1c).
    - `.driver-toast-invoice`: Hoàn tất xanh lục (#15803d).
  - `.driver-notification-bar`: Thanh banner xin quyền trang nhã.

### 3.5. Kiểm thử tự động Vitest
- **`frontend/src/features/driver/DriverCharging.test.tsx`**:
  - 4 test cases kiểm tra độc lập các luồng thông báo, chuyển đổi SSE, quyền Web Notification và cơ chế auto-dismiss.

---

## 4. Kết quả kiểm tra Quality Gates

### 4.1. Linter (`npm run lint --prefix frontend`)
```text
> frontend@0.0.0 lint
> eslint .

(0 errors, 0 warnings)
```

### 4.2. Build & TypeScript (`npm run build --prefix frontend`)
```text
> frontend@0.0.0 build
> tsc -b && vite build

✓ 117 modules transformed.
dist/index.html                                 0.58 kB │ gzip:   0.36 kB
dist/assets/DriverWorkspace-Byyiw8K0.css       29.40 kB │ gzip:   6.20 kB
dist/assets/DriverWorkspace-Nn8xJSNA.js        74.23 kB │ gzip:  20.21 kB
✓ built in 266ms
```

### 4.3. Test tự động (`npm test --prefix frontend`)
- Toàn bộ frontend test suite: **62/62 files passed, 386/386 tests passed**.
- Riêng `DriverCharging.test.tsx`: **24/24 tests passed** (gồm 4 tests mới cho S-59).

### 4.4. Kiểm tra định dạng Git (`git diff --check`)
- Mã thoát: `0` (không có khoảng trắng thừa hay dòng trống ở cuối file).

---

## 5. Hướng dẫn kiểm thử thủ công (Manual Verification)

1. **Khởi động ứng dụng**:
   - Chạy backend CSMS và frontend dev server: `npm run dev --prefix frontend`.
   - Đăng nhập tài khoản tài xế (`driver`).
2. **Cấp quyền thông báo**:
   - Tại trang Sạc xe của tài xế, nếu trình duyệt chưa cấp quyền, thanh thông báo *"Nhận thông báo khi phiên sạc dừng hoặc hoàn tất"* sẽ xuất hiện.
   - Nhấn **"Bật thông báo"** -> Trình duyệt hiển thị popup xin quyền -> Chọn **Allow**.
   - Thanh thông báo chuyển sang huy hiệu xanh *"Đã bật thông báo trình duyệt"*.
3. **Mô phỏng dừng phiên sạc (Stop/Idle)**:
   - Khi phiên sạc đang chạy được bấm nút dừng hoặc trụ gửi StopTransaction:
   - Quan sát toast thông báo màu cam xuất hiện góc trên: *"Đã dừng sạc — Vui lòng rút súng"*.
   - Browser notification xuất hiện thông báo tới hệ điều hành.
4. **Mô phỏng rút súng sạc (Unplug -> Invoice)**:
   - Khi súng sạc được rút ra (hoặc bấm nút demo "Đã rút súng sạc"):
   - Quan sát toast thông báo màu xanh lá: *"Phiên sạc hoàn tất"*.
   - Bấm vào nút *"Xem hóa đơn"* trên toast -> Ứng dụng điều hướng ngay lập tức đến trang chi tiết hóa đơn `#driver-invoice-${id}`.
5. **Kiểm tra tự đóng**:
   - Không bấm nút đóng, sau 8 giây thông báo tự động mờ dần và biến mất khỏi DOM.
