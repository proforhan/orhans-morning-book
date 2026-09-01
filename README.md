# Orhan's Morning Intelligence

Daily, mobile-friendly morning newsletter delivered at 7:00 AM Central through
[Buttondown](https://buttondown.com/home) to everyone subscribed via the
website's subscribe form (proforhan.github.io). Four sections: Weather
Snapshot (Irving and Dallas), Top News (8-10 items, one of which is a Thought
Leaders Monitor item), Research Radar (one notable paper), and Chart of the
Day.

Curation and summaries use the Claude API (Impact x Novelty x Relevance,
weighted toward AI, economics, finance, academic research, and medicine).
Without an API key the generator falls back to cleaned feed text.

This system replaces the earlier "Orhan Times" project.

## Delivery: Buttondown

The script builds the full HTML issue locally, then hands it to Buttondown
via its API (`send_via_buttondown` in `main.py`), which owns the subscriber
list and handles unsubscribe automatically (every Buttondown email includes
an unsubscribe link in the footer - no code needed here for that). The
chart-of-the-day image is uploaded to Buttondown's image host first, since
Buttondown's API has no equivalent of an email's inline `cid:` attachment -
this only applies to a tracked chart; a fallback chart (see below) is already
hosted at its original news-outlet URL, so it's linked directly instead.

Safety default: every run creates the issue as a **draft** in Buttondown
first. It's only advanced to actually send (`about_to_send`) when
`OMI_BUTTONDOWN_LIVE=true` is set - `run_newsletter.ps1` (the real scheduled
run) sets it; `test_delivery.ps1` deliberately does not, so testing never
emails real subscribers. Review or manually send a draft at
https://buttondown.com/emails.

Gmail SMTP delivery (`send_email` in `main.py`, keyed off `config.json`'s
`recipients` list) is retained in the code but no longer called by default -
kept only as a manual fallback if you ever need to email a fixed list
directly again.

## One-time setup

1. Buttondown API key: run `.\setup_buttondown.ps1` and paste a key from
   https://buttondown.com/settings/api (API -> Keys). Stored encrypted with
   Windows DPAPI, decryptable only by this Windows account on this computer.
2. Claude API key: run `.\setup_claude_api.ps1` and paste a key from
   https://console.anthropic.com. Stored the same way.
3. Test privately (builds a Buttondown draft, does not send):
   `.\test_delivery.ps1`
4. Install the daily 7:00 AM task: `.\install_task.ps1`
5. After verifying delivery, remove the old newsletter's task:
   `.\remove_orhan_times_task.ps1` - then the old "Orhan Times" folder can be
   deleted.

(Gmail app password setup, `.\setup_gmail_smtp.ps1`, is only needed if you
fall back to the legacy `send_email` path.)

## Everyday commands

```powershell
python .\main.py --no-send   # generate output\latest.html without sending
.\test_delivery.ps1          # full run, creates a Buttondown draft only
.\run_newsletter.ps1         # what the scheduled task runs (sends live)
```

## Configuration (`config.json`)

- `recipients`: only used by the legacy Gmail fallback path now; Buttondown
  manages its own subscriber list independent of this file.
- `thought_leaders`: add a new account by appending an object with `name`,
  `handle`, `url`, optional `feeds` (RSS/Atom URLs the person publishes), and
  optional `news_query` (Google News fallback). One leader item appears in Top
  News each day; source priority is X (via public mirrors), then their own
  publications, then clearly-labelled press coverage. If nothing is
  retrievable, the newsletter says so explicitly instead of substituting
  unverified content.
- `chart_sources`: local chart images with a `trigger_path` whose update
  causes the chart to be featured once. FRED charts (GDP growth, CPI
  inflation, 10-year Treasury fallback) are built automatically.
- `claude_model`: default `claude-sonnet-4-6`.

## Chart of the Day

The newest eligible chart wins by (priority, recency); each update is featured
once and recorded in `output\chart_of_the_day_state.json` (only advanced on a
live Buttondown send, not on a draft/test run).

- Walmart Inflation Tracker: export the updated Google Sheets chart as PNG to
  `...\Walmart Shopping Cart\Walmart_Inflation_Tracker.png` (must be newer
  than the `.gsheet` pointer).
- Zillow Texas cities: produced by the existing "TX house prices agent"
  output PNG.
- GDP and CPI: rebuilt automatically when FRED publishes new data; the
  y-axis includes zero, since these growth rates can meaningfully go
  negative.
- 10-year Treasury yield: low-priority daily fallback so the section is
  rarely empty; the y-axis zooms to the data's actual range rather than
  forcing a zero floor, since it's a trend line, not a bar chart.

**Fallback when nothing tracked is new:** if none of the above have anything
newly updated (`select_chart_of_the_day` returns nothing - e.g. the Walmart
and Zillow trackers haven't been re-exported and the FRED series haven't
moved), `select_fallback_chart` in `main.py` looks instead for a genuinely
chart-led piece published in the last four days from a short list of
data-journalism outlets (`FALLBACK_CHART_FEEDS`: The Economist's Graphic
Detail, Visual Capitalist, Our World in Data, plus Google News searches for
Reuters Graphics and Axios Visuals), ranked by recency and a "does this look
chart-led" keyword check (`CHART_KEYWORDS`: chart, graphic, in numbers,
visualized, infographic, ...). It only considers items that carry an image.
The newsletter clearly labels this case ("No tracked chart updated today -
spotted in coverage") and links straight to the original outlet's image
rather than treating it as one of your tracked series - it isn't recorded in
`chart_of_the_day_state.json`, so it never blocks a tracked chart from being
featured once it actually updates.

## Notes

- Secrets live only in the `.credential.xml` files (DPAPI-encrypted) and are
  never written to `config.json` or the log.
- Logs: `output\scheduler.log`. Generated issues: `output\omi_YYYY-MM-DD.html`.
- FT content uses the personal myFT RSS feed; The Economist uses public RSS
  metadata only; summaries link to the originals for subscription reading.
