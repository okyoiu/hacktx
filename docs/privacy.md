# Privacy: what Hello Again does with your face and your words

Facts from the code on main `7754241`. Each line points at the part of [`security-review.md`](security-review.md) that checks it. If the code changes, this page and those sections change with it.

**In one paragraph.** Hello Again runs on the host's laptop. It only recognises people who agreed to be remembered. It turns your face into numbers (a *face print*) and never keeps your photo. To write its notes, it sends what is said on the call to Meta's Muse. It keeps everything for one year, or until you delete it, and you can delete it yourself at any time.

## What it keeps, and where

The database is Postgres. By default it is a Docker container on the host's laptop, reachable only from that laptop (`127.0.0.1:5432`). If the host sets `DATABASE_URL` to **Tiger Cloud**, the same tables live in that cloud database instead (TLS connection), so with Tiger the face prints and notes are stored on Tiger's servers, not only on the laptop.

| Where | What | Why it exists |
|---|---|---|
| table `people` | an id, your name, the date you first met, who you are to the host (a label the host types or Muse suggests), one line on how you met, a **hash** of your delete key (never the key) | to name you and to let you delete yourself |
| table `faces` | your **face print**: 512 numbers made from your face. Not a photo, and not turned back into one by this app | to recognise you on a call |
| table `consents` | when you agreed, when it ends, and what you agreed to: your face print, name, voice, notes and facts, and the Muse app only if you ticked it | one year of memory, then deletion |
| table `notes` | short notes Muse wrote from what was said on calls | the "last time" memory |
| table `encounters` | for each call: the date, what you talked about, a topic, whether you spoke, "work" or "personal" | "last seen / last spoke" on your card |
| table `calls` | for each finished call: when, the app, its topic, the key points and the suggested actions Muse wrote, and who was there (names and labels). The key points can mention people who were **not** remembered. **Today these rows are never deleted automatically and are not removed when you delete yourself** (finding R15-2) | the Recap history and the Muse app's "what happened in my last meeting?" |
| table `facts` | plain facts Muse noticed you said about yourself ("Loves F1"), at most 3 new per call | your card and the dashboard |
| `notes/<date-time>.md` on the laptop | one note per call: who was there, what Muse noted, key points, AI answers | a readable copy for the host |
| `notes/people/<id>.md` on the laptop | one readable file per person | the same, per person |
| `logs/<name>.log` on the laptop | what the app's parts print: no sentences (unless a developer runs with `--verbose`), no keys, no face prints; web requests (their paths) of the memory server, which can include an invite code | debugging; private to the host's account (mode 0600) and cut to 1 MB each time the app starts |
| in the computer's memory only | the face print of someone who is **not** remembered, while their face is on screen; the call's last transcript lines; the Ask AI chat; the print and card of a remembered person for **30 seconds after their face leaves** (so switching Zoom's view doesn't reset their card) | gone when the call ends, 30 seconds after the face leaves, or when the app quits |

Not kept: **your photo** (the photo you take to enroll is turned into numbers and dropped; the `selfie` column exists but is never filled), **the call's audio** (it is streamed, not saved), **screenshots** (frames of the call window are looked at in memory and dropped), and **faces of people who did not agree** (their print stays in memory while the face is on screen and is dropped when the call ends; nothing is written to disk).
Backed by: [the selfie](security-review.md#7-medium-the-selfie-is-stored-but-never-used), [what is kept and what is checked](security-review.md#checked-and-fine), [files and logs](security-review.md#round-4-final-pre-demo-pass-on-the-combined-code).

## For how long

One year from the day you agree (`CONSENT_DAYS = 365`), or until you delete yourself. After the year, you are no longer recognised and your rows and files are removed the next time the app starts. The log files are cut to the last 1 MB at each start.

## What leaves the laptop, and to whom

| To | What | When |
|---|---|---|
| **Meta's Muse** (speech to text) | the **call audio**: everyone's voice, enrolled or not, streamed live | while Hello Again is listening; the pause button stops it |
| **Meta's Muse** (Muse Spark, the writing model) | the call's **transcript lines** with the speakers' names, plus the name, label, notes and facts of the people on screen, and any question the host types | during the call and when it ends, to write notes, facts, summaries and answers |
| **SerpApi** | a **place, event or web search** written by Muse from the conversation, only when the host clicks that action | one query per click; it does not include face prints or notes |
| **The Muse app** (the optional *connector*) | name, label, dates, topic, work or personal, facts, how we met, last conversation and notes, **only of people who ticked the optional box** | **only if** the host sets `MUSE_CONNECTOR_KEY` and starts the demo tunnel; read-only, with a key. Face prints, photos and delete keys are never in it |
| **Tiger Cloud** | all the tables above | **only if** the host points `DATABASE_URL` at Tiger |
| other phones on the Wi-Fi | nothing, except the enroll page and "delete my data" | the host's laptop answers nothing else to other devices |

What Meta, SerpApi and Tiger do with what they receive is covered by their own terms; this app can't change it.

**What never leaves the laptop** (for Meta and SerpApi): **face prints** and **photos**. They are not sent to Muse, SerpApi, or the Muse app connector. (With Tiger Cloud the prints are stored in the host's own Tiger database, as in the first section.)
Backed by: [the connector and the tunnel](security-review.md#muse-connector-and-the-demo-tunnel), [the refreshed connector review](security-review.md#round-9-the-refreshed-review-branches-connector-stale-hypertable-windows-finder-mockups), [consent against what is sent](security-review.md#consent-round-11).

## How to delete

- **Yourself, from your phone:** open the link you were given after you enrolled (it holds your private delete key) and press **Delete my data**.
- **The host, in the app:** the **People** window, open the person, **Delete**, then confirm.
- **The host, from the command line or code:** `DELETE /people/{id}` on the laptop (no key needed from the laptop itself; a phone needs the delete key).

Deleting removes the person's rows from every table (`people`, `faces`, `consents`, `notes`, `encounters`, `facts`), their section from every call note and their own file in `notes/people/`, and takes them off the screen, out of the live call and out of the stored recap. A test checks each of these against a real database.
Backed by: [deletion is complete](security-review.md#deletion-is-complete-round-11).

**What deletion cannot undo:** text already sent to Meta, SerpApi or the Muse app, copies in a database backup or a `pg_dump` the host made, and anything already shown on a screen share.

## What is not protected

- **A screen share can show the overlay.** The overlay hides itself from screen sharing on Windows only; newer macOS screen sharing can still capture it. The host should check their share before presenting.
- **People on the call who did not enrol** still have their voice sent to Meta's Muse, and their words are in the live prompts. Nothing about them is saved, but the host should say so at the start of a call.
- **Anyone who can use the host's laptop account** can read the database (the local password is the Docker default, on `127.0.0.1` only) and the files in `notes/`.
- **Enrolling over a shared Wi-Fi** sends your selfie over plain HTTP; use the host's phone hotspot, and the invite code stops strangers on the network from enrolling.
- **While the tunnel for the Muse app is running**, the connector's address is public; it asks for a key, and the host stops the tunnel and changes the key afterwards.
- **People enrolled before the consent text was updated** never saw the words about voice, facts and the Muse app. Their record says only what they did agree to (face print, notes), they are kept out of the Muse app connector, but the app still writes facts and summaries about them. Re-ask them or delete them ([Consent, round 11](security-review.md#consent-round-11), [Round 13](security-review.md#round-13-consent-page-scope-and-the-roomier-overlay)).
