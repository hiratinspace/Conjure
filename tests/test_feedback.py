import time

from pipeline.audio import AudioPlayer
from pipeline.engine import StepResult
from pipeline.events import Action, ClickEvent
from pipeline.feedback import Feedback, FeedbackSettings
from pipeline.modes import Mode
from pipeline.overlay import trail_color
from pipeline.ui_state import SpellCast, UiState
from pipeline.voice import LocalVoice, slug


class FakePlayer:
    def __init__(self):
        self.played, self.said = [], []

    def play_file(self, path):
        self.played.append(str(path))

    def say(self, text):
        self.said.append(text)


class FakeVoice:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def make(settings=None):
    player, voice = FakePlayer(), FakeVoice()
    return Feedback(player, voice, "click.aiff", "spell.aiff", settings), player, voice


def test_click_plays_the_click_sound_but_not_for_scroll_or_drag_end():
    fb, player, voice = make()
    fb.on_click(ClickEvent(Action.LEFT, (0, 0)))
    fb.on_click(ClickEvent(Action.SCROLL, (0, 0), 3))
    fb.on_click(ClickEvent(Action.DRAG_END, (0, 0)))
    assert player.played == ["click.aiff"]
    assert voice.spoken == []  # spoken click confirmations are opt-in


def test_spoken_click_confirmation_when_enabled():
    fb, _, voice = make(FeedbackSettings(voice_clicks=True))
    fb.on_click(ClickEvent(Action.RIGHT, (0, 0)))
    assert voice.spoken == ["Right click"]


def test_spell_cast_plays_a_sound_and_speaks_the_name():
    fb, player, voice = make()
    fb.on_spell("Illuminate")
    assert player.played == ["spell.aiff"] and voice.spoken == ["Illuminate"]


def test_mode_changes_and_pauses_are_spoken():
    fb, _, voice = make()
    fb.on_mode(Mode.PINCH, Mode.DWELL)
    fb.on_mode(Mode.DWELL, Mode.PAUSED)
    fb.on_mode(Mode.PAUSED, Mode.DWELL)
    assert voice.spoken == ["Dwell mode", "Paused", "Resumed"]


def test_every_effect_can_be_switched_off():
    fb, player, voice = make()
    for name in ("sound", "voice"):
        assert fb.toggle(name) is False
    fb.on_click(ClickEvent(Action.LEFT, (0, 0)))
    fb.on_spell("Summon")
    fb.on_mode(Mode.PINCH, Mode.DWELL)
    assert player.played == [] and voice.spoken == []
    assert fb.toggle("trail") is False


def test_local_voice_prefers_a_pregenerated_clip_then_falls_back_to_say(tmp_path):
    (tmp_path / "illuminate.mp3").write_bytes(b"ID3")
    player = FakePlayer()
    voice = LocalVoice(player, tmp_path)
    voice.speak("Illuminate")
    voice.speak("Brand New Spell")
    assert player.played == [str(tmp_path / "illuminate.mp3")]
    assert player.said == ["Brand New Spell"]


def test_slug():
    assert slug("Pinch mode") == "pinch-mode" and slug("Wingardium!!") == "wingardium" and slug("??") == "phrase"


def test_audio_player_runs_jobs_off_the_calling_thread_in_order():
    ran = []
    player = AudioPlayer(runner=lambda argv: (time.sleep(0.01), ran.append(argv)))
    t = time.perf_counter()
    player.play_file("a.aiff")
    player.say("hello")
    assert time.perf_counter() - t < 0.005  # enqueue only
    player.wait()
    assert ran == [["afplay", "a.aiff"], ["say", "hello"]]
    player.close()


def test_audio_player_drops_sounds_when_backed_up_instead_of_blocking():
    player = AudioPlayer(runner=lambda argv: time.sleep(0.2), max_queue=2)
    t = time.perf_counter()
    for _ in range(20):
        player.say("x")
    assert time.perf_counter() - t < 0.05
    player.close()


def test_spell_cast_reaches_the_ui_as_an_event():
    ui = UiState()
    click = ClickEvent(Action.LEFT, (10, 20))
    ui.publish(None, None, StepResult(cursor=(11, 21), events=[click], spell="Summon"), 30.0, "custom")
    assert ui.drain_events() == [click, SpellCast("Summon", (10, 20))]


def test_trail_fades_from_violet_to_gold():
    assert trail_color(0, 10) != trail_color(9, 10)
    assert trail_color(9, 10) == "#f5c542"


def test_short_sounds_use_the_low_latency_bank_when_given():
    class Bank:
        def __init__(self):
            self.played = []

        def play(self, path):
            self.played.append(path)
    player, voice, bank = FakePlayer(), FakeVoice(), Bank()
    fb = Feedback(player, voice, "click.aiff", "spell.aiff", sounds=bank)
    fb.on_click(ClickEvent(Action.LEFT, (0, 0)))
    assert bank.played == ["click.aiff"] and player.played == []


def test_sound_bank_preloads_system_sounds():
    import config
    from pipeline.audio import SoundBank
    bank = SoundBank(FakePlayer())
    bank.preload(config.CLICK_SOUND, config.SPELL_SOUND)
    if bank._appkit is not None:
        assert all(s is not None for s in bank._sounds.values())
