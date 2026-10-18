# Orhan's Morning Brief

Daily email briefing, built and sent by GitHub Actions (no computer involved).

## Layout

| File | Section / job |
|---|---|
| `main.py` | Orchestrates the run; each section is built inside its own guard |
| `omi/weather.py` | Weather Snapshot (Open-Meteo) |
| `omi/news.py` | Top News and Research Radar: feeds, ranking, selection |
| `omi/leaders.py` | Thought Leaders Monitor |
| `omi/curate.py` | One Claude call picks and summarises everything |
| `omi/charts.py` | Chart of the Day: FRED API charts, "already featured" state, coverage fallback |
| `omi/render.py` | HTML email template |
| `omi/deliver.py` | Buttondown delivery |
| `omi/health.py` | Problem tracking and the "needs attention" alert |
| `config.json` | Newsletter name, weather cities, FT feed, thought leaders, Claude model |

## When something breaks

A section that fails degrades on its own; the newsletter still goes out. Every
run writes `output/health.json`. If anything needs attention you get:

1. an email "Morning Brief needs attention" (or "FAILED" if the run crashed),
2. a red workflow run with the problems listed as annotations.

Problems checked: weather unavailable, fewer than 4 top stories, no research
item, news feeds mostly failing, any FRED chart failing or no chart featured
for 5+ days, Claude curation unavailable, missing `FRED_API_KEY`, crashes.
One slow feed is only a note in the log.

## Secrets (repo Settings > Secrets > Actions)

`BUTTONDOWN_API_KEY`, `ANTHROPIC_API_KEY`, `FRED_API_KEY`, `GMAIL_USER`,
`GMAIL_APP_PASSWORD` (the last two are used only to email you alerts).

## Testing

Actions > Morning Intelligence > Run workflow, leave "test_only" ticked. It
builds everything, sends nothing to subscribers, keeps chart state untouched,
and attaches `latest.html` and `health.json` to the run. Locally:
`python main.py --no-send` (add `--no-ai` to skip Claude).

## Chart of the Day

GDP growth, CPI inflation and the 10-year Treasury yield are built from FRED
and each data release is featured once (tracked by a hash of the data in
`output/chart_of_the_day_state.json`). If nothing new, a chart-led piece from a
data-journalism outlet is shown, labelled as spotted in coverage.
