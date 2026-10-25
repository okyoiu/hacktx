#!/bin/bash
# Double-click in Finder to start Hello Again. It opens the overlay app, which starts the database, the memory
# server, face capture and transcription. Quit the app (⌘Q) or close this window to stop everything.
cd "$(dirname "$0")" || exit 1
if [ ! -f .env ]; then
  echo "First time: copy .env.example to .env and add the API keys (see README → Quick start)."
  read -r -p "Press Enter to close." _; exit 1
fi
[ -d .venv ] || uv sync                                  # first run only: Python packages
[ -d overlay/node_modules ] || (cd overlay && npm install) # first run only: the overlay app
cd overlay && exec npm start
