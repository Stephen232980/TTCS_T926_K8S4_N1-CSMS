---
name: CSMS Admin Workspace — World A
description: Observed production admin workspace; tokens apply only to the admin shell.
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
  selected-surface: "#edf6f5"
  field-border: "#b9cdd6"
  divider: "#dce7eb"
  focus: "#2688c1"
  success-ink: "#116443"
  success-surface: "#e4f5eb"
  danger-ink: "#a3382c"
  danger-surface: "#fff0ec"
  danger-hover: "#fce1d9"
  warning-ink: "#705410"
  warning-surface: "#faf3df"
typography:
  headline:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "30px"
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "20px"
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    lineHeight: 1.45
  label:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "12px"
  action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 650
    lineHeight: 1.4
rounded:
  badge: "6px"
  control: "9px"
  row: "10px"
  navigation: "12px"
  strip: "14px"
  panel: "16px"
spacing:
  small-gap: "8px"
  compact-gap: "12px"
  page-gap: "14px"
  content-gap: "16px"
  panel-gap: "18px"
  form-padding: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.ink}"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  button-danger:
    backgroundColor: "{colors.danger-surface}"
    textColor: "{colors.danger-ink}"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
  badge-good:
    backgroundColor: "{colors.success-surface}"
    textColor: "{colors.success-ink}"
    rounded: "{rounded.badge}"
    padding: "4px 8px"
  badge-neutral:
    backgroundColor: "{colors.secondary-surface}"
    textColor: "{colors.secondary-ink}"
    rounded: "{rounded.badge}"
    padding: "4px 8px"
  badge-warning:
    backgroundColor: "{colors.warning-surface}"
    textColor: "{colors.warning-ink}"
    rounded: "{rounded.badge}"
    padding: "4px 8px"
---

# Design System: CSMS Admin Workspace — World A

## Overview

**Creative North Star: "World A — Operate workspace"**

The implemented admin workspace inherits the approved owner palette and compact operating character: dark teal navigation, a pale canvas, white panels and green primary actions. It makes account access, attributable actions and measured OCPP signals readable without ornamental imagery. The three implemented compositions are accounts sample 1, audit sample 3 and health sample 2; they share visual primitives while retaining distinct task structures.

**Scope boundary:** This file records `admin.css`, `AdminWorkspace.tsx`, `AdminAccounts.tsx`, `AdminAudit.tsx`, `AdminHealth.tsx` and their shared helpers. Its tokens are normative only inside the admin shell. Root `DESIGN.md` remains the owner identity authority and `PRODUCT.md` remains product truth. Admin inheritance does not change owner behavior or the visual identity of login and other roles. This is a recording of user-authorized production implementation, not an implementation-disabled preview seed. The approved direction and inherited seeds are preserved in `.local/admin-ui-direction.md`.

Evidence comes from shipped source and the local browser report in `impeccable/review/admin-implementation/report.json`. All twelve recorded desktop/mobile captures meet their canvas bounds: desktop (1366×768) has matching document width and height; mobile (390×844) has matching width with deliberate vertical flow. The real local backend (port 8015) and PostgreSQL exercised account creation, role changes, lock with rejected login, unlock, journal filters and health. `docs/ADMIN_UI_IMPLEMENTATION.md` records (182/182) frontend tests across (31) files, passing lint/build and the existing main bundle warning (about 527 kB); the lazy admin chunk is about (33 kB). These are local implementation evidence, not remote CI, staging, deployment or complete Later-story acceptance.

**Key Characteristics:**

- Stationary desktop navigation with independent long-content scrolling.
- Factual list/detail workspaces and a numbered account wizard.
- Four measured health plots, with an individual expanded view.
- Native controls, visible keyboard focus and explicit unknown/stale states.

## Colors

The inherited World A palette balances blue teal text and navigation with a pale cool canvas and a restrained green action accent. Frontmatter preserves the source CSS values as the normative tokens.

### Primary

Deep green `accent` marks the primary action, current wizard step, selection outline, chart data and text selection. `accent-hover` deepens an enabled primary button without changing its geometry.

### Secondary

Dark teal `sidebar` anchors persistent navigation and pressed audit-source controls. `sidebar-selected` supplies hover/current navigation fill; white text and stronger weight identify the current destination. Pale blue secondary surfaces support ordinary actions, initials and neutral badges. Initials and badges use `secondary-ink`; ordinary buttons inherit `ink`.

### Neutral

`canvas` surrounds white `surface` panels and groups explanations, role choices and payload disclosures. `ink` names current content; `muted` carries supporting copy, timestamps and units. `field-border` defines native fields and `divider` separates access controls, wizard footers and graph guides. Selected rows combine `selected-surface` with the green outline. Blue `focus` identifies keyboard interaction independently of selection.

Success green is reused by active-account badges, saved audit entries and notices. Danger ink on a pale peach surface marks destructive account actions and errors. Warning ink on a pale warm surface marks stale data and incomplete observation windows. Suspended accounts and non-Accepted control results retain neutral badges; do not invent severity variants from their names.

**The State Has a Name Rule.** Pair each status color with its visible label. A freshness badge describes observation recency, not a verdict that the system is healthy.

## Typography

The shell uses Segoe UI with sans-serif fallback for operational text; there is no distinct display font or webfont request. Native inputs, selects and buttons inherit the shell font. Page headings use the headline role, panel headings use title, and body copy uses body. Supporting labels, filter labels, badges and timestamps use the compact label role; badges use (600) weight. Buttons use the action role. Native heading weights remain inherited rather than a separately authored display scale.

Chart headings use (16px), detail subheadings (15px), chart labels and inspection outputs (11px), and metric values (29px) with (1.15) line height and (-0.02em) tracking. Metrics and factual data use tabular numerals. This is a role-specific hierarchy, not a complete mathematical type scale. Page headings reduce to (27px) on short desktop and (26px) on mobile. Long email addresses and factual values wrap; the sidebar email truncates with a title exposing its full value.

## Layout

Desktop fills (100dvh) with a (220px) sidebar and flexible main column. Outer overflow is hidden; the page is a flex column with (26px 30px 22px) padding and the page-gap rhythm. Headers, filters, notices and pagination remain outside flexible scroll regions. Accounts and audit use a flexible list plus a (330px) detail column with the panel-gap rhythm; lists and details scroll independently. Both retain `min-height: 0` and `min-width: 0` where flexible sizing requires them.

The guide presents three ordered steps in columns. The account wizard separates scrollable form content from its step strip and action footer; its first step uses (1fr / 0.8fr) columns with a (60px) gap. Health occupies a two-by-two flexible graph grid; expansion changes the grid to one visible plot, not a modal overlay.

At width (1150px) and below, page padding becomes (22px), the detail column becomes (300px), and audit rows compact from three columns to two. At maximum height (700px), desktop above width (800px) tightens page spacing and chart/guide padding.

At width (800px) and below, the shell has one column, automatic height, a minimum (100dvh), and visible outer overflow. The sidebar becomes compact normal-flow navigation above content; its icons are hidden while labels remain. Page padding becomes (20px 14px). Guide, list/detail, wizard columns and health panels stack. Filters/actions wrap; account badges move beneath the name; list scroll regions cap at (420px). Graph panels have a (280px) minimum height, or (450px) when expanded. The mobile frame intentionally scrolls vertically rather than copying the owner's fixed mobile drawer or page-height model.

**The Shell Stays Rule.** Preserve the tested desktop frame while allowing long lists, details and forms to scroll inside it; preserve normal-flow stacking and no horizontal overflow on mobile.

## Elevation & Depth

The local admin stylesheet uses flat white panels and tonal groupings rather than an authored shadow vocabulary. Selection is a (1px) green inset outline, offset (-1px). Keyboard focus uses a (3px) blue outline offset (3px). The stylesheet defines background-color transitions of (150ms ease-out) for buttons and navigation only when reduced motion is not requested. Shared application resets remain inherited; no owner card shadow or reveal animation is promoted into the admin system.

## Shapes

Small status badges use badge corners; fields, actions, role choices and payload disclosures use control corners. Account rows and initials use row corners; navigation and explanation panels use navigation corners. Guides, filter containers and step strips use strip corners; main containers use panel corners. Wizard step numbers are circular. Borders communicate field boundaries and factual grouping; rounded containers do not require shadows.

## Components

### Buttons

Compact and explicit. Main actions use green with white text; ordinary actions use the pale blue surface; destructive lock confirmation uses the danger pair. Base controls have a (36px) minimum height and frontmatter padding. Pagination uses (32px), while chart expansion uses (30px); these observed differences must not become a claim that every target has one fixed height. Disabled buttons use native disabling, (0.55) opacity and the default cursor. Retry/dismiss actions in notices are transparent and underlined.

### Inputs / Fields

Native fields use white fill, a (1px) field-border stroke, control corners, frontmatter padding and a (36px) minimum height. Stacked labels use a (5px) gap; placeholders use muted ink at full opacity. Checkbox/range controls and the text caret use the green accent. Errors appear as labelled alert content, including backend field messages when present.

**The Focus Stays Visible Rule.** Preserve the authored blue focus outline and native keyboard behavior on actions, navigation, disclosures and fields.

### Navigation and source controls

The sidebar has three hash-linked admin destinations with `aria-current="page"` on the current link. Desktop links have a (50px) minimum height with (12px) padding; mobile links use (40px) and compact text. Footer identity, optional return-to-operating-area action and logout remain visible in normal flow. Audit source buttons use `aria-pressed`, with dark teal/white for the active source. Source changes clear filters, pagination and selected details.

### Cards, rows and factual details

White main panels use panel corners without a universal padding token: title strips use (18px 20px 14px), details (22px), wizard content the form-padding role and graphs (16px 18px 12px). List rows are transparent at rest, pale blue on hover, and outlined green when selected; `aria-pressed` carries their selected state. Initials are textual identity cues, not decorative glyph icons. Facts are label/value pairs; payload and metric definitions use native disclosures.

### Accounts guide and wizard

Accounts retain the approved sample 1 list/detail structure and collapsible three-step guide. The guide initially opens unless its previous open/closed preference says otherwise; only that preference is stored locally. Search is debounced (300ms); list pages request (20) records. Role choices come from the backend. Detail selection fetches current account data rather than treating a list row as full detail.

Creation proceeds through login information, one or more roles, and review. Password reveal is an explicit button; review states that a password was entered without displaying it. Password input remains in memory and is cleared after successful creation. Numbered current steps are green and use `aria-current="step"`; the footer identifies progress and keeps continuation actions outside the scrollable form body.

Role editing and lock/unlock have separate states. Self-lock is absent and the current user's admin checkbox cannot be removed. Only active/suspended accounts expose mutations; other statuses are informational. Lock/unlock uses an inline explicit confirmation with its consequence. Saving sends the observed version timestamp; a conflict closes edit/confirmation, reloads detail and retains an actionable error rather than silently overwriting another change. Backend authorization remains final authority.

### Actor-group audit

The approved sample 3 composition groups only the current response page by actor, with a selected-detail pane. It uses actual control and account sources; it does not combine them into invented history. Exact actor email, source-specific target/action filters and Vietnam-time date fields are applied through an explicit submit action. Invalid reversed time ranges show an error. Details remain read-only: command status, response time and payload for control entries, before/after state for account entries. Accepted explicitly means command acceptance, not completed physical execution.

### Health plots and observation states

The approved sample 2 composition shows four actual metrics: online charge points, running sessions, rolling-five-minute OCPP errors and backend response latency. SVG plots resize from their actual container, include labelled axes and measured-point titles, and expose a keyboard-operable range inspector. A plot expands in place and contracts by its button or Escape. Resolution is selectable; definitions explain each metric and the latency sample count.

The main reading and inspector format missing numeric observations as an em dash. Null metrics or absent measured timestamps split plotted segments; no line connects a missing bucket. Zero is plotted only when the backend actually measured zero. The local history had zero online/running/error measurements and no latency calls; that snapshot is evidence, not a default or a fixture to reproduce. Incomplete five-minute windows retain their warning, observed error count and response count. Snapshot age uses the server clock plus elapsed local time; stale retained readings are labelled with their measurement time. Polling is nonoverlapping, aborts on cleanup, observes tab visibility, and supports pause/manual refresh. Load failures retain the last successful health pair with an error and retry.

**The Missing Stays Missing Rule.** Keep unknown readings, warm-up windows and unavailable historical buckets distinct from measured zero; keep measurement timestamps and metric definitions attached to the data.

### Icons and imagery

Navigation uses the existing shared SVG icon component; graphs are authored SVG. No production admin raster asset is introduced. The twelve ignored browser captures are visual QA evidence, not product content or a shipping image vocabulary.

## Do's and Don'ts

### Do:

- **Do** scope these tokens to admin and preserve the root owner identity and other role surfaces.
- **Do** retain the three approved task compositions and their native keyboard-operable controls.
- **Do** pair color with visible status names and distinguish account state, command result and observation freshness.
- **Do** keep timestamps, before/after facts, metric units and missing-data explanations visible.
- **Do** use actual API content and explicit errors/retry instead of substitute data.

### Don't:

- **Don't** turn a local test result or reviewer disposition into remote CI, deployment or whole-backlog acceptance.
- **Don't** fill gaps with fabricated history, zero latency or interpolated unknown observations.
- **Don't** equate Accepted with physical completion or a freshness badge with system health.
- **Don't** expose unsupported journal mutations or account reset/delete/email actions.
- **Don't** ship QA screenshots or reuse their test identities as product assets/data.

**Not canonized:** The CSMS brand label and metric readout are utility identity/data roles, not a reusable system-font display treatment. Single-use decorative colors, arbitrary plot geometry and test snapshot values are not tokens. No detected kicker, eyebrow, glyph-icon or hard-offset-shadow defect is made into a future system rule.
