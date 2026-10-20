"""Outlook mail via Microsoft Graph: read/search and save drafts; no send operation."""
from __future__ import annotations

import requests
from memory.config_manager import load_api_keys

_SCOPES = ["User.Read", "Mail.Read", "Mail.ReadWrite"]
_GRAPH = "https://graph.microsoft.com/v1.0"


def _token():
    try:
        import msal
        from msal_extensions import PersistedTokenCache, build_persistence
    except ImportError:
        raise RuntimeError("MSAL token-cache packages are missing; install requirements.txt.")
    cfg = load_api_keys().get("plugin_config", {}).get("outlook_mail", {})
    client_id = str(cfg.get("client_id") or "").strip()
    if not client_id:
        raise RuntimeError("Outlook is not configured. Add plugin_config.outlook_mail.client_id for a Microsoft public client app.")
    authority = "https://login.microsoftonline.com/common"
    from pathlib import Path
    cache_dir = Path.home() / "AppData" / "Local" / "SPIDY-AI" / "tokens"
    cache_dir.mkdir(parents=True, exist_ok=True)
    persistence = build_persistence(str(cache_dir / "outlook_msal_cache.bin"), fallback_to_plaintext=False)
    token_cache = PersistedTokenCache(persistence)
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=token_cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(_SCOPES, account=accounts[0]) if accounts else None
    if not result:
        flow = app.initiate_device_flow(scopes=_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(flow.get("error_description", "Could not start Microsoft sign-in."))
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", result.get("error", "Microsoft sign-in failed.")))
    return result["access_token"]


def outlook_mail(parameters: dict, **_kwargs) -> str:
    action = str(parameters.get("action", "list")).lower().strip()
    try:
        headers = {"Authorization": f"Bearer {_token()}", "Prefer": 'outlook.body-content-type="text"'}
        if action in ("list", "search", "unread"):
            limit = max(1, min(int(parameters.get("limit", 10)), 25))
            params = {"$top": limit, "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview", "$orderby": "receivedDateTime desc"}
            query = str(parameters.get("query", "")).strip()
            if action == "unread":
                params["$filter"] = "isRead eq false"
            elif query:
                params["$search"] = f'"{query}"'
                headers["ConsistencyLevel"] = "eventual"
            resp = requests.get(f"{_GRAPH}/me/messages", headers=headers, params=params, timeout=20)
            if not resp.ok:
                return f"Outlook returned HTTP {resp.status_code}: {resp.text[:300]}"
            messages = resp.json().get("value", [])
            if not messages:
                return "No matching Outlook messages found."
            return "Outlook messages: " + "; ".join(
                f"{m.get('subject') or '(no subject)'} from {m.get('from', {}).get('emailAddress', {}).get('address', 'unknown')}"
                f" — {m.get('bodyPreview', '')[:160]}" for m in messages)
        if action == "draft":
            recipient = str(parameters.get("to", "")).strip()
            subject = str(parameters.get("subject", "")).strip()
            body = str(parameters.get("body", "")).strip()
            if not recipient or not subject or not body:
                return "A draft needs to, subject, and body."
            payload = {"subject": subject, "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}]}
            resp = requests.post(f"{_GRAPH}/me/messages", headers=headers, json=payload, timeout=20)
            if not resp.ok:
                return f"Outlook couldn't save the draft (HTTP {resp.status_code}): {resp.text[:300]}"
            return f"Saved a draft to {recipient} with subject '{subject}'. It has not been sent."
        return "Outlook action must be list, search, unread, or draft. Sending email is not available through this action."
    except (requests.RequestException, RuntimeError) as exc:
        return f"Outlook mail couldn't complete that request: {exc}"


TOOL = {"name": "outlook_mail", "description": "Read recent or unread Outlook email, search messages, or save a draft. This action cannot send email.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["list", "search", "unread", "draft"]},
        "query": {"type": "STRING"}, "limit": {"type": "INTEGER"},
        "to": {"type": "STRING"}, "subject": {"type": "STRING"}, "body": {"type": "STRING"}}, "required": ["action"]},
    "handler": outlook_mail}
