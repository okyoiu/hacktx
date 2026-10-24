# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The surfaces are web technology: the overlay is an Electron app (HTML/CSS/JS renderers), the enrollment page is a plain web page.

## Stack

delegated: Electron for the overlay (transparent, always-on-top windows over the call) plus a Python service (FastAPI) for screen capture, YOLO26 tracking, InsightFace face prints, Muse, SerpApi and the Tiger Data (Postgres + pgvector) database. Chosen because the vision code is Python and Electron makes a click-through overlay straightforward. No front-end framework: plain HTML/CSS/JS renderers.

## Users

People at work who meet many clients, candidates and coworkers on video calls and need to recall who someone is and what they last talked about, without asking "Sorry, who are you again?"

## Product Purpose

Hello Again (working name) is a private overlay installed on the user's own screen. During a call on any app (Zoom, FaceTime, Teams, Meet, Discord…) it recognizes people who have opted in, reminds the user who they are, turns what Muse hears into live insights and one-click actions, and leaves a note after the call. Success: the user never has to admit they forgot someone.

## Positioning

Only the user sees it: it lives on their screen, not inside the call, and works with any call app because it reads the screen rather than integrating with one. Recognition is mutual and opt-in: a person enrolls with their own selfie, sees exactly what is saved and for how long, and can delete it.

## Operating Context

- Runs beside a live video call; it reads the call window by screen capture and listens to call audio through Muse Voice Transcribe.
- Built at HackTX 26 by a team of three (A: capture and vision, B: memory and AI, C: consent and experience), each with a Claude agent.
- Judged mainly in Meta's "Bringing People Closer Together with AI" track, plus SerpApi and Tiger Data tracks.

## Capabilities and Constraints

- Layout: a control bar (pause, waveform, timer, Ask AI ⌘↵, Show/Hide ⌘\), a Live insights panel (topic, points, transcript toggle, actions) and an AI response panel, plus glass name cards beside faces.
- Computer vision (boxes, track ids, scores) is never shown to users; it exists only in the debugging tool `tools/cv_check.py`.
- Face recognition only for people who consented; unknown faces show a thinking card and nothing about them is saved.
- Tools: Muse Voice Transcribe, Muse Spark, SerpApi (google, google_maps, google_events), Tiger Data, YOLO26, InsightFace.
- Undecided: final product name.

## Brand Commitments

- Visual direction is pinned by `docs/ui-reference.png` (user-supplied): dark smoked glass panels with real blur over the call, white text, a sparkle mark for AI, keyboard-shortcut keycaps in the control bar, emoji-led action rows with a hover highlight.

## Evidence on Hand

None yet. All names, places and scores in demos and mocks are sample data and must be labelled as such.

## Product Principles

1. Private to the user: nothing appears to other people in the call.
2. Consent before recognition, every time.
3. Quiet over clever: the overlay must never become its own awkward moment.
4. Memory serves connection: every feature leads to a better conversation or a plan together.
