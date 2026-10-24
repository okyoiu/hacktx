# SerpApi connection

`memory.pipeline` owns every SerpApi call, inside the Meta-driven flow: final
Muse Voice transcript lines → Meta Muse Spark writes Live insights actions with an
explicit search query → the user clicks one → `memory.pipeline` → SerpApi → the
AI response panel. `app.py` never calls SerpApi itself. Partial or blank transcript
lines never schedule Muse Spark, blank queries never reach SerpApi, and notes,
points and the other action kinds never trigger a search. There is no polling
search task.

A `places` or `events` action calls `memory.serp.lookup` and the first real result
becomes the AI response, with a link. A `search` action calls `memory.serp.search`
(engine `google`) and Muse Spark summarises the top 3 web results, which are listed
as the response's sources. Missing results answer "Nothing found"; a failed search
ends that response as an error with a credential-safe message, and the call goes on.

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
