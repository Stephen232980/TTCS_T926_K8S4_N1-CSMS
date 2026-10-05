---
name: CSMS Driver Workspace — A
description: Observed driver interface, scoped to the driver shell and preserving the approved owner visual system.
colors:
  ink: "#193d4b"
  muted: "#526e7b"
  canvas: "#f2f6f7"
  surface: "#fff"
  accent: "#14795e"
  accent-hover: "#0d624b"
  sidebar: "#173b47"
  sidebar-text: "#d7e8ee"
  sidebar-selected: "#2c5664"
  secondary-ink: "#244e60"
  secondary-surface: "#eaf2f5"
  secondary-hover: "#dce9ee"
  field-border: "#b9cdd6"
  line: "#e4edf0"
  focus: "#2688c1"
  available-ink: "#116443"
  available-surface: "#e4f5eb"
  charging-ink: "#155e9e"
  charging-surface: "#e8f2ff"
  fault-ink: "#a3382c"
  fault-surface: "#fff0ec"
typography:
  heading:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "26px"
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  panel-title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "22px"
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
  field:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "16px"
  primary-action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 720
  secondary-action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 680
  meter:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "27px"
    fontWeight: 720
    lineHeight: 1.3
rounded:
  field: "9px"
  action: "10px"
  navigation: "12px"
  station-card: "14px"
  panel: "16px"
spacing:
  compact-gap: "8px"
  field-gap: "12px"
  standard-padding: "16px"
  workspace-gap: "20px"
  wide-padding: "28px"
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
  search-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.field}"
    rounded: "{rounded.field}"
    padding: "10px 12px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "22px 18px"
  navigation-current:
    backgroundColor: "{colors.sidebar-selected}"
    textColor: "{colors.surface}"
    rounded: "{rounded.navigation}"
  connector-charging:
    backgroundColor: "{colors.charging-surface}"
    textColor: "{colors.charging-ink}"
    rounded: "{rounded.field}"
---

# Design System: CSMS Driver Workspace — A

## Overview

**Creative North Star: "A — Your charging session"**

This records the shipped driver interface in this directory. The user selected A for the current session and required the existing owner map. Dark teal navigation, pale canvas, white panels, green actions and authored equipment drawings carry the approved owner identity into the driver area. It is a practical Vietnamese operating interface whose current session, station discovery and connector selection have separate views.

The frontmatter applies inside the driver shell only. Root `DESIGN.md` remains the owner specification; neither document replaces the other roles or login. Sources are `driver.css`, `DriverWorkspace.tsx`, `DriverCharging.tsx`, `DriverMapPage.tsx`, shared `StationMap.tsx`, owner `OwnerVisuals.tsx` and inherited application styles. The scoped sidecar lives at `.impeccable/design.json` beside this file.

**Key Characteristics:**
- Responsive bottom navigation, compact rail and full sidebar.
- Large paired energy and elapsed-time readings with explicit units.
- The same Leaflet station map, pins and popups used by owners.
- Authored equipment symbols with named operational states.

## Colors

### Primary

Deep green accent identifies primary actions, station symbols, selection and the text caret. The darker hover surface changes color without moving the control.

### Secondary

Dark teal navigation anchors the workspace. Its selected fill marks both hover and current links. Pale blue secondary surfaces support lower-priority actions and request feedback.

### Neutral

Blue teal ink carries facts; muted slate carries labels and supporting copy. Pale canvas groups readings and surrounds white cards. Fields use a visible border; fact rows use a quiet dividing line. Blue focus marks keyboard location and selected stations or connectors.

Available and preparing connectors use the green pair; charging uses the blue pair; faulted uses the peach/red pair. Remaining connector states use the secondary neutral treatment. Errors retain red text and, on station-search errors, a peach container.

**The Named State Rule.** Pair status color with a visible state label and accessible name; keep unavailable connectors legible while disabled.

## Typography

Segoe UI with sans-serif fallback is inherited through the shell; there is no driver webfont. Paragraphs use the body role. Search inputs and native connector selects retain the field role. Primary and secondary button weights come from shared application CSS.

Headings grow to (30px) at the tablet breakpoint. Session station titles grow from (20px) to (24px), while meter readings grow from the frontmatter role to (38px); units remain smaller. Facts, meter values and distances use tabular numerals. Supporting timestamps and badges are commonly (13px). At the narrow-phone rule, station titles use (18px) and readings use (23px). Keep long station names wrapping rather than assuming fixed sample names.

## Layout

Below (700px), the document scrolls naturally. The compact header holds brand and account disclosure; two fixed bottom links reserve a safe-area-aware main-content footer. Main padding is (22px 16px) with bottom padding of `calc(88px + env(safe-area-inset-bottom))`. Session and station content stack.

At (700px), the shell becomes a (100dvh) grid with an (88px) navigation rail and flexible main column. Outer overflow is hidden; main content scrolls. Main padding becomes (26px 24px 18px). Search field and action sit beside one another. Map and results use (1.3fr / 1fr) columns with a (250px) minimum result column. The results scroll independently with a height limit related to the map viewport.

At (1100px), navigation becomes a (220px) sidebar and main padding becomes (28px 32px 20px). The A session composition pairs the current-session panel with a guide in (1.55fr / 1fr) columns, with a (280px) guide minimum. Both panels can scroll internally. The guide is hidden below this breakpoint. Map/results use (1.65fr / 1fr) with a (310px) result minimum; the map container can scroll.

Map canvas height is `clamp(280px, 40dvh, 400px)` on phones and `clamp(360px, 60dvh, 680px)` from tablet width. At tablet-or-wider widths with height at most (650px), map height becomes (330px), results cap at (384px), and session layout stops flexing to fill available height. At widths at most (370px), side padding tightens, distances wrap below station text, and connector tiles switch from four columns to two.

**The Reachable Content Rule.** Preserve these scroll and safe-area regions so session facts, map controls, connector confirmation and account actions remain reachable at short and narrow viewports.

## Elevation & Depth

White session, connector and guide panels use `0 10px 28px rgba(25, 61, 75, .045)`. Station cards use `0 6px 18px rgba(25, 61, 75, .045)`. The account disclosure has a stronger structural shadow. Selection uses blue outlines rather than lifting cards. Buttons have no shadow or transform; the inherited primary transition is (180ms ease-out) with movement and shadow neutralized by driver overrides. No driver-specific entrance animation is defined.

## Shapes

Fields, badges and connector tiles use field corners. Buttons use action corners; navigation links and meter groups use navigation corners. Station cards use the station-card radius; session and guide panels use panel corners. Map clipping follows the shared rounded canvas. Station pins are circular with a white border; the optional user position is a separate blue circle marker.

## Components

### Buttons and fields

Driver buttons have at least (44px) height. Primary and secondary actions use the frontmatter padding and flat treatment. Disabled shared action buttons inherit (0.62) opacity; disabled connector tiles explicitly retain full opacity and readable state labels. Search has a native labeled search input; connector choice also retains a native select, plus grouped visual tiles. Search inputs use a (1px) border; the inherited select has (8px) corners and (10px) padding.

**The Visible Focus Rule.** Preserve the (3px) blue keyboard outline offset by (3px), native input behavior and explicit labels. Selected station cards have a (2px) inset outline; selected connectors have a (2px) outline offset by (2px).

### Navigation and account

Phone links have (52px) minimum height; tablet rail links use (80px) height and stacked icon/text; desktop links use (50px) height with inline icon/text. Current links expose `aria-current`. Account uses a native details/summary disclosure containing email, logout and an area switch when the existing role flow permits it. Its position changes with the shell.

### Session and guide

The session panel uses the imported owner charger drawing and connector symbol. Energy and elapsed time share a two-column pale meter group. Facts keep station, charge-point code, connector number, session ID, start time and latest reading time separate and explicit. Missing meter data is an em dash or a waiting message. The empty session state uses the same drawing with a station-search action. Desktop guide content explains readings, equipment matching and interruptions.

Current data comes from the real current-session endpoint, with sequential one-second polling after each response, kept mounted while changing views. Polling failure labels retained data as potentially old. Accepted start requests remain waiting; session navigation requires a matching backend-confirmed Started request and session. These are observed display constraints, not invented status variants.

### Shared station map and results

Import the actual shared `StationMap`; preserve its Leaflet tiles, configured attribution, station pins and text-safe name/address popups. The driver supplies station selection, optional location callback and optional user-position marker. Location is requested only by the existing button. The browser sorts all fetched search-result pages using Haversine straight-line distance; copy identifies it as distinct from driving distance. Device coordinates are not posted to CSMS. Tile requests expose the viewed region to the configured provider.

Station cards expose selection, real name/address, optional distance, connector entry and an external station-position link. Returning from connector selection preserves search and selected station. Loading, empty, retry, location failure and tile failure remain visible text states.

### Connector selection and symbols

Group real connector tiles by charge-point code with native disclosures and availability counts. Each tile keeps number, imported owner symbol and status name. Busy/reserved/unavailable states remain disabled. Starting requires an eligible connector, explicit cable confirmation and no open session; backend eligibility remains authoritative. The production interface uses real driver APIs, existing credentialed requests and existing session-expiry handling. No mock facts, price/payment screens, stop/reset action or authorization expansion are implied by this document.

## Do's and Don'ts

### Do:
- Do preserve the owner palette, authored equipment drawings and exact shared StationMap implementation.
- Do retain visible units, timestamps, named states and missing-data feedback.
- Do preserve the bottom navigation, rail and sidebar transitions and their scroll regions.
- Do ground station, connector and session facts in the real driver API responses.

### Don't:
- Don't request device location before the user presses the location button.
- Don't describe straight-line distance as a driving route or treat Accepted as confirmed charging.
- Don't apply these scoped tokens to login, owner layouts or other roles.
- Don't hide unavailable connector labels through disabled opacity or color alone.
