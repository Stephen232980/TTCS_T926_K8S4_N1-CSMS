# ADR-0001: Sử dụng Python cho backend

- Trạng thái: Accepted
- Ngày: 2026-09-23

## Bối cảnh

CSMS cần REST API, WebSocket OCPP 1.6J, SSE, PostgreSQL, job nền, giao dịch tài chính và kiểm thử tự động. Nhóm mới cần cấu trúc dễ học nhưng vẫn đủ rõ để phát triển toàn bộ backlog.

## Quyết định

Toàn bộ backend dùng Python 3.12+ với stack chuẩn:

- FastAPI và Uvicorn cho HTTP, WebSocket, SSE và OpenAPI;
- Pydantic cho cấu hình và schema vào/ra;
- SQLAlchemy 2 async với Psycopg 3 cho PostgreSQL;
- Alembic cho migration;
- Pytest và HTTPX cho kiểm thử;
- `argon2-cffi` cho Argon2id;
- thư viện `ocpp` được bọc trong module OCPP nội bộ, không để domain phụ thuộc trực tiếp vào thư viện.

Backend được tổ chức theo modular monolith. HTTP API, OCPP gateway và worker là các entry point riêng trong cùng repository.

## Hệ quả

- Một ngôn ngữ dùng xuyên suốt backend và worker.
- Các luồng I/O phải viết async; không gọi thư viện blocking trong event loop.
- Mỗi tác vụ đồng thời có `AsyncSession` riêng.
- Giai đoạn đầu OCPP chạy một worker vì registry kết nối nằm trong bộ nhớ. Khi scale nhiều instance phải bổ sung registry/kênh lệnh dùng chung.
- Frontend là quyết định độc lập và có thể dùng JavaScript/TypeScript mà không thay đổi ADR này.

