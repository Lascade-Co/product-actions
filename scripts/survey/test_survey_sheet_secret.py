"""Survey Sheet IDs are private: configs name a secret, never the ID itself."""
import json
from pathlib import Path

import pytest

import survey_main

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("digest, env_name", [("survey_marine", "SURVEY_MARINE_SHEET_ID"),
                                              ("survey_measure", "SURVEY_MEASURE_SHEET_ID")])
def test_config_names_the_secret_and_holds_no_sheet_id(digest, env_name):
    config = json.loads((ROOT / "data" / f"{digest}.json").read_text(encoding="utf-8"))
    assert config["sheet_id_env"] == env_name
    assert "sheet_id" not in config and "sheet_url" not in config
    workflow = (ROOT / ".github/workflows/_digest.yml").read_text(encoding="utf-8")
    assert f"{env_name}: ${{{{ secrets.{env_name} }}}}" in workflow


def test_missing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("SURVEY_MARINE_SHEET_ID", raising=False)
    with pytest.raises(ValueError, match="SURVEY_MARINE_SHEET_ID not set"):
        survey_main._fetch_sheets({"sheet_id_env": "SURVEY_MARINE_SHEET_ID", "surveys": []}, None, None, None)


def test_sheets_fetch_uses_the_secret_id_and_derives_the_link(monkeypatch):
    seen = []
    monkeypatch.setenv("SURVEY_MARINE_SHEET_ID", " synthetic-sheet ")
    monkeypatch.setattr(survey_main, "_google_settings", lambda: ({}, None))
    monkeypatch.setattr(survey_main, "fetch_sheet_tab", lambda sa, sheet_id, tab: seen.append(sheet_id) or [])
    config = {"sheet_id_env": "SURVEY_MARINE_SHEET_ID", "surveys": [{"sheet_name": "D2"}]}
    survey_main._fetch_sheets(config, None, None, None)
    assert seen == ["synthetic-sheet"]
    assert config["sheet_url"] == "https://docs.google.com/spreadsheets/d/synthetic-sheet/edit"
