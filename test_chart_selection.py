"""Regression tests for Chart of the Day selection.

The invariant being protected: whether a chart is "new" depends only on its
content (a hash of the data) compared with what was recorded
when it was last featured. It must not depend on file timestamps or on what
happens to be left in the working directory, because the newsletter runs on
ephemeral CI runners where both are reset every day.

Run from the repo root:  python -m unittest discover -v
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omi import charts as main


def month_range(first: tuple[int, int], last: tuple[int, int]) -> list[dt.date]:
    dates, (year, month) = [], first
    while (year, month) <= last:
        dates.append(dt.date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


class FakeFred:
    """Stands in for fred_observations; lets a test 'publish' new data."""

    def __init__(self) -> None:
        self.cpi_last = (2026, 8)
        self.gdp_last = (2026, 4)
        self.dgs_days = 30
        self.fail: set[str] = set()

    def __call__(self, series_id: str, start: str) -> list[tuple[dt.date, float]]:
        if series_id in self.fail:
            raise RuntimeError("simulated FRED outage")
        if series_id == "CPIAUCSL":
            dates = month_range((2014, 1), self.cpi_last)
            return [(d, 230.0 * (1.0025 ** i)) for i, d in enumerate(dates)]
        if series_id == "GDP":
            dates = [d for d in month_range((2014, 1), self.gdp_last) if d.month in (1, 4, 7, 10)]
            return [(d, 17000.0 * (1.01 ** i)) for i, d in enumerate(dates)]
        if series_id == "DGS10":
            first = dt.date(2024, 6, 3)
            return [(first + dt.timedelta(days=i), 4.0 + 0.01 * (i % 7)) for i in range(400 + self.dgs_days)]
        raise AssertionError(f"unexpected series {series_id}")


class ChartSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name) / "output"
        self.fred = FakeFred()
        patches = [
            mock.patch.object(main, "OUTPUT", out),
            mock.patch.object(main, "CHART_STATE", out / "chart_of_the_day_state.json"),
            mock.patch.object(main, "fred_observations", self.fred),
            mock.patch.object(main, "log", lambda message: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def select(self) -> tuple[dict | None, list[str]]:
        errors: list[str] = []
        return main.select_chart_of_the_day(errors), errors

    def feature_everything_available(self) -> None:
        """Simulate days of live sends until nothing eligible remains."""
        for _ in range(10):
            chart, _ = self.select()
            if not chart:
                return
            main.mark_chart_featured(chart)
        self.fail("selection never settled")

    def test_fresh_checkout_features_the_newest_high_priority_chart(self) -> None:
        # No output/ dir, no state: exactly what a clean CI checkout looks like.
        chart, errors = self.select()
        self.assertEqual(chart["id"], "fred_cpi_inflation")
        self.assertEqual(errors, [])

    def test_featured_chart_is_not_repeated(self) -> None:
        chart, _ = self.select()
        main.mark_chart_featured(chart)
        again, _ = self.select()
        self.assertNotEqual(again["id"], chart["id"])

    def test_new_release_is_featured_with_no_code_change(self) -> None:
        """The bug: once everything was featured, a new release was never picked up."""
        self.feature_everything_available()
        self.assertIsNone(self.select()[0])

        self.fred.cpi_last = (2026, 9)  # BLS/FRED publish a new CPI month
        chart, _ = self.select()
        self.assertEqual(chart["id"], "fred_cpi_inflation")
        main.mark_chart_featured(chart)

        self.assertIsNone(self.select()[0])  # featured once, then quiet again
        self.fred.gdp_last = (2026, 7)       # and the next release works too
        self.assertEqual(self.select()[0]["id"], "fred_gdp_growth")

    def test_file_timestamps_are_irrelevant(self) -> None:
        """Old logic skipped any chart whose image predated its metadata file."""
        first, _ = self.select()
        for png in main.OUTPUT.glob("*.png"):
            os.utime(png, (0, 0))                       # ancient
        second, _ = self.select()                       # rebuilt fresh, mtimes arbitrary
        self.assertEqual(first["id"], second["id"])
        for png in main.OUTPUT.glob("*.png"):
            os.utime(png, (4102444800, 4102444800))     # year 2100
        third, _ = self.select()
        self.assertEqual(first["id"], third["id"])

    def test_leftover_working_directory_files_do_not_matter(self) -> None:
        main.mark_chart_featured(self.select()[0])
        state = main.CHART_STATE.read_text(encoding="utf-8")
        for path in main.OUTPUT.iterdir():              # wipe everything except state
            if path != main.CHART_STATE:
                path.unlink()
        self.assertEqual(main.CHART_STATE.read_text(encoding="utf-8"), state)
        self.assertEqual(self.select()[0]["id"], "fred_gdp_growth")

    def test_state_records_the_signature(self) -> None:
        chart, _ = self.select()
        main.mark_chart_featured(chart)
        saved = json.loads(main.CHART_STATE.read_text(encoding="utf-8"))
        self.assertEqual(saved[chart["id"]]["featured_signature"], chart["signature"])

    def test_fallback_charts_are_never_recorded(self) -> None:
        main.mark_chart_featured({"id": "fallback", "is_fallback": True})
        self.assertFalse(main.CHART_STATE.exists())

    def test_fred_failure_is_reported_not_swallowed(self) -> None:
        self.fred.fail = {"CPIAUCSL"}
        chart, errors = self.select()
        self.assertEqual(chart["id"], "fred_gdp_growth")  # others still work
        self.assertIn("FRED fred_cpi_inflation: RuntimeError", errors)
        self.assertEqual(errors[0], "FRED fred_cpi_inflation: RuntimeError")  # survives [:6] truncation

    def test_total_outage_is_reported(self) -> None:
        self.fred.fail = {"CPIAUCSL", "GDP", "DGS10"}
        chart, errors = self.select()
        self.assertIsNone(chart)
        self.assertIn("Chart of the Day: no tracked chart source could be loaded.", errors)

    def test_long_silence_raises_a_visible_warning(self) -> None:
        self.feature_everything_available()
        state = json.loads(main.CHART_STATE.read_text(encoding="utf-8"))
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
        for entry in state.values():
            entry["featured_at"] = old
        main.CHART_STATE.write_text(json.dumps(state), encoding="utf-8")
        chart, errors = self.select()
        self.assertIsNone(chart)
        self.assertTrue(any("no tracked chart has been featured since" in e for e in errors), errors)

    def test_short_quiet_spell_is_not_a_warning(self) -> None:
        self.feature_everything_available()
        chart, errors = self.select()
        self.assertIsNone(chart)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
