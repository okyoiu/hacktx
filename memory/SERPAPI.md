# SerpApi connection

Muse's `place` and `event` picks with a `search` query call `memory.serp.lookup`
from the transcript background task. The first real result replaces the pick's
title and detail, using the existing overlay event format. Missing results or
failed searches do not publish a place/event card; captions and other picks continue.

Set `SERPAPI_KEY` in the root `.env` (see `.env.example`). The key stays on the
Python server. `DEMO_LL` centers Maps searches and defaults to downtown Austin.
Optional `SERPAPI_LOCATION` centers Events searches and defaults to
`Austin, Texas, United States`. Mention another city in the query to target it.

Check the connection independently of Muse, Postgres and capture:

```sh
uv run --env-file .env python -m memory.serp place "climbing gyms in Austin"
uv run --env-file .env python -m memory.serp event "climbing meetups in Austin"
```

The command prints the first result as JSON, or `null` for no results. Configuration
and provider failures exit with status 1 and a credential-safe message.

The cache holds up to 256 normalized queries in memory per server process.
Kind, credentials and location settings are part of the cache key. Concurrent
lookups are serialized to prevent duplicate requests for the same query. Failures
are not cached. Restart the memory server between demo sessions to clear results.

Offline tests (no API credits):

```sh
python -m pytest memory/test_serp.py -q
```

API references: [Maps](https://serpapi.com/maps-local-results) and
[Events](https://serpapi.com/google-events-api).
