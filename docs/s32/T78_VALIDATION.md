# T-78 / S-32 — Kiểm thử theo đáp án T-77

Người làm: Hoàng Hữu Đạt. Người review: Đào Minh Tâm.
T-77 được Đào Minh Tâm xác nhận trong chat ngày 11/10/2026.

## Đầu vào và phạm vi

`docs/s32/dap_an_tay.json` chứa 22 ca cố định, đọc được ngoài code, cùng phép tính
ở `T77_DAP_AN_VA_NGHIEM_THU.md` và bản Excel `dap_an_tay.xlsx`.
Backlog yêu cầu ít nhất 12 ca. Bộ mở rộng do người dùng yêu cầu có 22 ca;
không tuyên bố 19 ca bổ sung là đề bài lấy từ tệp refinement gốc còn thiếu.

Test gọi `chia_doan`, `tinh_phi_chiem_tru` và adapter `_idle_lines` thực tế của T-80.
So từng đoạn: ngày trạm, UTC instant bắt đầu/kết thúc, Wh, giá, nhãn, phiên bản,
cờ nội suy, tiền; so từng dòng idle và tổng. Không sinh expected từ hàm sản phẩm,
không dùng bộ tính tiền JavaScript riêng, không đọc kết quả Excel làm oracle động.
KT-19 kiểm ánh xạ ngày đã được chọn giá hiệu lực: không thay thế test DB lookup T-68.
KT-22 kiểm phí với idle_since cuối đã lưu: không thay thế test xử lý trạng thái T-63.

## Chạy và phát hiện sai lệch

```powershell
python -m pytest tests/test_t78_billing_answers.py -q
python scripts/verify_t78_mutation.py
```

Bộ test có 22 ca tính tiền và một ca kiểm tra nội dung thông báo sai lệch.
Local: 23 passed trong 0,44 giây (không gồm startup Python).

Mutation plugin chỉ được nạp bởi lệnh kiểm chứng riêng: đổi hàm làm tròn tiền
được `chia_doan` sử dụng thành làm tròn xuống trong tiến trình pytest con.
KT-10 phải thất bại với `energy[1]`, đáp án 3, kết quả 2, chênh -1 đồng và exit 1.
Script kiểm cả exit code và thông báo; nếu mutation không bị phát hiện thì
script thất bại. Mã sản phẩm trên đĩa không bị thay đổi; pytest thường không nạp plugin.
Đây là bằng chứng test thật từ chối sai lệch, không tuyên bố đã cố ý push code sai.

CI quality giữ các kiểm tra backend/frontend/OCPP/deploy hiện có, thêm bước chạy
bộ S-32 và mutation dưới timeout 60 giây. Sai đáp án hoặc timeout làm quality job
thất bại, chặn các job phụ thuộc. Quy tắc required checks của GitHub repository
là cấu hình ngoài workflow; CI đỏ không tự chứng minh branch protection được bật.

Không thay đổi mã tính tiền, schema/API, dependency Python, frontend hay deployment.
Phí sau Stop đến rút súng là phần còn thiếu của S-28; bảng này theo phạm vi hiện tại.
PR giữ các commit gốc và thêm merge develop + commit sửa.
