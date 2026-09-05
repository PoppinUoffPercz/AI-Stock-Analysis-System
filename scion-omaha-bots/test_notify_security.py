from datetime import datetime, timezone

from notify import ScionNotifier, _format_generated_date


class _Stream:
    def write(self, _value):
        return None

    def flush(self):
        return None

    def readline(self):
        return "{}\n"

    def close(self):
        return None


class _Process:
    stdin = _Stream()
    stdout = _Stream()

    def terminate(self):
        return None


def test_stdio_spawn_passes_untrusted_paths_without_shell(monkeypatch, tmp_path):
    zappy_path = tmp_path / "zappy; malicious.js"
    zappy_path.touch()
    captured = {}

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr("notify.subprocess.Popen", fake_popen)

    notifier = ScionNotifier(recipient_id="chat; malicious", config_path="config; malicious")
    notifier.zappy_path = str(zappy_path)

    assert notifier.send_via_stdio("message; malicious") is True
    assert captured["args"] == (
        ["node", str(zappy_path), "--config", "config; malicious"],
    )
    assert captured["kwargs"]["shell"] is False


def test_generated_date_format_is_deterministic():
    timestamp = datetime(2026, 9, 4, 22, 3, tzinfo=timezone.utc)

    assert _format_generated_date(timestamp) == "09/04/2026"
