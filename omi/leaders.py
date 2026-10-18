"""Thought Leaders Monitor: one notable recent item per configured person."""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from typing import Any

from .common import Story
from .news import parse_feed, rank

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
        username = handle.lstrip("@")
        leader_posts: list[Story] = []

        # 1. Own publications (Substack, blogs).
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

