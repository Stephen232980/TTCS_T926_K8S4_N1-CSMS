---
name: CSMS G6 reservation fees
description: Local Operate extension of the inherited owner and driver workspaces.
colors:
  ink: "#193d4b"
  muted: "#526e7b"
  canvas: "#f2f6f7"
  surface: "#fff"
  accent: "#14795e"
  accent-hover: "#0d624b"
  secondary-surface: "#eaf2f5"
  secondary-ink: "#244e60"
  field-border: "#b9cdd6"
  line: "#e4edf0"
  focus: "#2688c1"
  error: "#a3382c"
typography:
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
    lineHeight: 1.5
  section-title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "16px"
  transaction:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
rounded:
  field: "9px"
  action: "10px"
  row: "12px"
  reservation: "14px"
spacing:
  label-gap: "6px"
  compact-gap: "8px"
  form-gap: "12px"
  section: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.action}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    rounded: "{rounded.action}"
    padding: "10px 16px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  reservation-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.reservation}"
    padding: "14px 16px"
---

# Design System: CSMS G6 reservation fees

## Overview

**Creative North Star: "Inherited owner and driver operating workspaces"**

This records the implemented G6 local Operate extension: owner `ReservationPolicy`, driver `ReservationForm` fee acceptance, `DriverReservations` fee outcome, and the reservation fee/reference row in `DriverWalletPage`. Root `PRODUCT.md`, root `DESIGN.md`, and `frontend/src/features/driver/DESIGN.md` retain authority over their existing scopes. There is no new direction contract or approved composition; this record adds no redesign or product-wide identity.

**Key Characteristics:**
- Inherited teal ink, pale canvas, white containers and green actions.
- Native forms and disclosures with visible loading, error and outcome copy.
- Explicit fee amounts, consent and links between reservations and wallet entries.

## Colors

### Primary

The inherited green accent carries primary actions; its darker partner carries hover. Secondary actions use pale blue with teal text.

### Neutral

Ink carries facts, muted slate carries supporting text, and quiet lines separate reservation sections. White fields have visible borders. Blue outlines identify keyboard focus. Error copy uses the inherited red. Wallet fee debits retain the existing wallet minus color and adjustment icon container; they do not introduce a new severity palette.

## Typography

Segoe UI and the inherited sans-serif fallback continue throughout. Reservation headings use the section-title role; reservation explanations and labels use body sizing. Wallet descriptions and amounts use the transaction role, with a bold amount. These are observed local roles rather than a new display ramp.

## Layout

Owner policy fields and actions wrap with the form gap. Driver booking fields wrap, while fee consent spans the form width with an aligned checkbox. Reservation detail is a native disclosure containing separated articles; station names and explanatory copy wrap.

Wallet fee description and amount share a desktop row. At widths at most (480px), they stack with a (4px) gap. The amount stays on one line with `white-space: nowrap` and no shrinking, preserving the minus sign and currency unit. Reference metadata wraps; long identifiers are exposed inside a native disclosure. Driver and owner navigation, safe areas and scrolling remain inherited.

**The Whole Amount Rule.** Keep the fee debit and its currency unit together; stack the fee row on narrow screens rather than splitting the amount.

Local review covered desktop (1366 × 768) and mobile (360 × 800). Screenshots are outside the project at `../../outputs/g6-ui`: `desktop-owner.png`, `mobile-owner.png`, `desktop-consent.png`, `mobile-consent.png`, `desktop-detail.png`, `mobile-detail.png`, `desktop-wallet-final.png`, `mobile-wallet-final.png`, and `mobile-wallet-detail-final.png`. They use disposable local demo data and are not staging or hardware acceptance evidence. Backend conditions and evidence limits remain in `docs/S50_RESERVATION_FEES.md`.

## Elevation & Depth

G6 adds no new elevation. Reservation sections use inherited white surfaces and quiet dividers. Wallet history retains its existing ambient panel shadow and tonal transaction rows; the balance card remains an inherited gradient surface.

## Shapes

Native fields use field corners; actions use action corners. Reservation disclosures use reservation corners and wallet rows use row corners. Fee consent retains a native (20px) checkbox. The reservation fee row uses the shared authored wallet SVG, sized to (20px), with current-color stroke rather than a glyph.

## Components

- Owner policy: labeled integer fee input, save/reload actions and textual status/error feedback. Existing reservations retain their accepted amount.
- Driver consent: positive fees require explicit acceptance of the displayed amount and conditions, including possible negative balance; zero-fee booking does not invent a consent checkbox.
- Reservation detail: accepted fee snapshot and named decision remain separate from reservation state. Charged entries link to the wallet; review copy does not imply automatic refund.
- Wallet reference: the fee row links to its reservation. “Mã giao dịch” discloses the ledger row and reference IDs; the backend fee description also contains the reservation UUID inline and wraps with the description.
- Inherited primitives: green primary actions, pale secondary actions, labeled native inputs, named wallet status badges and the existing navigation. Driver actions and disclosure summaries retain (44px) targets and (3px) blue keyboard outlines offset by (3px); owner inputs retain (42px) minimum height with mobile actions at (44px).

**The Explicit Outcome Rule.** Show the accepted fee and named decision; never infer a charged, waived or refunded outcome from reservation state alone.

## Do's and Don'ts

### Do:
- Do preserve the inherited workspace palettes, native controls and keyboard focus.
- Do keep fee amounts whole and use the authored wallet SVG for reservation fee entries.
- Do retain fee consent, named outcomes and reservation/wallet reference links.

### Don't:
- Don't treat local demo screenshots as staging, hardware or release acceptance.
- Don't turn existing glyph icons elsewhere in the wallet into a new G6 icon convention.
- Don't infer a refund or settled fee from reservation state alone.
