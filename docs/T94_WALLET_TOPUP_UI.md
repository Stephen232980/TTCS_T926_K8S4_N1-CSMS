# T-94 — Wallet top-up UI and return status

## Behavior

- POST a validated integer VND amount once; use only the backend redirect URL.
- Before POST, retain an unresolved marker in sessionStorage, scoped to the authenticated user. Retain the returned order ID, including IDs from uncertain API errors.
- Navigation and reload in the same browser tab retain the lock. Unknown attempts without an order ID stay locked and show support guidance. This is a UI guard, not server-side idempotency across independent tabs or browsers.
- Read order_code only as an identifier. GET backend status every 3 seconds for at most 2 minutes. URL status is not proof of payment.
- Keep the status component mounted while navigating between driver areas and when returning to the wallet. After succeeded, fetch fresh wallet data and remount the wallet summary/history. Failed/cancelled release the attempt lock; needs_review remains locked.
- Existing wallet top-up buttons focus the actual amount form. At 360px, show a labelled button, wrap long order IDs and keep controls reachable above the navigation bar.

## Validation on 2026-10-10

- Frontend: 282 tests passed, including recovery across navigation/remount, unknown order without an ID, pending polling after returning to the wallet, and terminal failure unlock. ESLint and production build passed (existing >500 kB bundle warning).
- Browser: actual frontend -> T-93 API -> FakeGateway -> T-95/T-96 webhook -> PostgreSQL, using a dedicated csms_t94_review database and local ports 5194/8094. No shared demo database was changed.
- Delayed webhook: created 50,000 VND, opened return in a second tab while dispatch remained active, clicked back to wallet while pending; balance was 0 before settlement and automatically became 50,000 with one ledger row after settlement.
- Five repeated success webhooks for a 10,000 VND order: final balance 60,000, exactly one additional ledger row.
- Failed and cancelled orders of 10,000 VND each: reasons displayed; balance stayed 60,000 and ledger stayed at two credit rows.
- Mobile 360x800: wallet, amount entry/validation, presets and cancelled return screen inspected. No horizontal overflow; submit remains reachable after scrolling. Wallet top-up CTA label restored on mobile.
- These are local FakeGateway results, not real payment sandbox S-67 or staging acceptance.

## Windows local setup

Use a dedicated PostgreSQL database, migrate to head and provision demo accounts with scripts.create_test_accounts. Configure PAYMENT_GATEWAY=fake, a local-only PAYMENT_WEBHOOK_SECRET, PAYMENT_FAKE_BASE_URL=http://127.0.0.1:8094 and PAYMENT_RETURN_URL=http://127.0.0.1:5194/wallet/topup/return. Set CSMS_DEV_API_TARGET=http://127.0.0.1:8094 for the frontend.

For psycopg asynchronous connections on Windows, run Uvicorn with an asyncio SelectorEventLoop; the default Proactor loop can start HTTP successfully while database-dependent requests/background scans fail. Do not change the team's shared running containers just to test this UI.
