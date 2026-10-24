# Proposal: name Muse speakers from the faces on screen

Status: proposal from Capture (A). Needs the coordinator's call on the API change and Memory (B) for the matching.

## Problem
`capture/transcribe.py` tags each line with Muse's diarization label (`speaker_0`, `speaker_1`, …). Someone has to type `POST /speakers` to turn a label into a name, once per call, and again if Muse's session restarts. Meanwhile `capture/faces.py` already knows which face track is which enrolled person. What's missing is the link between a voice label and a face track.

## Idea
Watch whose mouth is moving while Muse says a given label is talking, and count it up over the call. After a few seconds of speech, one person clearly wins for each label.

## Signal (capture side)
- **Mouth movement per track.** InsightFace's `buffalo_l` pack, which we already load, includes a 106-point landmark model, so this needs no new model or dependency. Mouth opening = lip gap divided by face height. "Talking" = how much that opening varied over the last second, sent as a 0–1 score.
- **Cost.** Today InsightFace runs once per new track. This would run it on every enrolled face at 2–3 per second. Measure on a 4-person call first. If it's too slow, score only while transcript partials are arriving.
- **Later, a cheap boost:** the call apps' own active-speaker cue (highlighted tile border in gallery view, the big tile in speaker view). It needs no model, but it breaks whenever Teams or Zoom restyle, so it only breaks ties.

## Matching (memory side)
- Every half second the server knows the label of the latest transcript line and the talking score of each face on screen. It gives one vote to `(label, person)` for the face that is clearly talking.
- Vote by person id, not track id, because tracks reset when someone leaves and comes back.
- Name a label once one person has at least ~6 votes (about 3 s of speech) and at least 70% of that label's votes.
- A name typed by hand with `/speakers` always wins and is never overwritten.
- Muse's partial transcripts lag the video by about a second, so compare against talking scores from about a second earlier. Server arrival time is enough; Muse doesn't need to send timestamps.

## Edge cases
- **Camera off, or not enrolled:** no face or no person, so no votes. The label stays as it is and `/speakers` still works.
- **One face and one voice:** name it right away.
- **Crosstalk:** two mouths moving split the votes; the 70% rule keeps a wrong name out.
- **Screen share or a tiny gallery:** skip faces under ~60 px tall; their landmarks are noise.
- **You:** call audio usually leaves out your own mic, and your self-view only votes if you enrolled yourself. Exclude your own person id.
- **Muse session restart (60-minute limit):** labels start over, so clear votes and automatic names when `transcribe.py` opens a new session.

## Changes this would need
- `POST /faces` gets an optional `talking` (0–1). README API table: coordinator.
- A way for `transcribe.py` to say "new Muse session" (a field on `/transcript` or a small call). README: coordinator.
- Voting and naming in `memory/app.py`: Memory (B). Nothing new is stored in the database; votes live in memory for the call only.

## How we'd test it
Play a recorded call with `faces.py --video` while its audio goes through BlackHole into `transcribe.py`. Name the speakers by hand once as ground truth, and count how often the automatic names agree and how long each takes to appear.
