# Voice integrations

These integrations are discovered from `actions/` when SPIDY starts. Install
the updated dependencies with the same Python environment used to run SPIDY:

```powershell
C:\Users\Asus\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Provider credentials are stored in `config/api_keys.json` under
`plugin_config`. This file is ignored by Git. Do not paste credentials into
chat or commit them.

```json
{
  "plugin_config": {
    "google_calendar": {},
    "todoist": { "api_token": "YOUR_TODOIST_API_TOKEN" },
    "outlook_mail": { "client_id": "YOUR_MICROSOFT_APP_CLIENT_ID" },
    "spotify": {
      "client_id": "YOUR_SPOTIFY_CLIENT_ID",
      "client_secret": "YOUR_SPOTIFY_CLIENT_SECRET",
      "redirect_uri": "http://127.0.0.1:8888/callback"
    }
  }
}
```

Keep any existing keys in `api_keys.json` when adding these entries.

## Connect each service

- **Google Calendar:** In Google Cloud, enable the Calendar API and create a
  Desktop OAuth client. Save its downloaded client JSON as
  `config/google_calendar_client.json`. The first calendar voice command opens
  Google's sign-in/consent flow; the refresh token is saved in the current
  Windows user's `%LOCALAPPDATA%\SPIDY-AI\tokens` folder.
- **Todoist:** Copy the API token from Todoist Settings → Integrations →
  Developer into `plugin_config.todoist.api_token`.
- **Outlook:** Register a Microsoft Entra public-client app, enable public
  client/device-code flow, and add delegated `User.Read`, `Mail.Read`, and
  `Mail.ReadWrite` permissions. Put its application (client) ID into
  `plugin_config.outlook_mail.client_id`. Sign-in uses a device code in the
  console. The action can read/search and save drafts; it has no send action or
  `Mail.Send` permission. Its token cache uses the operating system's protected
  storage through MSAL Extensions.
- **Spotify:** Create a Spotify Web API app and add the exact redirect URI
  `http://127.0.0.1:8888/callback` in its settings. Put the client ID and
  secret in `plugin_config.spotify`. The first request opens Spotify sign-in.
  Playback control requires Spotify Premium and an active Spotify playback
  device.

Restart SPIDY after adding the credentials. OAuth token caches are kept under
the current Windows user's local application data folder and are not added to
the repository. Outlook's cache is OS-protected; the Google and Spotify SDK
caches are local files protected by the current Windows user account.

## Example voice commands

- “What's on my calendar today?”
- “Add dentist appointment to my calendar tomorrow at 3 PM.” (SPIDY must
  provide ISO-8601 start and end times to the calendar action.)
- “What are my open Todoist tasks?” / “Add buy groceries to Todoist.”
- “Read my latest unread Outlook emails.” / “Draft an email to Alex about the
  meeting.”
- “What's playing on Spotify?” / “Play Not Your Type on Spotify.”

Calendar creation needs unambiguous start and end times; ask for them if the
request doesn't establish both. Outlook drafts are saved but never sent by this
integration.
