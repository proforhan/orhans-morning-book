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
SEEN_STATE = OUTPUT / "seen_links.json"
SEEN_LEDGER_DAYS = 3
USER_AGENT = "OrhanMorningIntelligence/2.0 (+personal research newsletter)"

TOPIC_WEIGHTS = {
    "artificial intelligence": 7, " ai ": 6, "machine learning": 7,
    "large language model": 7, "openai": 6, "anthropic": 6, "nvidia": 6,
    "economy": 8, "economic": 8, "inflation": 8, "federal reserve": 8,
    "interest rate": 8, "market": 6, "trade": 6, "technology": 6,
    "microsoft": 5, "google": 5, "apple": 5, "meta": 5, "amazon": 5,
    "science": 7, "research": 7, "study": 7, "arxiv": 7,
    "medicine": 8, "health": 7, "clinical": 8, "cancer": 8, "drug": 7,
    "world cup": 6, "football": 4, "soccer": 5,
    "politics": 6, "congress": 6, "senate": 6, "white house": 7,
    "president": 5, "election": 7, "legislation": 6,
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
    ("Google News: Politics", "https://news.google.com/rss/search?q=US+politics+congress+government+senate+when:1d&hl=en-US&gl=US&ceid=US:en"),
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
    via: str = ""        # e.g. "own publication", "press coverage"


def load_config() -> dict[str, Any]:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_seen_links() -> dict[str, str]:
    """Links featured in recent editions, pruned to the last SEEN_LEDGER_DAYS."""
    if not SEEN_STATE.exists():
        return {}
    try:
        data = json.loads(SEEN_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=SEEN_LEDGER_DAYS)).date()
    kept: dict[str, str] = {}
    for link, seen_on in data.items():
        try:
            if dt.date.fromisoformat(seen_on) >= cutoff:
                kept[link] = seen_on
        except (TypeError, ValueError):
            continue
    return kept


def record_seen_links(links: list[str]) -> None:
    """Append today's featured links to the ledger (idempotent, pruned)."""
    seen = load_seen_links()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for link in links:
        if link:
            seen[link] = today
    SEEN_STATE.parent.mkdir(exist_ok=True)
    SEEN_STATE.write_text(json.dumps(seen, indent=2), encoding="utf-8")


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
    if any(x in text for x in ("artificial intelligence", " ai ", " ai.", " ai,",
                               "machine learning", "llm", "openai", "anthropic",
                               "chatgpt", "gpt-", "gemini", "nvidia", "chatbot",
                               "generative ai", "neural network", "deepmind",
                               "technology", "software", "semiconductor", "chip",
                               "microsoft", "google", "apple", "meta", "amazon")):
        return "tech"
    if any(x in text for x in ("election", "congress", "senate", "white house",
                               "president", "parliament", "government", "policy",
                               "diplomat", "sanction", "politics", "legislation")):
        return "politics"
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


# Categories that must appear at least once in the final Top News selection
# when a qualifying candidate exists, mirroring the AI/tech hard cap above but
# as a floor instead of a ceiling. Both topics tend to be under-weighted by
# TOPIC_WEIGHTS and actively discouraged by the curation prompt's "avoid
# low-impact political commentary" guidance, so they need an explicit backstop
# or they can vanish from the newsletter entirely on a given day.
FLOOR_CATEGORIES = ("politics", "football")


def enforce_category_floor(top: list[Story], pool: list[Story]) -> list[Story]:
    """Guarantee at least one story per FLOOR_CATEGORIES in `top`.

    If Claude's curation (or the heuristic fallback) didn't already include a
    qualifying item, the best-scoring eligible candidate is pulled from `pool`
    (the same candidate set the editor saw) and swapped in for the
    lowest-scoring item that isn't itself filling another floor slot. Categories
    with no eligible candidate in `pool` at all are left alone -- the floor
    never invents coverage that doesn't exist that day.
    """
    result = list(top)
    used_links = {s.link for s in result}
    for cat in FLOOR_CATEGORIES:
        if any(category(s) == cat for s in result):
            continue
        candidate = next(
            (s for s in sorted(pool, key=lambda x: x.score, reverse=True)
             if category(s) == cat and s.link not in used_links),
            None,
        )
        if candidate is None:
            continue
        heuristic_text(candidate)
        evictable = [i for i, s in enumerate(result) if category(s) not in FLOOR_CATEGORIES]
        if not evictable:
            result.append(candidate)
        else:
            worst = min(evictable, key=lambda i: result[i].score)
            result[worst] = candidate
        used_links.add(candidate.link)
    return result


# ---------------------------------------------------------------------------
# Thought Leaders Monitor
# ---------------------------------------------------------------------------

def collect_thought_leaders(config: dict[str, Any], now: dt.datetime,
                            errors: list[str]) -> tuple[list[Story], list[str]]:
    """Best recent public item per configured leader, plus availability notes.

    Source priority per leader:
      1. The leader's own publication feeds (Substack, CFR blog, ...).
      2. Google News coverage of the leader, clearly labelled as coverage.
    """
    cutoff = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=26)
    candidates: list[Story] = []
    notes: list[str] = []
    for leader in config.get("thought_leaders", []):
        handle = leader.get("handle", "")
        name = leader.get("name", handle)
        leader_posts: list[Story] = []

        # 1. Own publications (Substack, blogs).
        if True:
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

        # 2. Press coverage as a clearly-labelled fallback.
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
                    6 if post.via == "own publication" else 0
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
) -> tuple[list[Story], Story | None, Story | None, str]:
    """Single Claude call: select, rank, and write summaries for all sections."""
    top_n = int(config.get("top_news_items", 8))

    def fallback() -> tuple[list[Story], Story | None, Story | None, str]:
        top = select_diverse(news_candidates, top_n)
        for story in top:
            heuristic_text(story)
        leader = leader_candidates[0] if leader_candidates else None
        if leader:
            leader.summary = leader.summary or leader.title
        research = research_candidates[0] if research_candidates else None
        if research:
            heuristic_text(research)
        return top, leader, research, ""

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
        "You are the editor of '" + config['newsletter_name'] + "', a concise daily briefing for a "
        "university professor interested in AI, economics, finance, technology, science, academic "
        "research, medicine, politics, and the football World Cup. Rank by Impact x Novelty x "
        "Relevance, weighting relevance heavily toward AI, economics, finance, academic research, "
        "medicine, and significant political developments. Avoid celebrity news, entertainment, "
        "frivolous or low-impact political commentary, "
        "investment-promotion content, and duplicate coverage of the same underlying story.\n\n"
        f"From news_candidates choose exactly {top_n} items (fewer only if the pool is smaller), "
        "ordered most consequential first. Deliberately spread coverage across topics: include no more than 2 AI/tech items, and make sure economics/finance, medicine/health, and academic research each appear when qualifying candidates exist. Also include at least one substantive politics/government/policy item and one football/World Cup item whenever a qualifying candidate exists -- 'substantive' means real policy, elections, or major geopolitical developments, not gossip or opinion-column speculation. For each "
        "write 'summary' (2-3 short factual sentences strictly grounded in the supplied metadata; "
        "no hype, no invented facts) and 'why' (one short sentence on why it matters to this "
        "reader).\n\n"
        "From thought_leader_posts choose the single most notable post (or null if empty) and "
        "write a 1-2 sentence 'summary'.\n\n"
        "From research_candidates choose the single most interesting genuine research item (a "
        "paper, study, or peer-reviewed finding - not general news; null if none qualify) and "
        "write 'summary' (a one-sentence statement of the finding) and 'why' (one sentence).\n\n"
        "Also write 'tldr': a single punchy sentence (max ~22 words) summarising the most "
        "important thing the reader should take from today's edition, grounded in the chosen items.\n\n"
        "Return ONLY valid JSON, no markdown fences, in this exact shape:\n"
        '{"tldr": "...", "top": [{"id": 0, "summary": "...", "why": "..."}], '
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
        tldr = clean_text(reply.get("tldr")) if isinstance(reply.get("tldr"), str) else ""
        return top, leader, research, tldr
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


# Charts are rendered at CHART_SCALE x the logical size so they stay crisp on
# high-DPI / Retina screens, then displayed at the original CSS width in email.
CHART_SCALE = 3


class ScaledDraw:
    """Wraps PIL ImageDraw so logical coordinates render at CHART_SCALE x."""

    def __init__(self, image: Image.Image, scale: int = CHART_SCALE) -> None:
        self._d = ImageDraw.Draw(image)
        self.scale = scale

    def _mul(self, xy):
        s = self.scale
        if isinstance(xy, (list, tuple)) and xy and isinstance(xy[0], (list, tuple)):
            return [(p[0] * s, p[1] * s) for p in xy]
        return tuple(v * s for v in xy)

    def text(self, xy, *args, **kwargs):
        self._d.text(self._mul(xy), *args, **kwargs)

    def line(self, xy, *args, width=1, **kwargs):
        self._d.line(self._mul(xy), *args, width=int(width * self.scale), **kwargs)

    def ellipse(self, xy, *args, **kwargs):
        self._d.ellipse(self._mul(xy), *args, **kwargs)

    def rectangle(self, xy, *args, **kwargs):
        self._d.rectangle(self._mul(xy), *args, **kwargs)

    def textlength(self, text, *args, **kwargs):
        return self._d.textlength(text, *args, **kwargs) / self.scale


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
    scaled = int(size * CHART_SCALE)
    for path in candidates:
        try:
            return ImageFont.truetype(path, scaled)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=scaled)
    except TypeError:
        return ImageFont.load_default()


def fred_observations(series_id: str, start: str) -> list[tuple[dt.date, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    rows = list(csv.DictReader(fetch(url, timeout=45).decode("utf-8-sig").splitlines()))
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
    image = Image.new("RGB", (width * CHART_SCALE, height * CHART_SCALE), "#FAF7F0")
    draw = ScaledDraw(image)
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
        else latest_date.strftime("%B %Y") if (yoy_lag or series_id == "UNRATE") else latest_date.strftime("%B %#d, %Y" if os.name == "nt" else "%B %-d, %Y")
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
        # Content signature: on ephemeral runners file mtimes are fresh every
        # run, so featuring once per data release must key on the data itself.
        "signature": metadata["data_signature"],
    }




def build_global_inflation_chart(now: dt.datetime) -> dict[str, Any] | None:
    """Compare year-over-year CPI inflation across major economies, monthly.

    Pulls monthly consumer-price index levels for the U.S., euro area, and
    UK from FRED (all reported monthly, unlike the World Bank's annual
    aggregate), derives year-over-year inflation for each, and plots them
    together so the reader can see how price pressure compares across
    regions month to month. Any single country's data being unavailable
    just drops that line; the chart still renders as long as at least two
    economies have usable data, so a temporary outage at one source doesn't
    blank the whole section.
    """
    chart_id = "global_inflation_comparison"
    chart_path = OUTPUT / f"{chart_id}.png"
    metadata_path = OUTPUT / f"{chart_id}.json"
    start = f"{now.year - 12}-01-01"
    plot_cutoff = dt.date(now.year - 5, 1, 1)
    countries = [
        ("United States", "CPIAUCSL"),
        ("Euro Area", "CP0000EZ19M086NEST"),
        ("United Kingdom", "GBRCPIALLMINMEI"),
    ]
    lines: list[tuple[str, list[tuple[dt.date, float]]]] = []
    latest_by_country: dict[str, tuple[dt.date, float, float]] = {}
    for name, series_id in countries:
        try:
            observations = fred_observations(series_id, start)
        except Exception:
            continue
        if len(observations) < 13:
            continue
        yoy = [
            (observations[i][0], (observations[i][1] / observations[i - 12][1] - 1) * 100)
            for i in range(12, len(observations))
        ]
        recent_points = [(d, v) for d, v in yoy if d >= plot_cutoff]
        if len(recent_points) < 6:
            continue
        lines.append((name, recent_points))
        latest_by_country[name] = (recent_points[-1][0], recent_points[-1][1], recent_points[-2][1])
    if len(lines) < 2:
        return None

    sig = hashlib.sha256(json.dumps(
        {name: [(d.isoformat(), round(v, 3)) for d, v in pts] for name, pts in lines},
        separators=(",", ":"),
    ).encode()).hexdigest()
    old_meta: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            old_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if old_meta.get("data_signature") != sig or not chart_path.exists():
        draw_multi_line_chart(
            chart_path, lines,
            title="Global Inflation Comparison",
            subtitle="Year-over-year CPI inflation, monthly, last 5 years",
            footer="Source: FRED (BLS, Eurostat, OECD)",
            unit="%",
        )
        metadata_path.write_text(json.dumps({"data_signature": sig}, indent=2), encoding="utf-8")

    latest_label = max(d for d, _, _ in latest_by_country.values()).strftime("%B %Y")
    parts = []
    for name, (_, latest, previous) in sorted(latest_by_country.items(), key=lambda kv: -kv[1][1]):
        direction = "up" if latest > previous else "down" if latest < previous else "flat"
        parts.append(f"{name} {latest:.1f}% ({direction} from {previous:.1f}%)")
    explanation = (
        f"Year-over-year consumer price inflation as of {latest_label}: " + "; ".join(parts) + ". "
        "Each line is computed directly from national statistical offices' monthly CPI/HICP levels via FRED, "
        "so the comparison updates every month rather than once a year."
    )
    return {
        "id": chart_id,
        "title": "Global Inflation Comparison",
        "image_path": str(chart_path),
        "trigger_path": str(metadata_path),
        "caption": "Year-over-year CPI inflation across major economies, monthly.",
        "explanation": explanation,
        "source": "FRED (national statistical offices)",
        "source_url": "https://fred.stlouisfed.org/release?rid=251",
        "priority": 8,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_mtime": metadata_path.stat().st_mtime if metadata_path.exists() else 0,
        "image_mtime": chart_path.stat().st_mtime if chart_path.exists() else 0,
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
             priority=12, start="2014-01-01", yoy_lag=12,
             explanation_template=(
                 "Consumer prices were {latest}% higher than a year earlier in {period}; "
                 "inflation {direction} from {previous}% the month before. This is the "
                 "headline CPI measure most directly comparable with household experience.")),
        dict(series_id="UNRATE", chart_id="fred_unemployment",
             title="U.S. Unemployment Rate Over the Last 10 Years",
             subtitle="Civilian unemployment rate, seasonally adjusted, monthly",
             caption="The share of the U.S. labor force that is unemployed and actively seeking work.",
             source="U.S. Bureau of Labor Statistics via FRED",
             source_url="https://fred.stlouisfed.org/series/UNRATE",
             priority=11, start="2014-01-01", yoy_lag=0,
             explanation_template=(
                 "The U.S. unemployment rate was {latest}% in {period}, having {direction} "
                 "from {previous}% the month before. It is one of the labor market's most "
                 "closely watched gauges and a key input to Federal Reserve policy.")),
        dict(series_id="MORTGAGE30US", chart_id="fred_mortgage_30y",
             title="30-Year Fixed Mortgage Rate Over the Last 5 Years",
             subtitle="Weekly average commitment rate, Freddie Mac survey",
             caption="The typical U.S. 30-year fixed mortgage rate.",
             source="Freddie Mac via FRED",
             source_url="https://fred.stlouisfed.org/series/MORTGAGE30US",
             priority=11, start="2019-01-01", yoy_lag=0, years_plotted=5,
             explanation_template=(
                 "The average 30-year fixed mortgage rate was {latest}% in the week of "
                 "{period}; it {direction} from {previous}% the week before. It is "
                 "the single rate that most directly sets the cost of buying a home.")),
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
    try:
        global_infl = build_global_inflation_chart(dt.datetime.now(dt.timezone.utc))
        if global_infl:
            sources.append(global_infl)
    except Exception:
        pass
    return sources


def draw_dual_line_chart(path: Path, series: list[tuple[str, str, list[tuple[str, float]]]],
                         title: str, subtitle: str, footer: str) -> None:
    """Draw up to two labelled index lines sharing one axis (matches house style)."""
    width, height = 600, 320
    left, top, right, bottom = 58, 84, 22, 50
    image = Image.new("RGB", (width * CHART_SCALE, height * CHART_SCALE), "#FAF7F0")
    draw = ScaledDraw(image)
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
    image = Image.new("RGB", (width * CHART_SCALE, height * CHART_SCALE), "#FAF7F0")
    draw = ScaledDraw(image)
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


# --- GDP per capita: rotating top-10 by world region (World Bank WDI) ---------

# World Bank 2-letter country ids grouped by continent. Aggregates (World, EU,
# OECD, etc.) are deliberately absent, so they are filtered out automatically.
_CONTINENT_CODES = {
    "Africa": "DZ AO BJ BW BF BI CV CM CF TD KM CD CG CI DJ EG GQ ER SZ ET GA GM "
              "GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL "
              "SO ZA SS SD TZ TG TN UG ZM ZW",
    "Asia": "AF AM AZ BH BD BT BN KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB "
            "MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM "
            "AE UZ VN YE",
    "Europe": "AL AD AT BY BE BA BG HR CY CZ DK EE FI FR DE GR HU IS IE IT XK LV "
              "LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB",
    "Americas": "AG AR BS BB BZ BO BR CA CL CO CR CU DM DO EC SV GD GT GY HT HN JM "
                "MX NI PA PY PE PR KN LC VC SR TT US UY VE",
    "Oceania": "AU FJ KI MH FM NR NZ PW PG WS SB TO TV VU",
}
_CONTINENT = {
    code: continent
    for continent, codes in _CONTINENT_CODES.items()
    for code in codes.split()
}


def draw_bar_chart(path: Path, items: list[tuple[str, float]], title: str,
                   subtitle: str, footer: str) -> None:
    """Horizontal top-N bar chart (e.g. dollar-valued rankings)."""
    width, left, right = 640, 168, 78
    top_pad, row_h, bottom = 78, 27, 34
    height = top_pad + len(items) * row_h + bottom
    image = Image.new("RGB", (width * CHART_SCALE, height * CHART_SCALE), "#FAF7F0")
    draw = ScaledDraw(image)
    title_font = chart_font(20, bold=True)
    label_font = chart_font(12)
    small_font = chart_font(10)
    draw.text((20, 15), title, fill="#17324D", font=title_font)
    draw.text((20, 44), subtitle, fill="#555555", font=small_font)
    max_v = max((v for _, v in items), default=1.0) or 1.0
    bar_area = width - left - right
    for i, (name, v) in enumerate(items):
        y = top_pad + i * row_h
        bar_w = max(2.0, bar_area * v / max_v)
        draw.rectangle((left, y + 3, left + bar_w, y + row_h - 6), fill="#17324D")
        label = name if len(name) <= 22 else name[:21] + "…"
        tw = draw.textlength(label, font=label_font)
        draw.text((left - 8 - tw, y + 5), label, fill="#333333", font=label_font)
        draw.text((left + bar_w + 6, y + 5), f"${v:,.0f}", fill="#8A2D3C", font=label_font)
    draw.text((20, height - 18), footer, fill="#777777", font=small_font)
    path.parent.mkdir(exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def _worldbank_latest(indicator: str, end_year: int) -> dict[str, tuple[float, int, str]]:
    """Most recent non-null value per country for a World Bank indicator."""
    url = (f"https://api.worldbank.org/v2/country/all/indicator/{indicator}"
           f"?format=json&date={end_year - 3}:{end_year}&per_page=20000")
    data = json.loads(fetch(url, timeout=40))
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return {}
    best: dict[str, tuple[float, int, str]] = {}
    for entry in data[1]:
        value = entry.get("value")
        if value is None:
            continue
        country = entry.get("country") or {}
        code = country.get("id")
        try:
            year = int(entry.get("date"))
        except (TypeError, ValueError):
            continue
        if not code:
            continue
        if code not in best or year > best[code][1]:
            best[code] = (float(value), year, country.get("value", code))
    return best


def gdp_per_capita_chart_sources(config: dict[str, Any], now: dt.datetime,
                                 state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Quarterly walk through every region's top-10 GDP-per-capita ranking.

    Once per calendar quarter the newsletter features each region in turn, one
    per day, in the configured order; after the whole set has run it goes
    dormant until the next quarter, when the queue resets automatically. A
    region is only consumed once it is actually featured, so a higher-priority
    chart on a given day delays the queue rather than skipping a region.

    Built fresh from the World Bank API; any failure simply yields no chart.
    """
    spec = config.get("gdp_per_capita")
    if not spec or not spec.get("enabled", True):
        return []
    regions = spec.get("regions") or ["World", "Africa", "Asia", "Europe",
                                      "Americas", "Oceania"]
    if state is None:
        state = load_chart_state()
    quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
    entry = state.get("gdp_per_capita", {})
    shown = entry.get("shown", []) if entry.get("quarter") == quarter else []
    remaining = [r for r in regions if r not in shown]
    if not remaining:                      # every region already done this quarter
        return []
    region = remaining[0]

    indicator = spec.get("indicator", "NY.GDP.PCAP.CD")
    try:
        rows = _worldbank_latest(indicator, now.year)
    except Exception:
        return []
    if not rows:
        return []

    ranked: list[tuple[str, float, int]] = []
    for code, (value, year, name) in rows.items():
        continent = _CONTINENT.get(code)
        if continent is None:                       # drops aggregates
            continue
        if region == "World" or continent == region:
            ranked.append((name, value, year))
    ranked.sort(key=lambda x: x[1], reverse=True)
    top = ranked[:10]
    if len(top) < 3:
        return []

    latest_year = max(y for _, _, y in top)
    signature = hashlib.sha256(json.dumps(
        [quarter, region, [(n, round(v)) for n, v, _ in top]],
        separators=(",", ":")).encode()).hexdigest()
    chart_path = OUTPUT / "gdp_per_capita.png"
    where = "the world" if region == "World" else region
    draw_bar_chart(
        chart_path, [(n, v) for n, v, _ in top],
        title=f"Top 10 GDP per Capita \u2014 {region}",
        subtitle=f"GDP per capita (current US$), {latest_year}",
        footer="Source: World Bank, World Development Indicators",
    )
    leader = top[0]
    explanation = (
        f"{leader[0]} leads {where} on GDP per capita at about ${leader[1]:,.0f} "
        f"({latest_year}), among countries with available World Bank data. "
        "Figures are nominal US dollars, not adjusted for local cost of living."
    )
    return [{
        "id": "gdp_per_capita",
        "title": f"Top 10 GDP per Capita \u2014 {region}",
        "image_path": str(chart_path),
        "trigger_path": str(chart_path),
        "caption": f"Highest GDP per capita in {where}.",
        "explanation": explanation,
        "source": "World Bank (WDI)",
        "source_url": "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD",
        "priority": int(spec.get("priority", 5)),
        "signature": signature,
        # Queue bookkeeping consumed by mark_chart_featured:
        "gdp_region": region,
        "gdp_quarter": quarter,
    }]


def select_chart_of_the_day(config: dict[str, Any],
                            now: dt.datetime | None = None,
                            repeat_after_days: int = 7) -> dict[str, Any] | None:
    if now is None:
        now = dt.datetime.now(ZoneInfo(config["timezone"]))
    state = load_chart_state()
    now_utc = dt.datetime.now(dt.timezone.utc)
    candidates: list[dict[str, Any]] = []
    sources = [{**source, "priority": source.get("priority", 100)}
               for source in config.get("chart_sources", [])]
    sources.extend(fred_chart_sources())
    sources.extend(sheet_chart_sources(config))
    sources.extend(zillow_chart_sources(config))
    sources.extend(gdp_per_capita_chart_sources(config, now, state))
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
        chart_state = state.get(source["id"], {})
        last_featured = float(chart_state.get("featured_mtime", 0))
        data_is_new = updated_at > last_featured
        stale_enough = False
        last_featured_at = chart_state.get("featured_at", "")
        if last_featured_at:
            try:
                age_days = (now_utc - dt.datetime.fromisoformat(last_featured_at)).days
                stale_enough = age_days >= repeat_after_days
            except ValueError:
                pass
        else:
            stale_enough = True  # never featured before
        if not data_is_new and not stale_enough:
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
    # Quarterly GDP queue: append the region just featured so it is not
    # repeated until the queue resets next quarter.
    if chart.get("gdp_region"):
        prev = state.get(chart["id"], {})
        shown = list(prev.get("shown", [])) if prev.get("quarter") == chart["gdp_quarter"] else []
        if chart["gdp_region"] not in shown:
            shown.append(chart["gdp_region"])
        entry["quarter"] = chart["gdp_quarter"]
        entry["shown"] = shown
    state[chart["id"]] = entry
    CHART_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# Curated FRED series for the always-on "Chart of the Day" fallback. When none of
# Orhan's own inputs (Walmart, Zillow, GDP/CPI, regional GDP-per-capita) have a
# fresh update, the section is filled with a genuinely interesting market or
# economic series built from REAL FRED data, chosen to match the day's headlines.
# Numbers are never fabricated; if FRED is unreachable the section stays empty.
FALLBACK_SERIES = [
    {"keywords": ("global inflation", "world inflation", "global cpi", "imf inflation",
                  "worldwide inflation", "international inflation"),
     "series_id": "GLOBAL_INFL", "chart_id": "global_inflation_comparison",
     "title": "Global Inflation Comparison", "subtitle": "Year-over-year CPI inflation, monthly, last 5 years",
     "caption": "Year-over-year CPI inflation across major economies, monthly.",
     "source": "FRED (national statistical offices)", "source_url": "https://fred.stlouisfed.org/release?rid=251",
     "years_plotted": 5, "unit": "%",
     "explanation_template": "Year-over-year CPI inflation compared across major economies, updated monthly from FRED."},
    {"keywords": ("stock", "equit", "s&p", "wall street", "nasdaq", "dow ", "rally", "sell-off", "selloff", "shares", "market"),
     "series_id": "SP500", "chart_id": "fallback_sp500_1m",
     "title": "S&P 500 Index", "subtitle": "Daily close, trailing month",
     "caption": "The benchmark U.S. large-cap stock index.",
     "source": "S&P Dow Jones Indices via FRED",
     "source_url": "https://fred.stlouisfed.org/series/SP500",
     "years_plotted": 0, "unit": "",
     "explanation_template": "The S&P 500 closed at {latest} on {period}, {direction} from {previous} the prior session. It is the most widely watched gauge of U.S. equity performance."},
    {"keywords": ("oil", "crude", "opec", "energy", "gasoline", "fuel", "barrel"),
     "series_id": "DCOILWTICO", "chart_id": "fallback_wti",
     "title": "WTI Crude Oil Price", "subtitle": "Daily spot price, USD per barrel, last 2 years",
     "caption": "West Texas Intermediate crude, the U.S. oil benchmark.",
     "source": "U.S. EIA via FRED",
     "source_url": "https://fred.stlouisfed.org/series/DCOILWTICO",
     "years_plotted": 2, "unit": "",
     "explanation_template": "WTI crude settled near ${latest} per barrel on {period}, {direction} from ${previous} previously. Oil prices feed directly into fuel costs and headline inflation."},
    {"keywords": ("treasury", "yield", "bond", "interest rate", "fed ", "federal reserve", "powell", "rate cut", "rate hike"),
     "series_id": "DGS10", "chart_id": "fallback_dgs10",
     "title": "10-Year U.S. Treasury Yield", "subtitle": "Daily market yield, last 2 years",
     "caption": "The benchmark long-term U.S. interest rate.",
     "source": "Federal Reserve Board via FRED",
     "source_url": "https://fred.stlouisfed.org/series/DGS10",
     "years_plotted": 2, "unit": "%",
     "explanation_template": "The 10-year Treasury yield stood at {latest}% as of {period}, {direction} from {previous}% in the prior session. It anchors mortgage rates, borrowing costs, and equity valuations."},
    {"keywords": ("job", "unemploy", "labor", "layoff", "hiring", "payroll", "wage"),
     "series_id": "UNRATE", "chart_id": "fallback_unrate",
     "title": "U.S. Unemployment Rate", "subtitle": "Monthly, last 10 years",
     "caption": "The headline U.S. unemployment rate.",
     "source": "U.S. Bureau of Labor Statistics via FRED",
     "source_url": "https://fred.stlouisfed.org/series/UNRATE",
     "years_plotted": 10, "unit": "%",
     "explanation_template": "Unemployment was {latest}% in {period}, {direction} from {previous}% the month before. It is the most-watched single read on U.S. labor-market health."},
    {"keywords": ("mortgage", "housing", "home price", "real estate", "homebuy", "rent"),
     "series_id": "MORTGAGE30US", "chart_id": "fallback_mortgage",
     "title": "30-Year Fixed Mortgage Rate", "subtitle": "Weekly average, last 5 years",
     "caption": "The typical U.S. 30-year fixed mortgage rate.",
     "source": "Freddie Mac via FRED",
     "source_url": "https://fred.stlouisfed.org/series/MORTGAGE30US",
     "years_plotted": 5, "unit": "%",
     "explanation_template": "The average 30-year fixed mortgage rate was {latest}% in {period}, {direction} from {previous}% the prior week. It largely sets the cost of buying a home."},
    {"keywords": ("bitcoin", "crypto", "btc", "ethereum", "coinbase", "digital asset"),
     "series_id": "CBBTCUSD", "chart_id": "fallback_btc",
     "title": "Bitcoin Price (USD)", "subtitle": "Daily, last 2 years",
     "caption": "Bitcoin priced in U.S. dollars.",
     "source": "Coinbase via FRED",
     "source_url": "https://fred.stlouisfed.org/series/CBBTCUSD",
     "years_plotted": 2, "unit": "",
     "explanation_template": "Bitcoin traded near ${latest} on {period}, {direction} from ${previous} previously. It remains the bellwether for the broader crypto market."},
    {"keywords": ("dollar", "currency", "forex", "exchange rate", "euro", "yen"),
     "series_id": "DTWEXBGS", "chart_id": "fallback_dollar",
     "title": "U.S. Dollar Index (Broad)", "subtitle": "Daily trade-weighted index, last 2 years",
     "caption": "The broad trade-weighted value of the U.S. dollar.",
     "source": "Federal Reserve Board via FRED",
     "source_url": "https://fred.stlouisfed.org/series/DTWEXBGS",
     "years_plotted": 2, "unit": "",
     "explanation_template": "The broad dollar index was {latest} on {period}, {direction} from {previous} previously. A stronger dollar pressures exporters and dampens import costs."},
]


def build_sp500_one_month_chart(now: dt.datetime) -> dict[str, Any] | None:
    """Always-on equity fallback: S&P 500 daily close over the trailing month.

    This is the guaranteed final chart when nothing else (Walmart, Zillow,
    FRED official series, GDP-per-capita rotation, or a news-matched fallback)
    is available, so Chart of the Day is never blank. Equities trade nearly
    every weekday, which makes this a reliably fresh series to fall back on.
    """
    chart_id = "fallback_sp500_1m"
    chart_path = OUTPUT / f"{chart_id}.png"
    metadata_path = OUTPUT / f"{chart_id}.json"
    start = (now.date() - dt.timedelta(days=45)).isoformat()
    try:
        observations = fred_observations("SP500", start)
    except Exception:
        return None
    if len(observations) < 3:
        return None
    cutoff = now.date() - dt.timedelta(days=30)
    plotted = [(d, v) for d, v in observations if d >= cutoff]
    if len(plotted) < 3:
        plotted = observations[-15:]
    latest_date, latest_value = plotted[-1]
    previous_value = plotted[-2][1]
    sig = hashlib.sha256(json.dumps(
        [(d.isoformat(), round(v, 2)) for d, v in plotted], separators=(",", ":"),
    ).encode()).hexdigest()
    old_meta: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            old_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if old_meta.get("data_signature") != sig or not chart_path.exists():
        draw_line_chart(
            chart_path, plotted,
            "S&P 500 Index",
            "Daily close, trailing month",
            "Source: S&P Dow Jones Indices via FRED",
            unit="",
        )
        metadata_path.write_text(json.dumps({"data_signature": sig}, indent=2), encoding="utf-8")
    direction = "up" if latest_value > previous_value else "down" if latest_value < previous_value else "flat"
    period = latest_date.strftime("%B %#d, %Y" if os.name == "nt" else "%B %-d, %Y")
    explanation = (
        f"The S&P 500 closed at {latest_value:,.0f} on {period}, {direction} from "
        f"{previous_value:,.0f} the prior session. It is the most widely watched gauge of "
        "U.S. equity performance, shown here as the trailing month."
    )
    return {
        "id": chart_id,
        "title": "S&P 500 Index",
        "image_path": str(chart_path),
        "trigger_path": str(metadata_path),
        "caption": "S&P 500 daily close, trailing month.",
        "explanation": explanation,
        "source": "S&P Dow Jones Indices via FRED",
        "source_url": "https://fred.stlouisfed.org/series/SP500",
        "priority": 1,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_mtime": metadata_path.stat().st_mtime if metadata_path.exists() else 0,
        "image_mtime": chart_path.stat().st_mtime if chart_path.exists() else 0,
    }


def web_search_chart_fallback(top_stories: list[Story],
                              now: dt.datetime, errors: list[str]) -> dict[str, Any] | None:
    """Last-resort chart: query Google News RSS to discover today's dominant topic,
    then map it to a real FRED or World Bank series.  Numbers are never fabricated.
    Returns None only if FRED is genuinely unreachable."""
    # Build a query from the top headlines to find what's dominating today
    headline_words = " ".join(s.title for s in top_stories[:6]).lower()
    # Map topic signals to FRED series (same pool as FALLBACK_SERIES but driven by
    # a fresh RSS search rather than the already-curated top list)
    topic_map = [
        (("inflation", "cpi", "price", "cost of living"), "CPIAUCSL", "fred_cpi_inflation",
         "U.S. CPI Inflation", "Year-over-year CPI change, monthly, last 10 years",
         "Year-over-year consumer price inflation in the United States.",
         "U.S. Bureau of Labor Statistics via FRED",
         "https://fred.stlouisfed.org/series/CPIAUCSL",
         10, 12, "%",
         "Consumer prices were {latest}% above a year earlier in {period}; inflation {direction} from {previous}%."),
        (("unemployment", "jobs", "labor", "layoff", "hiring"), "UNRATE", "fallback_unrate",
         "U.S. Unemployment Rate", "Monthly, last 10 years",
         "The headline U.S. unemployment rate.",
         "U.S. Bureau of Labor Statistics via FRED",
         "https://fred.stlouisfed.org/series/UNRATE",
         10, 0, "%",
         "Unemployment was {latest}% in {period}, {direction} from {previous}% the month before."),
        (("mortgage", "housing", "home price"), "MORTGAGE30US", "fallback_mortgage",
         "30-Year Fixed Mortgage Rate", "Weekly average, last 5 years",
         "The average U.S. 30-year fixed mortgage rate.",
         "Freddie Mac via FRED",
         "https://fred.stlouisfed.org/series/MORTGAGE30US",
         5, 0, "%",
         "The 30-year mortgage rate was {latest}% in {period}, {direction} from {previous}%."),
        (("oil", "crude", "opec", "energy"), "DCOILWTICO", "fallback_wti",
         "WTI Crude Oil Price", "Daily spot price USD/barrel, last 2 years",
         "West Texas Intermediate crude — the U.S. oil benchmark.",
         "U.S. EIA via FRED",
         "https://fred.stlouisfed.org/series/DCOILWTICO",
         2, 0, "",
         "WTI crude settled near ${latest}/barrel on {period}, {direction} from ${previous}."),
    ]
    # Try to fetch a fresh RSS signal to supplement the top-stories text
    search_text = headline_words
    try:
        query = urllib.parse.quote("economics finance markets today when:1d")
        rss_stories = parse_feed("Google News", f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")
        search_text = headline_words + " " + " ".join(s.title for s in rss_stories[:8]).lower()
    except Exception:
        pass
    # Pick the best-matching series
    for keywords, series_id, chart_id, title, subtitle, caption, source, source_url, years, yoy_lag, unit, tmpl in topic_map:
        if any(k in search_text for k in keywords):
            try:
                chart = build_fred_chart(
                    series_id=series_id, chart_id=chart_id,
                    title=title, subtitle=subtitle, caption=caption,
                    source=source, source_url=source_url, priority=3,
                    start=f"{now.year - (years + 2)}-01-01",
                    yoy_lag=yoy_lag, years_plotted=years, unit=unit,
                    explanation_template=tmpl,
                )
                if chart:
                    chart["updated_at"] = now.astimezone(dt.timezone.utc).isoformat()
                    return chart
            except Exception as exc:
                errors.append(f"Web-search chart fallback ({series_id}): {type(exc).__name__}")
    # Absolute last resort: S&P 500, trailing month. Equities trade nearly
    # every weekday, so this is the most reliably-available chart of all.
    try:
        chart = build_sp500_one_month_chart(now)
        if chart:
            return chart
    except Exception as exc:
        errors.append(f"Last-resort S&P 500 chart: {type(exc).__name__}")
    # Secondary safety net if FRED's S&P 500 series itself is unreachable.
    try:
        chart = build_fred_chart(
            series_id="DGS10", chart_id="fallback_dgs10_last",
            title="10-Year U.S. Treasury Yield", subtitle="Daily market yield, last 2 years",
            caption="The benchmark long-term U.S. interest rate.",
            source="Federal Reserve Board via FRED",
            source_url="https://fred.stlouisfed.org/series/DGS10",
            priority=1, start=f"{now.year - 4}-01-01",
            yoy_lag=0, years_plotted=2, unit="%",
            explanation_template=(
                "The 10-year Treasury yield stood at {latest}% as of {period}, "
                "{direction} from {previous}% the prior session."
            ),
        )
        if chart:
            chart["updated_at"] = now.astimezone(dt.timezone.utc).isoformat()
            return chart
    except Exception as exc:
        errors.append(f"Last-resort Treasury chart: {type(exc).__name__}")
    return None


def news_fallback_chart(config: dict[str, Any], top_stories: list[Story],
                        now: dt.datetime, errors: list[str]) -> dict[str, Any] | None:
    """Always-on Chart of the Day: a real FRED series matched to today's news."""
    text = " ".join(
        f"{s.title} {s.summary or s.description or ''}" for s in top_stories
    ).lower()
    matched = [spec for spec in FALLBACK_SERIES
               if any(k in text for k in spec["keywords"])]
    # Unmatched series follow in a date-rotated order so quiet days still vary.
    rot = now.timetuple().tm_yday % len(FALLBACK_SERIES)
    rotated = FALLBACK_SERIES[rot:] + FALLBACK_SERIES[:rot]
    ordered = matched + [spec for spec in rotated if spec not in matched]
    for spec in ordered:
        years = spec.get("years_plotted", 2)
        try:
            if spec["series_id"] == "GLOBAL_INFL":
                chart = build_global_inflation_chart(now)
            elif spec["series_id"] == "SP500":
                chart = build_sp500_one_month_chart(now)
            else:
                chart = build_fred_chart(
                    series_id=spec["series_id"], chart_id=spec["chart_id"],
                    title=spec["title"], subtitle=spec["subtitle"], caption=spec["caption"],
                    source=spec["source"], source_url=spec["source_url"], priority=5,
                    start=f"{now.year - (years + 2)}-01-01",
                    yoy_lag=0, years_plotted=years, unit=spec.get("unit", ""),
                    explanation_template=spec["explanation_template"],
                )
        except Exception as exc:
            errors.append(f"Fallback chart {spec['series_id']}: {type(exc).__name__}")
            chart = None
        if chart:
            chart["updated_at"] = now.astimezone(dt.timezone.utc).isoformat()
            return chart
    return None


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
           errors: list[str], tldr: str = "") -> str:
    date_label = (
        now.strftime("%B %-d, %Y, %A")
        if os.name != "nt"
        else now.strftime("%B %#d, %Y, %A")
    )
    # Internal source errors are logged to latest.json and the scheduler log,
    # but never shown in the delivered newsletter.
    source_note = ""

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
          <font face="Arial, sans-serif" color="#17324D" size="2">
            <strong>{esc(row['city'])}</strong><br>
            <font size="4"><strong>{row['current']}°</strong></font><br>
            {esc(row.get('conditions', ''))}<br>
            H {row['high']}° · L {row['low']}° · Rain {row['rain']}%
          </font>
        </td>""")
    weather_table = f"""
      <table role="presentation" width="100%" border="0" cellspacing="2" cellpadding="4" bgcolor="#DCE7EE">
      <tr>{''.join(weather_cells)}</tr>
      </table>"""

    chart_html = ""
    if chart_of_day:
        updated_label = ""
        if chart_of_day.get("updated_at"):
            updated = dt.datetime.fromisoformat(chart_of_day["updated_at"]).astimezone(
                ZoneInfo(config["timezone"])
            )
            updated_label = updated.strftime("%B %#d, %Y") if os.name == "nt" else updated.strftime("%B %-d, %Y")
        chart_html = f'''
          <h3>{esc(chart_of_day["title"])}</h3>
          <p align="center"><img src="cid:chart-of-the-day" width="600" style="max-width:100%;height:auto"
             alt="{esc(chart_of_day["title"])}"></p>
          <p>{esc(chart_of_day.get("explanation") or chart_of_day.get("caption") or "")}</p>
          <p><small><strong>Source:</strong> {esc(chart_of_day["source"])}
          {f'· <a href="{esc(chart_of_day["source_url"])}">View source</a>' if chart_of_day.get("source_url") else ''}
          {f"· Updated {esc(updated_label)}" if updated_label else ""}</small></p>'''

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
          <strong>{esc(date_label)}</strong>
        </font>
      </td></tr>
      </table>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="7" bgcolor="#8A2D3C">
      <tr><td align="center">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2">
          TOP NEWS &nbsp;·&nbsp; RESEARCH RADAR &nbsp;·&nbsp; CHART OF THE DAY
        </font>
      </td></tr>
      </table>

      {weather_table}

      <h2>Good morning</h2>
      {f'''<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="10" bgcolor="#EDE6D6">
      <tr><td>
        <font face="Georgia, Times New Roman, serif" color="#17324D" size="3">
          <strong>TODAY'S TAKEAWAY &nbsp;</strong>{esc(tldr)}
        </font>
      </td></tr>
      </table>''' if tldr else ''}

      {section_html("1 · Top News", top_html, "No qualifying stories were available in this run.")}
      {section_html("2 · Research Radar", research_html, "No qualifying research items were available in this run.")}
      {section_html("3 · Chart of the Day", chart_html, "No newly updated chart today; the next release of the Walmart tracker, Zillow data, GDP, or CPI will appear here.")}
      {source_note}

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="10" bgcolor="#17324D">
      <tr><td align="center">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2">
          <strong>{esc(config['newsletter_name'].upper())}</strong> &nbsp;·&nbsp; A PERSONAL FIVE-MINUTE BRIEFING
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
    name = config.get("newsletter_name", "Orhan's Morning Times")
    msg = EmailMessage()
    msg["From"] = f"{name} <{user}>"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(f"{name} is best viewed as HTML.")
    msg.add_alternative(body, subtype="html")
    chart = None
    try:
        saved = json.loads((OUTPUT / "latest.json").read_text(encoding="utf-8"))
        chart = saved.get("chart_of_the_day")
    except (OSError, json.JSONDecodeError):
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
    if (os.getenv("OMI_PRESERVE_CHART_STATE", "").lower() not in {"1", "true", "yes"}
            and chart and chart.get("updated_mtime")):
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
        select_diverse(news, 16, per_category=2, per_source=2)
        + select_diverse(ft_items + economist_items, 6, per_category=3, per_source=2)
    )
    news_candidates.sort(key=lambda x: x.score, reverse=True)
    # Hard-cap AI in the candidate pool so the editor receives a diverse slate
    # and cannot be forced into AI dominance by the available candidates.
    ai_cap = 3
    capped: list[Story] = []
    ai_seen = 0
    for story in news_candidates:
        if category(story) == "tech":
            if ai_seen >= ai_cap:
                continue
            ai_seen += 1
        capped.append(story)
    news_candidates = capped
    seen_links = load_seen_links()
    if seen_links:
        filtered = [s for s in news_candidates if s.link not in seen_links]
        if filtered:
            news_candidates = filtered
    research_candidates = select_diverse(research_pool, 10, per_category=4, per_source=2)
    for item in research_candidates:
        item.kind = "research"
    leader_candidates, leader_notes = collect_thought_leaders(config, now, errors)

    if no_ai:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    top, leader_post, research_pick, tldr = claude_curate(
        news_candidates, leader_candidates, research_candidates, config, errors,
    )
    top = enforce_category_floor(top, news_candidates)
    research_items = [research_pick] if research_pick else []

    total_items = len(top) + (1 if leader_post else 0)
    if total_items > 6:
        top = top[:6 - (1 if leader_post else 0)]

    chart_of_day = select_chart_of_the_day(config, now)
    if not chart_of_day:
        chart_of_day = news_fallback_chart(config, top, now, errors)
    if not chart_of_day:
        chart_of_day = web_search_chart_fallback(top, now, errors)
    body = render(config, now, weather_rows, top, leader_post, leader_notes,
                  research_items, chart_of_day, errors, tldr)
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
    subject = f"{config['newsletter_name']} | {date_label}"
    return dated, subject, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and deliver the daily newsletter.")
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
        if os.getenv("OMI_PRESERVE_CHART_STATE", "").lower() not in {"1", "true", "yes"}:
            record_seen_links([s.get("link", "") for s in manifest.get("stories", [])])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
