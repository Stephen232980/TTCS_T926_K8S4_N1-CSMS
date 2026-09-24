# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.12+, FastAPI, SQLAlchemy 2, Psycopg 3 async, Alembic và PostgreSQL. Lựa chọn đã được người dùng xác nhận cho toàn bộ backend của dự án.

## Users

- Tài xế theo dõi và điều khiển phiên sạc của mình.
- Chủ trạm quản lý trạm, trụ, đầu nối, biểu giá và doanh thu thuộc sở hữu của mình.
- Vận hành viên theo dõi mạng lưới và điều khiển trụ từ xa.
- Kế toán đối soát điện năng, tiền và doanh thu đối tác.
- Quản trị viên quản lý tài khoản, vai trò và phạm vi toàn hệ thống.

## Product Purpose

CSMS giúp đơn vị vận hành theo dõi trụ và phiên sạc theo thời gian thực qua OCPP, tính tiền theo biểu giá, kiểm soát công suất, quản lý ví và đối soát doanh thu.

## Operating Context

Dự án được phát triển theo sprint một tuần bởi nhóm thực tập hoặc mới ra trường. Hệ thống chạy cục bộ bằng Docker Compose, qua CI trước khi triển khai staging, và dùng môi trường sandbox cho thanh toán.

## Capabilities and Constraints

- OCPP 1.6J qua WebSocket.
- PostgreSQL là nguồn dữ liệu chính.
- Phân quyền theo vai trò và quyền sở hữu; route mới mặc định bị từ chối.
- Dữ liệu cá nhân tài xế gồm vị trí và lịch sử di chuyển phải tuân thủ Nghị định 13/2023/NĐ-CP.
- Bí mật chỉ đến từ biến môi trường và không được ghi vào log.
- Sprint 1 chỉ xây nền tảng, đăng nhập/phân quyền và quản lý trạm, trụ, đầu nối; OCPP sản phẩm bắt đầu từ Sprint 2.

## Evidence on Hand

Nguồn yêu cầu: `Backlog CSMS.xlsx`, `Tasks.xlsx`, `Tong quan.xlsx` do người dùng cung cấp. Chưa có mã nguồn, nhận diện thương hiệu, máy chủ staging hoặc repository từ xa.

## Product Principles

- Từ chối mặc định khi thiếu quyền hoặc thiếu khai báo bảo mật.
- Quyền sở hữu được áp dụng tại tầng truy vấn.
- Tác vụ tài chính và OCPP phải chống xử lý trùng.
- Thay đổi dữ liệu quan trọng phải truy vết được.
- Mỗi sprint tạo ra một luồng chạy và demo được.
