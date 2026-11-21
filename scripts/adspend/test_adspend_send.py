import hashlib
import json
from pathlib import Path

import pytest
import yaml

import adspend_send as ads
import delivery
import workflow

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "daily-ad-spend.yml"


def test_adspend_key_format():
    assert ads.key_for("A", "2026-11-20", "x@y") == (
        "ad-spend-A-2026-11-20-" + hashlib.sha1(b"x@y").hexdigest()[:8])


def test_adspend_sent_step_names():
    assert workflow.step_name("ad spend A", "", "2026-11-21", "real") == "Deliver ad spend A for 2026-11-21"
    wf = yaml.safe_load(WF.read_text())
    names = [s.get("name") for s in wf["jobs"]["email"]["steps"]]
    for v in "AB":
        assert f"Deliver ad spend {v} for ${{{{ needs.gate2.outputs.report_date }}}}" in names
    assert wf["jobs"]["delivered"]["name"] == "Delivered ad spend for ${{ needs.gate2.outputs.report_date }}"
    agg = [s.get("name") for s in wf["jobs"]["delivered"]["steps"]]
    assert "Delivered ad spend for ${{ needs.gate2.outputs.report_date }}" in agg
    text = WF.read_text()
    assert '--sent-step "Delivered ad spend for "' in text
    assert "--tz America/Los_Angeles --target 05:45" in text
    assert "send_resend" not in text


def _out(tmp_path):
    (tmp_path / "email-A.html").write_text("<p>x</p>")
    (tmp_path / "email-A.txt").write_text("x")
    (tmp_path / "email-A.subject").write_text("Ad spend")


def test_main_builds_payload_and_sends(tmp_path, monkeypatch):
    _out(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "k")
    sent = {}
    monkeypatch.setattr(delivery, "send_frozen", lambda path, key: sent.update(key=key))
    frozen = tmp_path / "frozen.json"
    ads.main(["--variant", "A", "--ad-date", "2026-11-20", "--out-dir", str(tmp_path),
              "--mail-to", "cherian@lascade.com, Jishnu M M <jishnu@lascade.com>",
              "--frozen", str(frozen)])
    env = json.loads(frozen.read_text())
    body = json.loads(env["body"])
    assert body["to"] == ["cherian@lascade.com", "Jishnu M M <jishnu@lascade.com>"]
    assert list(body) == ["from", "to", "subject", "html", "text"]
    assert body["from"] == "Lascade Ad Spend <noreply@metrics.lascade.com>"
    assert env["key"].startswith("ad-spend-A-2026-11-20-")
    assert sent["key"] == "k"


def test_mail_to_defaults_to_cherian(tmp_path, monkeypatch):
    _out(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.delenv("MAIL_TO", raising=False)
    monkeypatch.setattr(delivery, "send_frozen", lambda path, key: None)
    frozen = tmp_path / "frozen.json"
    ads.main(["--variant", "A", "--ad-date", "2026-11-20", "--out-dir", str(tmp_path), "--frozen", str(frozen)])
    env = json.loads(frozen.read_text())
    assert json.loads(env["body"])["to"] == ["cherian@lascade.com"]
    assert env["key"].endswith(hashlib.sha1(b"cherian@lascade.com").hexdigest()[:8])


def test_a_409_is_not_success(tmp_path, monkeypatch):
    _out(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "k")

    def boom(path, key):
        raise delivery.DeliveryError("Resend delivery failed: HTTP 409 (idempotency conflict)")

    monkeypatch.setattr(delivery, "send_frozen", boom)
    with pytest.raises(SystemExit):
        ads.main(["--variant", "A", "--ad-date", "2026-11-20", "--out-dir", str(tmp_path),
                  "--frozen", str(tmp_path / "f.json")])
