"""Weather Snapshot via Open-Meteo (no key needed)."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .common import fetch

def weather(city: str, lat: float, lon: float, timezone: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": timezone,
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
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
    }

