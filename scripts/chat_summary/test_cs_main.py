"""Port of diagnostics.test.js: the CLI prints fixed messages only, never stacks or data."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from claude_api import ClaudeError
import cs_main
from cs_errors import DigestError
from delivery import DeliveryError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GENERIC = "Chat digest build failed; no delivery marker was recorded."


def cli(tmp_path, *args, **env):
    pythonpath = os.pathsep.join(str(ROOT / d) for d in ("scripts/common", "scripts/ai", "scripts/chat_summary"))
    # setup-python's toolcache interpreter may need LD_LIBRARY_PATH to start on Linux runners.
    runtime = {k: os.environ[k] for k in ("LD_LIBRARY_PATH",) if k in os.environ}
    return subprocess.run([sys.executable, str(HERE / "cs_main.py"), *args], cwd=tmp_path, capture_output=True,
                          text=True, env={"PATH": os.environ["PATH"], "PYTHONPATH": pythonpath, **runtime, **env})


def test_cli_prints_a_known_missing_environment_name_without_a_stack(tmp_path):
    result = cli(tmp_path, "marine-radar", "build", DRY_RUN="true")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Missing env var MARINE_RADAR_SHEET_ID\n"


def test_cli_keeps_raw_json_errors_and_credentials_behind_the_generic_line(tmp_path):
    result = cli(tmp_path, "marine-radar", "build", DRY_RUN="true", MARINE_RADAR_SHEET_ID="private-sheet-id",
                 GOOGLE_SERVICE_ACCOUNT_JSON='{"private_key":"PRIVATE_CREDENTIAL_AND_ROW_CONTENT')
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == GENERIC + "\n"


def test_cli_send_without_a_frozen_envelope_is_a_fixed_delivery_error(tmp_path):
    result = cli(tmp_path, "travel-animator", "send", DRY_RUN="false", EDITION="ist", RESEND_API_KEY="re_PRIVATE")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Invalid frozen envelope\n"


@pytest.mark.parametrize("args", [[], ["marine-radar"], ["unknown", "build"], ["marine-radar", "hold"],
                                  ["marine-radar", "run"], ["marine-radar", "build", "extra"]])
def test_cli_usage_lists_products_and_commands(tmp_path, args):
    result = cli(tmp_path, *args)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Usage: cs_main.py <marine-radar|travel-animator> <build|send>\n"


def test_only_trusted_error_classes_expose_a_message():
    safe = DigestError("Source tab unavailable at deadline")
    safe.__cause__ = RuntimeError("PRIVATE_CAUSE")
    assert cs_main.failure_message(safe, "build") == "Source tab unavailable at deadline"
    assert cs_main.failure_message(DeliveryError("Resend delivery failed: HTTP 0 (transport)"), "send") == \
        "Resend delivery failed: HTTP 0 (transport)"
    assert cs_main.failure_message(ClaudeError("rate-limit"), "build") == "Claude API: rate-limit"
    look_alike = type("DigestError", (Exception,), {})
    for error in (RuntimeError("PRIVATE_GOOGLE_RESPONSE"), TypeError("PRIVATE_FETCH_REQUEST"),
                  ValueError("PRIVATE_JSON_CONTENT"), look_alike("PRIVATE_ROW_CONTENT"), "PRIVATE_STRING", None):
        assert cs_main.failure_message(error, "build") == GENERIC
    assert cs_main.failure_message(None, "send") == "Chat digest send failed; no delivery marker was recorded."


def test_main_dispatches_build_and_send(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cs_main.cs_pipeline, "build", lambda product, **_: calls.append(("build", product["slug"])))
    monkeypatch.setattr(cs_main.cs_pipeline, "send", lambda product, **_: calls.append(("send", product["slug"])))
    assert cs_main.main(["travel-animator", "build"]) == 0
    assert cs_main.main(["marine-radar", "send"]) == 0
    assert calls == [("build", "travel-animator"), ("send", "marine-radar")]


def test_main_hides_unexpected_errors(monkeypatch, capsys):
    def boom(product, **_):
        raise RuntimeError("PRIVATE https://sheets.googleapis.com/v4/spreadsheets/PRIVATE_SHEET_ID")

    monkeypatch.setattr(cs_main.cs_pipeline, "build", boom)
    assert cs_main.main(["travel-animator", "build"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == GENERIC + "\n"
