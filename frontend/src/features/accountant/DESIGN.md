---
name: CSMS Accountant
description: Tra cứu hóa đơn phí sạc và bằng chứng quyết toán trong hệ giao diện teal CSMS hiện có.
colors:
  primary: "#14795e"
  primary-hover: "#0d624b"
  ink: "#193d4b"
  muted: "#526e7b"
  canvas: "#f2f6f7"
  surface: "#fff"
  line: "#dce6ea"
  sidebar: "#173b47"
  sidebar-active: "#2c5664"
  secondary: "#eaf2f5"
  settled: "#116443"
  settled-surface: "#e4f5eb"
  pending: "#705410"
  pending-surface: "#faf3df"
  review: "#9b3025"
  review-surface: "#fff0ec"
typography:
  heading:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "29px"
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
rounded:
  field: "8px"
  control: "9px"
  panel: "14px"
spacing:
  small: "8px"
  group: "12px"
  section: "16px"
components:
  primary-button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "44px"
---

## Overview

Mode: Operate. Mở rộng khung kế toán teal/Segoe UI hiện có để tìm phiên, đối chiếu hóa đơn và khoản trừ ví. Chỉ đọc, không dùng nút giả cho chức năng chưa triển khai.

## Colors

Canvas sáng, panel trắng, sidebar teal tối. Xanh cho quyết toán hoàn tất, vàng nhạt cho chờ, đỏ nhạt cho cần kiểm tra; luôn kèm chữ. Tổng hóa đơn và tiền đã trừ ví là hai đại lượng riêng.

## Typography

Segoe UI xuyên suốt. H1 29px desktop/25px mobile, H2 18px, body 14px, bảng 13px. Tiền dùng tabular-nums và BigInt, không float. Thông tin phụ dùng muted trên nền sáng.

## Layout

Desktop sidebar 220px, nội dung dùng phần rộng còn lại và cuộn riêng; dưới 1150px sidebar 200px. Dưới 800px cuộn trang, sidebar gọn, tài khoản/bộ lọc thu gọn; bảng phiên thành các khối theo dòng. Bảng phí/số đo cuộn ngang bên trong, không tràn trang. URL giữ query/mã phiên, quay lại khôi phục cuộn tức thời.

## Elevation & Depth

Panel dùng viền và sắc độ nền, không shadow. Summary xanh xám nhạt thể hiện toàn bộ kết quả lọc.

## Shapes

Field 8px, nút 9px, panel 14px. Control cao tối thiểu 44px; focus ring xanh 3px có offset. Bảng dùng phân cách dòng, không tách từng cell thành thẻ.

## Components

Bộ lọc gồm từ khóa toàn phạm vi, trạm, ngày bắt đầu phiên theo giờ Việt Nam và trạng thái, có Áp dụng/Xóa lọc. Chi tiết gồm trạng thái, snapshot dòng phí, sổ cái và vùng kỹ thuật tải theo yêu cầu. Tiền thiếu dùng dấu —, không tự chuyển thành 0.

Ba phần có chức năng riêng: sessions dùng biểu đồ so sánh hóa đơn/trừ ví và bảng phiên; invoices dùng cơ cấu khoản phí và sổ chứng từ; reconciliation dùng biểu đồ tuổi chờ và hàng đợi hồ sơ có hướng dẫn/sao chép. Ngày của invoices là ngày lập chứng từ. Cột hóa đơn xanh xám #5b7f9c, cột trừ ví/tiền điện teal #14795e; luôn có nhãn hoặc số liệu văn bản. Biểu đồ không lấy tổng riêng trang. Bấm trạm/trạng thái/tuổi chờ áp bộ lọc server. Desktop chia vùng phân tích 1.4:1, dưới 1000px xếp dọc; bảng chứng từ dưới 800px chuyển dòng thành khối. Chi tiết kỹ thuật giữ thu gọn.

## Do's and Don'ts

Giữ CSS accountant và quyền read-only. Không dùng GET để lập hóa đơn/quyết toán. Không coi kết thúc là đã thanh toán, hóa đơn nội bộ là hóa đơn điện tử, hoặc miễn quyết toán là tiền đã thu. Không sửa snapshot để làm số liệu trông khớp.
