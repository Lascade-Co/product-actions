"""Google Sheets REST access with a service account (replaces the googleapis client)."""
from datetime import datetime, timezone
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

import cs_sheets
from cs_errors import DigestError
from cs_sheets import SheetsClient, serial_to_wall_clock, tab_name_for, tab_range


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload or {}
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def test_tabs_request_only_sheet_properties():
    session = Session(Response({"sheets": [{"properties": {"sheetId": 7, "title": "2026-10-22"}}]}))
    assert SheetsClient(session).tabs("sheet/id") == [{"sheetId": 7, "title": "2026-10-22"}]
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "https://sheets.googleapis.com/v4/spreadsheets/sheet%2Fid")
    assert kwargs["params"] == {"fields": "sheets.properties(sheetId,title)"}
    assert kwargs["timeout"] == 60


def test_tabs_tolerate_a_spreadsheet_without_sheets():
    assert SheetsClient(Session(Response({}))).tabs("id") == []


def test_read_tab_reads_a2_to_h_unformatted_with_serial_dates():
    session = Session(Response({"values": [[46315.5, "s", "c"]]}))
    assert SheetsClient(session).read_tab("id", "Bob's tab") == [[46315.5, "s", "c"]]
    method, url, kwargs = session.calls[0]
    assert url == ("https://sheets.googleapis.com/v4/spreadsheets/id/values/"
                   "%27Bob%27%27s%20tab%27%21A2%3AH")
    assert kwargs["params"] == {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"}


def test_read_tab_of_an_empty_tab_is_empty():
    assert SheetsClient(Session(Response({}))).read_tab("id", "t") == []


def test_batch_write_is_one_raw_batch_update_in_order():
    session = Session(Response({}))
    SheetsClient(session).batch_write("id", [("'t'!G1", [["Sentiment"]]), ("'t'!E3:F3", [["s", "answered"]])])
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", "https://sheets.googleapis.com/v4/spreadsheets/id/values:batchUpdate")
    assert kwargs["json"] == {"valueInputOption": "RAW", "data": [
        {"range": "'t'!G1", "values": [["Sentiment"]]}, {"range": "'t'!E3:F3", "values": [["s", "answered"]]}]}


def test_write_is_a_single_range_batch():
    session = Session(Response({}))
    SheetsClient(session).write("id", "'t'!D2", [["hello"]])
    assert session.calls[0][2]["json"]["data"] == [{"range": "'t'!D2", "values": [["hello"]]}]


def test_http_errors_raise():
    with pytest.raises(RuntimeError):
        SheetsClient(Session(Response(status=403))).tabs("id")


def test_tab_name_is_today_in_kolkata_for_both_editions():
    assert tab_name_for(datetime(2026, 10, 21, 18, 29, tzinfo=timezone.utc)) == "2026-10-21"
    assert tab_name_for(datetime(2026, 10, 21, 18, 30, tzinfo=timezone.utc)) == "2026-10-22"


def test_tab_range_quotes_and_doubles_apostrophes():
    assert tab_range("2026-10-22") == "'2026-10-22'!"
    assert tab_range("it's") == "'it''s'!"


def test_serials_are_sheet_wall_clock_not_converted():
    assert serial_to_wall_clock(46315.5) == datetime(2026, 10, 20, 12, 0)  # node: 2026-10-20T12:00:00.000Z
    assert serial_to_wall_clock(45951.1875) == datetime(2025, 10, 21, 4, 30)
    for value in ("46315.5", "", None, True, float("nan"), 1e20):
        assert serial_to_wall_clock(value) is None


def _service_account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return json.dumps({"type": "service_account", "project_id": "p", "private_key_id": "k", "private_key": pem,
                       "client_email": "digest@p.iam.gserviceaccount.com", "client_id": "1",
                       "token_uri": "https://oauth2.googleapis.com/token"})


def test_from_env_builds_a_spreadsheets_scoped_session_without_network():
    client = SheetsClient.from_env({"GOOGLE_SERVICE_ACCOUNT_JSON": _service_account()})
    assert client.session.credentials.scopes == ["https://www.googleapis.com/auth/spreadsheets"]
    assert client.session.credentials.service_account_email == "digest@p.iam.gserviceaccount.com"


def test_from_env_requires_the_variable_and_valid_json():
    with pytest.raises(DigestError, match="^Missing env var GOOGLE_SERVICE_ACCOUNT_JSON$"):
        SheetsClient.from_env({})
    with pytest.raises(ValueError):
        SheetsClient.from_env({"GOOGLE_SERVICE_ACCOUNT_JSON": '{"private_key":"PRIVATE'})


def test_module_never_imports_the_googleapiclient():
    assert "googleapiclient" not in open(cs_sheets.__file__, encoding="utf-8").read()
