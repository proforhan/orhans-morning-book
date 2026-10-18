"""Shared paths, the Story record, text helpers and HTTP fetch with retries."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CHART_STATE = OUTPUT / "chart_of_the_day_state.json"
USER_AGENT = "OrhanMorningBrief/3.0 (+personal research newsletter)"


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
    via: str = ""        # "own publication" | "press coverage"


def load_config() -> dict[str, Any]:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def log(message: str) -> None:
    """Diagnostics for the CI log (stderr). Never shown in the email itself."""
    print(f"[omb] {message}", file=sys.stderr)


def fetch(url: str, timeout: int = 20, retries: int = 1,
          headers: dict[str, str] | None = None) -> bytes:
    """GET a URL. Retries on network errors, 429 and 5xx with growing waits."""
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts:
                raise
        time.sleep(2 * attempt * attempt)   # 2s, 8s, 18s
    raise RuntimeError("unreachable")


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shorten_title(title: str, limit: int = 70) -> str:
    """Trim an over-long headline to a word boundary, adding an ellipsis."""
    title = title.strip()
    if len(title) <= limit:
        return title
    truncated = title[:limit].rsplit(" ", 1)[0].rstrip(",.;:-–— ")
    return f"{truncated}…" if truncated else f"{title[:limit].rstrip()}…"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
