---
name: CSMS Operator
description: Approved operator surface, extracted from the implemented CSMS teal equipment workspace.
colors:
  primary: "#14795e"
  primary-hover: "#0d624b"
  ink: "#193d4b"
  muted: "#526e7b"
  canvas: "#f2f6f7"
  surface: "#fff"
  sidebar: "#173b47"
  sidebar-text: "#d7e8ee"
  sidebar-active: "#2c5664"
  secondary: "#eaf2f5"
  secondary-hover: "#dce9ee"
  secondary-text: "#244e60"
  focus: "#2688c1"
  field-border: "#b9cdd6"
  available: "#116443"
  available-surface: "#e4f5eb"
  charging: "#155e9e"
  charging-surface: "#e8f2ff"
  fault: "#a3382c"
  fault-surface: "#fff0ec"
  unknown-surface: "#edf2f4"
  session-review: "#a33123"
  session-closed-surface: "#edf3f5"
  session-row-hover: "#f8fbfc"
typography:
  headline:
    fontFamily: "'Segoe UI', sans-serif"
    fontSize: "clamp(24px, 2.1vw, 34px)"
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "'Segoe UI', sans-serif"
    fontSize: "23px"
  equipment-label:
    fontFamily: "'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 700
  label:
    fontFamily: "'Segoe UI', sans-serif"
    fontSize: "12px"
  reading:
    fontFamily: "'Segoe UI', sans-serif"
    fontSize: "21px"
    fontWeight: 700
rounded:
  field: "9px"
  button: "10px"
  navigation: "12px"
  equipment: "14px"
  panel: "16px"
  status-badge: "5px"
spacing:
  compact: "8px"
  small: "12px"
  equipment: "14px"
  regular: "16px"
  split: "18px"
  detail: "20px"
  panel: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.button}"
    padding: "0 18px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-text}"
    rounded: "{rounded.button}"
    padding: "0 18px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  equipment-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.equipment}"
    padding: "14px"
  connector-available:
    backgroundColor: "{colors.available-surface}"
    textColor: "{colors.available}"
    rounded: "{rounded.field}"
    height: "42px"
  connector-charging:
    backgroundColor: "{colors.charging-surface}"
    textColor: "{colors.charging}"
    rounded: "{rounded.field}"
    height: "42px"
  connector-faulted:
    backgroundColor: "{colors.fault-surface}"
    textColor: "{colors.fault}"
    rounded: "{rounded.field}"
    height: "42px"
  navigation-active:
    backgroundColor: "{colors.sidebar-active}"
    textColor: "{colors.surface}"
    rounded: "{rounded.navigation}"
    padding: "0 14px"
---

# Design System: CSMS Operator

## Overview

**Creative North Star: "CSMS teal equipment workspace"**

This document records the built operator surface and its inherited owner visual world. It describes the approved status-groups variant 3 (seed `0bbde6cb`); it does not establish a new global brand. The dark teal shell, pale canvas, equipment silhouettes and numbered connector symbols keep the operator area visually continuous with the owner area.

The surface is compact and operational: scan real exceptions, choose a connector, inspect its session, then confirm a command. Group headings and connector symbols carry meaning alongside color. Loading, absent measurements, stale data and backend errors remain visible instead of being replaced with invented telemetry.

**Key Characteristics:**

- Fixed desktop shell with independent equipment and detail scrolling.
- White equipment cards, restrained shadows and a clear blue selection outline.
- Numbered SVG connector symbols with backend status and accessible names.
- Shared session charts, measurements and recovery history with an operator data scope.

Scope: `OperatorWorkspace.tsx`, `OperatorMonitoring.tsx`, `operator.css`, and the portions of `../owner/owner.css` and `../owner/OwnerCharging.tsx` actually used by operator. Delivery behavior and local verification are recorded in [OPERATOR_UI_DELIVERY.md](../../../../docs/OPERATOR_UI_DELIVERY.md). This document does not authorize driver, accountant, owner or admin redesigns. Current screenshots under `impeccable/review/operator-refinement/` are local evidence, not CI or deployment evidence; `operator-implementation/` captures are historical.

## Colors

The inherited palette combines deep teal navigation, quiet cool neutrals and separate status hues.

### Primary

- **Operational teal:** primary actions, online connection symbols and inherited equipment accents. The deeper hover shade changes emphasis without movement.
- **Selection blue:** keyboard focus and selected equipment or connectors; it is distinct from the charging status tone.

### Secondary

- **Quiet blue-gray:** secondary actions use a pale fill and dark text, with a slightly stronger fill on hover.

### Neutral

- **Deep equipment ink:** headings, identifiers and readings.
- **Muted slate:** station names, timestamps, units and supporting labels.
- **Cool canvas and white surface:** separate the workspace from equipment cards and detail panels.
- **Dark teal sidebar:** light text and a lighter active row preserve navigation contrast.

Status colors are semantic: available is green, charging is blue, faulted is red, and unknown or other unstyled states use muted neutral treatment. The card's attention group never erases individual connector states.

**The Status Redundancy Rule.** Keep connector numbers, symbols and accessible status names alongside color.

## Typography

The inherited font is Segoe UI with a sans-serif fallback. Hierarchy favors compact reading rather than display typography: page headings use the responsive headline role; detail titles use the title role; equipment codes use the equipment-label role; timestamps and metadata use the label role; current measurements use the reading role.

Group headings are (18px) with muted counts (13px), detail subheadings (16px), and detail paragraphs (13px). On narrow screens the page heading is (24px); on the inherited short desktop layout it is (26px). Shared measurement tables use (13px) and tabular numerals. Long card codes truncate; detail identifiers wrap so the full value remains inspectable.

## Layout

Desktop uses a (100dvh) shell with hidden outer overflow and a sidebar (220px), reduced to (190px) at widths up to (1250px). The final desktop page rule uses padding (20px 24px 16px) and gap (12px). Headers, toolbar and pagination remain outside the scrolling monitor body.

Monitoring splits flexible equipment space from a detail rail (320px), separated by (18px). At widths from (1600px), the rail is (380px) and the equipment grid has four columns. The ordinary grid has three columns, two at widths up to (1200px), with gap (14px). Each status group ends with (24px) of space. Connector strips always use four equal columns: one connector occupies one cell rather than stretching across the card; fifth and later connectors wrap into further rows.

At widths up to (800px), the operator overrides the inherited sidebar into a static top navigation strip. The shell may scroll, the monitor becomes one column, and selecting a charger swaps the equipment list for detail. “Quay lại trụ” clears selection and restores the list. Mobile cards remain two columns with gap (10px) and padding (12px); toolbar and pagination wrap.

Shared session detail places chart and measurement table in a (3:2) grid above (1000px). Below that width they stack; the table has its own scrolling region. At widths up to (800px), session facts and live readings use two columns. These are the shared session surface's rules, not a second operator visual world.

## Elevation & Depth

White surfaces against the cool canvas establish the main layering. Equipment cards use a shallow diffuse shadow (`0 8px 24px #193d4b0c`); inherited panels use `0 10px 28px rgba(25, 61, 75, 0.045)`. Selection uses an inset outline (2px), while keyboard focus uses an outline (3px) with offset (3px). Do not infer a selected state from shadow strength.

The shared success notice uses a brief clip reveal (0.22s ease-out) only when reduced motion is not requested. Operator adds no decorative animation.

## Shapes

Equipment cards and detail panels use the equipment and panel corner roles. Connector cells inherit the field radius; confirmations and close forms use corners (12px). Controls are rounded rectangles, and equipment remains a recognizable SVG silhouette. The selected connector outline sits outside its cell (2px offset), separate from the card's inset outline.

## Components

### Buttons and fields

Primary and secondary controls inherit owner styling with a base minimum height (44px). Desktop header/footer actions become compact (34px); monitoring pagination uses (32px). Primary hover changes fill without translating the button. Disabled buttons use opacity (0.55) and a not-allowed cursor. Inputs and selects use a white fill, a subtle border and minimum height (42px). The operator close-reason textarea has corners (8px), padding (10px), and vertical resizing. Focus uses the inherited blue outline.

### Navigation

Three operator entries: Giám sát trụ, Phiên sạc, Cần xem xét. The active entry has a lighter teal fill, bold label and `aria-current="page"`. Desktop rows have minimum height (50px); mobile rows have minimum height (36px) and compact labels. Account identity and logout remain in the shell footer.

### Equipment and connector controls

Each card combines the charger code, station name, online symbol, equipment drawing, connector strip and connection summary. The operator drawing is (52 × 65px); connector symbols are (19 × 19px). Clicking the card heading or drawing chooses connector 1, falling back to the smallest declared number. Clicking a numbered cell chooses that connector, exposes `aria-pressed`, and preserves that choice on live updates.

Groups appear in this order: Cần chú ý → Đang sạc → Sẵn sàng và trạng thái khác. Offline, faulted, unavailable or unknown states take attention precedence even when another connector is charging. Search and filters operate on the current page and say so; do not imply a whole-network filtered result.

### Operator session list

The operator overview retains the approved full-width horizontal row list. Each row displays session state, station, charger code, connector, energy, elapsed minutes and latest meter timestamp. Elapsed minutes use the clock captured at a successful backend fetch, rather than a clock read during rendering. Search and station filters apply to the current page; the state filter is sent to the server. A collapsed native details guide explains the flow without occupying the first viewport.

Rows use white surfaces, equipment corners, padding (18px), identifier text (18px) and compact metadata (13px). Mobile padding becomes (14px), and summaries wrap. Hover uses the session-row-hover token. Semantic badges use corners (5px), padding (4px 8px), and labels (12px): charging blue for open, muted slate for closed, and the session-review red for review. The review color, compact typography and row padding are intentional operational styling, not defects inferred from detector advisories.

Only selecting a session opens the shared owner detail. The list does not request samples or render a chart before selection. Back restores the list with its page and filters preserved.

### Detail, session and action states

The rail shows the selected connector's status, latest valid measurements with units and timestamps, session link, reset control, and expandable connection metadata. Missing measurements show an em dash and an explanation. A Charging connector without an open session shows a check-data message.

Sessions and Cần xem xét reuse the owner session surface with `area="ops"`; the latter starts with the review filter. Charts, measurement tables and recovery history are shared. Pending messages are read-only. Operator hides the owner card-management area. Reset and remote stop require confirmation and expose command state. Accepted is receipt of a command, not proof that a session has ended or a charger is Ready. After Reset the UI waits for a real StatusNotification; intentionally faulted demo chargers can remain faulted when a simulator only acknowledges Reset. Manual close is shown only for eligible open abnormal sessions, requires a reason and acknowledgement, and relies on backend meter data rather than entered energy.

**The Data Truth Rule.** Present absence, stale data and command acknowledgement explicitly; never substitute synthetic measurements or pretend Accepted ended a session.

## Do's and Don'ts

### Do:

- **Do** preserve the inherited teal shell, equipment silhouettes and numbered connector symbols.
- **Do** retain independent desktop scrolling and the mobile detail/back flow.
- **Do** keep status semantics and units visible alongside icons and color.
- **Do** reuse the shared session surface with operator-scoped backend data.

### Don't:

- **Don't** treat page-local search or group counts as network-wide filtered totals.
- **Don't** reset connector selection merely because live data arrived.
- **Don't** invent telemetry or promote command Accepted to completed operation.
- **Don't** add owner management, driver or accountant workflows to this operator design contract.
