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
        def __init__(self, on_press):
            pressed["on_press"] = on_press
            self.daemon = False

        def start(self):
            pressed["started"] = True

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


def test_panic_key_failure_is_harmless(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pynput", None)
    assert panic_key.start_panic_key("f8", FakeEngine(), lambda e: None) is None
