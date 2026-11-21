"""Google Sheets v4 over REST with a service account (google-auth + requests).

GOOGLE_SERVICE_ACCOUNT_JSON holds the full key JSON; each product Sheet is shared
with its client_email as Editor. Errors from here can carry the sheet ID in their
URL, so callers must never print them (cs_main prints a generic line).
"""
from datetime import datetime, timedelta
import json
import math
import os
from urllib.parse import quote
from zoneinfo import ZoneInfo

from cs_errors import DigestError

API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
KOLKATA = ZoneInfo("Asia/Kolkata")
TIMEOUT = 60


def tab_name_for(now):
    """The extractor names its tab for its IST run day, in both editions."""
    return now.astimezone(KOLKATA).date().isoformat()


def tab_range(tab):
    """A1 prefix for a tab name, quoted with apostrophes doubled: 'it''s'!"""
    return "'" + tab.replace("'", "''") + "'!"


def serial_to_wall_clock(serial):
    """Sheets serial date -> naive datetime holding the sheet's wall-clock time."""
    if not isinstance(serial, (int, float)) or isinstance(serial, bool):
        return None
    try:
        milliseconds = math.floor((serial - 25569) * 86400000 + 0.5)  # JS Math.round
        return datetime(1970, 1, 1) + timedelta(milliseconds=milliseconds)
    except (OverflowError, ValueError):
        return None


class SheetsClient:
    def __init__(self, session):
        self.session = session

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        raw = env.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise DigestError("Missing env var GOOGLE_SERVICE_ACCOUNT_JSON")
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        credentials = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        session = AuthorizedSession(credentials)
        # Reads retry transient failures, as the googleapis client did; writes do not.
        retry = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), raise_on_status=False)
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return cls(session)

    def _url(self, sheet_id, suffix=""):
        return f"{API}/{quote(sheet_id, safe='')}{suffix}"

    def _get(self, url, params):
        response = self.session.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    def tabs(self, sheet_id):
        """[{"sheetId": ..., "title": ...}] for every tab."""
        data = self._get(self._url(sheet_id), {"fields": "sheets.properties(sheetId,title)"})
        return [sheet.get("properties", {}) for sheet in data.get("sheets") or []]

    def read_tab(self, sheet_id, tab):
        """Rows 2+ of columns A:H, unformatted, with dates as serial numbers."""
        a1 = quote(tab_range(tab) + "A2:H", safe="")
        data = self._get(self._url(sheet_id, f"/values/{a1}"),
                         {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
        return data.get("values") or []

    def batch_write(self, sheet_id, data):
        """One RAW values.batchUpdate for [(range_a1, values), ...], in order."""
        response = self.session.post(self._url(sheet_id, "/values:batchUpdate"), timeout=TIMEOUT, json={
            "valueInputOption": "RAW",
            "data": [{"range": range_a1, "values": values} for range_a1, values in data],
        })
        response.raise_for_status()

    def write(self, sheet_id, range_a1, values):
        self.batch_write(sheet_id, [(range_a1, values)])
