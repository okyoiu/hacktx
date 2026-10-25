"""Speaker naming on scripted data, like memory/replay.py: fake people, fake lip readings, Muse-like caption timings."""
from types import SimpleNamespace

import numpy as np
from insightface.data import get_image

from capture.embed import mouths_in
from capture.speakers import UNLABELED, Namer, lip_gap

MAYA, JORDAN = {"id": "p_maya", "name": "Maya Chen"}, {"id": "p_jordan", "name": "Jordan Lee"}


def lips(gap: float):
    """A 100 px face whose inner lips are gap (share of face height) apart."""
    lm = np.zeros((68, 3))
    lm[[61, 62, 63], 1], lm[[65, 66, 67], 1] = 50, 50 + gap * 100
    return SimpleNamespace(bbox=[0, 0, 100, 100], landmark_3d_68=lm)


def line(namer, label, start, talking=(), still=(), seconds=3.0, fps=5):
    """One Muse line: talking people's lips move, still people's barely do; partial captions, then the final one."""
    rng = np.random.default_rng(int(start))
    for i in range(int(seconds * fps)):
        t = start + i / fps
        for p in talking:
            namer.saw(p, lips(rng.uniform(0.0, 0.07)), t)
        for p in still:
            namer.saw(p, lips(0.02 + rng.normal(0, 0.001)), t)
        if i % 2:
            namer.caption(t, label, False)
    return namer.caption(start + seconds, label, True)


def test_names_a_voice_once_the_same_face_talked_through_three_of_its_lines():
    namer = Namer()
    got = [line(namer, "B", 10 * i, talking=[MAYA], still=[JORDAN]) for i in range(3)]
    assert got == [None, None, ("B", "Maya Chen")]
    assert line(namer, "B", 40, talking=[MAYA], still=[JORDAN]) == ("B", "Maya Chen")  # memory forgot: say it again
    assert line(namer, "Maya Chen", 50, talking=[MAYA], still=[JORDAN]) is None  # memory has it now


def test_never_guesses():
    crosstalk = Namer()
    assert all(line(crosstalk, "A", 10 * i, talking=[MAYA, JORDAN]) is None for i in range(6))

    off_camera = Namer()  # someone we can't see talks; Maya on screen laughs during one of their lines
    assert all(line(off_camera, "C", 10 * i, talking=[MAYA] if i == 2 else [], still=[] if i == 2 else [MAYA]) is None
               for i in range(6))

    nobody = Namer()  # nobody recognized on screen
    assert all(line(nobody, "A", 10 * i) is None for i in range(6))

    by_hand = Namer()  # a voice already named by hand reaches us as that name
    by_hand.met(JORDAN)
    assert all(line(by_hand, "Jordan Lee", 10 * i, talking=[JORDAN]) is None for i in range(6))
    assert all(line(by_hand, UNLABELED, 100 + 10 * i, talking=[JORDAN]) is None for i in range(6))

    one_voice_each = Namer()
    assert [line(one_voice_each, "B", 10 * i, talking=[MAYA], still=[JORDAN]) for i in range(3)][-1] == ("B", "Maya Chen")
    assert all(line(one_voice_each, "D", 100 + 10 * i, talking=[MAYA], still=[JORDAN]) is None for i in range(6))


def test_lip_gap_reads_open_mouths_wider_on_the_sample_photo():
    faces = sorted(mouths_in(get_image("t1")), key=lambda f: f.bbox[0])  # six people, left to right
    assert len(faces) == 6
    assert lip_gap(faces[3]) > 2 * lip_gap(faces[1])  # laughing, mouth open vs. lips closed


def test_only_lips_inside_the_lines_window_and_on_big_enough_faces_count():
    namer = Namer()
    for i in range(3):
        start = 10 * i
        rng = np.random.default_rng(i)
        for k in range(15):  # Maya talked, but 5 s before this line: outside the lead-in
            namer.saw(MAYA, lips(rng.uniform(0.0, 0.07)), start - 6 + k / 5)
        namer.caption(start, "B", False)
        for k in range(15):  # during the line she is still
            namer.saw(MAYA, lips(0.02), start + k / 5)
        assert namer.caption(start + 3, "B", True) is None

    tiny = Namer()
    small = lips(0.0)
    small.bbox = [0, 0, 100, 30]  # under MIN_FACE: ignored, so no evidence
    for i in range(6):
        for k in range(15):
            tiny.saw(MAYA, small, 10 * i + k / 5)
        assert tiny.caption(10 * i + 3, "B", True) is None
    assert not tiny.gaps
