"""Three SAMPLE conversations (invented people, not real) run through the insights prompt with a fake Muse.
A fake can't judge quality, so this checks what we control: the prompt carries each conversation and asks for a
specific topic, at most 3 concrete points and grounded actions, and the parser holds any reply to those limits."""
import json

import pytest

from memory import picks

PEOPLE = {"p_ana": {"name": "Ana Rivera", "notes": []}, "p_ben": {"name": "Ben Okafor", "notes": ["Plays guitar"]}}

# (lines, what an ideal Muse reply looks like for them)
SAMPLES = {
    "move": (
        ["Ana Rivera: I finally moved to Denver last week.", "Ben Okafor: Nice! Did you find a climbing gym yet?",
         "Ana Rivera: Not yet, I want one near Capitol Hill."],
        {"topic": "Ana's move to Denver", "points": ["Ana moved to Denver last week", "Ana wants a climbing gym near Capitol Hill"],
         "actions": [{"kind": "places", "label": "Find climbing gyms near Capitol Hill", "query": "climbing gyms near Capitol Hill Denver"}]},
    ),
    "term": (
        ["Ben Okafor: We switched the backend to Rust.", "Ana Rivera: What's a borrow checker again?",
         "Ben Okafor: It's how Rust proves memory is used safely."],
        {"topic": "Ben's backend moving to Rust", "points": ["Ben's team switched the backend to Rust"],
         "actions": [{"kind": "define", "label": "What is a borrow checker?", "query": "Rust borrow checker"}]},
    ),
    "small talk": (
        ["Ana Rivera: Hey, how's it going?", "Ben Okafor: Good, you?", "Ana Rivera: Good, good."],
        {"topic": "", "points": [], "actions": []},
    ),
}


@pytest.mark.parametrize("name", SAMPLES)
def test_prompt_carries_the_conversation_and_asks_for_specific_useful_output(name, monkeypatch):
    lines, ideal = SAMPLES[name]
    prompts = []
    monkeypatch.setattr(picks, "chat", lambda prompt, seconds=None: prompts.append(prompt) or json.dumps(ideal))
    out = picks.extract(PEOPLE, [], lines)

    prompt = prompts[0]
    assert "New lines:\n<transcript>\n" + "\n".join(lines) + "\n</transcript>" in prompt
    for ask in ("specific subject", "Never a vague label", "at most 3", "concrete", "Small talk and greetings get no actions",
                "Use the names, places and cities they said"):
        assert ask in prompt
    assert len(out["topic"].split()) <= 8 and len(out["points"]) <= picks.MAX_POINTS
    assert all(len(p) < picks.POINT_CHARS for p in out["points"])
    assert out["points"] == ideal["points"] and [a["kind"] for a in out["actions"]] == [a["kind"] for a in ideal["actions"]]
    if name == "small talk":
        assert out["actions"] == [] and out["points"] == []  # nothing useful: nothing shown


def test_a_rambling_reply_is_held_to_the_limits():
    reply = json.dumps({"topic": "Conversation " * 20, "points": [f"point {i}" for i in range(6)],
                        "actions": [{"kind": "helpful", "label": f"Help {i}"} for i in range(9)]})
    out = picks.parse(reply, set(PEOPLE))
    assert len(out["points"]) == 3 and len(out["actions"]) == 4 and len(out["topic"]) <= 80
