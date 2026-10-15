---
name: CSMS G4 — Station operation and discovery
description: Scoped extension of the inherited owner and driver teal operating interfaces.
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
  focus: "#2688c1"
  fault-ink: "#a3382c"
  fault-surface: "#fff0ec"
typography:
  supporting-copy:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
  action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
  station-title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "16px"
rounded:
  field: "9px"
  action: "10px"
  station-card: "14px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.action}"
    rounded: "{rounded.action}"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.action}"
    rounded: "{rounded.action}"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  owner-reason-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  station-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.station-card}"
---

# Design System: CSMS G4 — Station operation and discovery

## Overview

**Creative North Star: "Inherited CSMS teal Operate world"**

This scoped record describes the shipped G4 additions to station operation and driver discovery. It inherits the owner world in root `DESIGN.md` and the driver world in `frontend/src/features/driver/DESIGN.md`; those documents retain authority over their shells. G4 adds factual operating controls and station summaries, without establishing a new product identity.

Evidence is `StationOperation.tsx`, `stationOperation.css`, its integration in `OwnerWorkspace.tsx`, `DriverMapPage.tsx` and the discovery rules in `driver.css`. The six reviewed desktop/mobile screenshots received a ship disposition. The subsequent stable geographic map-prop correction changes refresh behavior, not the visual layout. This record describes local UI implementation, not deployment or backend acceptance.

**Key Characteristics:**
- Inline native confirmation with visible keyboard focus.
- Explicit operation consequences and recoverable errors.
- Readable station facts beside the existing geographic map.
- Retained results clearly identified when refresh fails.

## Colors

### Primary

The inherited deep green accent marks primary confirmation and search actions; its darker partner supplies hover feedback without movement.

### Secondary

Pale blue action surfaces with teal ink distinguish cancellation, retry and secondary navigation from confirmation.

### Neutral

Blue teal ink carries station identity and availability counts. Muted slate carries connector types, rates and supporting explanations. White fields and cards preserve the incumbent surface vocabulary. Blue outlines distinguish keyboard focus and selected stations.

Fault ink marks operational errors. Driver search errors also use the inherited pale fault surface. G4 creates no new severity palette.

## Typography

Segoe UI with sans-serif fallback remains inherited. Station titles are stronger than compact discovery summaries; availability counts receive emphasis within supporting copy. Owner operation guidance and field labels remain compact. The frontmatter records recurring local roles rather than a new display ramp. Units stay attached to prices and power; distances retain tabular numerals. Long names, addresses and connector summaries wrap.

## Layout

Owner operation stays inline above the selected station's content. The reason field and action group wrap within the available width; opening confirmation focuses the native field and brings it into the nearest scroll region. The existing owner shell and its responsive scrolling remain authoritative.

Driver discovery keeps search above the map/list composition. Below the inherited tablet breakpoint, map and results stack; wider screens pair them with independently scrollable results. The implemented phone map reduction keeps station summaries reachable. Existing safe-area and navigation rules remain in force. Local gaps, card padding and map dimensions are implementation measurements, not a new spacing scale.

**The Geographic Continuity Rule.** Refreshing price or availability alone must preserve the user's map viewport. Geographic marker data is memoized separately from refreshed commercial and status facts; changes to geographic identity or coordinates can still update the map.

## Elevation & Depth

Discovery cards retain the restrained ambient shadow of the driver world. Selected cards gain a blue inset outline rather than extra elevation. Operation controls and fields add no shadow vocabulary; inherited buttons stay still on hover.

## Shapes

Rounded native fields, actions and station cards reuse the incumbent corner roles. The operation form remains part of the station workspace rather than introducing an overlay or new container silhouette.

## Components

### Operation controls

The station state determines the owner's action: active stations expose suspension confirmation; inactive eligible states expose activation. A blocked station shows the administrative explanation without an owner unblock control. Required reasons are trimmed; whitespace alone cannot enable confirmation. Busy requests disable competing actions and expose `aria-busy`.

**The Consequence Before Confirmation Rule.** Suspension explains that discovery and new starts are blocked while existing sessions continue normally. The result notice repeats the existing-session continuation. Activation explains configuration prerequisites and that discovery updates after refresh.

### Inputs / Fields

The suspension reason is a labelled native input with the inherited field border and corner role. It receives focus on confirmation entry. Blue focus outlines remain visible; cancellation resets the reason and current error. The search field is a native search input with an explicit label and submit action.

### Feedback and recovery

Success uses `role="status"`; errors use `role="alert"`. Station version conflicts and invalid transitions explain that the station changed and offer a reload action. Reload exits the current confirmation so the next action can use current station state. Configuration failures identify the missing prerequisite instead of claiming activation succeeded.

**The Retained Is Not Current Rule.** Failed driver refresh retains the last successful results with an explicit stale-data warning and retry action. Connector navigation is disabled while loading or in error. A changed search clears previous-query results. Current availability is presented as changeable, not a reservation.

### Station discovery cards and map selection

Each card combines station identity and address with available/total connector counts, deduplicated connector type/current/power summaries, current energy rate, and occupation rate with grace minutes when provided. Missing types and rates have explicit fallback text; zero rates remain valid facts. The selection button uses `aria-pressed` and the selected outline. Connector navigation is offered only when the current energy rate exists; external location links remain separate.

The incumbent Leaflet map and native list remain complementary. Local geolocation sorts by straight-line distance and explicitly distinguishes it from driving distance. An over-broad result set requests a narrower search instead of presenting a partial list as complete. Refresh cadence is runtime behavior, not a design token.

## Do's and Don'ts

### Do:
- **Do** inherit the owner and driver shell systems within their existing boundaries.
- **Do** explain operational consequences before confirmation and preserve named feedback states.
- **Do** pair retained discovery data with an explicit stale warning and recovery action.
- **Do** preserve geographic viewport continuity when only prices or availability refresh.

### Don't:
- **Don't** expose owner unblock actions for an administratively blocked station.
- **Don't** present free connector counts as a reservation or straight-line distance as driving distance.
- **Don't** promote local gaps, refresh cadence or screenshot dimensions into global design tokens.

Not canonized: incidental spacing, polling intervals and inherited system-font headings are implementation facts, not a new global scale, motion rule or display-face recommendation.
