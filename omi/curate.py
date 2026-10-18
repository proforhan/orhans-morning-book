"""Claude curation: one API call selects and summarises every section."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from .common import Story, clean_text
from .news import select_diverse

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

