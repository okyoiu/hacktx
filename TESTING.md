# Testing Hello Again

## Repeatable local diagnostics

From the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -ra
npm.cmd test --prefix overlay
```

The default Python run removes real database and API credentials for the test
session. Individual tests supply fake keys, fake Muse replies and fake SerpApi
responses. It does not load `.env`. The previous environment is restored after
pytest finishes. Real model tests require `--models` and do not run by default.
Database tests report skips rather than silently passing without a database.

The memory API can be imported and enrollment mocked without OpenCV or loading
InsightFace. Speaker naming uses synthetic landmarks by default. Capture logic
uses OpenCV and MSS, but imports YOLO only when capture actually starts. If an
optional capture dependency is absent, those tests report a specific skip.

POSIX file-mode assertions are skipped on Windows because mode bits cannot
prove Windows ACL privacy. Windows ACL protection remains unverified; these
skips are not security passes. The three strict expected failures correspond
to existing open findings in `docs/security-review.md`.

## Database and face-model integration

Use a dedicated test database, not a teammate's demo database. Existing database
tests create their own rows and clean them up. With dependencies installed:

```powershell
.\.venv\Scripts\uv.exe run --env-file .env pytest --integration -q -ra
.\.venv\Scripts\python.exe -m pytest --models capture -q -ra
```

`--integration` preserves credentials explicitly supplied by the shell/launcher;
it does not load `.env` itself. `--models` permits real model tests, including
weight downloads. Missing model dependencies are reported as skips. A complete
integration run needs all dependencies from `pyproject.toml` and pgvector.

## Zoom rehearsal

Passing automated tests does not certify live Zoom readiness. On Windows,
automatic window following still needs a Windows implementation; capture can
instead take an explicit `--region x,y,width,height`. Start the database, memory
server, overlay, microphone and capture, then rehearse: a consenting participant
appears, is remembered, speaks, receives insights/search results, leaves, and
rejoins with saved memory. Verify pause, deletion and that the overlay stays out
of the shared screen. Live Meta/SerpApi requests consume provider quota.
