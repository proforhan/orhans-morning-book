# Orhan's Morning Intelligence

Daily, mobile-friendly morning newsletter delivered at 7:00 AM Central to the
recipients in `config.json`. Four sections: Weather Snapshot (Irving and
Dallas), Top News (8-10 items, one of which is a Thought Leaders Monitor item),
Research Radar (one notable paper), and Chart of the Day.

Curation and summaries use the Claude API (Impact x Novelty x Relevance,
weighted toward AI, economics, finance, academic research, and medicine).
Without an API key the generator falls back to cleaned feed text.

This system replaces the earlier "Orhan Times" project.

## One-time setup

1. Gmail app password (already configured if `.gmail-smtp.credential.xml`
   exists; otherwise run `.\setup_gmail_smtp.ps1`).
2. Claude API key: run `.\setup_claude_api.ps1` and paste a key from
   https://console.anthropic.com. Stored encrypted with Windows DPAPI,
   decryptable only by this Windows account on this computer.
3. Test privately (sends only to orhanerdem@gmail.com):
   `.\test_delivery.ps1`
4. Install the daily 7:00 AM task: `.\install_task.ps1`
5. After verifying delivery, remove the old newsletter's task:
   `.\remove_orhan_times_task.ps1` - then the old "Orhan Times" folder can be
   deleted.

## Everyday commands

```powershell
python .\main.py --no-send   # generate output\latest.html without emailing
.\test_delivery.ps1          # full run, email only to Orhan
.\run_newsletter.ps1         # what the scheduled task runs (emails everyone)
```

## Configuration (`config.json`)

- `recipients`: add or remove email addresses (comma-separated list entries).
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
once and recorded in `output\chart_of_the_day_state.json`.

- Walmart Inflation Tracker: export the updated Google Sheets chart as PNG to
  `...\Walmart Shopping Cart\Walmart_Inflation_Tracker.png` (must be newer
  than the `.gsheet` pointer).
- Zillow Texas cities: produced by the existing "TX house prices agent"
  output PNG.
- GDP and CPI: rebuilt automatically when FRED publishes new data.
- 10-year Treasury yield: low-priority daily fallback so the section is
  rarely empty.

## Notes

- Secrets live only in the two `.credential.xml` files (DPAPI-encrypted) and
  are never written to `config.json` or the log.
- Logs: `output\scheduler.log`. Generated issues: `output\omi_YYYY-MM-DD.html`.
- FT content uses the personal myFT RSS feed; The Economist uses public RSS
  metadata only; summaries link to the originals for subscription reading.
