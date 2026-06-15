"""Orhan's Morning Times.

Daily, mobile-friendly morning newsletter covering AI, economics and finance,
technology, science, academic research, medicine, and limited major
geopolitical developments, with a Weather Snapshot, Top News (including one
thought-leader item), Research Radar, and Chart of the Day.

Curation and summaries are produced by the Claude API when a key is
available; the generator degrades gracefully to cleaned feed text otherwise.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CHART_STATE = OUTPUT / "chart_of_the_day_state.json"
USER_AGENT = "OrhanMorningIntelligence/2.0 (+personal research newsletter)"

TOPIC_WEIGHTS = {
    "artificial intelligence": 10, " ai ": 9, "machine learning": 9,
    "large language model": 9, "openai": 8, "anthropic": 8, "nvidia": 7,
    "economy": 7, "economic": 7, "inflation": 7, "federal reserve": 7,
    "interest rate": 7, "market": 5, "trade": 5, "technology": 6,
    "microsoft": 5, "google": 5, "apple": 5, "meta": 5, "amazon": 5,
    "science": 6, "research": 7, "study": 6, "arxiv": 7,
    "medicine": 7, "health": 6, "clinical": 7, "cancer": 7, "drug": 6,
    "world cup": 6, "football": 4, "soccer": 5,
}

SOURCE_BONUS = {
    "Reuters": 12, "Associated Press": 11, "BBC": 8, "NPR": 8,
    "Nature": 12, "Science": 12, "NEJM": 12, "JAMA": 11, "arXiv": 8,
    "SSRN": 9, "Financial Times": 12, "The Economist": 10,
    "The New York Times": 8, "The Washington Post": 8, "The Guardian": 6,
    "MIT Technology Review": 10, "STAT": 10, "Scientific American": 8,
    "Federal Reserve": 12, "World Health Organization": 12,
}

NEGATIVE_TERMS = {
    "stocks poised": 18, "stock to buy": 18, "prediction:": 12,
    "could make you": 15, "millionaire": 15, "motley fool": 16,
    "aol.com": 10, "sponsored": 20, "opinion:": 5, "celebrity": 20,
    "moneyshow.com": 16, "digital journal": 7,
    "american council on science and health": 7,
}

NEWS_FEEDS = [
    ("Reuters", "https://news.google.com/rss/search?q=source:Reuters+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("Google News: AI", "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News: Economics & Finance", "https://news.google.com/rss/search?q=economics+finance+financial+markets+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News: Science", "https://news.google.com/rss/search?q=science+research+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News: Medicine", "https://news.google.com/rss/search?q=medicine+healthcare+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News: World Cup", "https://news.google.com/rss/search?q=FIFA+World+Cup+when:1d&hl=en-US&gl=US&ceid=US:en"),
]

ECONOMIST_FEEDS = [
    ("The Economist", "https://www.economist.com/the-world-this-week/rss.xml"),
    ("The Economist", "https://www.economist.com/business/rss.xml"),
    ("The Economist", "https://www.economist.com/science-and-technology/rss.xml"),
]

RESEARCH_FEEDS = [
    ("Nature", "https://news.google.com/rss/search?q=site:nature.com+research+when:3d&hl=en-US&gl=US&ceid=US:en"),
    ("Science", "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"),
    ("NEJM", "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm"),
    ("JAMA", "https://jamanetwork.com/rss/site_3/67.xml"),
    ("arXiv", "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:econ.EM+OR+cat:q-bio&sortBy=submittedDate&sortOrder=descending&max_results=20"),
    ("SSRN", "https://news.google.com/rss/search?q=site:ssrn.com+OR+%22SSRN%22+paper+when:7d&hl=en-US&gl=US&ceid=US:en"),
    ("AI Conferences", "https://news.google.com/rss/search?q=NeurIPS+OR+ICML+OR+ICLR+OR+%22AI+conference%22+paper+when:3d&hl=en-US&gl=US&ceid=US:en"),
]


@dataclass
class Story:
    title: str
    link: str
    source: str
    published: dt.datetime | None
    description: str = ""
    summary: str = ""
    why: str = ""
    score: float = 0.0
    image_url: str = ""
    image_alt: str = ""
    kind: str = "news"   # news | leader | research
    via: str = ""        # e.g. "X via Nitter", "Substack", "press coverage"


def load_config() -> dict[str, Any]:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        if child.tag.split("}")[-1].lower() in names and child.text:
            return child.text.strip()
    return ""


def parse_date(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def parse_feed(source: str, url: str) -> list[Story]:
    raw = fetch(url)
    raw = re.sub(
        rb"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)[A-Za-z][A-Za-z0-9]+;",
        b" ",
        raw,
    )
    root = ET.fromstring(raw)
    entries = [n for n in root.iter() if n.tag.split("}")[-1].lower() in {"item", "entry"}]
    stories: list[Story] = []
    for entry in entries:
        title = clean_text(child_text(entry, ("title",)))
        link = child_text(entry, ("link",))
        if not link:
            link_node = next((n for n in entry.iter() if n.tag.split("}")[-1].lower() == "link"), None)
            link = link_node.attrib.get("href", "") if link_node is not None else ""
        elif not link.startswith("http"):
            link_node = next((n for n in entry.iter() if n.tag.split("}")[-1].lower() == "link"), None)
            link = link_node.attrib.get("href", link) if link_node is not None else link
        raw_description = child_text(entry, ("description", "summary", "content"))
        description = clean_text(raw_description)
        published = parse_date(child_text(entry, ("pubdate", "published", "updated", "date")))
        item_source = clean_text(child_text(entry, ("source",)))
        resolved_source = item_source if source.startswith("Google News:") and item_source else source
        image_url = ""
        for node in entry.iter():
            tag = node.tag.split("}")[-1].lower()
            candidate = node.attrib.get("url", "")
            media_type = node.attrib.get("type", "")
            if tag in {"thumbnail", "content", "enclosure"} and candidate:
                if tag == "thumbnail" or media_type.startswith("image/"):
                    image_url = candidate
                    break
        if not image_url:
            image_match = re.search(r'<img[^>]+src=["\']([^"\']+)', raw_description, re.I)
            image_url = html.unescape(image_match.group(1)) if image_match else ""
        if any(x in image_url.lower() for x in ("gstatic.com/favicon", "google.com/s2/favicons")):
            image_url = ""
        if title and link:
            stories.append(Story(
                title, link, resolved_source, published, description[:1200],
                image_url=image_url, image_alt=f"Source visual for {title}",
            ))
    return stories


def collect(feeds: list[tuple[str, str]], errors: list[str]) -> list[Story]:
    stories: list[Story] = []
    for source, url in feeds:
        try:
            stories.extend(parse_feed(source, url))
        except Exception as exc:
            errors.append(f"{source}: {type(exc).__name__}")
    return stories


def canonical_title(title: str) -> str:
    title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title.lower())
    return re.sub(r"[^a-z0-9 ]", "", title)


def deduplicate(stories: list[Story]) -> list[Story]:
    seen: set[str] = set()
    result: list[Story] = []
    for story in stories:
        key = " ".join(canonical_title(story.title).split()[:12])
        digest = hashlib.sha1(key.encode()).hexdigest()[:12]
        if digest not in seen:
            seen.add(digest)
            result.append(story)
    return result


def rank(story: Story, now: dt.datetime) -> float:
    text = f" {story.title} {story.description} ".lower()
    relevance = sum(weight for term, weight in TOPIC_WEIGHTS.items() if term in text)
    penalty = sum(weight for term, weight in NEGATIVE_TERMS.items() if term in text)
    source = SOURCE_BONUS.get(story.source, 1)
    age_bonus = 0.0
    if story.published:
        age = max(0, (now.astimezone(dt.timezone.utc) - story.published.astimezone(dt.timezone.utc)).total_seconds() / 3600)
        age_bonus = max(0, 8 - age / 4)
    title_signal = min(6, len(story.description) / 120)
    impact = sum(
        2 for term in ("announces", "launches", "approves", "breakthrough", "war", "ceasefire",
                       "federal reserve", "inflation", "clinical trial", "study finds")
        if term in text
    )
    return relevance * 1.8 + source + age_bonus + title_signal + impact - penalty


def recent(stories: list[Story], now: dt.datetime, hours: int) -> list[Story]:
    cutoff = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=hours)
    return [s for s in stories if not s.published or s.published.astimezone(dt.timezone.utc) >= cutoff]


def category(story: Story) -> str:
    text = f" {story.title} {story.description} ".lower()
    if any(x in text for x in ("medicine", "health", "clinical", "cancer", "drug", "physician")):
        return "health"
    if any(x in text for x in ("econom", "market", "inflation", "federal reserve", "trade", "tariff")):
        return "economics"
    if any(x in text for x in ("world cup", "football", "soccer", "fifa")):
        return "football"
    if any(x in text for x in ("artificial intelligence", " ai ", "machine learning", "llm")):
        return "ai"
    if any(x in text for x in ("research", "science", "study", "arxiv")):
        return "science"
    return "world-tech"


def select_diverse(stories: list[Story], limit: int, per_category: int = 3,
                   per_source: int = 2) -> list[Story]:
    selected: list[Story] = []
    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    for story in sorted(stories, key=lambda x: x.score, reverse=True):
        group = category(story)
        if categories.get(group, 0) >= per_category or sources.get(story.source, 0) >= per_source:
            continue
        selected.append(story)
        categories[group] = categories.get(group, 0) + 1
        sources[story.source] = sources.get(story.source, 0) + 1
        if len(selected) == limit:
            break
    return selected


# ---------------------------------------------------------------------------
# Thought Leaders Monitor
# ---------------------------------------------------------------------------

def original_x_url(link: str, handle: str) -> str:
    match = re.search(r"/status/(\d+)", link)
    username = handle.lstrip("@")
    return f"https://x.com/{username}/status/{match.group(1)}" if match else f"https://x.com/{username}"


def collect_thought_leaders(config: dict[str, Any], now: dt.datetime,
                            errors: list[str]) -> tuple[list[Story], list[str]]:
    """Best recent public item per configured leader, plus availability notes.

    Source priority per leader:
      1. Direct X posts via public Nitter mirrors (when reachable).
      2. The leader's own publication feeds (Substack, CFR blog, ...).
      3. Google News coverage of the leader, clearly labelled as coverage.
    """
    cutoff = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=26)
    candidates: list[Story] = []
    notes: list[str] = []
    for leader in config.get("thought_leaders", []):
        handle = leader.get("handle", "")
        name = leader.get("name", handle)
        username = handle.lstrip("@")
        leader_posts: list[Story] = []

        # 1. X via Nitter mirrors.
        for instance in config.get("nitter_instances", []):
            try:
                posts = parse_feed(name, f"{instance}/{urllib.parse.quote(username)}/rss")
            except Exception:
                continue
            for post in posts:
                if post.published and post.published.astimezone(dt.timezone.utc) < cutoff:
                    continue
                if post.title.startswith("RT by "):
                    continue
                post.title = re.sub(r"^R to @[^:]+:\s*", "", post.title).strip()
                post.link = original_x_url(post.link, handle)
                post.via = "X"
                leader_posts.append(post)
            if leader_posts:
                break

        # 2. Own publications (Substack, blogs).
        if not leader_posts:
            for feed_url in leader.get("feeds", []):
                try:
                    posts = parse_feed(name, feed_url)
                except Exception:
                    continue
                for post in posts:
                    if post.published and post.published.astimezone(dt.timezone.utc) < cutoff:
                        continue
                    post.via = "own publication"
                    leader_posts.append(post)

        # 3. Press coverage as a clearly-labelled fallback.
        if not leader_posts and leader.get("news_query"):
            query = urllib.parse.quote(leader["news_query"])
            try:
                posts = parse_feed(
                    name,
                    f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
                )
                for post in posts[:5]:
                    if post.published and post.published.astimezone(dt.timezone.utc) < cutoff:
                        continue
                    post.via = "press coverage"
                    leader_posts.append(post)
            except Exception as exc:
                errors.append(f"Thought leader {handle}: {type(exc).__name__}")

        if leader_posts:
            for post in leader_posts:
                post.kind = "leader"
                post.source = f"{name} ({handle})"
                post.summary = post.title
                post.score = rank(post, now) + (4 if post.image_url else 0) + (
                    10 if post.via == "X" else 6 if post.via == "own publication" else 0
                )
            candidates.append(max(leader_posts, key=lambda post: post.score))
        else:
            notes.append(f"{name} ({handle}): no retrievable public posts in the last 24 hours.")
    candidates.sort(key=lambda post: post.score, reverse=True)
    return candidates, notes


# ---------------------------------------------------------------------------
# Claude curation
# ---------------------------------------------------------------------------

def claude_call(prompt: str, model: str, max_tokens: int) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read())
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def parse_json_reply(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def heuristic_text(story: Story) -> None:
    story.summary = story.summary or story.description[:360] or story.title
    story.why = story.why or "Selected for impact, novelty, and relevance."


def claude_curate(
    news_candidates: list[Story],
    leader_candidates: list[Story],
    research_candidates: list[Story],
    config: dict[str, Any],
    errors: list[str],
) -> tuple[list[Story], Story | None, Story | None]:
    """Single Claude call: select, rank, and write summaries for all sections."""
    top_n = int(config.get("top_news_items", 8))

    def fallback() -> tuple[list[Story], Story | None, Story | None]:
        top = select_diverse(news_candidates, top_n)
        for story in top:
            heuristic_text(story)
        leader = leader_candidates[0] if leader_candidates else None
        if leader:
            leader.summary = leader.summary or leader.title
        research = research_candidates[0] if research_candidates else None
        if research:
            heuristic_text(research)
        return top, leader, research

    if not os.getenv("ANTHROPIC_API_KEY"):
        errors.append("ANTHROPIC_API_KEY unavailable; used heuristic selection and feed summaries.")
        return fallback()

    def pack(stories: list[Story], limit: int) -> list[dict[str, Any]]:
        return [
            {
                "id": index,
                "title": story.title,
                "source": story.source,
                "via": story.via,
                "description": story.description[:700],
                "published": story.published.isoformat() if story.published else None,
            }
            for index, story in enumerate(stories[:limit])
        ]

    payload = {
        "news_candidates": pack(news_candidates, 22),
        "thought_leader_posts": pack(leader_candidates, 6),
        "research_candidates": pack(research_candidates, 10),
    }
    prompt = (
        "You are the editor of 'Orhan's Morning Intelligence', a concise daily briefing for a "
        "university professor interested in AI, economics, finance, technology, science, academic "
        "research, medicine, and the football World Cup. Rank by Impact x Novelty x Relevance, "
        "weighting relevance heavily toward AI, economics, finance, academic research, and "
        "medicine. Avoid celebrity news, entertainment, low-impact political commentary, "
        "investment-promotion content, and duplicate coverage of the same underlying story.\n\n"
        f"From news_candidates choose exactly {top_n} items (fewer only if the pool is smaller), "
        "ordered most consequential first, covering a diverse mix of the priority topics. For each "
        "write 'summary' (2-3 short factual sentences strictly grounded in the supplied metadata; "
        "no hype, no invented facts) and 'why' (one short sentence on why it matters to this "
        "reader).\n\n"
        "From thought_leader_posts choose the single most notable post (or null if empty) and "
        "write a 1-2 sentence 'summary'.\n\n"
        "From research_candidates choose the single most interesting genuine research item (a "
        "paper, study, or peer-reviewed finding - not general news; null if none qualify) and "
        "write 'summary' (a one-sentence statement of the finding) and 'why' (one sentence).\n\n"
        "Return ONLY valid JSON, no markdown fences, in this exact shape:\n"
        '{"top": [{"id": 0, "summary": "...", "why": "..."}], '
        '"thought": {"id": 0, "summary": "..."} | null, '
        '"research": {"id": 0, "summary": "...", "why": "..."} | null}\n\n'
        + json.dumps(payload, separators=(",", ":"))
    )
    model = os.getenv("OMI_MODEL", config.get("claude_model", "claude-sonnet-4-6"))
    try:
        reply = parse_json_reply(claude_call(prompt, model, int(config.get("claude_max_tokens", 4000))))
        top: list[Story] = []
        for item in reply.get("top", [])[:top_n]:
            story = news_candidates[int(item["id"])]
            story.summary = clean_text(item.get("summary")) or story.description[:360]
            story.why = clean_text(item.get("why")) or "A potentially consequential development."
            top.append(story)
        if not top:
            raise ValueError("Claude returned no top stories")
        leader = None
        if reply.get("thought") and leader_candidates:
            leader = leader_candidates[int(reply["thought"]["id"])]
            leader.summary = clean_text(reply["thought"].get("summary")) or leader.title
        elif leader_candidates:
            leader = leader_candidates[0]
            leader.summary = leader.title
        research = None
        if reply.get("research") and research_candidates:
            research = research_candidates[int(reply["research"]["id"])]
            research.summary = clean_text(reply["research"].get("summary")) or research.description[:300]
            research.why = clean_text(reply["research"].get("why")) or "Notable new research."
        elif research_candidates:
            research = research_candidates[0]
            heuristic_text(research)
        return top, leader, research
    except Exception as exc:
        errors.append(f"Claude curation unavailable ({type(exc).__name__}); used heuristic fallback.")
        return fallback()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def weather(city: str, lat: float, lon: float, timezone: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": timezone,
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "hourly": "temperature_2m,precipitation_probability",
        "forecast_days": 1,
    })
    data = json.loads(fetch(f"https://api.open-meteo.com/v1/forecast?{query}"))
    code = int(data["current"]["weather_code"])
    labels = {
        0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow",
        80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
        95: "Thunderstorms", 96: "Thunderstorms", 99: "Severe thunderstorms",
    }
    return {
        "city": city, "current": round(data["current"]["temperature_2m"]),
        "high": round(data["daily"]["temperature_2m_max"][0]),
        "low": round(data["daily"]["temperature_2m_min"][0]),
        "rain": data["daily"]["precipitation_probability_max"][0],
        "conditions": labels.get(code, "Mixed conditions"),
        "hourly_time": data["hourly"]["time"],
        "hourly_temp": [round(x) for x in data["hourly"]["temperature_2m"]],
        "hourly_rain": data["hourly"]["precipitation_probability"],
    }


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def weather_chart_url(weather_rows: list[dict[str, Any]]) -> str:
    if not weather_rows or any("hourly_time" not in row for row in weather_rows):
        return ""
    labels = [dt.datetime.fromisoformat(x).strftime("%-I %p") if os.name != "nt"
              else dt.datetime.fromisoformat(x).strftime("%#I %p")
              for x in weather_rows[0]["hourly_time"][6:22:3]]
    datasets = []
    colors = ["#174f78", "#b44b3e"]
    for index, row in enumerate(weather_rows):
        datasets.append({
            "label": row["city"],
            "data": row["hourly_temp"][6:22:3],
            "borderColor": colors[index % len(colors)],
            "backgroundColor": "transparent",
            "fill": False,
            "lineTension": 0.25,
        })
    chart = {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "legend": {"position": "bottom"},
            "title": {"display": True, "text": "Today's temperature outlook (°F)"},
            "scales": {"yAxes": [{"ticks": {"beginAtZero": False}}]},
        },
    }
    return "https://quickchart.io/chart?" + urllib.parse.urlencode({
        "width": 480, "height": 190, "backgroundColor": "white",
        "c": json.dumps(chart, separators=(",", ":")),
    })


# ---------------------------------------------------------------------------
# Charts (FRED + configured local charts)
# ---------------------------------------------------------------------------

def load_chart_state() -> dict[str, Any]:
    if not CHART_STATE.exists():
        return {}
    try:
        return json.loads(CHART_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def chart_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fred_observations(series_id: str, start: str) -> list[tuple[dt.date, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    rows = list(csv.DictReader(fetch(url).decode("utf-8-sig").splitlines()))
    observations: list[tuple[dt.date, float]] = []
    for row in rows:
        try:
            observations.append((dt.date.fromisoformat(row["observation_date"]), float(row[series_id])))
        except (KeyError, TypeError, ValueError):
            continue
    return observations


def draw_line_chart(path: Path, plotted: list[tuple[dt.date, float]], title: str,
                    subtitle: str, footer: str, unit: str = "%") -> None:
    width, height = 600, 300
    left, top, right, bottom = 58, 54, 22, 45
    image = Image.new("RGB", (width, height), "#FAF7F0")
    draw = ImageDraw.Draw(image)
    title_font = chart_font(20, bold=True)
    label_font = chart_font(11)
    small_font = chart_font(10)
    draw.text((left, 15), title, fill="#17324D", font=title_font)
    draw.text((left, 38), subtitle, fill="#555555", font=small_font)

    values = [value for _, value in plotted]
    spread = max(1.0, max(values) - min(values))
    y_min = min(values) - spread * 0.15
    y_max = max(values) + spread * 0.15
    if unit == "%":
        y_min = min(y_min, -1.0)
    plot_width = width - left - right
    plot_height = height - top - bottom

    def point(index: int, value: float) -> tuple[float, float]:
        x = left + index * plot_width / max(1, len(plotted) - 1)
        y = top + (y_max - value) * plot_height / (y_max - y_min)
        return x, y

    tick_step = max(1, round((y_max - y_min) / 5))
    tick = int(y_min)
    while tick <= int(y_max) + 1:
        y = point(0, tick)[1]
        if top <= y <= height - bottom:
            draw.line((left, y, width - right, y), fill="#D6D6D6", width=1)
            draw.text((8, y - 6), f"{tick}{unit}", fill="#666666", font=small_font)
        tick += tick_step
    if y_min < 0 < y_max:
        zero_y = point(0, 0)[1]
        draw.line((left, zero_y, width - right, zero_y), fill="#999999", width=1)

    points = [point(index, value) for index, (_, value) in enumerate(plotted)]
    draw.line(points, fill="#17324D", width=4, joint="curve")
    latest_x, latest_y = points[-1]
    latest_value = plotted[-1][1]
    draw.ellipse((latest_x - 5, latest_y - 5, latest_x + 5, latest_y + 5), fill="#8A2D3C")
    draw.text((latest_x - 48, latest_y - 24), f"{latest_value:.1f}{unit}",
              fill="#8A2D3C", font=label_font)

    first_year = plotted[0][0].year
    last_year = plotted[-1][0].year
    year_step = 2 if last_year - first_year > 4 else 1
    for year in range(first_year, last_year + 1, year_step):
        nearest = min(range(len(plotted)), key=lambda i: abs(
            (plotted[i][0] - dt.date(year, 6, 30)).days))
        x = points[nearest][0]
        draw.text((x - 13, height - 30), str(year), fill="#666666", font=small_font)
    draw.text((left, height - 14), footer, fill="#777777", font=small_font)
    path.parent.mkdir(exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def build_fred_chart(series_id: str, chart_id: str, title: str, subtitle: str,
                     caption: str, source: str, source_url: str, priority: int,
                     start: str, yoy_lag: int = 0, years_plotted: int = 10,
                     unit: str = "%",
                     explanation_template: str = "") -> dict[str, Any] | None:
    chart_path = OUTPUT / f"{chart_id}.png"
    metadata_path = OUTPUT / f"{chart_id}.json"
    observations = fred_observations(series_id, start)
    if len(observations) < max(5, yoy_lag + 1):
        return None
    if yoy_lag:
        series = [
            (observations[i][0], (observations[i][1] / observations[i - yoy_lag][1] - 1) * 100)
            for i in range(yoy_lag, len(observations))
        ]
    else:
        series = observations
    latest_date, latest_value = series[-1]
    previous_value = series[-2][1]
    cutoff = latest_date.replace(year=latest_date.year - years_plotted)
    plotted = [(date, value) for date, value in series if date >= cutoff]
    metadata = {
        "latest_date": latest_date.isoformat(),
        "latest_value": round(latest_value, 2),
        "previous_value": round(previous_value, 2),
        "data_signature": hashlib.sha256(json.dumps(
            [(date.isoformat(), round(value, 3)) for date, value in series],
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }
    old_metadata = {}
    if metadata_path.exists():
        try:
            old_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if old_metadata.get("data_signature") != metadata["data_signature"] or not chart_path.exists():
        draw_line_chart(chart_path, plotted, title, subtitle, f"Source: {source}", unit)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    direction = "rose" if latest_value > previous_value else "eased" if latest_value < previous_value else "held steady"
    period = (
        f"Q{((latest_date.month - 1) // 3) + 1} {latest_date.year}"
        if series_id == "GDP"
        else latest_date.strftime("%B %Y") if yoy_lag else latest_date.strftime("%B %#d, %Y" if os.name == "nt" else "%B %-d, %Y")
    )
    explanation = explanation_template.format(
        latest=f"{latest_value:.1f}", previous=f"{previous_value:.1f}",
        direction=direction, period=period,
    )
    return {
        "id": chart_id,
        "title": title,
        "image_path": str(chart_path),
        "trigger_path": str(metadata_path),
        "caption": caption,
        "explanation": explanation,
        "source": source,
        "source_url": source_url,
        "priority": priority,
    }


def fred_chart_sources() -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    builders = [
        dict(series_id="GDP", chart_id="fred_gdp_growth",
             title="U.S. GDP Growth Over the Last 10 Years",
             subtitle="Year-over-year percent change in nominal GDP, quarterly",
             caption="Year-over-year growth in nominal U.S. gross domestic product.",
             source="U.S. Bureau of Economic Analysis via FRED",
             source_url="https://fred.stlouisfed.org/series/GDP",
             priority=10, start="2014-01-01", yoy_lag=4,
             explanation_template=(
                 "U.S. nominal GDP was {latest}% higher than a year earlier in {period}, "
                 "after {previous}% in the preceding quarter. The series captures both "
                 "changes in real output and the price level.")),
        dict(series_id="CPIAUCSL", chart_id="fred_cpi_inflation",
             title="U.S. CPI Inflation Over the Last 10 Years",
             subtitle="Year-over-year percent change in CPI, all items, monthly",
             caption="Year-over-year consumer price inflation in the United States.",
             source="U.S. Bureau of Labor Statistics via FRED",
             source_url="https://fred.stlouisfed.org/series/CPIAUCSL",
             priority=10, start="2014-01-01", yoy_lag=12,
             explanation_template=(
                 "Consumer prices were {latest}% higher than a year earlier in {period}; "
                 "inflation {direction} from {previous}% the month before. This is the "
                 "headline CPI measure most directly comparable with household experience.")),
        dict(series_id="DGS10", chart_id="fred_treasury_10y",
             title="10-Year U.S. Treasury Yield",
             subtitle="Daily market yield, last two years",
             caption="The benchmark long-term U.S. interest rate.",
             source="Federal Reserve Board via FRED",
             source_url="https://fred.stlouisfed.org/series/DGS10",
             priority=1, start="2024-06-01", yoy_lag=0, years_plotted=2,
             explanation_template=(
                 "The 10-year Treasury yield stood at {latest}% as of {period}, "
                 "{direction} from {previous}% in the prior session. It anchors mortgage "
                 "rates, corporate borrowing costs, and equity valuations.")),
    ]
    for kwargs in builders:
        try:
            built = build_fred_chart(**kwargs)
            if built:
                sources.append(built)
        except Exception:
            continue
    return sources


def draw_dual_line_chart(path: Path, series: list[tuple[str, str, list[tuple[str, float]]]],
                         title: str, subtitle: str, footer: str) -> None:
    """Draw up to two labelled index lines sharing one axis (matches house style)."""
    width, height = 600, 320
    left, top, right, bottom = 58, 84, 22, 50
    image = Image.new("RGB", (width, height), "#FAF7F0")
    draw = ImageDraw.Draw(image)
    title_font = chart_font(20, bold=True)
    label_font = chart_font(11)
    small_font = chart_font(10)
    draw.text((left, 15), title, fill="#17324D", font=title_font)
    draw.text((left, 40), subtitle, fill="#555555", font=small_font)

    all_values = [value for _, _, points in series for _, value in points]
    if not all_values:
        return
    spread = max(0.5, max(all_values) - min(all_values))
    y_min = min(all_values) - spread * 0.2
    y_max = max(all_values) + spread * 0.2
    labels = [label for label, _ in series[0][2]]
    n = max(1, len(labels) - 1)
    plot_width = width - left - right
    plot_height = height - top - bottom

    def point(index: int, value: float) -> tuple[float, float]:
        x = left + index * plot_width / n
        y = top + (y_max - value) * plot_height / (y_max - y_min)
        return x, y

    tick_step = max(0.5, round((y_max - y_min) / 5 * 2) / 2)
    tick = y_min
    while tick <= y_max:
        y = point(0, tick)[1]
        if top <= y <= height - bottom:
            draw.line((left, y, width - right, y), fill="#D6D6D6", width=1)
            draw.text((6, y - 6), f"{tick:.1f}", fill="#666666", font=small_font)
        tick += tick_step

    for index, label in enumerate(labels):
        x = point(index, y_min)[0]
        draw.text((x - 10, height - bottom + 8), label, fill="#666666", font=small_font)

    colors = ["#17324D", "#8A2D3C"]
    legend_x = left
    for order, (name, _, points) in enumerate(series):
        color = colors[order % len(colors)]
        pts = [point(i, value) for i, (_, value) in enumerate(points)]
        draw.line(pts, fill=color, width=3, joint="curve")
        last_x, last_y = pts[-1]
        draw.ellipse((last_x - 4, last_y - 4, last_x + 4, last_y + 4), fill=color)
        draw.text((last_x - 26, last_y + (6 if order else -16)),
                  f"{points[-1][1]:.2f}", fill=color, font=label_font)
        draw.rectangle((legend_x, 60, legend_x + 14, 70), fill=color)
        draw.text((legend_x + 18, 59), name, fill="#444444", font=small_font)
        legend_x += 20 + int(draw.textlength(name, font=small_font)) + 18

    draw.text((left, height - 16), footer, fill="#777777", font=small_font)
    path.parent.mkdir(exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def _parse_sheet_csv(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.reader(text.splitlines()))


def sheet_chart_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the Walmart basket chart directly from the shared Google Sheet.

    The chart is redrawn from live data each run; a content signature drives the
    'feature once when the numbers change' behaviour, so no local file mtimes or
    manual PNG exports are involved.
    """
    spec = config.get("walmart_sheet")
    if not spec or not spec.get("csv_url"):
        return []
    chart_path = OUTPUT / "walmart_sheet.png"
    try:
        rows = _parse_sheet_csv(fetch(spec["csv_url"]))
    except Exception:
        return []

    # Locate the header row and the columns we need by name.
    header_idx = next(
        (i for i, r in enumerate(rows)
         if any(c.strip().lower() == "date" for c in r)),
        None,
    )
    if header_idx is None:
        return []
    header = [c.strip() for c in rows[header_idx]]

    def col(*names: str) -> int | None:
        for name in names:
            for j, c in enumerate(header):
                if c.lower() == name.lower():
                    return j
        return None

    date_c = col("Date")
    basket_c = col("Walmart Index")
    official_c = col("US Official Index")
    if date_c is None or basket_c is None:
        return []

    basket: list[tuple[str, float]] = []
    official: list[tuple[str, float]] = []
    for r in rows[header_idx + 1:]:
        if len(r) <= date_c or not r[date_c].strip():
            continue
        label = r[date_c].strip()[:3]  # "January 2026" -> "Jan"
        def num(j: int | None) -> float | None:
            if j is None or len(r) <= j:
                return None
            cell = r[j].replace("$", "").replace(",", "").replace("%", "").strip()
            try:
                return float(cell)
            except ValueError:
                return None
        b = num(basket_c)
        if b is None:
            continue
        basket.append((label, b))
        o = num(official_c)
        if o is not None:
            official.append((label, o))

    if len(basket) < 2:
        return []

    signature = hashlib.sha256(
        json.dumps(basket + official, separators=(",", ":")).encode()
    ).hexdigest()

    series = [("Walmart basket (Irving, TX)", "#17324D", basket)]
    if len(official) >= 2:
        series.append(("US official CPI (normalized)", "#8A2D3C", official))

    latest = basket[-1][1]
    prior = basket[-2][1]
    direction = "rose from" if latest > prior else "eased from" if latest < prior else "was unchanged from"
    explanation = (
        f"The tracked Walmart basket index stood at {latest:.2f} "
        f"(Jan 2026 = 100) in {basket[-1][0]}; the index {direction} {prior:.2f} the month before."
    )
    if len(official) >= 2:
        gap = latest - official[-1][1]
        cmp_word = "below" if gap < 0 else "above" if gap > 0 else "level with"
        explanation += (
            f" That leaves the basket running {abs(gap):.2f} points {cmp_word} the "
            "normalized official CPI over the same window."
        )

    draw_dual_line_chart(
        chart_path, series,
        title=spec.get("title", "Walmart Basket Price Index"),
        subtitle="Index, Jan 2026 = 100",
        footer="Source: personal Walmart basket tracker (Irving, TX) + BLS CPI via FRED",
    )
    return [{
        "id": "walmart_sheet",
        "title": spec.get("title", "Walmart Basket Price Index"),
        "image_path": str(chart_path),
        "trigger_path": str(chart_path),
        "caption": "Monthly movement in the tracked Walmart shopping basket.",
        "explanation": explanation,
        "source": "Walmart Inflation Tracker (personal)",
        "source_url": spec.get("source_url", ""),
        "priority": int(spec.get("priority", 20)),
        "signature": signature,
    }]


def draw_multi_line_chart(path: Path, series: list[tuple[str, list[tuple[dt.date, float]]]],
                          title: str, subtitle: str, footer: str,
                          unit: str = "$") -> None:
    """Draw N labelled dollar-valued lines over a multi-year monthly x-axis."""
    width, height = 600, 340
    left, top, right, bottom = 64, 92, 18, 48
    image = Image.new("RGB", (width, height), "#FAF7F0")
    draw = ImageDraw.Draw(image)
    title_font = chart_font(20, bold=True)
    small_font = chart_font(10)
    draw.text((left, 15), title, fill="#17324D", font=title_font)
    draw.text((left, 40), subtitle, fill="#555555", font=small_font)

    palette = ["#17324D", "#8A2D3C", "#2E6E4E", "#B0792C", "#5B4B8A", "#447099"]
    all_points = [p for _, pts in series for p in pts]
    if not all_points:
        return
    values = [v for _, v in all_points]
    dates = [d for d, _ in all_points]
    spread = max(1.0, max(values) - min(values))
    y_min = min(values) - spread * 0.1
    y_max = max(values) + spread * 0.1
    d_min, d_max = min(dates), max(dates)
    span_days = max(1, (d_max - d_min).days)
    plot_width = width - left - right
    plot_height = height - top - bottom

    def point(d: dt.date, value: float) -> tuple[float, float]:
        x = left + (d - d_min).days / span_days * plot_width
        y = top + (y_max - value) * plot_height / (y_max - y_min)
        return x, y

    def money(v: float) -> str:
        return f"${v/1000:.0f}k" if unit == "$" else f"{v:.1f}{unit}"

    for frac in range(0, 6):
        v = y_min + (y_max - y_min) * frac / 5
        y = top + (y_max - v) * plot_height / (y_max - y_min)
        draw.line((left, y, width - right, y), fill="#D6D6D6", width=1)
        draw.text((6, y - 6), money(v), fill="#666666", font=small_font)

    year_step = 2 if (d_max.year - d_min.year) > 6 else 1
    for year in range(d_min.year + 1, d_max.year + 1, year_step):
        d = dt.date(year, 1, 1)
        if d_min <= d <= d_max:
            x = point(d, y_min)[0]
            draw.text((x - 11, height - bottom + 8), str(year), fill="#666666", font=small_font)

    legend_x = left
    for order, (name, pts) in enumerate(series):
        color = palette[order % len(palette)]
        line = [point(d, v) for d, v in pts]
        draw.line(line, fill=color, width=3, joint="curve")
        last_x, last_y = line[-1]
        draw.ellipse((last_x - 4, last_y - 4, last_x + 4, last_y + 4), fill=color)
        draw.rectangle((legend_x, 62, legend_x + 14, 72), fill=color)
        draw.text((legend_x + 18, 61), name, fill="#444444", font=small_font)
        legend_x += 20 + int(draw.textlength(name, font=small_font)) + 18
        if legend_x > width - 90:           # wrap the legend onto a second row
            legend_x = left
    draw.text((left, height - 14), footer, fill="#777777", font=small_font)
    path.parent.mkdir(exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def zillow_chart_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the Texas-cities home-price chart from Zillow's public ZHVI CSV.

    Streams the (large) city-level file, keeps only the configured cities in the
    configured state, and redraws a 10-year line per city. Any failure (e.g.
    Zillow moved the download path) simply yields no chart.
    """
    spec = config.get("zillow")
    if not spec or not spec.get("csv_url"):
        return []
    targets = {c.lower() for c in spec.get("cities", [])}
    state = spec.get("state", "TX")
    years = int(spec.get("years", 10))
    if not targets:
        return []

    try:
        text = fetch(spec["csv_url"]).decode("utf-8-sig", errors="replace")
    except Exception:
        return []
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        return []
    idx = {name: i for i, name in enumerate(header)}
    date_cols = [(i, dt.date.fromisoformat(name))
                 for i, name in enumerate(header)
                 if re.fullmatch(r"\d{4}-\d{2}-\d{2}", name)]
    if not date_cols or "RegionName" not in idx or "State" not in idx:
        return []
    latest_date = date_cols[-1][1]
    cutoff = latest_date.replace(year=latest_date.year - years)

    found: dict[str, list[tuple[dt.date, float]]] = {}
    for row in reader:
        if len(row) <= idx["State"]:
            continue
        if row[idx["State"]].strip() != state:
            continue
        name = row[idx["RegionName"]].strip()
        if name.lower() not in targets:
            continue
        pts: list[tuple[dt.date, float]] = []
        for col, d in date_cols:
            if d < cutoff or len(row) <= col or not row[col].strip():
                continue
            try:
                pts.append((d, float(row[col])))
            except ValueError:
                continue
        if len(pts) >= 2:
            found[name] = pts

    if not found:
        return []
    # Preserve the configured city order; only include cities actually found.
    ordered = [(c, found[c]) for c in spec.get("cities", []) if c in found]
    signature = hashlib.sha256(
        json.dumps({c: [(d.isoformat(), round(v, 1)) for d, v in p] for c, p in ordered},
                   separators=(",", ":")).encode()
    ).hexdigest()

    chart_path = OUTPUT / "zillow_texas.png"
    draw_multi_line_chart(
        chart_path, ordered,
        title=spec.get("title", "Texas Home Prices: Selected Cities"),
        subtitle=f"Zillow Home Value Index, last {years} years",
        footer="Source: Zillow Research (ZHVI, mid-tier, smoothed & seasonally adjusted)",
    )
    newest = max((p[-1] for _, p in ordered), key=lambda x: x[0])
    explanation = (
        "Typical home values across "
        + ", ".join(c for c, _ in ordered)
        + f", on Zillow's Home Value Index through {newest[0].strftime('%B %Y')}. "
        "The chart shows where local housing momentum is strengthening, cooling, or diverging."
    )
    return [{
        "id": "zillow_texas",
        "title": spec.get("title", "Texas Home Prices: Selected Cities"),
        "image_path": str(chart_path),
        "trigger_path": str(chart_path),
        "caption": "Ten-year Zillow Home Value Index trends for selected Texas cities.",
        "explanation": explanation,
        "source": "Zillow Research",
        "source_url": spec.get("source_url", "https://www.zillow.com/research/data/"),
        "priority": int(spec.get("priority", 15)),
        "signature": signature,
    }]


def select_chart_of_the_day(config: dict[str, Any]) -> dict[str, Any] | None:
    state = load_chart_state()
    candidates: list[dict[str, Any]] = []
    sources = [{**source, "priority": source.get("priority", 100)}
               for source in config.get("chart_sources", [])]
    sources.extend(fred_chart_sources())
    sources.extend(sheet_chart_sources(config))
    sources.extend(zillow_chart_sources(config))
    for source in sources:
        # Content-signature charts (sheet/FRED in the cloud) feature once per
        # data change and do not rely on local file modification times.
        signature = source.get("signature")
        if signature is not None:
            if not Path(source["image_path"]).is_file():
                continue
            if state.get(source["id"], {}).get("featured_signature") == signature:
                continue
            now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
            candidates.append({
                **source,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "updated_mtime": now_ts,
                "image_mtime": now_ts,
            })
            continue

        image_path = Path(source["image_path"])
        trigger_path = Path(source.get("trigger_path", source["image_path"]))
        if not image_path.is_file() or not trigger_path.exists():
            continue
        image_mtime = image_path.stat().st_mtime
        trigger_mtime = trigger_path.stat().st_mtime
        if trigger_path != image_path and image_mtime < trigger_mtime:
            continue
        updated_at = max(image_mtime, trigger_mtime)
        last_featured = float(state.get(source["id"], {}).get("featured_mtime", 0))
        if updated_at <= last_featured:
            continue
        candidates.append({
            **source,
            "updated_at": dt.datetime.fromtimestamp(updated_at, dt.timezone.utc).isoformat(),
            "updated_mtime": updated_at,
            "image_mtime": image_mtime,
        })
    return max(
        candidates,
        key=lambda item: (item.get("priority", 0), item["updated_mtime"]),
    ) if candidates else None


def mark_chart_featured(chart: dict[str, Any] | None) -> None:
    if not chart:
        return
    state = load_chart_state()
    entry = {
        "featured_mtime": chart["updated_mtime"],
        "featured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if chart.get("signature") is not None:
        entry["featured_signature"] = chart["signature"]
    state[chart["id"]] = entry
    CHART_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def story_html(story: Story, number: int | None = None, show_image: bool = False) -> str:
    label = f"{number}. " if number else ""
    visual = ""
    if show_image and story.image_url:
        visual = (
            f'<p><a href="{esc(story.link)}"><img src="{esc(story.image_url)}" width="640" '
            f'style="max-width:100%;height:auto" alt="{esc(story.image_alt)}"></a>'
            f'<br><small>Source visual: {esc(story.source)}</small></p>'
        )
    return f"""
      <h3>{label}<a href="{esc(story.link)}">{esc(story.title)}</a></h3>
      {visual}
      <p>{esc(story.summary or story.description or story.title)}</p>
      <blockquote><strong>Why it matters:</strong> {esc(story.why or "Selected for impact and relevance.")}</blockquote>
      <p><small><strong>{esc(story.source)}</strong> · <a href="{esc(story.link)}">Read original →</a></small></p>
      <hr>"""


def leader_html(post: Story, number: int, timezone: str) -> str:
    visual = ""
    if post.image_url:
        visual = (
            f'<p><a href="{esc(post.link)}"><img src="{esc(post.image_url)}" width="560" '
            f'style="max-width:100%;height:auto" alt="{esc(post.image_alt or "Visual attached to the post")}"></a></p>'
        )
    time_label = ""
    if post.published:
        local = post.published.astimezone(ZoneInfo(timezone))
        time_label = local.strftime("%#I:%M %p, %B %#d" if os.name == "nt" else "%-I:%M %p, %B %-d")
    via_label = {
        "X": "Post on X",
        "own publication": "New publication",
        "press coverage": "In the news (direct post access unavailable)",
    }.get(post.via, "Public post")
    return f"""
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="6" bgcolor="#EDE6D6">
      <tr><td>
        <font face="Arial, sans-serif" color="#6B5310" size="2"><strong>&#9733; THOUGHT LEADERS MONITOR · {esc(via_label.upper())}</strong></font>
      </td></tr>
      </table>
      <h3>{number}. <a href="{esc(post.link)}">{esc(post.source)}</a></h3>
      <blockquote>{esc(post.summary or post.title)}</blockquote>
      {visual}
      <p><small>{esc(time_label)}{" · " if time_label else ""}<a href="{esc(post.link)}">View original →</a>
      · <a href="{esc(post.link if post.via == "X" else "https://x.com/" + post.source.split("(@")[-1].rstrip(")"))}">Profile on X</a></small></p>
      <hr>"""


def section_html(title: str, content: str, empty_message: str = "") -> str:
    body = content or f"<p><em>{esc(empty_message)}</em></p>"
    return f"""
    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
      <tr>
        <td bgcolor="#17324D" align="left">
          <font face="Arial, sans-serif" color="#FFFFFF" size="4">
            <strong>&nbsp; {esc(title)}</strong>
          </font>
        </td>
      </tr>
    </table>
    {body}"""


def render(config: dict[str, Any], now: dt.datetime, weather_rows: list[dict[str, Any]],
           top: list[Story], leader_post: Story | None, leader_notes: list[str],
           research: list[Story], chart_of_day: dict[str, Any] | None,
           errors: list[str]) -> str:
    date_label = (
        now.strftime("%B %-d, %Y, %A")
        if os.name != "nt"
        else now.strftime("%B %#d, %Y, %A")
    )
    chart_url = weather_chart_url(weather_rows)
    unavailable = "; ".join(errors[:6])
    source_note = f"<p><small><strong>Source notes:</strong> {esc(unavailable)}</small></p>" if unavailable else ""

    # Top News: insert the thought-leader item among the numbered stories.
    leader_position = min(3, len(top))
    items_html: list[str] = []
    number = 0
    for index, story in enumerate(top):
        if leader_post and index == leader_position:
            number += 1
            items_html.append(leader_html(leader_post, number, config["timezone"]))
        number += 1
        items_html.append(story_html(story, number, show_image=(
            index < 2 or (story.source in {"Financial Times", "The Economist"} and bool(story.image_url))
        )))
    if leader_post and leader_position >= len(top):
        number += 1
        items_html.append(leader_html(leader_post, number, config["timezone"]))
    if not leader_post and leader_notes:
        items_html.append(
            "<p><small><em>Thought Leaders Monitor: "
            + esc(" ".join(leader_notes))
            + " Direct X retrieval is limited without API access; this is reported "
            "rather than substituted with unverified content.</em></small></p>"
        )
    top_html = "".join(items_html)

    research_html = "".join(story_html(s, show_image=True) for s in research)

    weather_cells = []
    for row in weather_rows[:2]:
        weather_cells.append(f"""
        <td width="50%" bgcolor="#EDF3F7" valign="top">
          <font face="Arial, sans-serif" color="#17324D">
            <strong>{esc(row['city'])}</strong><br>
            <font size="6"><strong>{row['current']}°</strong></font><br>
            {esc(row.get('conditions', ''))}<br>
            H {row['high']}° · L {row['low']}° · Rain {row['rain']}%
          </font>
        </td>""")
    weather_table = f"""
      <table role="presentation" width="100%" border="0" cellspacing="4" cellpadding="10" bgcolor="#DCE7EE">
      <tr>{''.join(weather_cells)}</tr>
      </table>
      {f'''<p align="center"><img src="{esc(chart_url)}" width="480" style="max-width:100%;height:auto"
        alt="Line chart comparing today's forecast temperatures in Irving and Dallas, Texas"></p>''' if chart_url else ''}"""

    chart_html = ""
    if chart_of_day:
        updated = dt.datetime.fromisoformat(chart_of_day["updated_at"]).astimezone(
            ZoneInfo(config["timezone"])
        )
        updated_label = updated.strftime("%B %#d, %Y") if os.name == "nt" else updated.strftime("%B %-d, %Y")
        chart_html = f'''
          <h3>{esc(chart_of_day["title"])}</h3>
          <p align="center"><img src="cid:chart-of-the-day" width="600" style="max-width:100%;height:auto"
             alt="{esc(chart_of_day["title"])}"></p>
          <p>{esc(chart_of_day.get("explanation") or chart_of_day["caption"])}</p>
          <p><small><strong>Source:</strong> {esc(chart_of_day["source"])}
          {f'· <a href="{esc(chart_of_day["source_url"])}">View source</a>' if chart_of_day.get("source_url") else ''}
          · Updated {esc(updated_label)}</small></p>'''

    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body bgcolor="#E7EDF2">
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="8" bgcolor="#E7EDF2">
<tr><td align="center">
  <table role="presentation" width="680" border="0" cellspacing="0" cellpadding="0" bgcolor="#17324D" style="max-width:100%">
  <tr><td>
    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="18" bgcolor="#FAF7F0">
    <tr><td>
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="12" bgcolor="#17324D">
      <tr><td align="center">
        <font face="Georgia, Times New Roman, serif" color="#FFFFFF" size="6">
          <strong>{esc(config['newsletter_name'])}</strong>
        </font><br>
        <font face="Arial, sans-serif" color="#DDE7EF" size="2">
          <strong>{esc(date_label)} &nbsp;·&nbsp; MORNING EDITION</strong>
        </font>
      </td></tr>
      </table>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="7" bgcolor="#8A2D3C">
      <tr><td align="center">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2">
          WEATHER &nbsp;·&nbsp; TOP NEWS &nbsp;·&nbsp; RESEARCH RADAR &nbsp;·&nbsp; CHART OF THE DAY
        </font>
      </td></tr>
      </table>

      <h2>Good morning</h2>
      <p>Your high-signal briefing for today. The most consequential items come first.</p>

      {section_html("1 · Weather Snapshot", weather_table)}
      {section_html("2 · Top News", top_html, "No qualifying stories were available in this run.")}
      {section_html("3 · Research Radar", research_html, "No qualifying research items were available in this run.")}
      {section_html("4 · Chart of the Day", chart_html, "No newly updated chart today; the next release of the Walmart tracker, Zillow data, GDP, or CPI will appear here.")}
      {source_note}

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="10" bgcolor="#17324D">
      <tr><td align="center">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2">
          <strong>ORHAN'S MORNING INTELLIGENCE</strong> &nbsp;·&nbsp; A PERSONAL FIVE-MINUTE BRIEFING
        </font>
      </td></tr>
      </table>
    </td></tr>
    </table>
  </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def send_email(config: dict[str, Any], subject: str, body: str) -> None:
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    configured = config.get("recipients") or ["orhanerdem@gmail.com"]
    override = os.getenv("OMI_RECIPIENTS")
    recipients = [address.strip() for address in override.split(",")] if override else configured
    recipients = [address for address in recipients if address]
    if not user or not password:
        raise RuntimeError("Set GMAIL_USER and GMAIL_APP_PASSWORD to enable SMTP delivery.")
    msg = EmailMessage()
    msg["From"] = f"Orhan's Morning Intelligence <{user}>"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content("Orhan's Morning Intelligence is best viewed as HTML.")
    msg.add_alternative(body, subtype="html")
    chart = select_chart_of_the_day(config)
    if chart and "cid:chart-of-the-day" in body:
        image_path = Path(chart["image_path"])
        subtype = image_path.suffix.lower().lstrip(".")
        if subtype == "jpg":
            subtype = "jpeg"
        msg.get_payload()[-1].add_related(
            image_path.read_bytes(),
            maintype="image",
            subtype=subtype or "png",
            cid="<chart-of-the-day>",
            filename=image_path.name,
            disposition="inline",
        )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg, to_addrs=recipients)
    if os.getenv("OMI_PRESERVE_CHART_STATE", "").lower() not in {"1", "true", "yes"}:
        mark_chart_featured(chart)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(no_ai: bool = False) -> tuple[Path, str, dict[str, Any]]:
    config = load_config()
    tz = ZoneInfo(config["timezone"])
    now = dt.datetime.now(tz)
    errors: list[str] = []

    weather_rows = []
    for location in config.get("weather_locations", []):
        city = location["city"]
        try:
            weather_rows.append(weather(city, location["latitude"], location["longitude"], config["timezone"]))
        except Exception as exc:
            errors.append(f"Weather {city}: {type(exc).__name__}")
            weather_rows.append({"city": city, "current": "–", "high": "–", "low": "–",
                                 "rain": "–", "conditions": "Unavailable"})

    news = recent(deduplicate(collect(NEWS_FEEDS, errors)), now, config["lookback_hours"])
    ft_items = recent(deduplicate(collect([("Financial Times", config["ft_feed"])], errors)), now, 48)
    economist_items = recent(deduplicate(collect(ECONOMIST_FEEDS, errors)), now, 48)
    research_pool = recent(deduplicate(collect(RESEARCH_FEEDS, errors)), now, 72)
    for group in (news, ft_items, economist_items, research_pool):
        for item in group:
            item.score = rank(item, now)
        group.sort(key=lambda x: x.score, reverse=True)

    news_candidates = deduplicate(
        select_diverse(news, 16, per_category=4, per_source=2)
        + select_diverse(ft_items + economist_items, 6, per_category=6, per_source=3)
    )
    news_candidates.sort(key=lambda x: x.score, reverse=True)
    research_candidates = select_diverse(research_pool, 10, per_category=4, per_source=2)
    for item in research_candidates:
        item.kind = "research"
    leader_candidates, leader_notes = collect_thought_leaders(config, now, errors)

    if no_ai:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    top, leader_post, research_pick = claude_curate(
        news_candidates, leader_candidates, research_candidates, config, errors,
    )
    research_items = [research_pick] if research_pick else []

    total_items = len(top) + (1 if leader_post else 0)
    if total_items > 10:
        top = top[:10 - (1 if leader_post else 0)]

    chart_of_day = select_chart_of_the_day(config)
    body = render(config, now, weather_rows, top, leader_post, leader_notes,
                  research_items, chart_of_day, errors)
    OUTPUT.mkdir(exist_ok=True)
    dated = OUTPUT / f"omi_{now:%Y-%m-%d}.html"
    latest = OUTPUT / "latest.html"
    dated.write_text(body, encoding="utf-8")
    latest.write_text(body, encoding="utf-8")
    manifest = {
        "generated_at": now.isoformat(),
        "top_count": len(top),
        "leader_included": bool(leader_post),
        "leader_notes": leader_notes,
        "research_count": len(research_items),
        "total_item_count": total_items,
        "chart_of_the_day": chart_of_day,
        "errors": errors,
        "stories": [
            asdict(s) | {"published": s.published.isoformat() if s.published else None}
            for s in top + ([leader_post] if leader_post else []) + research_items
        ],
    }
    (OUTPUT / "latest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    date_label = (
        now.strftime("%B %#d, %Y")
        if os.name == "nt"
        else now.strftime("%B %-d, %Y")
    )
    return dated, f"{config['newsletter_name']} | {date_label}", manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and deliver Orhan's Morning Intelligence.")
    parser.add_argument("--no-send", action="store_true", help="Generate files without sending email.")
    parser.add_argument("--no-ai", action="store_true", help="Use feed descriptions instead of Claude summaries.")
    args = parser.parse_args()
    path, subject, manifest = build(no_ai=args.no_ai)
    body = path.read_text(encoding="utf-8")
    print(json.dumps({
        "subject": subject,
        "html": str(path),
        **{k: manifest[k] for k in (
            "top_count", "leader_included", "research_count", "total_item_count", "errors"
        )},
    }, indent=2))
    if not args.no_send:
        send_email(load_config(), subject, body)
        print("Email sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
