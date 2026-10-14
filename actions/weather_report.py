import json
import logging
import urllib.parse
import webbrowser
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_WMO_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _fetch_open_meteo_weather(city: str) -> Optional[str]:
    """Fetches real-time weather using Open-Meteo (fast, unmetered, zero API key)."""
    try:
        import requests

        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
        r = requests.get(geo_url, timeout=5.0, headers={"User-Agent": "SPIDY/1.0"})
        if r.status_code != 200:
            return None

        geo = r.json()
        results = geo.get("results")
        if not results:
            return None

        loc = results[0]
        lat, lon = loc.get("latitude"), loc.get("longitude")
        resolved_name = loc.get("name", city)

        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        rw = requests.get(w_url, timeout=5.0, headers={"User-Agent": "SPIDY/1.0"})
        if rw.status_code != 200:
            return None

        w_data = rw.json()
        cw = w_data.get("current_weather", {})
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        code = cw.get("weathercode", 0)
        condition = _WMO_WEATHER_CODES.get(code, "clear conditions")

        return f"Sir, the weather in {resolved_name} is currently {condition} at {temp}°C with winds around {wind} km/h."
    except Exception as e:
        logger.debug(f"[Weather] Open-Meteo lookup failed: {e}")
        return None


def weather_action(
    parameters: dict,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    city = parameters.get("city")
    when = parameters.get("time", "today")
    open_browser = bool(parameters.get("open_browser", False))

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()
    search_query = f"weather in {city} {when}"
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(search_query)}"

    # If user explicitly requested to open the browser on screen
    if open_browser:
        try:
            webbrowser.open(url)
            msg = f"Showing the weather for {city}, {when} in your browser, sir."
            _log(msg, player)
            return msg
        except Exception as e:
            msg = f"Sir, I couldn't open the browser for the weather report: {e}"
            _log(msg, player)
            return msg

    # 1. Fetch real-time spoken forecast
    weather_report = _fetch_open_meteo_weather(city)

    # 2. Resilient fallback: if real-time forecast could not be fetched, open browser
    if not weather_report:
        try:
            webbrowser.open(url)
            weather_report = f"Sir, I have opened the weather report for {city} in your browser."
        except Exception:
            weather_report = f"Sir, I could not retrieve the weather for {city} at this time."

    _log(weather_report, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=weather_report)
        except Exception:
            pass

    return weather_report


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "weather_report",
    "description": "Gives the weather report to user verbally or opens browser if requested",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "City name"
            },
            "open_browser": {
                "type": "BOOLEAN",
                "description": "Set to true only if the user explicitly asks to view/open the weather in their browser"
            }
        },
        "required": [
            "city"
        ]
    },
    "handler": weather_action,
}
