"""Tests for the FRED API client, fetch retries and the health check.

Run from the repo root:  python -m unittest discover -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from omi import charts, common, health


class FredApiTests(unittest.TestCase):
    def test_api_key_uses_official_endpoint_and_skips_missing_values(self) -> None:
        payload = {"observations": [
            {"date": "2026-01-01", "value": "100.5"},
            {"date": "2026-02-01", "value": "."},          # FRED's "missing"
            {"date": "2026-03-01", "value": "101.5"},
        ]}
        seen: list[str] = []

        def fake_fetch(url, timeout=20, retries=1, headers=None):
            seen.append(url)
            self.assertEqual(retries, 3)
            return json.dumps(payload).encode()

        with mock.patch.dict(os.environ, {"FRED_API_KEY": "abc"}), \
                mock.patch.object(charts, "fetch", fake_fetch):
            rows = charts.fred_observations("CPIAUCSL", "2024-01-01")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1][1], 101.5)
        self.assertIn("api.stlouisfed.org/fred/series/observations", seen[0])
        self.assertIn("api_key=abc", seen[0])

    def test_no_key_falls_back_to_csv(self) -> None:
        csv_body = "observation_date,DGS10\n2026-01-02,4.1\n2026-01-03,.\n2026-01-04,4.2\n"
        env = {k: v for k, v in os.environ.items() if k != "FRED_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(charts, "fetch", lambda *a, **k: csv_body.encode()):
            rows = charts.fred_observations("DGS10", "2026-01-01")
        self.assertEqual([v for _, v in rows], [4.1, 4.2])

    def test_empty_response_raises_instead_of_going_silent(self) -> None:
        with mock.patch.dict(os.environ, {"FRED_API_KEY": "abc"}), \
                mock.patch.object(charts, "fetch", lambda *a, **k: b'{"observations": []}'):
            with self.assertRaises(ValueError):
                charts.fred_observations("CPIAUCSL", "2024-01-01")


class FetchRetryTests(unittest.TestCase):
    class _Response:
        def __init__(self, body: bytes) -> None:
            self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.body

    def test_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
            return self._Response(b"ok")

        with mock.patch("urllib.request.urlopen", flaky), mock.patch("time.sleep"):
            self.assertEqual(common.fetch("https://x.test", retries=3), b"ok")
        self.assertEqual(calls["n"], 3)

    def test_client_errors_are_not_retried(self) -> None:
        calls = {"n": 0}

        def forbidden(req, timeout=0):
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)

        with mock.patch("urllib.request.urlopen", forbidden), mock.patch("time.sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                common.fetch("https://x.test", retries=3)
        self.assertEqual(calls["n"], 1)

    def test_gives_up_after_the_last_attempt(self) -> None:
        def down(req, timeout=0):
            raise urllib.error.URLError("down")

        with mock.patch("urllib.request.urlopen", down), mock.patch("time.sleep"):
            with self.assertRaises(urllib.error.URLError):
                common.fetch("https://x.test", retries=2)


class HealthTests(unittest.TestCase):
    def test_empty_health_is_ok(self) -> None:
        h = health.Health()
        self.assertTrue(h.ok)
        self.assertEqual(h.summary(), "")

    def test_problem_flips_status_and_summarises(self) -> None:
        h = health.Health()
        h.errors("chart").append("FRED fred_cpi_inflation: URLError")
        h.problem("news", "only 2 top stories")
        self.assertFalse(h.ok)
        self.assertEqual(set(h.problems()), {"chart", "news"})
        self.assertIn("chart: FRED fred_cpi_inflation: URLError", h.summary())

    def test_notes_do_not_count_as_problems(self) -> None:
        h = health.Health()
        h.notes.append("feed NPR: TimeoutError")
        self.assertTrue(h.ok)

    def test_write_produces_json(self) -> None:
        h = health.Health()
        h.problem("weather", "Dallas URLError")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(health, "OUTPUT", Path(tmp)):
                h.write()
            saved = json.loads((Path(tmp) / "health.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["problems"], {"weather": ["Dallas URLError"]})

    def test_alert_without_credentials_does_not_crash(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("GMAIL_USER", "GMAIL_APP_PASSWORD")}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(health, "log"):
            self.assertFalse(health.send_alert("s", "b"))

    def test_alert_smtp_failure_does_not_crash(self) -> None:
        with mock.patch.dict(os.environ, {"GMAIL_USER": "a@b.c", "GMAIL_APP_PASSWORD": "x"}), \
                mock.patch.object(health, "log"), \
                mock.patch("smtplib.SMTP_SSL", side_effect=OSError("no network")):
            self.assertFalse(health.send_alert("s", "b"))


if __name__ == "__main__":
    unittest.main()
