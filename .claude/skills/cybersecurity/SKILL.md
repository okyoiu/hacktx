---
name: cybersecurity
description: Security review for Hello Again. Use before merging anything that touches face prints, consent, people's notes, API keys, server routes, file uploads, the Electron overlay, or text that came from Muse/SerpApi; and whenever someone asks "is this safe?". Reports ranked findings with file:line and a fix; never writes exploit code.
---

# Hello Again security review

Hello Again stores **biometric data** (face prints), **notes about real people**, and **API keys**, and it shows text written by an AI that read untrusted speech. Review with that in mind. Say "Using the cybersecurity skill" when you start.

## 1. Run the tools first

- `/security-review` on the branch's changes, and `ponytail:ponytail-audit` for risky untested code.
- Secrets in history: `git log -p --all | grep -nE "(sk-|api_key=|tsdbadmin:[^@]+@|SERPAPI_KEY=.+|MODEL_API_KEY=.+)"` (print only file and line, never the value).
- Dependencies: `uv run --with pip-audit pip-audit` and `cd overlay && npm audit --omit=dev`.

## 2. Check these, in this order

| Area | What must hold |
|---|---|
| **Secrets** | Keys only in `.env` (git-ignored). Never in code, commits, logs, error messages or URLs that get logged. Watch `httpx` errors: they include the request URL, and SerpApi's key is a query parameter. |
| **Consent and biometrics** | No face print is stored without a consent row. Unknown faces are never saved. Delete removes the person, prints, notes and encounters (cascade). Expired consent is purged. Test data uses only InsightFace's bundled images or fakes, never real people's media. `notes/` stays git-ignored. |
| **Network exposure** | The server listens on the LAN so phones can enroll, so every route is reachable from that Wi-Fi. Flag any route that leaks names, notes or transcript to an unauthenticated caller (`/ws`, `/people/{id}`, `/ask`), and propose the smallest fix (bind to 127.0.0.1 and expose only `/enroll`, or a shared token header). |
| **Input** | Every body is a pydantic model with length and size limits; uploads are capped and decoded safely; SQL uses parameters only (`%s`), never string building; file paths (notes) can't be steered by user text. |
| **AI and search output** | Transcript text is untrusted (prompt injection). Model output is validated before use (`picks.parse`), never executed, never used as a SQL fragment or path. Links shown in the overlay are `http(s)` only and opened with `shell.openExternal` after that check. |
| **Electron** | `contextIsolation` on, `nodeIntegration` off, a strict CSP, no remote pages loaded, `setWindowOpenHandler` denies new windows, IPC handlers validate their arguments, `preload.js` exposes only named functions. |
| **Overlay and web pages** | Untrusted text goes in with `textContent`, never `innerHTML`. The enroll page needs the consent box and shows what is stored. |

## 3. Report

One list, most severe first. Each finding: **severity** (critical, high, medium, low), **file:line**, **what an attacker or accident could do** in one plain sentence, and **the smallest fix**. Say what you checked and found fine, in one line. No exploit code or step-by-step attack recipes.

Fix only what your role owns (see CLAUDE.md); for code in another folder, hand the finding to the coordinator with the fix written out.
