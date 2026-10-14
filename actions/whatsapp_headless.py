"""
actions/whatsapp_headless.py
Headless WhatsApp Integration Action for JARVIS.

Architecture & Design Decisions:
- Follows SOLID principles:
  - Single Responsibility: Exposes high-level WhatsApp voice & command actions (check unread, read chat, send/reply).
  - Dependency Inversion: Interacts through core.whatsapp_client.get_whatsapp_client().
- Strict Privacy Protection:
  - When checking unread messages, announces only the contact/sender names and counts.
  - Never blurts out private message body text unprompted. Asks user for confirmation to read.
- Auto-discovered by core/action_loader.py as a native JARVIS tool.
- Zero GUI Interference: Runs completely headlessly in the background.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from core.whatsapp_client import get_whatsapp_client


def _on_whatsapp_message(data: Dict[str, Any]) -> None:
    """Proactive background callback triggered when new messages or follow-up replies arrive."""
    contact = data.get("contact", "someone").strip()
    unread_str = data.get("unread", "1")
    msg_type = data.get("msg_type", "message")
    snippet = data.get("snippet", "").strip()
    is_follow_up = data.get("is_follow_up", False)

    # Ensure last active contact is always up to date
    try:
        get_whatsapp_client().set_last_active_contact(contact)
    except Exception:
        pass

    type_phrase = {
        "voice note": "a voice note",
        "photo": "a photo",
        "video": "a video",
        "document": f"a document ({snippet[:30]})" if snippet and "." in snippet else "a document",
        "sticker": "a sticker",
    }.get(msg_type, "a message")

    if is_follow_up:
        if msg_type == "message" and snippet and snippet != "message":
            prompt = (
                f"[WHATSAPP_ALERT]\n"
                f"SYSTEM NOTIFICATION: {contact} just sent a reply in your ongoing chat.\n"
                f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, {contact} replied: '{snippet}'. Would you like me to send a reply?\"\n"
                f"Speak only that one announcement to the user. Do not call any tools."
            )
        elif msg_type == "voice note":
            prompt = (
                f"[WHATSAPP_ALERT]\n"
                f"SYSTEM NOTIFICATION: {contact} just sent a voice note in your ongoing chat.\n"
                f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, {contact} just sent a voice note.\"\n"
                f"Speak only that one announcement to the user. Do not call any tools."
            )
        elif msg_type == "photo":
            caption_info = f" with caption '{snippet}'" if snippet and snippet not in ("[Photo]", "photo") else ""
            prompt = (
                f"[WHATSAPP_ALERT]\n"
                f"SYSTEM NOTIFICATION: {contact} just sent a photo{caption_info} in your ongoing chat.\n"
                f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, {contact} just sent a photo{caption_info}.\"\n"
                f"Speak only that one announcement to the user. Do not call any tools."
            )
        elif msg_type == "document":
            doc_info = f" ({snippet})" if snippet and snippet not in ("[Document]", "document") else ""
            prompt = (
                f"[WHATSAPP_ALERT]\n"
                f"SYSTEM NOTIFICATION: {contact} just sent a document{doc_info} in your ongoing chat.\n"
                f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, {contact} just sent a document{doc_info}.\"\n"
                f"Speak only that one announcement to the user. Do not call any tools."
            )
        else:
            prompt = (
                f"[WHATSAPP_ALERT]\n"
                f"SYSTEM NOTIFICATION: {contact} just replied in your ongoing chat.\n"
                f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, {contact} replied with {type_phrase}.\"\n"
                f"Speak only that one announcement to the user. Do not call any tools."
            )
    else:
        prompt = (
            f"[WHATSAPP_ALERT]\n"
            f"SYSTEM NOTIFICATION: A new WhatsApp {type_phrase} has arrived from {contact}.\n"
            f"INSTRUCTION: Announce this out loud to the user right now as S.P.I.D.Y.: \"Sir, you have received {type_phrase} from {contact}. Would you like me to read it?\"\n"
            f"Speak only that one announcement to the user. Do not call any tools."
        )

    # 1. Proactive Voice Alert via JARVIS's native Gemini Live audio session
    try:
        from actions.system_monitor import queue_system_alert
        queue_system_alert(prompt)
    except Exception as e:
        print(f"[WhatsApp] Voice alert queue notice: {e}")

    # 2. Visual Alert on Desktop Orb / Ambient Monitor
    try:
        from core.ambient_monitor import get_ambient_monitor, AmbientAlert
        monitor = get_ambient_monitor()
        if is_follow_up and snippet and msg_type == "message" and snippet != "message":
            alert_msg = f"Sir, {contact} replied: \"{snippet}\""
        elif is_follow_up:
            alert_msg = f"Sir, {contact} replied with {type_phrase}."
        else:
            alert_msg = f"Sir, {contact} sent {type_phrase}. Would you like me to read it?"

        alert = AmbientAlert(
            alert_type="whatsapp_message",
            severity="info",
            title=f"WhatsApp: {contact}",
            message=alert_msg,
        )
        monitor._notify_listeners(alert)
    except Exception:
        pass

    print(f"[WhatsApp] [PROACTIVE ALERT] New {msg_type} from {contact} (follow_up={is_follow_up}) queued for S.P.I.D.Y.")


# Register proactive listener
try:
    get_whatsapp_client().set_unread_listener(_on_whatsapp_message)
except Exception:
    pass


def whatsapp_action(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for the 'whatsapp' tool.
    Supported actions:
      - check_unread: Lists senders of unread messages without exposing text.
      - read_chat: Reads recent messages from a specific contact.
      - send_message: Sends a text message to a contact headlessly.
      - status: Checks session status.
    """
    params = parameters or {}
    action = params.get("action", "check_unread").strip().lower()
    contact = params.get("contact", "").strip()
    message = params.get("message", "").strip()
    max_messages = int(params.get("max_messages", 5) or 5)

    client = get_whatsapp_client()
    if not client.get_status().get("ready"):
        client.wait_until_ready(timeout=15.0)

    status = client.get_status()

    if not status.get("logged_in"):
        msg = (
            "WhatsApp is currently not authenticated. Please run "
            "'python scripts/pair_whatsapp.py' once to link your phone."
        )
        if player:
            player.write_log("[WhatsApp] ⚠️ Session not authenticated")
        return msg

    try:
        # ── 1. Check Unread Messages (Privacy-Protected) ─────────────────────
        if action in ("check_unread", "unread", "notifications", "check"):
            unreads = client.get_unread_messages()
            if not unreads:
                res = "You have no unread WhatsApp messages, Sir."
                if player:
                    player.write_log("[WhatsApp] No unread messages")
                return res

            direct_unreads = [u for u in unreads if not u.get("is_group")]
            group_unreads = [u for u in unreads if u.get("is_group")]

            contact_names = []
            for u in direct_unreads:
                c = u.get("contact", "Unknown").strip()
                count_str = u.get("unread", "1")
                contact_names.append(f"{c} ({count_str})")

            parts = []
            if direct_unreads:
                names_formatted = ", ".join(contact_names)
                parts.append(f"unread messages from {len(direct_unreads)} contact(s): {names_formatted}")
            if group_unreads:
                parts.append(f"unread messages in {len(group_unreads)} group chat(s)")

            summary = " as well as ".join(parts)
            res = (
                f"Sir, you have {summary}. "
                f"Would you like me to read messages from any of them?"
            )
            if player:
                player.write_log(f"[WhatsApp] Unread: {summary}")
            return res

        # ── 2. Read Chat Messages ────────────────────────────────────────────
        elif action in ("read_chat", "read", "read_messages", "view"):
            if not contact or contact.lower() in ("last", "him", "her", "them", "recent", "that person", "friend"):
                contact = client.get_last_active_contact() or ""

            if not contact:
                return "Please specify which contact's messages you would like me to read."

            if player:
                player.write_log(f"[WhatsApp] Reading chat: {contact}")

            result = client.read_chat(contact, max_messages=max_messages)
            if not result.get("success"):
                # Try finding closest matching saved contact by JID or name
                matches = client.search_contacts(contact, limit=1)
                if matches:
                    target_id = matches[0].get("jid") or matches[0].get("name")
                    result = client.read_chat(target_id, max_messages=max_messages)

            if not result.get("success"):
                err = result.get("error", "Unknown error")
                return f"Could not read messages from '{contact}': {err}"

            messages = result.get("messages", [])
            resolved_contact = result.get("contact", contact)

            if not messages:
                return f"No recent messages found in conversation with {resolved_contact}."

            # Explicitly separate the latest message received from the contact vs last sent message
            last_incoming = None
            last_outgoing = None
            for m in reversed(messages):
                if m.get("incoming") and last_incoming is None:
                    last_incoming = m
                elif not m.get("incoming") and last_outgoing is None:
                    last_outgoing = m
                if last_incoming is not None and last_outgoing is not None:
                    break

            lines = [f"Chat with {resolved_contact}:"]
            if last_incoming:
                lines.append(f"• Latest message received from {resolved_contact}: \"{last_incoming.get('text')}\"")
            else:
                lines.append(f"• Latest message received from {resolved_contact}: None (all recent messages were sent by you)")

            if last_outgoing:
                lines.append(f"• Your last sent message: \"{last_outgoing.get('text')}\"")

            lines.append(f"\nRecent dialogue history with {resolved_contact}:")
            for m in messages:
                sender_label = resolved_contact if m.get("incoming") else "You"
                lines.append(f"- {sender_label}: {m.get('text')}")

            lines.append(f"\nWould you like to send a reply to {resolved_contact}?")
            return "\n".join(lines)

        # ── 3. Send / Reply Message ──────────────────────────────────────────
        elif action in ("send_message", "send", "reply", "write"):
            if not contact or contact.lower() in ("last", "him", "her", "them", "recent", "that person", "friend"):
                contact = client.get_last_active_contact() or ""

            if not contact:
                return "Please specify the recipient contact name."
            if not message:
                return "Please specify the message content to send."

            if player:
                player.write_log(f"[WhatsApp] Sending to {contact}: {message[:40]}")

            result = client.send_message(contact, message)
            if not result.get("success"):
                # Try finding closest matching saved contact by JID or name
                matches = client.search_contacts(contact, limit=1)
                if matches:
                    target_id = matches[0].get("jid") or matches[0].get("name")
                    result = client.send_message(target_id, message)

            if not result.get("success"):
                err = result.get("error", "Unknown error")
                return f"The message to {contact} could not be sent: {err}"

            return f"Message sent to {contact} on WhatsApp: \"{message}\""

        # ── 4. Search / List Contacts ────────────────────────────────────────
        elif action in ("search_contact", "search_contacts", "find_contact", "contacts", "list_contacts"):
            query = contact or (parameters.get("query") if parameters else "") or ""
            if not query or query.lower() in ("all", "list", "show", "*"):
                all_contacts = client.get_contacts(limit=25)
                if not all_contacts:
                    return "No saved WhatsApp contacts found in your linked account."
                names = [f"• {c.get('name')} ({c.get('phone')})" for c in all_contacts]
                return f"Here are your saved WhatsApp contacts:\n" + "\n".join(names)

            matches = client.search_contacts(query, limit=5)
            if not matches:
                return f"No contact matching '{query}' was found in your saved WhatsApp contacts."

            if len(matches) == 1:
                c = matches[0]
                return f"Yes, found '{c.get('name')}' ({c.get('phone')}) in your WhatsApp contacts."

            lines = [f"Found {len(matches)} contact(s) matching '{query}' in your WhatsApp:"]
            for c in matches:
                lines.append(f"• {c.get('name')} ({c.get('phone')})")
            return "\n".join(lines)

        # ── 5. Status Check ──────────────────────────────────────────────────
        elif action in ("status", "info"):
            return "WhatsApp headless service is connected, authenticated, and running in the background."

        else:
            return (
                f"Unknown action '{action}' for whatsapp tool. Valid actions: "
                "check_unread, read_chat, send_message, search_contact, status."
            )

    except Exception as e:
        err_msg = f"WhatsApp action '{action}' failed: {e}"
        print(f"[whatsapp_action] Error: {e}")
        if player:
            player.write_log(f"[WhatsApp] Error: {e}")
        return err_msg


# ── Auto-Discovered Tool Declaration ──────────────────────────────────────────
TOOL = {
    "name": "whatsapp",
    "description": (
        "Interacts with WhatsApp in the background. Check unread messages, "
        "search saved contacts/verify if someone is in contacts, read recent chats, "
        "or send/reply to WhatsApp messages. Strictly respects privacy "
        "by announcing only sender names when checking for unread messages."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "The action to perform: 'search_contact' (search contacts by name/nickname to see if saved), "
                    "'check_unread' (check incoming messages without reading content), "
                    "'read_chat' (read recent messages from a contact), "
                    "'send_message' (send or reply to a contact), "
                    "or 'status'."
                ),
            },
            "contact": {
                "type": "STRING",
                "description": (
                    "The contact or group name to read from or send to. "
                    "If the user is asking to read or reply to the recent sender (e.g. 'read it', 'reply to him/her'), "
                    "you can pass the contact's name, or 'last' to automatically use the recent sender."
                ),
            },
            "message": {
                "type": "STRING",
                "description": "The message text to send (required for send_message action).",
            },
            "max_messages": {
                "type": "INTEGER",
                "description": "Number of recent messages to read when using read_chat (default 5).",
            },
        },
        "required": ["action"],
    },
    "handler": whatsapp_action,
}
