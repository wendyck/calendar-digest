# verify_calendar.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone

# --- edit these three ---
KEY_FILE = "testfile.json"
IMPERSONATE = "email"                        # the user whose calendar you're reading (you)
CALENDAR_ID = "calemail"
# ------------------------

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

creds = service_account.Credentials.from_service_account_file(
    KEY_FILE, scopes=SCOPES
).with_subject(IMPERSONATE)

service = build("calendar", "v3", credentials=creds, cache_discovery=False)

now = datetime.now(timezone.utc).isoformat()
events = service.events().list(
    calendarId=CALENDAR_ID,
    timeMin=now,
    maxResults=10,
    singleEvents=True,
    orderBy="startTime",
).execute().get("items", [])

if not events:
    print("Connected OK — no upcoming events found.")
for e in events:
    start = e["start"].get("dateTime", e["start"].get("date"))
    print(f'{start}  {e.get("summary", "(no title)")}  [{e.get("location", "no location")}]')