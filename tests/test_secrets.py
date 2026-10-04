import os

from pipeline.secrets import load_secrets


def test_secrets_file_loads_into_the_environment_without_overriding(tmp_path, monkeypatch):
    path = tmp_path / "secrets.env"
    path.write_text("# comment\nELEVENLABS_API_KEY = 'abc'\nOTHER=x\n\nALREADY=new\n")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("ALREADY", "old")
    monkeypatch.delenv("OTHER", raising=False)
    assert load_secrets(path) == ["ELEVENLABS_API_KEY", "OTHER"]
    assert os.environ["ELEVENLABS_API_KEY"] == "abc" and os.environ["ALREADY"] == "old"


def test_missing_file_is_fine(tmp_path):
    assert load_secrets(tmp_path / "none.env") == []


def test_secrets_file_is_ignored_by_git():
    import subprocess
    out = subprocess.run(["git", "check-ignore", "secrets.env"], capture_output=True, text=True)
    assert out.returncode == 0
