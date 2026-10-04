import types

from pipeline import panic_key


class FakeEngine:
    def __init__(self):
        self.submitted = []

    def submit(self, fn):
        self.submitted.append(fn)


def test_panic_key_submits_the_toggle_on_the_configured_key(monkeypatch):
    pressed = {}

    class Listener:
        running = True

        def __init__(self, on_press, on_release):
            pressed["on_press"] = on_press
            pressed["on_release"] = on_release
            self.daemon = False

        def start(self):
            pressed["started"] = True

        def wait(self):
            pass

    fake_keyboard = types.SimpleNamespace(Key=types.SimpleNamespace(f8="F8"), KeyCode=None, Listener=Listener)
    monkeypatch.setitem(__import__("sys").modules, "pynput.keyboard", fake_keyboard)
    monkeypatch.setitem(__import__("sys").modules, "pynput", types.SimpleNamespace(keyboard=fake_keyboard))
    engine = FakeEngine()
    toggle = lambda e: None
    assert panic_key.start_panic_key("f8", engine, toggle) is not None
    assert pressed["started"]
    pressed["on_press"]("F7")
    assert engine.submitted == []
    pressed["on_press"]("F8")
    assert engine.submitted == [toggle]
    pressed["on_press"]("F8")  # autorepeat while held: no second toggle
    pressed["on_press"]("F8")
    assert engine.submitted == [toggle]
    pressed["on_release"]("F8")
    pressed["on_press"]("F8")
    assert engine.submitted == [toggle, toggle]


def test_a_listener_that_dies_without_input_monitoring_is_reported(monkeypatch, caplog):
    class Listener:
        running = False

        def __init__(self, on_press, on_release):
            self.daemon = False

        def start(self):
            pass

        def wait(self):
            pass

    fake_keyboard = types.SimpleNamespace(Key=types.SimpleNamespace(f8="F8"), KeyCode=None, Listener=Listener)
    monkeypatch.setitem(__import__("sys").modules, "pynput.keyboard", fake_keyboard)
    monkeypatch.setitem(__import__("sys").modules, "pynput", types.SimpleNamespace(keyboard=fake_keyboard))
    monkeypatch.setattr(panic_key.time, "sleep", lambda s: None)
    assert panic_key.start_panic_key("f8", FakeEngine(), lambda e: None) is None
    assert "Input Monitoring" in caplog.text


def test_panic_key_failure_is_harmless(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pynput", None)
    assert panic_key.start_panic_key("f8", FakeEngine(), lambda e: None) is None
