import json
import re
import time
import urllib.error
from pathlib import Path

import pytest

from pipeline.voice import LocalVoice
from pipeline.voice_elevenlabs import ElevenLabsVoice
from tests.test_feedback import FakePlayer

KEY = "sk-test-not-a-real-key"
ROOT = Path(__file__).resolve().parent.parent


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def opener(delay=0.0, error=None, data=b"ID3fake-mp3"):
    calls = []

    def open_(request, timeout):
        calls.append((request, timeout))
        time.sleep(delay)
        if error:
            raise error
        return FakeResponse(data)
    open_.calls = calls
    return open_


def make(tmp_path, open_fn, deadline=0.5):
    player = FakePlayer()
    fallback = LocalVoice(player, [tmp_path / "voice", tmp_path / "cache"])
    voice = ElevenLabsVoice(KEY, "voice123", "eleven_flash_v2_5", [tmp_path / "voice"], tmp_path / "cache",
                            player, fallback, deadline, opener=open_fn)
    return voice, player


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_live_speech_is_fetched_cached_and_played(tmp_path):
    open_fn = opener()
    voice, player = make(tmp_path, open_fn)
    voice.speak("Brand New Spell")
    assert wait_for(lambda: player.played)
    assert player.played == [str(tmp_path / "cache" / "brand-new-spell.mp3")]
    request, timeout = open_fn.calls[0]
    assert request.full_url.startswith("https://api.elevenlabs.io/v1/text-to-speech/voice123")
    assert request.get_header("Xi-api-key") == KEY
    assert json.loads(request.data) == {"text": "Brand New Spell", "model_id": "eleven_flash_v2_5"}
    assert timeout == 0.5


def test_existing_clip_plays_with_no_network(tmp_path):
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "illuminate.mp3").write_bytes(b"ID3")
    open_fn = opener()
    voice, player = make(tmp_path, open_fn)
    voice.speak("Illuminate")
    assert player.played == [str(tmp_path / "voice" / "illuminate.mp3")]
    assert open_fn.calls == []


@pytest.mark.parametrize("error", [urllib.error.URLError("no network"), TimeoutError(), OSError("dns"),
                                   urllib.error.HTTPError("u", 401, "bad key", {}, None)])
def test_any_failure_falls_back_to_the_offline_voice(tmp_path, error):
    voice, player = make(tmp_path, opener(error=error))
    voice.speak("Summon")
    assert wait_for(lambda: player.said)
    assert player.said == ["Summon"] and player.played == []


def test_slow_response_falls_back_at_the_deadline_and_caches_for_next_time(tmp_path):
    voice, player = make(tmp_path, opener(delay=0.8), deadline=0.2)
    t = time.monotonic()
    voice.speak("Levitate")
    assert wait_for(lambda: player.said)
    assert time.monotonic() - t < 0.6  # spoke offline at the deadline, did not wait for the network
    assert wait_for(lambda: (tmp_path / "cache" / "levitate.mp3").exists())
    voice.speak("Levitate")
    assert player.played == [str(tmp_path / "cache" / "levitate.mp3")]


def test_speak_never_blocks_the_caller(tmp_path):
    voice, _ = make(tmp_path, opener(delay=1.0), deadline=1.0)
    t = time.perf_counter()
    voice.speak("Ignite")
    assert time.perf_counter() - t < 0.05


def test_the_key_never_appears_in_repr_or_logs(tmp_path, caplog):
    voice, player = make(tmp_path, opener(error=OSError("down")))
    assert KEY not in repr(voice)
    voice.speak("Unlock")
    wait_for(lambda: player.said)
    assert KEY not in caplog.text


def test_missing_key_is_refused(tmp_path):
    with pytest.raises(ValueError):
        ElevenLabsVoice("", "v", "m", [], tmp_path, FakePlayer(), None, 1.0)


def test_no_other_module_touches_the_network():
    """CONJ-18 constraint: the ElevenLabs module is the only network code."""
    pattern = re.compile(r"^\s*(import|from)\s+(urllib|http|socket|requests|ssl|aiohttp|httpx)\b", re.M)
    offenders = []
    for path in list((ROOT / "pipeline").glob("*.py")) + [ROOT / "main.py", ROOT / "config.py"]:
        if path.name == "voice_elevenlabs.py":
            continue
        if pattern.search(path.read_text()):
            offenders.append(path.name)
    assert offenders == []


def test_no_api_key_is_committed_anywhere():
    """Scan only files git tracks: secrets.env is gitignored and must never be read or printed here."""
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, cwd=ROOT).stdout.split("\0")
    for name in tracked:
        path = ROOT / name
        if not name or not path.is_file() or path.suffix in (".task", ".jsonl", ".mp3", ".png"):
            continue
        text = path.read_text(errors="ignore")
        assert not re.search(r"sk_[A-Za-z0-9]{32,}", text), f"possible ElevenLabs key in {name}"
    assert "secrets.env" not in tracked
