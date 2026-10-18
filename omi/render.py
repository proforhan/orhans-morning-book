"""HTML email template."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any
from zoneinfo import ZoneInfo

from .common import Story, esc, shorten_title

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
      <h3>{label}<a href="{esc(story.link)}">{esc(shorten_title(story.title))}</a></h3>
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
    return f"""
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="6" bgcolor="#EDE6D6">
      <tr><td>
        <font face="Arial, sans-serif" color="#6B5310" size="2"><strong>&#9733; THOUGHT LEADERS MONITOR</strong></font>
      </td></tr>
      </table>
      <h3>{number}. <a href="{esc(post.link)}">{esc(post.source)}</a></h3>
      <blockquote>{esc(shorten_title(post.summary or post.title, 140))}</blockquote>
      {visual}
      <p><small>{esc(time_label)}{" · " if time_label else ""}<a href="{esc(post.link)}">View original →</a>
      · <a href="{esc("https://x.com/" + post.source.split("(@")[-1].rstrip(")"))}">Profile on X</a></small></p>
      <hr>"""


def section_html(title: str, content: str, empty_message: str = "") -> str:
    body = content or f"<p><em>{esc(empty_message)}</em></p>"
    return f"""
    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
      <tr>
        <td bgcolor="#17324D" align="left" class="omi-section-title" style="padding:8px 12px;">
          <font face="Arial, sans-serif" color="#FFFFFF" size="4">
            <strong>&nbsp; {esc(title)}</strong>
          </font>
        </td>
      </tr>
    </table>
    {body}"""


def render(config: dict[str, Any], now: dt.datetime, weather_rows: list[dict[str, Any]],
           top: list[Story], leader_post: Story | None, leader_notes: list[str],
           research: list[Story], chart_of_day: dict[str, Any] | None) -> str:
    date_label = (
        now.strftime("%B %-d, %Y, %A")
        if os.name != "nt"
        else now.strftime("%B %#d, %Y, %A")
    )

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
            + "</em></small></p>"
        )
    top_html = "".join(items_html)

    research_html = "".join(story_html(s, show_image=True) for s in research)

    weather_cells = []
    column_width = f"{100 // len(weather_rows)}%" if weather_rows else "100%"
    for row in weather_rows:
        weather_cells.append(f"""
        <td width="{column_width}" bgcolor="#EDF3F7" valign="top" class="omi-weather-cell" style="padding:10px;">
          <font face="Arial, sans-serif" color="#17324D" class="omi-weather-text">
            <strong>{esc(row['city'])}</strong><br>
            <font size="6" class="omi-temp"><strong>{row['current']}°</strong></font><br>
            {esc(row.get('conditions', ''))}<br>
            H {row['high']}° · L {row['low']}° · Rain {row['rain']}%
          </font>
        </td>""")
    weather_table = f"""
      <table role="presentation" width="100%" border="0" cellspacing="4" cellpadding="10" bgcolor="#DCE7EE" class="omi-weather-table">
      <tr class="omi-weather-row">{''.join(weather_cells)}</tr>
      </table>"""

    chart_html = ""
    if chart_of_day:
        updated = dt.datetime.fromisoformat(chart_of_day["updated_at"]).astimezone(
            ZoneInfo(config["timezone"])
        )
        updated_label = updated.strftime("%B %#d, %Y") if os.name == "nt" else updated.strftime("%B %-d, %Y")
        is_fallback = bool(chart_of_day.get("is_fallback"))
        image_src = esc(chart_of_day["image_url"]) if is_fallback else "cid:chart-of-the-day"
        fallback_note = (
            '''<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="6" bgcolor="#EDE6D6">
          <tr><td>
            <font face="Arial, sans-serif" color="#6B5310" size="2"><strong>&#9733; NO TRACKED CHART UPDATED TODAY · SPOTTED IN COVERAGE</strong></font>
          </td></tr>
          </table>'''
            if is_fallback else ""
        )
        chart_html = f'''
          {fallback_note}
          <h3>{esc(shorten_title(chart_of_day["title"]))}</h3>
          <p align="center"><img src="{image_src}" width="600" style="max-width:100%;height:auto"
             alt="{esc(chart_of_day["title"])}"></p>
          <p>{esc(chart_of_day.get("explanation") or chart_of_day["caption"])}</p>
          <p><small><strong>Source:</strong> {esc(chart_of_day["source"])}
          {f'· <a href="{esc(chart_of_day["source_url"])}">View source</a>' if chart_of_day.get("source_url") else ''}
          · {"Found" if is_fallback else "Updated"} {esc(updated_label)}</small></p>'''

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="format-detection" content="telephone=no">
<style>
  body,table,td {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  img {{ -ms-interpolation-mode:bicubic; }}
  a {{ text-decoration:none; }}
  h2,h3 {{ line-height:1.25; margin:8px 0 4px; }}
  p {{ line-height:1.4; margin:4px 0; }}
  blockquote {{ line-height:1.4; margin:4px 0 6px; padding:6px 10px; }}
  li {{ line-height:1.4; }}
  hr {{ margin:6px 0 12px; border:none; border-top:1px solid #E0DCD2; }}
  @media only screen and (max-width:620px) {{
    .omi-wrap {{ width:100% !important; }}
    .omi-pad {{ padding:10px !important; }}
    .omi-masthead {{ padding:12px 8px !important; }}
    .omi-title {{ font-size:20px !important; }}
    .omi-subtitle {{ font-size:10px !important; }}
    .omi-navbar {{ font-size:9.5px !important; padding:6px 4px !important; }}
    .omi-navbar-text {{ font-size:9.5px !important; }}
    .omi-section-title {{ padding:7px 10px !important; }}
    .omi-section-title font {{ font-size:14px !important; }}
    .omi-weather-cell {{ padding:6px 4px !important; }}
    .omi-weather-text {{ font-size:9.5px !important; }}
    .omi-weather-cell strong {{ font-size:10px !important; }}
    .omi-temp {{ font-size:18px !important; }}
    h2 {{ font-size:16px !important; }}
    h3 {{ font-size:14px !important; }}
    p, blockquote, li {{ font-size:12.5px !important; }}
    blockquote {{ margin:4px 0 !important; padding:6px 8px !important; }}
    small {{ font-size:10.5px !important; }}
    hr {{ margin:4px 0 8px !important; }}
  }}
</style>
</head>
<body bgcolor="#E7EDF2">
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="8" bgcolor="#E7EDF2">
<tr><td align="center">
  <table role="presentation" width="680" border="0" cellspacing="0" cellpadding="0" bgcolor="#17324D" style="max-width:100%" class="omi-wrap">
  <tr><td>
    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="18" bgcolor="#FAF7F0">
    <tr><td class="omi-pad">
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="12" bgcolor="#17324D">
      <tr><td align="center" class="omi-masthead">
        <font face="Georgia, Times New Roman, serif" color="#FFFFFF" size="6" class="omi-title">
          <strong>{esc(config['newsletter_name'])}</strong>
        </font><br>
        <font face="Arial, sans-serif" color="#DDE7EF" size="2" class="omi-subtitle">
          <strong>{esc(date_label)} &nbsp;·&nbsp; MORNING EDITION</strong>
        </font>
      </td></tr>
      </table>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="7" bgcolor="#8A2D3C">
      <tr><td align="center" class="omi-navbar">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2" class="omi-navbar-text">
          WEATHER &nbsp;·&nbsp; TOP NEWS &nbsp;·&nbsp; RESEARCH RADAR &nbsp;·&nbsp; CHART OF THE DAY
        </font>
      </td></tr>
      </table>

      <h2>Good morning</h2>
      <p>Your high-signal briefing for today. The most consequential items come first.</p>

      {section_html("1 · Weather Snapshot", weather_table)}
      {section_html("2 · Top News", top_html, "No qualifying stories were available in this run.")}
      {section_html("3 · Research Radar", research_html, "No qualifying research items were available in this run.")}
      {section_html("4 · Chart of the Day", chart_html, "No newly updated chart today; the next data release will appear here.")}

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="10" bgcolor="#17324D">
      <tr><td align="center">
        <font face="Arial, sans-serif" color="#FFFFFF" size="2">
          <strong>A PERSONAL FIVE-MINUTE BRIEFING</strong>
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

