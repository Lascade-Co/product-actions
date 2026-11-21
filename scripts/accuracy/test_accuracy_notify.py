import sys

import notify
import ship_accuracy_report as sar


def _run(monkeypatch, tmp_path, extra, env=None):
    calls = []
    monkeypatch.setattr(notify, "telegram_send_document", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sar, "fetch_vf_ships", lambda *a, **k: ([], None))
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    out = tmp_path / "report.html"
    monkeypatch.setattr(sys, "argv", ["x", "--bbox=1,2,3,4", "--output", str(out), *extra])
    sar.main()
    return calls, out


def test_accuracy_uses_notify(monkeypatch, tmp_path):
    calls, out = _run(
        monkeypatch, tmp_path,
        ["--telegram-chat-id", "-100", "--caption", "Ship Accuracy Report - Test"],
        {"TELEGRAM_TOKEN": "tok"},
    )
    assert len(calls) == 1
    args, _ = calls[0]
    assert args[0] == "tok" and args[1] == "-100"
    assert args[2].endswith(".html")
    assert args[3] == out.read_bytes()
    assert args[4] == "Ship Accuracy Report - Test"


def test_accuracy_without_chat_id_sends_nothing(monkeypatch, tmp_path):
    calls, out = _run(monkeypatch, tmp_path, [], {"TELEGRAM_TOKEN": "tok"})
    assert calls == [] and out.exists()
