"""CONJ-18: render every fixed phrase and stock spell name to audio/voice/<slug>.mp3 with ElevenLabs.

These clips are committed, so the demo speaks them with no network at all; only a
brand-new spell name ever needs a live request. Run once, with the key in the
environment (never pass it on the command line or write it to a file):

    export ELEVENLABS_API_KEY=...        # in your shell, not in the repo
    python scripts/pregenerate_voices.py            # skips clips that already exist
    python scripts/pregenerate_voices.py --force    # re-render everything
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from pipeline.feedback import FIXED_PHRASES  # noqa: E402
from pipeline.voice import SilentVoice, slug  # noqa: E402
from pipeline.voice_elevenlabs import ElevenLabsVoice  # noqa: E402


def explain(error):
    """The server's own reason for an HTTP error (its body never contains the key)."""
    code = getattr(error, "code", None)
    if code is None:
        return ""
    try:
        body = json.loads(error.read().decode("utf-8", "replace"))
        detail = body.get("detail", body)
        reason = detail.get("status") or detail.get("message") or detail if isinstance(detail, dict) else detail
        hint = {401: "the key is wrong, revoked, or lacks the Text to Speech permission "
                     "(check its length with: echo ${#ELEVENLABS_API_KEY})",
                402: "the plan's quota is exhausted", 429: "rate limited or quota exhausted"}.get(code, "")
        return f"\n         server says: {reason}" + (f"\n         meaning: {hint}" if hint else "")
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-render clips that already exist")
    args = parser.parse_args()

    from pipeline.secrets import load_secrets
    load_secrets(config.SECRETS_PATH)
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("ELEVENLABS_API_KEY is not set. Export it in this shell, or create secrets.env (see README).")
        return 1
    voice = ElevenLabsVoice(key, os.environ.get("ELEVENLABS_VOICE_ID", config.ELEVENLABS_VOICE_ID),
                            config.ELEVENLABS_MODEL_ID, [], config.VOICE_CACHE_DIR, None, SilentVoice(), 10.0)
    config.VOICE_DIR.mkdir(parents=True, exist_ok=True)
    phrases = FIXED_PHRASES + config.STOCK_SPELL_NAMES
    failures = 0
    for text in phrases:
        path = config.VOICE_DIR / f"{slug(text)}.mp3"
        if path.exists() and not args.force:
            print(f"  skip   {text!r} (exists)")
            continue
        try:
            audio = voice.synthesize(text, timeout_s=15)
        except Exception as e:  # report and keep going; never print the key
            print(f"  FAIL   {text!r}: {type(e).__name__}: {e}{explain(e)}")
            failures += 1
            if getattr(e, "code", None) in (401, 402, 429):
                print("  Stopping: the same error would repeat for every phrase.")
                failures += len(phrases) - phrases.index(text) - 1
                break
            continue
        path.write_bytes(audio)
        print(f"  ok     {text!r} -> {path.relative_to(config.ROOT)} ({len(audio) // 1024} KB)")
    print(f"\n{len(phrases) - failures}/{len(phrases)} phrases ready in {config.VOICE_DIR.relative_to(config.ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
