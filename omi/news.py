"""Top News and Research Radar: feed collection, ranking and selection."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import re
import xml.etree.ElementTree as ET

from .common import Story, clean_text, fetch

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

# Used only when none of the tracked local/FRED charts have anything newly
# updated to feature (see select_fallback_chart). These are outlets whose
# posts are built around a chart or graphic, so a story pulled from here is

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

