from pipeline.injector import RecordingInjector
from pipeline.permissions import PermissionWatch, main_screen_size


def test_screen_size_is_positive():
    w, h = main_screen_size()
    assert w > 0 and h > 0


def test_revoked_permission_is_logged_loudly_once(caplog):
    answers = iter([True, False, False, True])
    clock = iter([0.0, 5.0, 10.0, 15.0])
    watch = PermissionWatch(1.0, check=lambda: next(answers), clock=lambda: next(clock))
    assert [watch.poll() for _ in range(4)] == [True, False, False, True]
    errors = [r for r in caplog.records if "ACCESSIBILITY PERMISSION MISSING" in r.message]
    assert len(errors) == 1


def test_poll_rechecks_only_after_interval():
    calls = []
    t = [0.0]
    watch = PermissionWatch(2.0, check=lambda: calls.append(1) or True, clock=lambda: t[0])
    watch.poll()
    t[0] = 1.0
    watch.poll()
    t[0] = 2.5
    watch.poll()
    assert len(calls) == 2


def test_disabled_injector_drops_input_but_still_releases_buttons():
    inj = RecordingInjector()
    inj.enabled = False
    inj.move(1, 1)
    inj.click()
    inj.press()
    inj.release()
    assert inj.calls == [("release", "left")]
