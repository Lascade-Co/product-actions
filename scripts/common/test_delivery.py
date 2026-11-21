"""Resend delivery payload, frozen-envelope, and public-log safety tests."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import delivery


@contextlib.contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class DeliveryTests(unittest.TestCase):
    def _module(self):
        return delivery

    def test_transport_encodes_subject_and_test_recipient_without_logging_content(self):
        delivery = self._module()
        config = {"digests": {"revenue": {"sender": "MarineRadar", "recipients": {
            "pt": ["production@example.com"], "ist": ["team@example.com"]}}}}
        subject = "MarineRadar web revenue · Tue, Oct 21 — $412 (3 purchases)"
        output = io.StringIO()
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        with tempfile.TemporaryDirectory() as directory, \
             _chdir(directory), \
             patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key", "MAIL_FROM": "noreply@lascade.com",
                                     "GITHUB_RUN_ID": "42", "GITHUB_ACTIONS": "false"}), \
             patch.object(delivery, "requests", mock_session), \
             contextlib.redirect_stdout(output):
            delivery.send_digest("revenue", "pt", subject, "<p>private body</p>",
                                 test_to="test@example.com", config=config,
                                 report_date="2026-10-21")

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs[0][1]
        self.assertIn("Bearer re_test_key", headers["Authorization"])
        self.assertIn("Idempotency-Key", headers)
        payload = json.loads(call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][2])
        self.assertEqual(payload["to"], ["test@example.com"])
        self.assertEqual(payload["subject"], "[TEST] " + subject)
        self.assertIn("MarineRadar", payload["from"])
        self.assertEqual(payload["html"], "<p>private body</p>")

        log = output.getvalue()
        for private in (subject, "private body", "production@example.com",
                        "test@example.com", "noreply@lascade.com", "re_test_key"):
            self.assertNotIn(private, log)
        self.assertIn(hashlib.sha256(("[TEST] " + subject).encode()).hexdigest()[:8], log)

    def test_preview_files_are_utf8_with_no_raw_subject_log(self):
        delivery = self._module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             contextlib.redirect_stdout(output):
            delivery.write_preview("conversion", "ist",
                                   "Install → Paid · Wed, Oct 21 — 14 days",
                                   "<html>private body</html>", out_dir=directory)
            files = sorted(p.name for p in Path(directory).iterdir())
            self.assertEqual(files, ["conversion-ist.html", "conversion-ist.subject.txt"])
            self.assertEqual((Path(directory) / "conversion-ist.subject.txt").read_text(),
                             "Install → Paid · Wed, Oct 21 — 14 days")
        self.assertNotIn("private body", output.getvalue())
        self.assertNotIn("Install → Paid", output.getvalue())

    def test_resend_api_error_does_not_expose_response_body(self):
        delivery = self._module()
        config = {"digests": {"revenue": {"sender": "MarineRadar", "recipients": {
            "pt": ["private@example.com"]}}}}
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_session.post.return_value = mock_response

        with tempfile.TemporaryDirectory() as directory, \
             _chdir(directory), \
             patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key", "MAIL_FROM": "noreply@lascade.com",
                                     "GITHUB_ACTIONS": "false"}), \
             patch.object(delivery, "requests", mock_session):
            with self.assertRaisesRegex(delivery.DeliveryError, "Resend delivery failed") as result:
                delivery.send_digest("revenue", "pt", "private subject", "private body",
                                     config=config, report_date="2026-10-21")
        self.assertNotIn("private@example.com", str(result.exception))
        self.assertNotIn("private subject", str(result.exception))

    def test_retry_on_429_then_success(self):
        delivery = self._module()
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)

        mock_session = MagicMock()
        response_429 = MagicMock()
        response_429.status_code = 429
        response_200 = MagicMock()
        response_200.status_code = 200
        mock_session.post.side_effect = [response_429, response_200]

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "envelope.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            result = delivery.send_frozen(path, "re_key", session=mock_session, sleep_fn=fake_sleep)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(mock_session.post.call_count, 2)
        self.assertEqual(len(sleeps), 1)

    def test_retry_on_5xx_then_success(self):
        delivery = self._module()
        mock_session = MagicMock()
        response_500 = MagicMock()
        response_500.status_code = 500
        response_200 = MagicMock()
        response_200.status_code = 200
        mock_session.post.side_effect = [response_500, response_200]

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "envelope.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            result = delivery.send_frozen(path, "re_key", session=mock_session, sleep_fn=lambda _: None)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["attempts"], 2)

    def test_409_concurrent_retries_then_succeeds(self):
        delivery = self._module()
        mock_session = MagicMock()
        response_409 = MagicMock()
        response_409.status_code = 409
        response_409.json.return_value = {"name": "concurrent_idempotent_requests"}
        response_200 = MagicMock()
        response_200.status_code = 200
        mock_session.post.side_effect = [response_409, response_200]

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "envelope.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            result = delivery.send_frozen(path, "re_key", session=mock_session, sleep_fn=lambda _: None)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["attempts"], 2)

    def test_409_payload_mismatch_fails_immediately(self):
        delivery = self._module()
        mock_session = MagicMock()
        response_409 = MagicMock()
        response_409.status_code = 409
        response_409.json.return_value = {"name": "invalid_idempotent_request"}
        mock_session.post.return_value = response_409

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "envelope.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            with self.assertRaisesRegex(delivery.DeliveryError, "invalid_idempotent_request"):
                delivery.send_frozen(path, "re_key", session=mock_session, sleep_fn=lambda _: None)
        self.assertEqual(mock_session.post.call_count, 1)

    def test_max_attempts_exhausted(self):
        delivery = self._module()
        mock_session = MagicMock()
        response_500 = MagicMock()
        response_500.status_code = 500
        mock_session.post.return_value = response_500

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "envelope.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            with self.assertRaisesRegex(delivery.DeliveryError, "Resend delivery failed"):
                delivery.send_frozen(path, "re_key", max_attempts=3,
                                     session=mock_session, sleep_fn=lambda _: None)
        self.assertEqual(mock_session.post.call_count, 3)

    def test_freeze_envelope_creates_private_file(self):
        delivery = self._module()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "frozen.json")
            delivery.freeze_envelope(path, "my/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            self.assertTrue(os.path.exists(path))
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            with open(path) as f:
                envelope = json.load(f)
            self.assertEqual(envelope["key"], "my/key")
            payload = json.loads(envelope["body"])
            self.assertEqual(payload["subject"], "s")

    def test_freeze_envelope_fails_if_file_exists(self):
        delivery = self._module()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "frozen.json")
            delivery.freeze_envelope(path, "my/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            with self.assertRaisesRegex(delivery.DeliveryError, "already exists"):
                delivery.freeze_envelope(path, "my/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})

    def test_idempotency_key_production_format(self):
        delivery = self._module()
        key = delivery.idempotency_key("revenue", "pt", report_date="2026-10-21")
        self.assertEqual(key, "revenue/pt/2026-10-21")

    def test_idempotency_key_test_format(self):
        delivery = self._module()
        key = delivery.idempotency_key("revenue", "pt", test_to="x@y.com", run_id="123")
        self.assertEqual(key, "revenue/pt/test/123")

    def test_missing_api_key_raises(self):
        delivery = self._module()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "frozen.json")
            delivery.freeze_envelope(path, "test/key", {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
            with self.assertRaisesRegex(delivery.DeliveryError, "API key is missing"):
                delivery.send_frozen(path, "")

    def _frozen(self, directory, payload=None):
        path = os.path.join(directory, "frozen.json")
        delivery.freeze_envelope(path, "report/pt/2026-10-21",
                                 payload or {"from": "a", "to": ["b"], "subject": "s", "html": "h"})
        return path

    @staticmethod
    def _response(status, body):
        response = MagicMock()
        response.status_code = status
        response.json.return_value = body
        response.text = json.dumps(body)
        return response

    def test_send_frozen_409_invalid_fails_closed(self):
        session = MagicMock()
        session.post.return_value = self._response(
            409, {"name": "invalid_idempotent_request", "message": "secret detail"})
        sleeps = []
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            with self.assertRaises(delivery.DeliveryError) as caught:
                delivery.send_frozen(path, "re_key", session=session, sleep_fn=sleeps.append)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("invalid_idempotent_request", str(caught.exception))
        self.assertNotIn("secret detail", str(caught.exception))

    def test_send_frozen_error_has_no_upstream_text(self):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                session = MagicMock()
                session.post.return_value = self._response(
                    status, {"name": "validation_error", "message": "secret detail"})
                with tempfile.TemporaryDirectory() as directory:
                    path = self._frozen(directory)
                    with self.assertRaises(delivery.DeliveryError) as caught:
                        delivery.send_frozen(path, "re_key", session=session, sleep_fn=lambda _: None)
                self.assertEqual(session.post.call_count, 1)
                self.assertEqual(str(caught.exception), f"Resend delivery failed: HTTP {status} (HTTP error)")
                self.assertNotIn("secret detail", str(caught.exception))
                self.assertNotIn("validation_error", str(caught.exception))

    def test_other_409_fails_closed_without_retry(self):
        session = MagicMock()
        session.post.return_value = self._response(409, {"name": "something_else", "message": "secret detail"})
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            with self.assertRaisesRegex(delivery.DeliveryError,
                                        r"^Resend delivery failed: HTTP 409 \(idempotency conflict\)$"):
                delivery.send_frozen(path, "re_key", session=session, sleep_fn=lambda _: None)
        self.assertEqual(session.post.call_count, 1)

    def test_backoff_timeout_and_transport_retry(self):
        session = MagicMock()
        session.post.side_effect = [OSError("secret detail"), self._response(500, {}),
                                    self._response(429, {}), self._response(503, {})]
        sleeps = []
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            with self.assertRaises(delivery.DeliveryError) as caught:
                delivery.send_frozen(path, "re_key", session=session, sleep_fn=sleeps.append)
        self.assertEqual(session.post.call_count, 4)
        self.assertEqual(sleeps, [1, 2, 4])
        self.assertEqual({call.kwargs["timeout"] for call in session.post.call_args_list}, {60})
        self.assertNotIn("secret detail", str(caught.exception))

    def test_backoff_is_capped_at_fifteen_seconds(self):
        session = MagicMock()
        session.post.return_value = self._response(500, {})
        sleeps = []
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            with self.assertRaises(delivery.DeliveryError):
                delivery.send_frozen(path, "re_key", max_attempts=6, session=session, sleep_fn=sleeps.append)
        self.assertEqual(sleeps, [1, 2, 4, 8, 15])

    def test_only_http_200_is_accepted(self):
        session = MagicMock()
        session.post.return_value = self._response(202, {"id": "x"})
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            with self.assertRaisesRegex(delivery.DeliveryError, "HTTP 202"):
                delivery.send_frozen(path, "re_key", session=session, sleep_fn=lambda _: None)
        self.assertEqual(session.post.call_count, 1)

    def test_success_result_shape(self):
        session = MagicMock()
        session.post.return_value = self._response(200, {"id": "x"})
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            result = delivery.send_frozen(path, "re_key", session=session)
        self.assertEqual(result, {"accepted": True, "status": 200, "attempts": 1})
        self.assertEqual(session.post.call_args.kwargs["headers"]["Idempotency-Key"], "report/pt/2026-10-21")

    def test_send_frozen_options_are_keyword_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory)
            session = MagicMock()
            with self.assertRaises(TypeError):
                delivery.send_frozen(path, "re_key", 4, session)
            session.post.assert_not_called()

    def test_frozen_body_is_compact_and_keeps_key_order(self):
        session = MagicMock()
        session.post.return_value = self._response(200, {})
        payload = {"to": ["b"], "from": "a", "subject": "s · t", "html": "h"}
        with tempfile.TemporaryDirectory() as directory:
            path = self._frozen(directory, payload)
            with open(path, encoding="utf-8") as source:
                raw = source.read()
            delivery.send_frozen(path, "re_key", session=session)
        body = json.dumps(payload, separators=(",", ":"))
        self.assertEqual(raw, json.dumps({"key": "report/pt/2026-10-21", "body": body}, separators=(",", ":")))
        self.assertEqual(session.post.call_args.kwargs["data"], body)
        self.assertEqual(list(json.loads(session.post.call_args.kwargs["data"])), ["to", "from", "subject", "html"])

    def test_scheduled_at_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(delivery.DeliveryError, "Invalid email payload"):
                delivery.freeze_envelope(os.path.join(directory, "frozen.json"), "k",
                                         {"to": ["b"], "scheduled_at": "2026-10-21T12:55:00Z"})

    def test_preview_writes_text_part_and_returns_paths(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            paths = delivery.write_preview("hunch", "pt", "Subject", "<p>h</p>", text="plain", out_dir=directory)
            self.assertEqual([p.name for p in paths], ["hunch-pt.html", "hunch-pt.subject.txt", "hunch-pt.txt"])
            self.assertTrue(all(isinstance(p, Path) for p in paths))
            self.assertEqual(paths[2].read_text(encoding="utf-8"), "plain")
            without = delivery.write_preview("hunch", "ist", "Subject", "<p>h</p>", out_dir=directory)
            self.assertIsInstance(without, list)
            self.assertEqual([p.name for p in without], ["hunch-ist.html", "hunch-ist.subject.txt"])

    def test_load_config_reads_repo_data_path(self):
        self.assertEqual(delivery.CONFIG_PATH,
                         Path(__file__).resolve().parents[2] / "data" / "email_config.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"digests": {}}', encoding="utf-8")
            self.assertEqual(delivery.load_config(path), {"digests": {}})

    def test_mask_only_prints_in_actions(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), contextlib.redirect_stdout(output):
            delivery.mask("secret")
        self.assertEqual(output.getvalue(), "")
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(output):
            delivery.mask("a%b\nc")
        self.assertEqual(output.getvalue(), "::add-mask::a%25b\n::add-mask::c\n")


if __name__ == "__main__":
    unittest.main()
