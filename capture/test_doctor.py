from capture import doctor


def test_report_has_one_line_per_item_with_the_fix_only_on_failures():
    results = [
        ("Screen Recording", True, "the window list has names", "allow it in System Settings"),
        ("grab", False, "1280x886 px, blank (all one colour)", "allow Screen Recording"),
    ]
    assert doctor.report(results).splitlines() == [
        "OK   Screen Recording: the window list has names",
        "FAIL grab: 1280x886 px, blank (all one colour)  ->  allow Screen Recording",
        "something to fix above",
    ]
    assert doctor.report([results[0]]).splitlines()[-1] == "all good"


def test_a_check_that_raises_is_a_failure_with_the_error_as_detail():
    def boom():
        raise OSError("no input device")

    assert doctor.check("microphone", "plug one in", boom) == ("microphone", False, "OSError('no input device')", "plug one in")
    assert doctor.check("memory", "start it", lambda: (True, "fine")) == ("memory", True, "fine", "start it")

    def unreadable():
        raise SystemExit("couldn't list windows: no permission")  # how window.windows() fails

    assert doctor.check("Screen Recording", "allow it", unreadable)[1:3] == (False, "SystemExit(\"couldn't list windows: no permission\")")


def test_main_exits_0_only_when_everything_is_ok(monkeypatch, capsys):
    import pytest

    monkeypatch.setattr(doctor, "checks", lambda: [("YOLO", True, "6 people in 80 ms", "uv sync")])
    with pytest.raises(SystemExit) as stop:
        doctor.main()
    lines = capsys.readouterr().out.splitlines()
    assert stop.value.code == 0 and lines[-2] == "all good" and lines[-1].startswith("tunables (capture/tuning.py): ") and "STILL_SECONDS=3.0" in lines[-1]
    monkeypatch.setattr(doctor, "checks", lambda: [("memory", False, "ConnectError", "start it")])
    with pytest.raises(SystemExit) as stop:
        doctor.main()
    assert stop.value.code == 1


def test_on_windows_the_permission_line_says_not_needed_but_the_window_finder_still_runs(monkeypatch):
    from capture import window as win

    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(win, "windows", lambda: [win.win32_window("Zoom Meeting", r"C:\\Zoom\\Zoom.exe", (0, 0, 1100, 700))])
    state = {}
    assert doctor.permission(state) == (True, "not needed on Windows; 1 windows listed through EnumWindows")
    assert doctor.found(state) == (True, "Zoom window at (0, 0, 1100, 700), a call app")
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert doctor.permission(state) == (True, "the window list has names, so this process may record the screen")
