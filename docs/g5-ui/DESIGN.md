---
name: CSMS G5 — Driver reservations
description: Implemented reservation extension of the incumbent teal driver Operate workspace.
colors:
  ink: "#193d4b"
  muted: "#526e7b"
  surface: "#fff"
  accent: "#14795e"
  accent-hover: "#0d624b"
  secondary-ink: "#244e60"
  secondary-surface: "#eaf2f5"
  secondary-hover: "#dce9ee"
  field-border: "#b9cdd6"
  line: "#e4edf0"
  focus: "#2688c1"
  error-ink: "#a3382c"
typography:
  title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "16px"
  supporting-copy:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
    lineHeight: 1.5
  field:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "16px"
  label:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
  primary-action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 720
  secondary-action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 680
rounded:
  field: "9px"
  action: "10px"
  disclosure: "14px"
spacing:
  text-gap: "8px"
  form-gap: "12px"
  section-gap: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.primary-action}"
    rounded: "{rounded.action}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.secondary-action}"
    rounded: "{rounded.action}"
    padding: "10px 16px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  booking-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.field}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  own-reservations:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.disclosure}"
    padding: "14px 16px"
---

# Design System: CSMS G5 — Driver reservations

## Overview

**Creative North Star: "A — Your charging session"**

G5 extends the existing driver Operate interface with booking at the selected connector and a disclosure for the driver's reservations. It inherits the teal shell, pale canvas, white containers, green primary actions and native controls recorded in `../../frontend/src/features/driver/DESIGN.md`. Compact Vietnamese copy keeps equipment identity, confirmation and expiry visible alongside the charging flow.

This is a local extension, not a new root visual world. `../../PRODUCT.md`, `../../DESIGN.md` and the incumbent driver design document remain authoritative and unchanged. Sources are `ReservationForm.tsx`, `DriverReservations.tsx`, `reservations.css`, `DriverCharging.tsx`, `DriverWorkspace.tsx` and inherited driver/application styles. The companion sidecar is `.impeccable/design.json` beside this document.

**Key Characteristics:**
- Booking stays with the selected connector.
- A native disclosure keeps personal reservations compact until expanded.
- Visible ownership and confirmation labels accompany connector status.
- Request uncertainty remains explicit until backend confirmation.

## Colors

### Primary

The inherited deep green accent identifies the request submission action. Hover uses its darker partner without raising or moving the button.

### Secondary

Pale blue surfaces and teal text mark checking support, refreshing, cancelling and paging. The surrounding navigation retains the incumbent dark teal shell.

### Neutral

White disclosures and fields sit against the inherited pale canvas. Teal ink carries titles and confirmed facts; muted slate carries equipment context, timing and explanatory copy. Field borders and quiet row dividers remain separate. Errors use the inherited red ink and visible alert text.

**The Named Ownership Rule.** Identify an owned reservation with “của bạn” in the selected connector label and the charging eligibility message; a generic Reserved badge alone does not establish ownership.

## Typography

Segoe UI with sans-serif fallback is inherited. Reservation headings use the title role; paragraphs use supporting copy, with explicit wrapping for long station names and timing text. Form labels use the label role, while native select and datetime input text keep the larger field role. Buttons keep the inherited action weights. The summary uses (600) weight; confirmed status is native strong text, not a new display style.

## Layout

The personal-reservations disclosure sits above the session/connector/map flow on non-wallet driver views. It starts collapsed; a successful booking/change event opens it. Its summary is at least (44px) high. Expanded content has (12px) top padding and rows with (14px) vertical padding and bottom dividers. Pagination wraps when needed.

The booking section sits inside the selected connector panel, below charging controls. Its top divider and (16px) vertical padding separate booking from immediate start. The expanded form wraps with a (12px) gap; labels flex from (200px), and expiry copy spans a full row. Below (700px), form buttons flex from (130px). The disclosure and form do not shrink in a flex column.

The reservation content has no maximum-height clip or nested scrolling cap. It grows within the inherited workspace scroll model: document scrolling on phones and the main content scroll region from tablet width. Preserve the driver's safe-area bottom padding and fixed mobile navigation. The G5 widgets do not redefine shell breakpoints or map-result scroll behavior.

**The Reachable Actions Rule.** Let expanded reservations grow so refresh, cancel, expiry text and the connector/start flow remain reachable through the shell's scroll region.

## Elevation & Depth

The reservation disclosure is a flat white container without its own shadow. The inline form gains separation from its divider, not elevation. Existing connector panels retain their ambient driver shadow. Primary and secondary controls remain flat on hover; no G5 entrance or expansion animation is introduced.

## Shapes

Fields use the inherited field corners and a (1px) border. Actions use the action corners. The reservation disclosure uses the rounded disclosure role; row separators stay straight and unobtrusive. Native details/summary and native form inputs preserve their browser behavior.

## Components

### Buttons and fields

Controls retain at least (44px) height. Primary submission is green; lower-priority actions are pale blue. The shell's keyboard focus is a (3px) blue outline offset by (3px). Native labels name arrival selection and datetime entry; choosing the later-arrival option focuses its datetime input. Busy mutations disable affected controls and expose explicit sending/cancelling copy.

### Selected-connector booking

The section explains that a request holds from now and is successful only when the charger accepts. Arrival is now or within the next two hours; the later option uses a native datetime-local field with min/max bounds. Displayed expiry is arrival plus (15 minutes), or (15 minutes) after recording an immediate request. The form is offered on connector data that declares reservation capability. Unverified or unsupported capability shows a support-check action with explanatory copy; current availability and existing charging conditions gate that action.

A booking UUID and its connector/arrival body are stored in sessionStorage before sending, scoped to driver and connector. When delivery is ambiguous, the same request is retried and the arrival controls stay locked. Definitive client errors clear the stored attempt; network ambiguity, HTTP 408 and server errors retain it. A recorded response announces its actual expiry and directs the driver to the disclosure rather than claiming charger confirmation.

### Personal reservations and cancellation

The summary carries the current status or count. Rows show station, charger code, connector number, named status, arrival and expiry. Pending, uncertain, cancellation-pending and expiry-release-pending rows explicitly say final confirmation is missing and the connector remains held. A successful fetch timestamp and five-second refresh interval accompany the data; load errors label retained data as potentially old. The list refreshes on visible-tab return and reservation changes and includes empty, loading, alert and pagination states.

Cancellation appears only when the backend supplies `can_cancel`. Its UUID is stored by driver and reservation; network ambiguity, HTTP 408 and server errors retain it for the same cancellation retry. Definitive client errors clear that identity. Busy actions block concurrent cancellation; list load errors disable cancellation of potentially stale facts. A request to cancel is not displayed as final cancellation until the response status supports that fact.

**The Confirmed Truth Rule.** Keep pending, uncertain, cancel-pending and release-pending states distinct from confirmed reservation or release; never replace uncertainty with a success claim.

### Reservation-aware charging

The connector picker and selected-connector text explicitly identify the driver's own reservation and whether it can start or is waiting. Backend `can_start` is authoritative when provided. The fallback permits Available/Preparing or an owned Reserved connector; it does not enable someone else's Reserved connector. Existing cable confirmation, open-session checks and backend start validation still apply. A reservation-related start rejection directs the driver to inspect their reservation.

Booking and disclosure copy state that no reservation fee is charged and no-show fees are not applied. G6 fee work remains separate; this extension defines no price, fee-calculation or settlement design. A backend-provided no-show exemption is shown only when present.

Source inspection and supplied captures bound this record. Initial form captures are `../../../../outputs/g5-ui/desktop-form.png` and `../../../../outputs/g5-ui/mobile-form.png`; final active captures are `../../../../outputs/g5-ui/desktop-active-final.png` and `../../../../outputs/g5-ui/mobile-active-final.png`. Final review disposition supplied for this scope was ship after removal of the content-height cap and explicit ownership labels. The captures show those rendered surfaces, not real-device OCPP acceptance, production rollout or full accessibility certification.

## Do's and Don'ts

### Do:
- Do inherit the driver palette, focus treatment and shell scroll behavior.
- Do keep connector identity, ownership, confirmation and expiry visible together.
- Do preserve the same request identity when delivery is uncertain.
- Do keep accepted cancellation separate from confirmed release.

### Don't:
- Don't clip expanded reservation content behind a fixed height cap.
- Don't label an uncertain request as a confirmed booking or cancellation.
- Don't interpret a generic Reserved state as the driver's permission to start.
- Don't infer G6 fees or real-device acceptance from this UI record.
