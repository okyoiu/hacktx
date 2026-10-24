# Hello Again: working rules for people and agents

Private glass overlay for Teams/Zoom calls: names people who opted in, shows Top picks from the Muse transcript. Architecture, setup and run commands are in README.md; read it first.

## Who owns what

| Role | Folder | Branch |
|---|---|---|
| Capture (Person A) | `capture/` | `agent/capture` |
| Memory (Person B) | `memory/` | `agent/memory` |
| Overlay (Person C) | `overlay/`, `web/` | `agent/overlay` |
| Coordinator (main session) | everything shared, merges | `starter-scaffold` |

- Work only in your own folder.
- **Shared files belong to the coordinator:** README.md (it defines the event shapes between parts), `pyproject.toml`/`uv.lock` (dependencies), `shared/mocks/`, IDEAS.md, CLAUDE.md. Need a change there, such as a new dependency or a new event field? Stop and ask instead of editing.
- Commit small, prefixed with your folder (`capture: …`). Open a PR into `starter-scaffold` (into `main` once that's merged).
- Never put API keys in code or commits. Keys live only in `.env`.

## Shared services: don't stop them

- Postgres + pgvector in Docker: container `hello-again-db`, port 5432.
- The coordinator's memory server on port 8000.
- To test your own branch's server, run it on another port: `uv run --env-file .env uvicorn memory.app:app --port 8001`, and point clients at it with `MEMORY_URL=http://localhost:8001`.
- Tests that touch the database must create their own rows and delete them afterwards, never wipe tables.

## Checks before you say "done"

- `uv run pytest`
- `node --check overlay/*.js` for overlay changes
- Overlay UI follows README "Overlay UI rules": click-through by default, one action per card shown on hover, thinking sparkle instead of "unknown".
- Electron windows draw on top of the user's real screen: run `npm run mock` briefly and close it.
