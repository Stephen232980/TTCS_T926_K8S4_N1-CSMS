---
name: CSMS Owner Workspace — World A
description: Observed owner workspace design; scoped to .owner-shell, not a replacement for other roles.
colors:
  ink: "#193d4b"
  muted: "#526e7b"
  canvas: "#f2f6f7"
  accent: "#14795e"
  accent-hover: "#0d624b"
  sidebar: "#173b47"
  sidebar-text: "#d7e8ee"
  sidebar-selected: "#2c5664"
  surface: "#fff"
  secondary-ink: "#244e60"
  secondary-surface: "#eaf2f5"
  secondary-hover: "#dce9ee"
  field-border: "#b9cdd6"
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
    fontSize: "clamp(24px, 2.1vw, 34px)"
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  panel-title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "23px"
  card-title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "21px"
  panel-body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
    lineHeight: 1.55
  field-label:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
  button-primary:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 720
  button-secondary:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 680
rounded:
  field: "9px"
  action: "10px"
  navigation: "12px"
  charger-card: "14px"
  panel: "16px"
spacing:
  small-gap: "8px"
  compact-gap: "12px"
  standard-gap: "16px"
  grid-gap: "20px"
  panel-padding: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.button-primary}"
    rounded: "{rounded.action}"
    padding: "0 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.button-secondary}"
    rounded: "{rounded.action}"
    padding: "0 18px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "24px"
  connector-available:
    backgroundColor: "{colors.available-surface}"
    textColor: "{colors.available-ink}"
    rounded: "{rounded.field}"
    padding: "4px"
  connector-charging:
    backgroundColor: "{colors.charging-surface}"
    textColor: "{colors.charging-ink}"
    rounded: "{rounded.field}"
    padding: "4px"
  connector-faulted:
    backgroundColor: "{colors.fault-surface}"
    textColor: "{colors.fault-ink}"
    rounded: "{rounded.field}"
    padding: "4px"
---

# Design System: CSMS Owner Workspace — World A

## Overview

**Creative North Star: "World A — Owner workspace"**

This records the implemented station-owner workspace in `frontend/src/features/owner`, chiefly `owner.css`, `OwnerWorkspace.tsx`, `OwnerVisuals.tsx`, the wizards and charging views. Its dark teal navigation, pale canvas, white containers and green actions follow the user-pinned World A. It is a compact operating interface with authored SVG equipment and status symbols, not a product-wide brand replacement.

**Scope boundary:** The frontmatter is normative only inside `.owner-shell`, reached by the `station_owner` home-role branch in `frontend/src/App.tsx`. Login and the other roles retain the incumbent visual world in `frontend/src/index.css`, `frontend/src/App.css` and their components: a light sidebar, pale green canvas, green action palette and system sans stack. Their current colors include canvas `#f4f7f6`, ink `#17211e`, muted `#66736f`, accent `#0b9d6c` and strong accent `#087a58`. Preserve those sources when editing those surfaces; do not apply the owner frontmatter globally. Owner controls inherit the shared font reset, button weights and primary-button transition, with local overrides.

**Key Characteristics:**
- Dark navigation beside a stationary desktop workspace.
- White rounded containers, restrained ambient shadows and compact information groups.
- Native form controls, clear blue keyboard focus and explicit operational states.
- Real station photos when provided; authored SVG drawings for equipment.

## Colors

### Primary

Deep green `accent` identifies primary actions, selected wizard steps, online connection symbols and text selection. Its darker hover partner changes the action surface without moving the button.

### Secondary

Dark teal `sidebar` anchors navigation and pressed session tabs. `sidebar-selected` is the shared hover/current navigation fill. Pale blue `secondary-surface` and its hover partner support lower-priority actions.

### Neutral

Blue teal `ink` and slate `muted` separate current facts from supporting labels. `canvas` surrounds white `surface` containers and also groups meter values and review summaries. `field-border` outlines native fields; `focus` marks keyboard focus and selected equipment.

### Operational states

Available uses green ink on pale green; charging uses blue ink on pale blue; faulted uses red ink on pale peach. Success and error notices reuse available and fault pairs. Unknown and other connector states use the observed neutral treatment rather than an invented severity palette.

**The State Has a Name Rule.** Connector color is paired with a number, authored symbol and accessible label. Connection symbols distinguish online, offline and unknown; selected details also expose the last contact time.

## Typography

The owner shell uses Segoe UI with sans-serif fallback. There is no webfont request or distinct editorial display family. Native buttons, inputs and selects inherit the application font reset.

The page heading is responsive, with the exact ramp in frontmatter. Panel titles use the panel-title role; station and charger group titles use card-title. Supporting panel copy and table/fact rows are compact, commonly (13px), while form labels and main action text use (14px). Session group headings use (20px); detail subheadings use (16px). Main meter values use (24px). Data rows and tables use tabular numerals. Do not infer a complete modular type scale from these role-specific sizes.

Heading sizes tighten to (26px) for the compact desktop height rule and (24px) on mobile. Panel copy has the recorded line height; detail copy uses (1.6). Text wrapping is explicit for names and facts; compact charger codes truncate with ellipsis. The brand label is utility identity, not a reusable display-text role.

## Layout

The desktop shell fills (100dvh), hides outer overflow and uses a (220px) sidebar plus a flexible main column. Pages are flex columns; base padding is (26px 30px 22px) with (16px) gaps, overridden on desktop (width above 800px) by (20px 24px 16px) padding and (12px) gaps. Selected-session pages tighten the gap to (8px). Long station lists, charger grids, detail panes and wizard content scroll internally; flexible regions set `min-height: 0`. Scroll containers contain overscroll. Headers and action footers remain separate from these regions.

Station and charger grids start at three columns. Detail uses a flexible equipment region and a second column of `minmax(280px, 31%)`. Wizard columns are (0.9fr / 1.1fr) with a (32px) gap. Sessions use two-column card grids, and session facts use four columns. These are workspace patterns, not mandatory page compositions for other roles.

At width (1250px) and below, sidebar width becomes (190px); station/charger grids and connector configuration use two columns. At width (800px) and below, a (52px) mobile bar replaces the persistent sidebar. The drawer is (240px) wide and `inert` while closed. Owner pages occupy the remaining viewport height with (16px) padding. Heading actions wrap below the heading; station/session/wizard/configuration grids become single-column, session facts become two-column, detail regions scroll together, and the redundant legend and device preview are hidden. Tables retain a (600px) minimum width inside their scroll region.

Session inspection gives the chart (3fr) and measurement table (2fr) desktop columns with a (24px) gap. The table scrolls independently with sticky column headings. Above width (1000px), the measurement panel is a flex column: retry alerts reserve their own space; the plot takes remaining height while selectors, readout, slider and caption remain nonshrinking. The SVG coordinate system updates from its rendered dimensions in the same paint, preserving readable chart geometry as available space changes. Error state explicitly labels retained samples from the previous successful load and keeps retry and inspection controls reachable. These synchronization and cache semantics are functional constraints, not design tokens.

At width (1000px) and below, chart/table stack, latest readings become two columns, and the plot has (240px) height. At mobile width, session facts, latest readings, tabs, chart and table share one flexible scroll pane with nonshrinking children. The sample table has its own (360px) maximum-height scroll region. Viewport screenshots establish inspection results, not fixed pane dimensions.

The compact desktop rule (minimum width 1100px, maximum height 780px) reduces panel padding and field height; the later desktop rule owns page padding. Desktop session facts use (12px 20px) padding; latest-reading blocks use (10px 20px), and action footers use (8px 16px). A separate short-desktop rule (minimum width 801px, maximum height 850px) reduces charger-card padding and drawing height. The shell responds to viewport dimensions; it does not enforce a 16:9 aspect ratio.

**The Shell Stays Rule.** Keep long content within the implemented scroll regions, with page-level controls reachable at the tested desktop sizes and on mobile. Session facts and inspection content share the mobile scroll pane.

## Elevation & Depth

Depth combines pale tonal groupings with restrained ambient shadows. Panels use `0 10px 28px rgba(25, 61, 75, 0.045)`, station cards use `0 8px 22px rgba(25, 61, 75, 0.07)`, and charger cards use `0 8px 20px rgba(25, 61, 75, 0.1)`. Owner primary and secondary buttons have no shadow; primary hover keeps `transform: none`. Selection uses outlines rather than additional elevation.

The inherited primary-button transition is (180ms ease-out) for background, transform and shadow, with the latter two neutralized by owner overrides. Confirmation notices reveal with a (0.22s ease-out) clip animation only when reduced motion is not requested. No drawer animation is defined in owner CSS.

## Shapes

Forms and numbered connector controls share the field corner role. Actions and meter blocks share action corners. Navigation, session cards and step strips use navigation corners; charger/review/photo-preview containers use charger-card corners; panels and station cards use panel corners. Step numbers and station status dots are circular. Station images crop within rounded card clipping; wizard photo previews contain the full image.

## Components

### Buttons

Primary actions are green with white text, no border or shadow, a base (44px) minimum height and the frontmatter padding. Above width (800px), heading actions, action-footer buttons and charger pagination use (34px) minimum height, (13px) type and (12px) horizontal padding; main form actions retain their base sizing. Mobile primary/secondary controls retain the base minimum height. Secondary actions use pale blue without a border. Their weights come from the shared application stylesheet. Disabled buttons use (0.55) opacity and the native disabled state. Text actions remain unfilled. Smaller equipment actions have their own compact sizes; do not claim every button is a 44px target.

### Inputs / Fields

Native inputs and selects use white fill, a (1px) field border, field corners, a (42px) minimum height and the frontmatter padding. Connector type is a native preset select (Type 2, CCS2, Type 1, CCS1, CHAdeMO, GB/T AC, GB/T DC and NACS), with an undeclared option and Other exposing a required custom field; existing custom values are preserved. Form fields stack a label with a (7px) gap. Placeholder ink is the muted role; the text caret is green. File upload keeps the native input and transfers visible focus to the styled upload label via `:focus-within`.

**The Focus Stays Visible Rule.** Owner `:focus-visible` uses a (3px) blue outline offset by (3px). Preserve native keyboard behavior and explicit labels; do not substitute ornamental focus glows for this treatment.

### Navigation

Sidebar links retain a (50px) minimum height, navigation corners and (14px) horizontal padding. Desktop workspace navigation tabs and subtabs use (34px) minimum height with (6px 12px) padding, (13px) type and (8px) corners; mobile tabs retain their original (12px 16px) padding rather than an explicit fixed-height token. Hover and current share the selected fill; current also uses white text, (700) weight and `aria-current`. Mobile navigation remains accessible through the named menu button with `aria-controls` and `aria-expanded`; closed drawer links are inert.

### Cards / Containers

White panels use the panel corner/padding roles and panel shadow. Station cards clip the (180px) cover photograph and pad content by (20px). Charger cards use the charger-card corner and charger shadow with compact height adjustments. Sessions use pale canvas cards with a hover fill of `#e4edf2`; selected sessions open their detail view rather than adopting the charger outline pattern.

### Numbered connectors and connection symbols

Connectors form a four-column strip, with (6px) gaps and (40px) minimum-height buttons. Their number is placed above a consistent authored SVG. Available, charging and faulted use the semantic pairs in frontmatter; pressed connector selection adds a (2px) blue outline offset by (2px). Charger selection uses the same width with an inset offset of (-2px). Connection uses separate authored online/offline/unknown SVG paths and accessible names, plus visible contact information in selected detail.

### Wizard steps and factual details

Wizard steps use numbered circles and a green current step. Review summaries and meter pairs use pale tonal blocks. Measurements keep units, labels and timestamps; nominal equipment metadata is a separate disclosure. Selected-session details refresh after the session closes rather than retaining open-session facts. Open-session delivered energy is the nonnegative latest-meter/start-meter delta; closed sessions use final energy. Latest aggregate power, temperature, voltage and current appear with units, timestamps and location independently of the inspected older sample page. Missing readings retain their explicit unavailable state. Photo and card validation messages identify their own action and fields rather than sharing an unrelated photo error. Connector-to-session navigation opens the exact backend session. Recovery history is keyed to the selected session and shows loading while changing sessions, preventing previous-session history from appearing as current. Cards identify expiration truthfully, and failed card actions retain their error until an actual retry rather than being cleared by background refresh. These are factual display requirements, not decorative variants.

### Photos and icons

Station photos are authenticated API content loaded into temporary blob URLs and released on cleanup. The upload control accepts JPEG, PNG and WebP with a (20MiB) byte limit and displayed (16 million pixel) limit; animated PNG/WebP use the first frame as the station cover. These are current upload constraints, not image-size design tokens. No photo, loading and failed loading have distinct visible states; a failed authenticated photo fetch offers an actionable retry rather than silently becoming the no-photo state. Card covers use `object-fit: cover`; wizard previews use `object-fit: contain`. The implementation ships authored SVG symbols and charger drawings; review screenshots and the isolated demo upload are not frontend raster assets. General owner icons are stroke-based (22px, 1.8 stroke width, rounded caps/joins); equipment drawings and charts have their own explicit dimensions and fills.

## Do's and Don'ts

### Do:
- **Do** keep owner tokens scoped to the owner shell and preserve incumbent visual sources for login and other roles.
- **Do** pair operational colors with labels and symbols, and retain visible contact and measurement context.
- **Do** use the implemented internal scrolling, responsive drawer and native controls.
- **Do** preserve separate cover cropping and full-photo wizard previews.

### Don't:
- **Don't** apply this owner workspace palette or dark sidebar as a global all-role redesign.
- **Don't** invent station imagery, zero readings or financial totals to fill missing data.
- **Don't** remove focus indicators or leave closed mobile navigation keyboard-accessible.
- **Don't** promote deferred capability placeholders, review screenshots or demo-only assets into a claimed completed product feature.
