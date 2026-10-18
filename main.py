"""Orhan's Morning Brief: build the daily newsletter and deliver it.

Each section (weather, news, research, chart) is built by its own module
inside a guard, so one failing source degrades that section only. Whatever
goes wrong is recorded by omi.health and reported as a "needs attention" email
plus a red workflow run; the newsletter itself still goes out.

    python main.py             build and send (what the workflow runs)
    python main.py --no-send   build output/latest.html only
    python main.py --no-ai     skip Claude, use raw feed text
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from omi.charts import select_chart_of_the_day, select_fallback_chart
from omi.common import OUTPUT, load_config, log
from omi.curate import claude_curate
from omi.deliver import send_via_buttondown
from omi.health import Health, send_alert
from omi.leaders import collect_thought_leaders
from omi.news import (ECONOMIST_FEEDS, NEWS_FEEDS, RESEARCH_FEEDS, collect, deduplicate,
                      rank, recent, select_diverse)
from omi.render import render
from omi.weather import weather

# Fewer top stories than this means the news section is effectively broken.
MIN_TOP_STORIES = 4


def build_weather(config: dict[str, Any], health: Health) -> list[dict[str, Any]]:
    rows = []
    errors = health.errors("weather")
    for loc in config.get("weather_locations", []):
        try:
            rows.append(weather(loc["city"], loc["latitude"], loc["longitude"], config["timezone"]))
        except Exception as exc:
            errors.append(f"{loc['city']} {type(exc).__name__}")
            rows.append({"city": loc["city"], "current": "–", "high": "–", "low": "–",
                         "rain": "–", "conditions": "Unavailable"})
    return rows


def build_stories(config: dict[str, Any], now: dt.datetime, health: Health, no_ai: bool):
    """News, thought leader and research items, curated by Claude when possible."""
    notes = health.notes
    news_errors: list[str] = []
    news = recent(deduplicate(collect(NEWS_FEEDS, news_errors)), now, config["lookback_hours"])
    if len(news_errors) > len(NEWS_FEEDS) // 2:
        health.problem("news", f"{len(news_errors)} of {len(NEWS_FEEDS)} news feeds failed")
    notes.extend(f"feed {e}" for e in news_errors)

    ft = recent(deduplicate(collect([("Financial Times", config["ft_feed"])], notes)), now, 48)
    economist = recent(deduplicate(collect(ECONOMIST_FEEDS, notes)), now, 48)
    research_pool = recent(deduplicate(collect(RESEARCH_FEEDS, notes)), now, 72)
    for group in (news, ft, economist, research_pool):
        for item in group:
            item.score = rank(item, now)
        group.sort(key=lambda x: x.score, reverse=True)

    news_candidates = deduplicate(
        select_diverse(news, 16, per_category=4, per_source=2)
        + select_diverse(ft + economist, 6, per_category=6, per_source=3))
    news_candidates.sort(key=lambda x: x.score, reverse=True)
    research_candidates = select_diverse(research_pool, 10, per_category=4, per_source=2)
    for item in research_candidates:
        item.kind = "research"
    leader_candidates, leader_notes = collect_thought_leaders(config, now, notes)

    if no_ai:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    top, leader, research = claude_curate(
        news_candidates, leader_candidates, research_candidates, config,
        health.errors("curation"))
    if no_ai:
        health.errors("curation").clear()   # deliberate, not a fault

    if len(top) < MIN_TOP_STORIES:
        health.problem("news", f"only {len(top)} top stories")
    if not research:
        health.problem("research", "no research item today")
    total = len(top) + (1 if leader else 0)
    if total > 10:
        top = top[:10 - (1 if leader else 0)]
    return top, leader, leader_notes, ([research] if research else [])


def build_chart(health: Health, now: dt.datetime):
    errors = health.errors("chart")
    chart = select_chart_of_the_day(errors)
    if chart is None:
        chart = select_fallback_chart(now, health.notes)
    if chart is None:
        errors.append("no chart available, tracked or fallback")
    return chart


def inline_chart(body: str, chart: dict[str, Any] | None) -> str:
    """For the saved preview only: embed the chart PNG so latest.html shows it.

    The email itself keeps the cid: placeholder, which delivery replaces with
    a hosted image URL; this copy is just for looking at a test run.
    """
    path = (chart or {}).get("image_path")
    if not path or "cid:chart-of-the-day" not in body:
        return body
    try:
        data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return body
    return body.replace("cid:chart-of-the-day", f"data:image/png;base64,{data}")


def build(no_ai: bool, health: Health):
    config = load_config()
    now = dt.datetime.now(ZoneInfo(config["timezone"]))

    if not os.getenv("FRED_API_KEY"):
        health.problem("setup", "FRED_API_KEY is not set; using the throttled anonymous CSV")

    sections: dict[str, Any] = {
        "weather": ([], lambda: build_weather(config, health)),
        "stories": (([], None, [], []), lambda: build_stories(config, now, health, no_ai)),
        "chart": (None, lambda: build_chart(health, now)),
    }
    results: dict[str, Any] = {}
    for name, (default, fn) in sections.items():
        try:
            results[name] = fn()
        except Exception as exc:   # one section failing must not stop the rest
            log(traceback.format_exc())
            health.problem(name if name != "stories" else "news", f"crashed: {type(exc).__name__}: {exc}")
            results[name] = default

    top, leader, leader_notes, research = results["stories"]
    body = render(config, now, results["weather"], top, leader, leader_notes,
                  research, results["chart"])
    OUTPUT.mkdir(exist_ok=True)
    dated = OUTPUT / f"omb_{now:%Y-%m-%d}.html"
    dated.write_text(body, encoding="utf-8")
    (OUTPUT / "latest.html").write_text(inline_chart(body, results["chart"]), encoding="utf-8")
    (OUTPUT / "latest.json").write_text(json.dumps({
        "generated_at": now.isoformat(),
        "chart_of_the_day": results["chart"],
        "stories": [asdict(s) | {"published": s.published.isoformat() if s.published else None}
                    for s in top + ([leader] if leader else []) + research],
    }, indent=2, default=str), encoding="utf-8")
    date_label = now.strftime("%B %#d, %Y" if os.name == "nt" else "%B %-d, %Y")
    return f"{config['newsletter_name']} | {date_label}", body, results["chart"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and deliver Orhan's Morning Brief.")
    parser.add_argument("--no-send", action="store_true", help="Build files without sending.")
    parser.add_argument("--no-ai", action="store_true", help="Skip Claude; use feed text.")
    args = parser.parse_args()

    health = Health()
    try:
        subject, body, chart = build(args.no_ai, health)
        if not args.no_send:
            send_via_buttondown(subject, body, chart, health)
    except Exception as exc:
        health.problem("run", f"failed: {type(exc).__name__}: {exc}")
        health.write()
        send_alert("Morning Brief FAILED", f"The run crashed.\n\n{traceback.format_exc()}")
        raise

    health.write()
    if health.ok:
        print("health: ok")
        return 0
    print(f"health: NEEDS ATTENTION - {health.summary()}", file=sys.stderr)
    # Don't alert on a manual --no-send/test build; do on every real run.
    if not args.no_send and not os.getenv("OMI_PRESERVE_CHART_STATE"):
        send_alert("Morning Brief needs attention",
                   f"Today's edition went out, but:\n\n{health.summary()}\n\n"
                   "Details: the run log, and output/health.json in the Actions run.")
    return 0   # the workflow's final "health gate" step turns the run red


if __name__ == "__main__":
    raise SystemExit(main())
