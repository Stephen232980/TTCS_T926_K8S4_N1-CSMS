# T-114 — Driver charging history

## Scope

PR #185 adds a separate driver session-history screen and retains the contributor's
`GET /api/v1/charging/my-sessions` endpoint. The existing wallet transaction history,
session detail and invoice endpoints remain the source for their respective data.
No new billing, settlement or payment behavior is introduced.

## Driver flow

- Desktop: **Lịch sử phiên sạc** in the sidebar.
- Phone: **Tài khoản → Lịch sử phiên sạc**, preserving the existing three bottom tabs.
- The list shows station/charger/connector, Vietnam start time, energy and session
  state. Ten entries per page. Status filters and page are preserved in the URL.
- Open a session, then its existing invoice. Return to the same list page/filter;
  direct links and browser Back/Forward remain usable.
- Ended means the charging transaction ended, not that billing/settlement completed.
  Invoice availability still comes from the existing invoice API.
- Missing final energy stays unknown; an open session can display the difference
  between its latest counter and start counter. No amount is recomputed in the UI.
- Loading/error/empty states are explicit. Previous results are masked when a
  different page/session is requested; aborted/late responses cannot replace the
  current results. A 401 uses the established session-expiry flow.

## API contract

`GET /api/v1/charging/my-sessions?page=1&page_size=10&state=all`

- Existing response fields retained, including station_id and latest meter values.
- Page >= 1; page_size 1..100. Accepted states: all/open/closed/review/abnormal.
- Ownership is always `ChargingSession.driver_id == authenticated_user.id`, before
  count and pagination. No user identity is accepted from request parameters.
- review = nonempty review_reasons; abnormal = not ended and abnormal_since set.
- Ordering: descending session ID. Page beyond the last returns an empty items
  list while retaining the owned/filtered total. No rows => total_pages = 0.
- Driver role required; combined roles do not expand the account's data scope.

## Preserve contributor work

All original commits, including head e5b12450c08f1734a995659d18ca67394551de8b,
remain in history; fixes are additive commits on the existing PR.
The contributor's T-80/T-81/T-104 learning functions are preserved in
`simulator/examples/billing_concepts.py`, with their limitation documented.
They no longer run inside the S-26 recovery acceptance scenario or randomly print
successful financial settlement without a backend record.

## Validation

- PostgreSQL tests with real driver cookies: cross-driver isolation of items and
  total, every state, pages/empty results, invalid parameters, role revocation and
  non-driver denial. Disposable local database only.
- Role/access inventory and existing owner session regression.
- Frontend tests: navigation, preserved page/filter, detail/invoice return,
  query/deep links, aborted late responses, errors/retry/empty/401 and unknown energy.
- Desktop (1366×768) and phone (390×844) inspected with illustrative local data.
  Screenshots are UI evidence, not staging or financial acceptance.
- Lint, TypeScript production build, Ruff and mypy. Remote CI and staging are
  reported separately after the fixes are pushed/deployed.
