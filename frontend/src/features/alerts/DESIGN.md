---
name: CSMS Alerts — Incumbent Extension
description: Scoped incident triage rules for the shared alerts panel; preserves existing role workspaces.
colors:
  ink: "#193d4b"
  muted: "#526e7b"
  surface: "#fff"
  secondary-ink: "#244e60"
  secondary-surface: "#eaf2f5"
  secondary-hover: "#dce9ee"
  field-border: "#b9cdd6"
  focus: "#2688c1"
  fault-ink: "#a3382c"
typography:
  supporting:
    fontSize: "13px"
rounded:
  field: "9px"
  action: "10px"
spacing:
  small-gap: "8px"
  compact-gap: "12px"
components:
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.supporting}"
    rounded: "{rounded.action}"
    padding: "7px 12px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  input:
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
---

# Design System: CSMS Alerts — Incumbent Extension

## Overview

**Creative North Star: "CSMS operational workspace"**

This is a local record of the shared incident triage panel implemented in `AlertsPanel.tsx` and `alerts.css`. It extends the incumbent teal operating interface with a white container, quiet secondary actions and factual Vietnamese labels. The project-root owner design remains authoritative for its shell; this file governs only the alerts feature.

The panel inherits each host's typography and preserves existing monitoring beneath it. Operational facts, delivery state and recovery context take precedence over decoration. Owner presentation is read-only; operator and administrator actions follow the displayed incident state and role.

**Key Characteristics:**
- Incumbent teal ink and pale secondary actions.
- Explicit incident, email and update context.
- Wrapped rows and a bounded scrolling list.
- Native labelled controls with visible keyboard focus.

## Colors

### Secondary

Pale blue secondary surfaces and dark teal secondary ink identify ordinary actions. Hover uses the existing deeper pale-blue surface. This feature does not introduce a primary action color.

### Neutral

White contains the incident panel. Teal ink carries incident identity; muted slate carries station, status, timestamps and delivery context. The inherited field border outlines the close-reason input.

### Operational states

Fault ink identifies fetch and action errors. Blue focus identifies keyboard location. Incident and email states are written as text, without introducing a new severity color scale.

**The State Has a Name Rule.** Pair incident identity with textual status and delivery context; preserve explicit unavailable, empty and stale-data messages.

## Typography

The feature inherits the host font. The owner workspace supplies Segoe UI with sans-serif fallback; the shared application supplies its system sans stack. Inputs and buttons explicitly inherit the font rather than defining a new family.

Incident identity uses native strong text; the section heading leads the list, while supporting copy, details, labels and actions share the compact supporting role. The total uses a lighter heading weight. This is a functional hierarchy, not a new display family or complete modular type ramp.

## Layout

The panel remains nonshrinking within its host. Heading controls and row actions wrap; details grow to occupy remaining space and wrap long identifiers anywhere. The close-reason form spans the row and wraps its controls. Action groups reuse the small gap and rows reuse the compact gap.

The list scrolls vertically inside a bounded region. At the inherited mobile breakpoint (800px), padding tightens, the list bound reduces and buttons receive a (44px) minimum height. Flexible wrapping and full-width inputs support the agreed (360px) reading layout without imposing a new shell or grid. Desktop buttons retain their observed (36px) minimum height; do not generalize mobile sizing to every host control.

**The Context Travels Rule.** Keep charge-point identity, station, incident state and update context available while rows and controls wrap.

## Elevation & Depth

Local alerts CSS uses a white surface and thin row dividers, with no authored shadow or motion vocabulary. Host styles remain inherited. Do not export owner card elevation or animation as alerts tokens.

## Shapes

Actions and native fields reuse the existing action and field corner roles. The panel has gently rounded corners, while row dividers provide separation without creating a card for every incident. Its container geometry is a feature implementation detail rather than a new global radius token.

## Components

### Buttons

Quiet secondary actions use pale surfaces and teal text. Hover changes the fill; disabled controls use native disabling, reduced opacity and a not-allowed cursor. All feature controls use a (3px) blue focus outline offset by (3px). Labels name the affected charge point for incident actions.

### Inputs / Fields

The close reason is a native, visibly labelled full-width input using the incumbent field border and corners. Opening the form focuses the input and scrolls it into view. Administrator closure before recovery requires a reason; submitting or cancelling is explicit. Pending actions disable the field and competing controls.

### Incident list and feedback

Rows expose identity, station, incident state, opening time, email delivery and any close reason. A recovered active incident explicitly says it recovered. Owner rows omit mutation controls. Operators may close recovered incidents; administrators may also close before recovery with a reason. Acknowledgement appears only for open incidents; email retry appears only for failed delivery.

Fetch errors and action errors use separate alert messages; successful mutations use a status message. Failed refresh retains the displayed list with an explicit stale-data warning. Loading and empty results remain distinct. Switching active/history views and pages clears displayed data while the requested view loads. The update timestamp and refresh explanation describe the displayed snapshot, and explicitly distinguish alerts from charge-point online status.

**The Authority Stays Visible Rule.** Omit unavailable role actions, and keep permitted controls tied to incident state. Do not treat hidden controls as an authorization substitute.

## Do's and Don'ts

### Do:
- **Do** keep this extension inside the alerts feature and retain the host workspace's font and layout.
- **Do** preserve textual incident and email states, recovery context and update timestamps.
- **Do** retain explicit stale-data errors, separate action feedback and native keyboard focus.
- **Do** wrap long identifiers and action groups within the bounded incident list.

### Don't:
- **Don't** promote local container geometry, polling intervals or list heights into global design tokens.
- **Don't** expose mutation controls in the read-only owner view.
- **Don't** clear retained facts on refresh failure or imply that alerts replace live charge-point status.
- **Don't** invent severity chips, navigation, imagery or a new brand palette for this extension.


## Compact alert summary

The default view is a single compact toolbar, wrapping to two rows on narrow screens.
Active and closed totals have separate explicit labels and remain visible while the
list is collapsed. Each total comes from its own server-filtered response; unknown
counts display an ellipsis rather than zero. History opens the list; collapse only
hides its contents. Refresh uses a labelled icon button with a mobile touch target.
The update time remains inside the expanded list; polling explanations are omitted.
Read-only owner permissions and operator/admin incident actions remain unchanged.

Expanded lists use a viewport-aware height of 18vh, bounded between 100px and
160px, and scroll internally so the charging area retains space on short screens.


## Floating list

Opening alerts or history now reveals a non-modal floating panel anchored below the
summary, aligned to its right edge. It overlays content without changing layout
height. The panel is at most 400px wide and min(50vh, 440px) tall with internal
scrolling, and sits above the bottom edge with 12px side margins on mobile. It has an explicit close button,
Escape dismissal with focus returned to the trigger, and outside-click dismissal.
The charging workspace remains interactive; no backdrop or focus trap is used.
This supersedes the previous expanded in-flow list and its height bounds.

On desktop the owner popover fits within the right detail column (31%, minimum
280px, capped at 400px); operator uses its existing 320px detail column. The
equipment grid stays unobscured. Mobile retains the viewport-bounded overlay.
