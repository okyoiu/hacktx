---
name: Hello Again
description: A private smoked-glass overlay that floats over a live video call.
colors:
  smoke: "rgba(24, 26, 32, 0.62)"
  smoke-card: "rgba(22, 24, 30, 0.74)"
  rim: "rgba(255, 255, 255, 0.17)"
  rim-top: "rgba(255, 255, 255, 0.24)"
  rule: "rgba(255, 255, 255, 0.14)"
  fill: "rgba(255, 255, 255, 0.08)"
  hover: "rgba(255, 255, 255, 0.13)"
  press: "rgba(255, 255, 255, 0.2)"
  ink: "#FFFFFF"
  ink-2: "rgba(255, 255, 255, 0.95)"
  ink-3: "rgba(255, 255, 255, 0.68)"
  known: "#7EE2B0"
  disc-ink: "#15171C"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 650
    letterSpacing: "-0.012em"
  name:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 650
    letterSpacing: "-0.01em"
  control:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    letterSpacing: "-0.005em"
  timer:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    letterSpacing: "0.01em"
    fontFeature: "tnum"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  small:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    fontFeature: "tnum"
rounded:
  panel: "16px"
  card: "14px"
  field: "12px"
  control: "11px"
  row: "10px"
  button: "8px"
  keycap: "7px"
  pill: "999px"
spacing:
  hairline: "2px"
  xs: "6px"
  sm: "9px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  window-margin: "24px"
components:
  panel:
    backgroundColor: "{colors.smoke}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "16px 20px 18px"
    width: "448px"
  control-bar:
    backgroundColor: "{colors.smoke}"
    rounded: "{rounded.panel}"
    padding: "0 9px 0 12px"
    width: "448px"
    height: "56px"
  pause-disc:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.disc-ink}"
    rounded: "{rounded.pill}"
    size: "32px"
  key-button:
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 6px 0 10px"
    height: "38px"
  key-button-hover:
    backgroundColor: "{colors.hover}"
  keycap:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.keycap}"
    padding: "0 6px"
    height: "26px"
  text-button:
    textColor: "{colors.ink-2}"
    typography: "{typography.body}"
    rounded: "{rounded.button}"
    padding: "0 9px 0 7px"
    height: "30px"
  text-button-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.ink}"
  text-button-pressed:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink}"
  icon-button:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.button}"
    size: "30px"
  action-row:
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.row}"
    padding: "8px 10px"
    height: "38px"
  action-row-hover:
    backgroundColor: "{colors.hover}"
  action-row-active:
    backgroundColor: "{colors.press}"
  query-chip:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "30px"
  ask-field:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "0 8px 0 14px"
    height: "46px"
  source-link:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink-2}"
    typography: "{typography.small}"
    rounded: "{rounded.button}"
    padding: "0 8px 0 10px"
    height: "28px"
  source-link-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.ink}"
  name-card:
    backgroundColor: "{colors.smoke-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "10px 12px 11px"
    width: "208px"
  thinking-pill:
    backgroundColor: "{colors.smoke-card}"
    rounded: "{rounded.pill}"
    padding: "8px 14px 8px 10px"
---

<!-- Lives at overlay/DESIGN.md (not the repo root) because this is a multi-owner repo and the overlay owner writes only inside overlay/. Scope: the Electron overlay. -->

# Design System: Hello Again

## Overview

**Creative North Star: "The Smoked-Glass Co-pilot"**

Three smoked-glass slabs float over a live call (control bar, Live insights, AI response) and small glass name cards sit beside faces. The world is the macOS HUD: real OS blur behind a light smoke, a hairline white rim, white system type on a monochrome ground. It never competes with the call. The call itself is the colour and the background; the overlay is a quiet, legible layer over it.

Density is calm and glanceable: one 448px column per panel, a 16px title, up to three points, a short answer. Hierarchy comes only from weight and size, never from dimming text. Motion is soft and optical (blur-in, a breathing waveform, a turning sparkle) and everything fades back into the call when the conversation goes quiet.

The system refuses the sidebar dashboard, a docked strip of picks, and any visible computer-vision chrome (boxes, landmarks, confidence numbers).

**Key Characteristics:**
- Smoked glass with OS blur (`vibrancy: 'hud'` on macOS, `acrylic` on Windows 11), a 1px white rim and a brighter inner top edge.
- White ink only; three weights (400, 500, 650) carry all hierarchy.
- Colour comes only from emoji action markers, the green "recognised" dot and the call showing through.
- Authored 1.6px-stroke line icons, keycap chips for shortcuts, the four-point AI sparkle mark.
- Optical motion on one expressive curve; panels fade to 0.3 after 20s of quiet.

## Colors

A monochrome glass palette: one smoke, white ink at three strengths, white veils for state, and a single green.

### Primary
- **Recognised Mint** (`known`): the 7px dot beside a recognised person's name on a name card. The only authored hue in the system.

### Neutral
- **Call Smoke** (`smoke`): the tint on panel and bar glass. It sits over real OS blur, so it stays light; at this strength white text on bare glass holds about 5:1 (body ink-2 about 4.7:1) even over a pure-white window before the OS tint.
- **Card Smoke** (`smoke-card`): the heavier tint on name cards. The full-screen cards window cannot blur the desktop, so the card carries its own darkness to read over video.
- **Glass Rim** (`rim`) and **Rim Highlight** (`rim-top`): the 1px outer border and the 1px inset top edge that give each slab its edge.
- **Hairline Rule** (`rule`): the divider under every panel header.
- **Veil** (`fill`), **Hover Veil** (`hover`), **Press Veil** (`press`): white washes for resting filled surfaces (chips, source links, the ask field, a pressed toggle), hover and press.
- **White Ink** (`ink`): titles, names, action labels, the live timer, the thinking verb, error headlines.
- **Near-White Ink** (`ink-2`): all secondary text (points, answer body, transcript, card lines, chip text, button labels at rest).
- **Mark Grey** (`ink-3`): marks only, specifically the paused or offline waveform bars. Never text.
- **Disc Ink** (`disc-ink`): the pause/play glyph on the white pause disc.

### Named Rules
**The Call Is the Colour Rule.** No authored hue beyond the recognised dot. Emoji action markers bring their own colour as content; the call behind the glass supplies the rest.

**The No-Dimming Rule.** Secondary text is `ink-2` (0.95), never lower. Hierarchy comes from weight and size. `ink-3` exists for marks, not words.

**The White Error Rule.** Errors carry no hue: the first line is white at 650, followed by a recovery line in body text.

## Typography

**Body Font:** the platform UI face: SF Pro Text on macOS, Segoe UI Variable on Windows (system-ui fallback).

**Character:** native HUD type. On a glass layer over someone else's app, the OS face is the world's own material; it reads as part of the desktop rather than a branded panel.

### Hierarchy
- **Title** (650, 16px, -0.012em): panel titles, the insight topic, "Actions".
- **Name** (650, 15px, -0.01em): the person's name on a card.
- **Control** (500, 15px, -0.005em): control-bar labels ("Ask AI", "Show/Hide").
- **Timer** (500, 15px, tabular figures, 0.01em): the call clock.
- **Body** (400, 14px, 1.45): points, answer paragraphs, action labels, transcript lines, panel-header text buttons.
- **Small** (400, 13px): card line, source links. Keycaps use 13px at 500.
- **Caption** (400, 12px, tabular figures): the "Met …" date on cards. Transcript speakers use 12.5px at 650.

### Named Rules
**The Three Weights Rule.** 400 body, 500 control labels and timer, 650 titles, names and the thinking verb. No other weights.

## Layout

Each panel is a fixed 448px column. Electron places them in a top-right cluster with a 24px screen margin and 12px gaps: the 56px control bar on top, the AI response panel under it, Live insights to its left and top-aligned. Each panel window resizes to its content height. Name cards (208px) are positioned beside faces on a full-screen, click-through window.

Spacing is small and tight: 2–3px between list rows, 6–10px between inline items, 14–16px around the header rule, 20px panel side padding. Action rows and transcript lines bleed into the padding with negative margins so their hover wash lines up with the text column. The transcript scrolls at 300px with a 6px thumb.

## Elevation & Depth

Depth is material, not shadow: the OS blur plus the smoke, edged by a 1px rim and a 1px inset top highlight. In the Electron panels that is all there is. Name cards add one soft drop because they float over video without blur; the browser preview adds a similar drop to stand in for window separation.

### Shadow Vocabulary
- **Rim highlight** (`box-shadow: inset 0 1px 0 rgba(255,255,255,0.24)`): every glass surface.
- **Card float** (`0 14px 32px -14px rgba(0,0,0,0.6)`): name cards, together with the rim highlight.
- **Preview float** (`0 22px 48px -20px rgba(0,0,0,0.6)`): panels in the browser preview only.

### Named Rules
**The Glass Not Shadow Rule.** A slab gets its depth from blur, smoke and rim. Drop shadows are soft, offset only downward with negative spread, and only where there's no OS blur.

## Shapes

Soft continuous corners that get smaller as the element gets smaller: panels 16px, cards 14px, ask field 12px, control-bar buttons 11px, action rows 10px, header buttons and source links 8px, keycaps 7px. Circles for the pause disc and the recognised dot; full pills for the query chip and the thinking card. Borders are 1px white hairlines only.

## Components

### Control Bar
A 56px glass strip that drags the window. In order: a 32px white pause disc (scale 1.06 on hover, 0.95 on press), a seven-bar waveform, the timer, then "Ask AI ⌘↵" and "Show/Hide ⌘\" as key buttons pushed right. Paused or offline: bars turn `ink-3` and settle flat, the timer drops to `ink-2`.

### Buttons
- **Key button:** transparent 38px label at Control weight with keycaps; hover `hover`, press `press`.
- **Text button / Icon button:** 30px, 8px radius, `ink-2` at rest; hover brings `hover` and white ink. A pressed toggle ("Show transcript") rests on `fill` with white ink. Disabled icons go to 0.35 opacity.
- **Icons:** authored line icons, 18px, 1.6px stroke, round caps and joins, drawn in `currentColor`. Copy flips to a check for confirmation.

### Keycap
26px minimum square, 1px border at white 0.3, 7px radius, 13px/500 `ink-2`. Shows shortcuts inline in labels and in the ask field.

### Action Row
A full-width 38px row: emoji marker (20px slot, 15px), then the label in white. Transparent at rest; the hover wash is the single affordance. Busy rows show `fill` and a progress cursor.

### Query Chip
A 30px pill in the response header: `fill` with a 1px white 0.2 border, optional emoji, the question ellipsized in `ink-2`.

### Ask Field
46px, 12px radius, `fill` with a 1px white 0.18 border that brightens to 0.45 on focus. 15px white input, white caret, `ink-2` placeholder, a ↵ keycap at the end.

### Source Link
28px, 8px radius, `fill`, 13px `ink-2`, followed by a 14px outward-arrow line icon. Hover: `hover` and white.

### Name Card
208px glass on `smoke-card`, 14px radius, card float shadow. Row one: recognised dot and name. Then a 13px context line and a 12px "Met" date. Click-through, never takes the mouse. While recalling it collapses to a thinking pill: turning sparkle and a shimmering verb.

### Thinking State
The sparkle mark turns (0 to 180deg, scale 0.8 to 1.06, 2.4s loop) beside a white 650 verb that rotates through a short list ("Thinking…", "Searching…"). A moving mask shimmers across the verb; the text itself stays white. Shown instead of "unknown" anywhere a result is pending.

### Motion
One curve, `cubic-bezier(0.16, 1, 0.3, 1)`. Panels enter with blur 8px, opacity and a 6px drop over 0.5s. Cards enter with blur 6px and scale 0.96, and leave in 0.25s ease-in. New content rises 4px out of a 4px blur over 0.45s, staggered 70ms per answer paragraph. Electron windows fade in over 220ms and out over 160ms; idle panels fade to 0.3 over 800ms. Hover colour changes take 0.15s. Under reduced motion, all animation and transition stop and the shimmer mask is removed.

## Do's and Don'ts

### Do:
- **Do** put every surface on `smoke` (panels) or `smoke-card` (cards) with the 1px rim and inset top highlight.
- **Do** set secondary text in `ink-2` and build hierarchy from the three weights (400 / 500 / 650) and size.
- **Do** keep each card or row to one action, revealed by its hover wash.
- **Do** show the turning sparkle and a thinking verb while a result is pending, never "unknown".
- **Do** draw icons as 1.6px round-stroke line art in `currentColor`; show shortcuts as keycaps.
- **Do** check contrast over a white window with no OS tint, including on `fill`, `hover` and `press` surfaces.

### Don't:
- **Don't** add a hue for status or error; errors are white at 650 with a recovery line.
- **Don't** set text in `ink-3` or anything below 0.95 white.
- **Don't** show computer-vision chrome (face boxes, landmarks, confidence scores).
- **Don't** arrange the overlay as a sidebar dashboard or a docked strip of picks.
- **Don't** use hard or offset shadows; depth is blur, smoke and rim.
