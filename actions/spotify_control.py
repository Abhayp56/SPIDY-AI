"""Spotify playback control and track search."""
from __future__ import annotations

from pathlib import Path
from memory.config_manager import load_api_keys

_SCOPES = "user-read-playback-state user-read-currently-playing user-modify-playback-state"


def _client():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        raise RuntimeError("Spotify integration requires spotipy; install requirements.txt.")
    cfg = load_api_keys().get("plugin_config", {}).get("spotify", {})
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Spotify is not configured. Add plugin_config.spotify.client_id and client_secret.")
    cache_dir = Path.home() / "AppData" / "Local" / "SPIDY-AI" / "tokens"
    cache_dir.mkdir(parents=True, exist_ok=True)
    auth = SpotifyOAuth(client_id=client_id, client_secret=client_secret,
        redirect_uri=str(cfg.get("redirect_uri") or "http://127.0.0.1:8888/callback"),
        scope=_SCOPES, cache_path=str(cache_dir / "spotify_cache.json"), open_browser=True)
    return spotipy.Spotify(auth_manager=auth)


def spotify_control(parameters: dict, **_kwargs) -> str:
    action = str(parameters.get("action", "now_playing")).lower().strip()
    try:
        sp = _client()
        if action in ("now_playing", "status"):
            item = (sp.current_playback() or {}).get("item")
            if not item:
                return "Spotify is not currently playing anything."
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            return f"Now playing {item.get('name')} by {artists}."
        if action == "search":
            query = str(parameters.get("query", "")).strip()
            if not query:
                return "Provide a track or artist to search for."
            items = sp.search(q=query, type="track", limit=5).get("tracks", {}).get("items", [])
            if not items:
                return "No Spotify tracks found."
            return "Spotify matches: " + "; ".join(f"{x['name']} by {', '.join(a['name'] for a in x['artists'])}" for x in items)
        if action == "pause":
            sp.pause_playback(); return "Paused Spotify playback."
        if action == "resume":
            sp.start_playback(); return "Resumed Spotify playback."
        if action == "next":
            sp.next_track(); return "Skipped to the next Spotify track."
        if action == "previous":
            sp.previous_track(); return "Went back to the previous Spotify track."
        if action == "play":
            query = str(parameters.get("query", "")).strip()
            if not query:
                return "Provide a track or artist to play."
            items = sp.search(q=query, type="track", limit=1).get("tracks", {}).get("items", [])
            if not items:
                return "No Spotify track found for that request."
            sp.start_playback(uris=[items[0]["uri"]])
            return f"Playing {items[0]['name']} by {', '.join(a['name'] for a in items[0]['artists'])}."
        return "Spotify action must be now_playing, search, play, pause, resume, next, or previous."
    except Exception as exc:
        return f"Spotify couldn't complete that request: {exc}"


TOOL = {"name": "spotify_control", "description": "Search tracks, report current playback, play a matching track, pause/resume, or skip. Spotify account and an active playback device are required for playback control.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["now_playing", "search", "play", "pause", "resume", "next", "previous"]},
        "query": {"type": "STRING"}}, "required": ["action"]}, "handler": spotify_control}
