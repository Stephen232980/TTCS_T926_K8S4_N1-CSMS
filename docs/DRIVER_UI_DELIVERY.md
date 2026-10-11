# Driver interface delivery — 05/10/2026

Local implementation on `feature/driver-interface`, based on main `7f1eae5` after PR #56. No commit, push, merge or deployment is part of this delivery. Live demo observations below are verification evidence at this date, not permanent system state.

## Approved direction and behavior

The user selected concept A for the current charging session, then approved implementation with the same map used by the station owner. The driver workspace inherits the approved owner palette, icons and equipment drawings. Phone navigation sits at the bottom; tablet navigation uses a compact rail; desktop uses a full sidebar. Session, station search and connector selection are separate views.

The driver map imports the existing `StationMap`, with its station pins, popups, configured tile URL and attribution. Optional location callbacks and a user-position marker extend it without changing owner defaults. Device location is requested only by the existing location button. All pages of the real search response are loaded before sorting by straight-line distance in the browser. Raw device coordinates are not posted to CSMS. Map tile requests still reveal the viewed map region to the configured tile provider.

Opening connector selection and returning preserves the search and selected station. The workspace keeps current-session polling mounted across its views. Role selection remains in the existing application flow; multi-role accounts can switch areas. Backend endpoint authorization and scope are unchanged, including the absence of automatic operator privileges for administrators.

## Acceptance criteria and API boundary

| Backlog item | Implemented behavior | Real endpoint |
| --- | --- | --- |
| S22 | Own open session, actual station/point/connector, energy and elapsed time, empty state, latest reading time and recovery feedback. Sequential polling every one second after each response. | `GET /api/v1/driver/charging/current` |
| S24 | Real station connectors, explicit cable confirmation, disabled busy/reserved connectors and new-start blocking for an existing session. Accepted remains waiting; navigation to the session requires a matching backend-confirmed Started request and session. | `GET /api/v1/driver/stations/{station_id}/connectors`, `POST /api/v1/driver/charging/start` |
| S24 recovery | Deadline recovery and retry behavior retained. A network-failed start retains its request UUID; request body contains only `request_id` and `connector_id`. Backend remains authoritative for eligibility and reservation conflicts. | Same charging endpoints |
| Station discovery extension | Server search, shared owner map, real station coordinates, optional nearby sorting and external station-position link. | `GET /api/v1/driver/stations` |

This delivery does not complete the full later S47 feature or introduce prices, payments, accounting screens or charging stop/reset actions. Tests support the polling behavior; a physical-device/network guarantee of the S22 two-second target has not been certified.

Production UI contains no mocked station, connector, session or meter data. API mocks exist only in component tests. Authentication continues to use the existing credentialed API requests and session-expiry notification.

## Validation

- Final full frontend suite: 193 tests across 34 files passed, including the new confirmation/navigation guard.
- Frontend lint and TypeScript/Vite production build passed. The existing main-bundle size warning remains.
- Read-only browser verification against the running demo APIs covered 320×740, 390×844, 844×390, 768×1024, 1024×768 and 1366×768. No horizontal document overflow or page errors were observed. Shared map tiles and actual station pins loaded at every size.
- The observed existing session blocked another start. Search was retained after opening connectors and returning. Verification sent no charging or control command and left demo sessions intact.
- Local review captures and browser checks are ignored artifacts under `impeccable/review/driver-implementation/`; they are not product assets or shared credentials.
- Fresh Impeccable finish review returned `ship` for the implementation after validating all 13 captures. Its scope was code, screenshots and supplied verification evidence; it did not certify physical devices or execute charging commands.

Review the running frontend at `http://localhost:5173/` in the driver area. The approved preview is historical design evidence; the implemented component is now the source for the driver map.
