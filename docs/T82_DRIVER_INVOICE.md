# T-82 / S-33 — Driver invoice

## Contract

- `GET /api/v1/driver/invoices?cursor=<session_id>&limit=20`: completed sessions belonging to the current driver, newest session ID first. Limit 1–50; `next_cursor` is null on the last page. Includes sessions awaiting an invoice, so waiting states remain discoverable.
- `GET /api/v1/driver/charging/sessions/{session_id}/invoice`: saved invoice details for one owned session.
- Both routes require `driver.invoice.view`, scope `own_wallet`, and the driver role. Anonymous requests return 401; another driver's session returns 403 even when its invoice has not been created. Unknown sessions return 404.
- Status is `ready`, `pending`, `needs_review`, or `in_progress`. Review reasons take precedence; an inconsistent invoice owner also produces `needs_review`. Non-ready responses contain no invoice ID, amounts, rounding rule, or lines.
- VND amounts and rates are integer strings, preserving PostgreSQL BIGINT precision. `energy_kwh` is a Decimal string converted from saved Wh. Lines expose saved band, local date, UTC interval, interpolation flag and tariff version. The UI explicitly labels UTC intervals and formats money as `1.234.567 đ`.
- These reads neither recompute tariffs nor write invoice or wallet records. Changes to current tariff rates do not change saved invoice amounts. Station names are current display metadata.

## Driver flow

Open **Ví của bạn → Xem hóa đơn phiên sạc**, then choose a completed session. A wallet transaction's session detail also has **Xem hóa đơn phiên này**. Direct hashes `#driver-invoices` and `#driver-invoice-<session_id>` restore the corresponding screen. Loading, empty list, read errors, pagination and retry are supported. Requests are cancelled on navigation and late responses are ignored.

## Local verification — 2026-10-10

- 21 PostgreSQL API and endpoint-policy inventory tests passed: ownership, multi-role ownership, missing/open sessions, review and pending amount masking, pagination, saved tariff snapshots and BIGINT precision.
- 295 frontend tests passed; ESLint, TypeScript/Vite build, Ruff check/format and mypy passed.
- Browser verified the real authenticated local API with persisted sample energy/idle invoice lines, pending/review sessions, wallet navigation and a 360px viewport. The detail screen had no horizontal overflow. Screenshots were saved separately for review.

## Integration boundary

This implements the T-82 reader and driver screen against T-79's persisted schema. T-80/T-81 were not merged into the starting develop revision `a4c2d14`; the browser sample is a saved fixture, not evidence of a real charging session producing an invoice. After those dependencies land, verify a completed charging session produces the expected saved lines and can be opened here. Wallet settlement belongs to T-102 and is not performed by these GET endpoints. No staging verification or Jira Done status is claimed.
