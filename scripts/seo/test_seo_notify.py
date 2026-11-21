import notify
import seo_blog_audit as audit_mod
from seo_report import RunSummary


def _stub(monkeypatch, tmp_path, has_findings=True):
    import seo_model
    site = seo_model.load_site_config(str(_cfg()), "travelanimator")
    summary = RunSummary(site=site, pages=[], findings=[], rules=[], started_at="t", duration_s=0.0)
    monkeypatch.setattr(audit_mod, "audit", lambda site, fetcher: summary)
    monkeypatch.setattr(audit_mod, "gate", lambda s: has_findings)
    monkeypatch.setattr(audit_mod, "write_github_output", lambda s: None)
    return summary


def _cfg():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "data" / "seo_sites.json"


def test_seo_audit_uses_notify(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notify, "telegram_send_document", lambda *a, **k: calls.append(a))
    _stub(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    out = tmp_path / "report.html"
    code = audit_mod.main(["--site", "travelanimator", "--config", str(_cfg()), "--output", str(out),
                           "--telegram-chat-id", "-5"])
    assert code == 0
    assert len(calls) == 1
    assert calls[0][0] == "tok" and calls[0][1] == "-5" and calls[0][2].endswith(".html")
    assert calls[0][3] == out.read_bytes()
    assert "Blog SEO Audit" in calls[0][4]


def test_seo_no_send_without_findings(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notify, "telegram_send_document", lambda *a, **k: calls.append(a))
    _stub(monkeypatch, tmp_path, has_findings=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    code = audit_mod.main(["--site", "travelanimator", "--config", str(_cfg()),
                           "--output", str(tmp_path / "r.html"), "--telegram-chat-id", "-5"])
    assert code == 0 and calls == []


def test_seo_send_failure_still_exits_zero(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise notify.NotifyError("Telegram sendDocument failed after 3 attempts: status 500")
    monkeypatch.setattr(notify, "telegram_send_document", boom)
    _stub(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    code = audit_mod.main(["--site", "travelanimator", "--config", str(_cfg()),
                           "--output", str(tmp_path / "r.html"), "--telegram-chat-id", "-5"])
    assert code == 0
    assert "sendDocument failed" in capsys.readouterr().err
