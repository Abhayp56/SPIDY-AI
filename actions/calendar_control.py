"""Google Calendar integration: list upcoming events and create simple events."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from memory.config_manager import get_base_dir, load_api_keys

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError("Google Calendar packages are missing; install requirements.txt.")

    cfg = load_api_keys().get("plugin_config", {}).get("google_calendar", {})
    client_path = Path(cfg.get("client_json", "")) if cfg.get("client_json") else get_base_dir() / "config" / "google_calendar_client.json"
    if not client_path.is_file():
        raise RuntimeError(f"Google OAuth client JSON is not configured. Save the Google Desktop OAuth file to {client_path}.")
    data_dir = Path.home() / "AppData" / "Local" / "SPIDY-AI" / "tokens"
    data_dir.mkdir(parents=True, exist_ok=True)
    token_path = data_dir / "google_calendar.json"
    creds = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_path), _SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def calendar_control(parameters: dict, **_kwargs) -> str:
    action = str(parameters.get("action", "list")).lower().strip()
    try:
        service = _service()
        if action in ("list", "upcoming", "today"):
            limit = max(1, min(int(parameters.get("limit", 10)), 20))
            now = dt.datetime.now(dt.timezone.utc)
            end = now + dt.timedelta(days=1 if action == "today" else 30)
            events = service.events().list(calendarId="primary", timeMin=now.isoformat(),
                timeMax=end.isoformat(), maxResults=limit, singleEvents=True,
                orderBy="startTime").execute().get("items", [])
            if not events:
                return "There are no upcoming calendar events in that period."
            return "Upcoming events: " + "; ".join(
                f"{e.get('summary', 'Untitled')} at {e.get('start', {}).get('dateTime', e.get('start', {}).get('date', 'unknown time'))}"
                for e in events)
        if action == "create":
            title = str(parameters.get("title", "")).strip()
            start = str(parameters.get("start", "")).strip()
            end = str(parameters.get("end", "")).strip()
            if not title or not start or not end:
                return "To create a calendar event, provide title, start, and end in ISO-8601 format."
            event = {"summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}}
            if parameters.get("description"):
                event["description"] = str(parameters["description"])
            created = service.events().insert(calendarId="primary", body=event, sendUpdates="none").execute()
            return f"Added '{title}' to your calendar."
        return "Calendar action must be list, today, upcoming, or create."
    except Exception as exc:
        return f"Google Calendar couldn't complete that request: {exc}"


TOOL = {
    "name": "calendar_control",
    "description": "Read upcoming Google Calendar events or create an event. For list requests, optionally use today/upcoming. Create requires title, start and end ISO-8601 date-times; no attendees or invitations are added.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["list", "today", "upcoming", "create"]},
        "title": {"type": "STRING"}, "start": {"type": "STRING"}, "end": {"type": "STRING"},
        "description": {"type": "STRING"}, "limit": {"type": "INTEGER"}}, "required": ["action"]},
    "handler": calendar_control,
}
