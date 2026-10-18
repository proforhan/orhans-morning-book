"""Chart of the Day: FRED charts, "already featured" state, coverage fallback."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import urllib.parse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .common import CHART_STATE, OUTPUT, Story, fetch, log
from .news import collect, deduplicate, rank, recent

FALLBACK_CHART_FEEDS = [
    ("The Economist: Graphic Detail", "https://www.economist.com/graphic-detail/rss.xml"),
    ("Visual Capitalist", "https://www.visualcapitalist.com/feed/"),
    ("Our World in Data", "https://ourworldindata.org/atom.xml"),
    ("Reuters Graphics", "https://news.google.com/rss/search?q=site:reuters.com+(graphic+OR+%22in+charts%22)+when:4d&hl=en-US&gl=US&ceid=US:en"),
    ("Axios Visuals", "https://news.google.com/rss/search?q=site:axios.com+chart+when:4d&hl=en-US&gl=US&ceid=US:en"),
]

CHART_KEYWORDS = ("chart", "charts", "graphic", "data show", "in numbers", "visualized", "infographic")


def load_chart_state() -> dict[str, Any]:
    if not CHART_STATE.exists():
        return {}
    try:
        return json.loads(CHART_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def chart_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # GitHub runner
         r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fred_observations(series_id: str, start: str) -> list[tuple[dt.date, float]]:
    """Observations from the official FRED API (needs FRED_API_KEY), with retries.

    Without a key it falls back to the anonymous CSV endpoint, which FRED may
    throttle on shared CI addresses; the caller flags that case as a problem.
    Raises when FRED returns nothing usable, so a failure is never silent.
    """
    key = os.getenv("FRED_API_KEY", "").strip()
    observations: list[tuple[dt.date, float]] = []
    if key:
        query = urllib.parse.urlencode({
            "series_id": series_id, "api_key": key, "file_type": "json",
            "observation_start": start,
        })
        data = json.loads(fetch(
            f"https://api.stlouisfed.org/fred/series/observations?{query}", retries=3))
        for row in data.get("observations", []):
            try:
                observations.append((dt.date.fromisoformat(row["date"]), float(row["value"])))
            except (KeyError, TypeError, ValueError):
                continue   # FRED marks missing values as "."
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
        rows = csv.DictReader(fetch(url, retries=3).decode("utf-8-sig").splitlines())
        for row in rows:
            try:
                observations.append((dt.date.fromisoformat(row["observation_date"]), float(row[series_id])))
            except (KeyError, TypeError, ValueError):
                continue
    if not observations:
        raise ValueError(f"no usable observations for {series_id}")
    return observations


def nice_tick_step(span: float, target_ticks: int = 5) -> float:
    """Round a raw tick spacing up to a 'neat' 1/2/2.5/5x10^n step."""
    if span <= 0:
        return 1.0
    raw_step = span / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * magnitude
        if step >= raw_step - 1e-9:
            return step
    return 10 * magnitude


def draw_line_chart(path: Path, plotted: list[tuple[dt.date, float]], title: str,
                    subtitle: str, footer: str, unit: str = "%",
                    zero_baseline: bool = False) -> None:
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
    # Only force the axis down to zero for series where "how far from zero"
    # is part of the story (growth/inflation rates that can turn negative).
    # For series like interest rates or temperatures, zooming to the data's
    # actual range shows the trend more clearly and isn't misleading, since
    # it's a line (trend) chart rather than a bar chart implying magnitude.
    if zero_baseline and y_min > 0:
        y_min = 0.0
    elif zero_baseline:
        y_min = min(y_min, -1.0)

    tick_step = nice_tick_step(y_max - y_min)
    y_min = math.floor(y_min / tick_step) * tick_step
    y_max = max(y_max, y_min + tick_step)

    plot_width = width - left - right
    plot_height = height - top - bottom

    def point(index: int, value: float) -> tuple[float, float]:
        x = left + index * plot_width / max(1, len(plotted) - 1)
        y = top + (y_max - value) * plot_height / (y_max - y_min)
        return x, y

    decimals = 0 if tick_step >= 1 and tick_step == int(tick_step) else 2 if tick_step < 1 else 1
    tick = y_min
    tick_count = 0
    while tick <= y_max + tick_step * 0.01 and tick_count < 20:
        y = point(0, tick)[1]
        if top <= y <= height - bottom:
            draw.line((left, y, width - right, y), fill="#D6D6D6", width=1)
            label = f"{tick:.{decimals}f}{unit}"
            draw.text((8, y - 6), label, fill="#666666", font=small_font)
        tick += tick_step
        tick_count += 1
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
                     unit: str = "%", zero_baseline: bool = False,
                     explanation_template: str = "") -> dict[str, Any] | None:
    chart_path = OUTPUT / f"{chart_id}.png"
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
    # The signature is a hash of the data itself. It alone decides whether
    # this chart counts as "new" (see select_chart_of_the_day) - never file
    # timestamps, which are reset on every ephemeral CI run.
    signature = hashlib.sha256(json.dumps(
        [(date.isoformat(), round(value, 3)) for date, value in series],
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    draw_line_chart(chart_path, plotted, title, subtitle, f"Source: {source}", unit,
                    zero_baseline=zero_baseline)

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
        "signature": signature,
        "data_date": latest_date.isoformat(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "caption": caption,
        "explanation": explanation,
        "source": source,
        "source_url": source_url,
        "priority": priority,
    }


def fred_chart_sources(errors: list[str]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    builders = [
        dict(series_id="GDP", chart_id="fred_gdp_growth",
             title="U.S. GDP Growth Over the Last 10 Years",
             subtitle="Year-over-year percent change in nominal GDP, quarterly",
             caption="Year-over-year growth in nominal U.S. gross domestic product.",
             source="U.S. Bureau of Economic Analysis via FRED",
             source_url="https://fred.stlouisfed.org/series/GDP",
             priority=10, start="2014-01-01", yoy_lag=4, zero_baseline=True,
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
             priority=10, start="2014-01-01", yoy_lag=12, zero_baseline=True,
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
             priority=1, start="2024-06-01", yoy_lag=0, years_plotted=2, zero_baseline=False,
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
            else:
                errors.insert(0, f"FRED {kwargs['chart_id']}: too few observations")
        except Exception as exc:
            # Inserted at the front so the email's 6-item "Source notes"
            # footer can't truncate a chart failure behind feed noise.
            errors.insert(0, f"FRED {kwargs['chart_id']}: {type(exc).__name__}")
    return sources


# If no tracked chart has been featured for longer than this, the Chart of the
# Day pipeline is presumed broken and the email says so (see below). The
# daily Treasury chart changes every business day, so a healthy pipeline never
# goes this long without featuring something.
STALE_CHART_DAYS = 5


def last_featured_at(state: dict[str, Any]) -> dt.datetime | None:
    stamps: list[dt.datetime] = []
    for entry in state.values():
        try:
            stamps.append(dt.datetime.fromisoformat(entry["featured_at"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(stamps) if stamps else None


def select_chart_of_the_day(errors: list[str] | None = None) -> dict[str, Any] | None:
    """Pick today's tracked chart, or None when nothing tracked is new.

    A chart is "new" when its content signature differs from the signature
    recorded when it was last featured. The signature is a hash of the chart's
    own data (FRED series), so the decision depends on
    nothing but that content: not file timestamps, not what files happen to be
    left in the working directory, not which machine or CI runner built it.
    Every source type goes through this one path, so a new data release is
    picked up automatically with no code or config change.
    """
    errors = errors if errors is not None else []
    state = load_chart_state()
    sources = fred_chart_sources(errors)

    candidates: list[dict[str, Any]] = []
    for source in sources:
        featured = state.get(source["id"], {}).get("featured_signature")
        if source["signature"] == featured:
            log(f"chart '{source['id']}': already featured, data unchanged; skipped")
            continue
        log(f"chart '{source['id']}': new data; eligible")
        candidates.append(source)

    if candidates:
        # Highest priority first; ties go to the most recent underlying data.
        chosen = max(candidates, key=lambda item: (
            item.get("priority", 0), item.get("data_date") or item["updated_at"][:10]))
        log(f"chart of the day: '{chosen['id']}'")
        return chosen

    # Nothing new. Fine for a day or two; a long gap means something is broken,
    # and that must be visible in the email rather than silent.
    if not sources:
        errors.insert(0, "Chart of the Day: no tracked chart source could be loaded.")
    else:
        last = last_featured_at(state)
        now = dt.datetime.now(dt.timezone.utc)
        if last is not None and now - last > dt.timedelta(days=STALE_CHART_DAYS):
            errors.insert(0, "Chart of the Day: no tracked chart has been featured since "
                             f"{last.date().isoformat()}; check the chart sources.")
    return None


def select_fallback_chart(now: dt.datetime, errors: list[str]) -> dict[str, Any] | None:
    """Chart of the Day fallback for when nothing tracked has anything new.

    Looks at a short list of outlets whose posts are themselves built around
    a chart or graphic (rather than general news that happens to include an
    image), and features the most recent, most clearly chart-led one with an
    image, clearly labelled in the newsletter as spotted-in-coverage rather
    than one of the tracked series.
    """
    candidates = recent(deduplicate(collect(FALLBACK_CHART_FEEDS, errors)), now, 96)
    with_image = [item for item in candidates if item.image_url]
    if not with_image:
        return None
    for item in with_image:
        text = f"{item.title} {item.description}".lower()
        item.score = rank(item, now) + (10 if any(k in text for k in CHART_KEYWORDS) else 0)
    with_image.sort(key=lambda item: item.score, reverse=True)
    best = with_image[0]
    return {
        "id": "fallback",
        "title": best.title,
        "image_url": best.image_url,
        "caption": best.description[:280] or best.title,
        "explanation": "",
        "source": best.source,
        "source_url": best.link,
        "updated_at": now.isoformat(),
        "is_fallback": True,
    }


def mark_chart_featured(chart: dict[str, Any] | None) -> None:
    if not chart or chart.get("is_fallback") or "signature" not in chart:
        return
    state = load_chart_state()
    state[chart["id"]] = {
        "featured_signature": chart["signature"],
        "featured_data_date": chart.get("data_date", ""),
        "featured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    CHART_STATE.parent.mkdir(exist_ok=True)
    CHART_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

