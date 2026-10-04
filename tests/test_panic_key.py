import threading

from pipeline import panic_key


class FakeEngine:
    def __init__(self):
        self.submitted = []

    def submit(self, fn):
        self.submitted.append(fn)


class FakeTap:
    """Stands in for the Quartz tap: records the bindings and lets a test press keys."""
    instances = []
    ok = True

    def __init__(self, bindings):
        self.bindings = bindings
        self.ready = threading.Event()
        FakeTap.instances.append(self)

    def start(self):
        self.ready.set()

    def press(self, code):
        fn = self.bindings.get(code)
        if fn:
            fn()


class DeadTap(FakeTap):
    ok = False


def test_f8_toggles_the_pause_and_f9_calls_its_callback():
    engine, calls = FakeEngine(), []
    toggle = lambda e: None
    tap = panic_key.start_panic_key("f8", engine, toggle, {"f9": lambda: calls.append("panel")}, tap_factory=FakeTap)
    assert tap is not None
    tap.press(panic_key.KEYCODES["f8"])
    assert engine.submitted == [toggle]
    tap.press(panic_key.KEYCODES["f9"])
    assert calls == ["panel"]
    tap.press(panic_key.KEYCODES["f7"])  # unbound
    assert engine.submitted == [toggle] and calls == ["panel"]


def test_a_tap_that_cannot_be_created_is_reported(caplog):
    assert panic_key.start_panic_key("f8", FakeEngine(), lambda e: None, tap_factory=DeadTap) is None
    assert "Input Monitoring" in caplog.text


def test_unknown_key_name_disables_hotkeys_harmlessly(caplog):
    assert panic_key.start_panic_key("f99", FakeEngine(), lambda e: None, tap_factory=FakeTap) is None
    assert "unknown hotkey" in caplog.text


def test_the_tap_never_uses_pynput_or_text_services():
    import inspect
    src = inspect.getsource(panic_key)
    assert "pynput" not in src.split('"""', 2)[2]  # only mentioned in the docstring's history note
    assert "TIS" not in src and "InputSource" not in src
