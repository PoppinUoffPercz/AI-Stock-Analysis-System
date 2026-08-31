from notify import ScionNotifier


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
