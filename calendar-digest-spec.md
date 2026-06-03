# Calendar + Traffic Morning Digest — Build Spec

## Project summary

Build a serverless AWS application that emails a daily calendar digest at 5 AM Pacific. The digest lists Google Calendar events for today and the next 7 days, and for events with physical addresses, flags relevant WSDOT highway alerts (current incidents and planned closures) that may affect travel to or from the event.

This is a single-user personal project. Optimize for simplicity and reliability over scale or flexibility.

## Tech stack

- **Language**: Python 3.12
- **Runtime**: AWS Lambda (ARM64 / `arm64`)
- **Schedule**: EventBridge Scheduler (NOT CloudWatch Events / EventBridge Rules — Scheduler supports timezones natively)
- **Email**: Amazon SES (sandbox mode, sender = recipient = the user's verified address)
- **Secrets**: AWS Secrets Manager
- **Observability**: CloudWatch Logs + a CloudWatch alarm on Lambda errors → SNS topic → email subscription
- **IaC**: AWS SAM (`infra/template.yaml`). SAM is a thin layer over CloudFormation: the `AWS::Serverless::*` resources expand into ordinary CloudFormation at deploy time, and `sam build` handles dependency packaging (including native arm64 wheels) so there's no hand-rolled build script. Deployed via `sam build --use-container` + `sam deploy`.
- **Region**: `us-west-2`

## External services

1. **Google Calendar API** — service account with domain-wide delegation, impersonating a Workspace user. Scope: `https://www.googleapis.com/auth/calendar.readonly`. (This is the broad read-only calendar scope, not the narrower `calendar.events.readonly`. It's required because the target calendar is a secondary calendar the impersonated user only has *reader* access to — see the Calendar configuration note below. This exact scope string must match in three places: this spec, `calendar_client.py`, and the Admin console domain-wide-delegation entry.)
2. **WSDOT Traveler Information API** — Highway Alerts endpoint. Free access code required (request at https://wsdot.wa.gov/traffic/api/).
3. **Anthropic API** — Claude is used for matching alerts to events. Model: `claude-sonnet-4-5` (or latest Sonnet at build time).

## Schedule

EventBridge Scheduler expression:

```
cron(0 5 * * ? *)
```

Timezone: `America/Los_Angeles`. Runs every day, 7 days a week.

## High-level flow

1. Lambda triggered by EventBridge Scheduler.
2. Fetch secrets from Secrets Manager (cache in module scope for warm invocations).
3. Fetch Google Calendar events from now → now + 7 days.
4. Fetch active WSDOT highway alerts (filter to alerts whose `EndTime` is in the future).
5. Call Anthropic API once, passing events + alerts, to get structured relevance matches.
6. Build a `Digest` object (structured, channel-agnostic).
7. Render to HTML email via the email renderer.
8. Send via SES.
9. Log structured summary (event count, alert count, matches, send status).

If step 4 or 5 fails, proceed without traffic info and include a note in the digest: "Traffic data unavailable today." Steps 3, 7, and 8 must succeed for the run to be considered successful; failures here should raise and trigger the CloudWatch alarm.

## Project structure

```
calendar-digest/
├── README.md
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── handler.py              # Lambda entrypoint
│   ├── config.py               # Env vars, constants
│   ├── secrets.py              # Secrets Manager client + caching
│   ├── calendar_client.py      # Google Calendar wrapper
│   ├── wsdot_client.py         # WSDOT API wrapper
│   ├── relevance.py            # Claude API call for matching
│   ├── digest.py               # Digest dataclass + builder
│   ├── renderers/
│   │   ├── __init__.py
│   │   ├── email_renderer.py   # HTML + text email
│   │   └── slack_renderer.py   # STUB ONLY for v1 — see "Future-proofing for Slack"
│   ├── senders/
│   │   ├── __init__.py
│   │   └── ses_sender.py
│   └── models.py               # Shared dataclasses (Event, Alert, RelevanceMatch, Digest)
├── infra/
│   ├── template.yaml           # SAM template (expands to all the CloudFormation resources)
│   ├── samconfig.toml          # SAM deploy config (stack name, region, params, capabilities)
│   └── README.md               # Deployment commands and parameter explanations
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── calendar_response.json
│   │   ├── wsdot_alerts.json
│   │   └── claude_match_response.json
│   ├── test_calendar_client.py
│   ├── test_wsdot_client.py
│   ├── test_relevance.py
│   ├── test_digest.py
│   ├── test_email_renderer.py
│   └── test_handler.py
├── scripts/
│   ├── bootstrap_oauth.py      # NOT NEEDED — using service account, but keep file for v1.5 OAuth fallback
│   └── local_run.py            # Run handler locally with real or mocked deps
├── requirements.txt            # Runtime deps — sam build reads this to package the Lambda
├── requirements-dev.txt        # Test/dev deps (pytest, moto, etc.) — NOT packaged into the Lambda
└── .gitignore                  # Must include: .aws-sam/, .env, infra/samconfig.toml if it holds anything sensitive
```

## Data models

Use dataclasses (or Pydantic if preferred). All times are timezone-aware `datetime` objects in `America/Los_Angeles`.

```python
@dataclass
class Event:
    id: str
    summary: str
    start: datetime           # tz-aware, America/Los_Angeles
    end: datetime
    location: str | None      # raw string from Google Calendar
    all_day: bool
    is_virtual: bool          # True if location is missing or looks like a URL/meeting link

@dataclass
class Alert:
    id: str                          # WSDOT AlertID
    headline: str                    # HeadlineDescription
    category: str                    # EventCategory (Construction, Collision, etc.)
    priority: str                    # Lowest, Low, Medium, High, Highest
    roadway: str                     # e.g. "I-405"
    region: str                      # e.g. "Northwest"
    start_time: datetime             # tz-aware
    end_time: datetime | None        # tz-aware; may be None for open-ended

@dataclass
class RelevanceMatch:
    event_id: str
    alert_id: str
    note: str                        # short human-readable, e.g. "Southbound I-405 closure on return"

@dataclass
class Digest:
    generated_at: datetime
    events: list[Event]
    matches_by_event_id: dict[str, list[tuple[Alert, str]]]   # event_id -> [(alert, note), ...]
    traffic_data_available: bool     # False if WSDOT or Claude API failed
```

## Module specs

### `config.py`

Reads from environment variables (set by the SAM template's `Environment.Variables`):

- `SECRETS_ARN` — ARN of the single Secrets Manager secret (`calendar-digest/keys`) holding all three credentials as a JSON object
- `USER_EMAIL` — the user's email (recipient AND impersonated calendar user AND SES sender)
- `CALENDAR_ID` — the calendar to read. **Required (no default).** Typically the secondary calendar holding the events (see the calendar_client.py note). Do NOT default to `primary`, which resolves to the impersonated user's own nearly-empty calendar.
- `LOOKAHEAD_DAYS` — defaults to `7`
- `TIMEZONE` — defaults to `America/Los_Angeles`
- `ANTHROPIC_MODEL` — defaults to `claude-sonnet-4-5`
- `LOG_LEVEL` — defaults to `INFO`

### `secrets.py`

```python
def get_secrets(arn: str) -> dict: ...
```

- Fetches the single secret `calendar-digest/keys` by ARN via `boto3` Secrets Manager client.
- `json.loads` the `SecretString` and return the dict. Expected keys (snake_case):
  - `google_service_account` — the value is **itself a JSON string** (the full service-account key file). Callers must `json.loads()` it a second time to get the service-account dict before passing to `calendar_client`. Document this clearly; the nested-JSON parse is the single easiest thing to get wrong here.
  - `wsdot_access_code` — plain string.
  - `anthropic_api_key` — plain string.
- Cache the parsed dict in a module-level variable so warm invocations don't re-fetch.
- Provide a small typed accessor or constants for the three key names so they aren't stringly-typed throughout the codebase, e.g. `KEY_GOOGLE_SA = "google_service_account"`.

### `calendar_client.py`

```python
def fetch_events(
    service_account_info: dict,
    user_email: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
    timezone: str,
) -> list[Event]: ...
```

- Build credentials with `google.oauth2.service_account.Credentials.from_service_account_info(...).with_subject(user_email)`. The `with_subject` value is the **impersonated Workspace user**, which is NOT necessarily the same as the calendar being read — see next note.
- Scope: `https://www.googleapis.com/auth/calendar.readonly` (must match the Admin console delegation entry exactly).
- **Calendar configuration note**: `user_email` (the impersonation subject) and `calendar_id` (the calendar to read) are distinct. The events may live on a secondary calendar (e.g., a personal Gmail calendar shared into the Workspace user's account) that the impersonated Workspace user has reader access to, not on the impersonated user's own `primary`. So the call impersonates the Workspace user but reads `calendarId=<the-secondary-calendar-id>`. Do not collapse these two into one value, and do not default `calendar_id` to `primary` — `primary` resolves to the impersonated user's own (often empty) calendar and will return no events.
- Build service: `googleapiclient.discovery.build('calendar', 'v3', credentials=creds, cache_discovery=False)` (cache_discovery=False is important in Lambda — avoids `oauth2client` warnings and filesystem writes).
- Call `events().list(calendarId=..., timeMin=..., timeMax=..., singleEvents=True, orderBy='startTime', maxResults=250)`.
- Convert each event to the `Event` dataclass.
- Handle both timed events (`start.dateTime`) and all-day events (`start.date`).
- `is_virtual` heuristic: `location` is None/empty, OR contains `http://`/`https://`, OR matches common video conference patterns (`meet.google.com`, `zoom.us`, `teams.microsoft.com`).

### `wsdot_client.py`

```python
def fetch_alerts(access_code: str, lookahead_end: datetime) -> list[Alert]: ...
```

- Endpoint: `https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetAlertsAsJson?AccessCode={code}`
- Parse the JSON response. The date fields come in `.NET` format: `/Date(1234567890000-0700)/`. Write a helper to parse these into tz-aware datetimes.
- Filter to alerts where `EndTime` is None or `EndTime >= now`.
- Filter further to alerts where `StartTime <= lookahead_end` (i.e., not starting more than 7 days out).
- Map to `Alert` dataclass.
- Timeout: 10 seconds. On failure, raise `WSDOTUnavailableError`.

### `relevance.py`

```python
def match_alerts_to_events(
    api_key: str,
    model: str,
    events: list[Event],
    alerts: list[Alert],
) -> list[RelevanceMatch]: ...
```

- Use the `anthropic` Python SDK.
- One API call. Pass events with physical locations only (skip virtual ones — they can't have road impacts).
- If `events` is empty after filtering, or `alerts` is empty, return `[]` without calling the API.
- Use **structured output via a tool definition** (most reliable way to get JSON):

```python
TOOL = {
    "name": "record_relevant_alerts",
    "description": "Record which highway alerts are relevant to which calendar events.",
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "alert_id": {"type": "string"},
                        "note": {
                            "type": "string",
                            "description": "Short note for the digest, e.g. 'Southbound I-405 closure on return'. Max 80 chars."
                        }
                    },
                    "required": ["event_id", "alert_id", "note"]
                }
            }
        },
        "required": ["matches"]
    }
}
```

- Force the tool call via `tool_choice={"type": "tool", "name": "record_relevant_alerts"}`.
- System prompt should establish: you are matching highway alerts to calendar events; only flag alerts likely to affect driving to or from the event's location; consider both timing (does the alert's window overlap the event's travel window?) and geography (does the road affect a plausible route to the location from Seattle area?); err on the side of fewer false positives; if unsure, do not match.
- User message: a structured rendering of events (id, summary, location, start, end) and alerts (id, headline, roadway, category, priority, start_time, end_time).
- Timeout: 30 seconds.
- On failure, raise `RelevanceUnavailableError`; the handler will catch this and produce a digest without traffic notes.

Example system prompt scaffold (refine during build):

```
You match Washington State highway alerts to a user's calendar events to help
them anticipate traffic disruptions.

The user lives in the Seattle area. For each event with a physical address,
decide whether any of the provided highway alerts are likely to affect their
drive to or from that location.

Rules:
- Only match alerts whose active window overlaps the plausible travel window
  for the event (assume departure up to 2 hours before, return up to 3 hours
  after).
- Only match alerts on roads that are plausibly on the route between the
  Seattle area and the event location.
- For each match, write a brief, useful note (max 80 chars) describing the
  impact, e.g. "Southbound I-405 closure on return" or "Construction on
  I-5 N near destination".
- Prefer no match over a speculative one. False positives are worse than
  false negatives here.
- An event may match zero, one, or multiple alerts.
```

### `digest.py`

```python
def build_digest(
    events: list[Event],
    alerts: list[Alert],
    matches: list[RelevanceMatch],
    traffic_data_available: bool,
    now: datetime,
) -> Digest: ...
```

- Group events by day (in user's timezone).
- Build `matches_by_event_id` dict.
- Sort events within each day by start time.

### `renderers/email_renderer.py`

```python
def render_email(digest: Digest) -> tuple[str, str]:
    """Returns (subject, html_body). Also exposes render_text(digest) -> str for the multipart text alternative."""
```

- Subject: `Morning digest — {weekday}, {Month D}` (e.g., "Morning digest — Friday, May 30").
- Layout follows the **canonical example digest** (see "Canonical example digest (Option B)" below). The renderer's job is to reproduce that structure in HTML. Match it closely — it's the reference for what "done" looks like.
- HTML structure:
  - A header with a date line ("Saturday, May 30, 2026").
  - If `traffic_data_available is False`: a small notice banner ("Traffic data unavailable today — calendar only.").
  - One section per day. Each day starts with a day header. The first two days are labeled "TODAY — {weekday}, {Month D}" and "TOMORROW — {weekday}, {Month D}"; subsequent days are just "{weekday}, {Month D}". (In the plain-text version, prefix the header with `▌`; in HTML, render it as a styled heading with a left accent bar.)
  - Within each day, one block per event, in this order:
    - Event summary (bold).
    - Time range on its own line ("1:00 PM – 3:00 PM"), or "All day" for all-day events.
    - Location on its own line, prefixed with a 📍 marker, showing the **full address** (street, city, state, zip) when available. Omit this line entirely for virtual/location-less events.
    - For each relevant traffic match: a callout line prefixed with ⚠️ showing the note, e.g. "⚠️ Southbound I-405 weekend closure — plan extra time on the way home". Multiple matches → multiple ⚠️ lines.
  - Generous vertical spacing between event blocks (Option B is deliberately airy, not dense).
  - Footer with the generated timestamp.
- Emoji (☀ in the header, 📍 for location, ⚠️ for traffic) are part of the intended look — keep them. They render reliably in modern email clients.
- Keep CSS inline (Gmail-friendly). A single-column block layout with inline styles is fine; use a table-based layout if cross-client consistency proves flaky.
- Also produce a plain-text alternative for the multipart message that mirrors the same structure (the Option B mock below doubles as the plain-text target).

### Canonical example digest (Option B)

This is the reference the email renderer should reproduce. It uses real example events plus one illustrative traffic flag (the Sunday Monroe event with a southbound I-405 weekend closure). Treat the structure, ordering, spacing, and markers as the target; exact copy can vary.

```
☀  MORNING DIGEST
   Saturday, May 30, 2026
   ──────────────────────────────────

   ▌TODAY — Saturday, May 30

   U Village Things
   1:00 PM – 3:00 PM
   📍 2746 NE 45th St, Seattle, WA 98105


   ▌TOMORROW — Sunday, May 31

   Nosework Sniff and Go
   10:45 AM – 11:15 AM
   📍 Monroe Bus Barn, 17815 W Main St, Monroe, WA 98272
   ⚠️  Southbound I-405 weekend closure — plan extra time on the way home


   ▌Monday, June 1

   Rally Class
   1:30 PM – 2:30 PM
   📍 West Seattle Wonder Dogs, 6040 California Ave SW, Seattle, WA 98136


   ▌Tuesday, June 2

   Pilates
   9:00 AM – 10:00 AM
   📍 2601 76th Ave SE Ste. 103, Mercer Island, WA 98040


   ▌Friday, June 5

   Wellsprings-K9 — Licensed Massage / Rehab & Swim Therapy
   10:30 AM – 11:15 AM
   📍  2684 NE 49th St, Seattle, WA 98105


   ──────────────────────────────────
   Generated 5:00 AM, Sat May 30
```

Notes on the example for the implementer:
- Days with no events are omitted entirely (no empty day headers). The example happens to have an event every day in range; on a quieter week, only days with events appear.
- A day with a traffic-unavailable run would show the banner near the top: "Traffic data unavailable today — calendar only." and omit all ⚠️ lines.
- A virtual event (e.g., a Google Meet) would appear under its day with the summary and time but no 📍 line and no traffic check.
- Event titles are shown cleaned up where reasonable (e.g., the raw calendar entry "Wellsprings-K9: Wellspringsk9 1 hr Licensed Massage/Rehabilitation and Swim Therar" is rendered as a tidied "Wellsprings-K9 — Licensed Massage / Rehab & Swim Therapy"). Keep tidying conservative — don't drop information, just trim obvious duplication and truncation artifacts. If unsure, show the title verbatim.

### `senders/ses_sender.py`

```python
def send_email(sender: str, recipient: str, subject: str, html_body: str, text_body: str) -> str:
    """Returns the SES MessageId."""
```

- Use `boto3` SES client (`boto3.client('ses', region_name='us-west-2')`).
- Use `send_email` with both `Html` and `Text` bodies.
- Raise on failure.

### `handler.py`

```python
def lambda_handler(event, context):
    config = load_config()
    now = datetime.now(ZoneInfo(config.timezone))
    window_end = now + timedelta(days=config.lookahead_days)

    # Secrets — one fetch, one JSON object with three keys
    secrets = get_secrets(config.secrets_arn)
    google_sa = json.loads(secrets["google_service_account"])  # nested JSON: parse again
    wsdot_code = secrets["wsdot_access_code"]
    anthropic_key = secrets["anthropic_api_key"]

    # Calendar (must succeed)
    events = fetch_events(google_sa, config.user_email, config.calendar_id, now, window_end, config.timezone)

    # Traffic (best-effort)
    traffic_ok = True
    alerts = []
    matches = []
    try:
        alerts = fetch_alerts(wsdot_code, window_end)
        matches = match_alerts_to_events(anthropic_key, config.anthropic_model, events, alerts)
    except (WSDOTUnavailableError, RelevanceUnavailableError) as e:
        logger.warning("Traffic data unavailable: %s", e)
        traffic_ok = False

    # Build + send
    digest = build_digest(events, alerts, matches, traffic_ok, now)
    subject, html_body = render_email(digest)
    text_body = render_text(digest)
    message_id = send_email(config.user_email, config.user_email, subject, html_body, text_body)

    logger.info(json.dumps({
        "event_count": len(events),
        "alert_count": len(alerts),
        "match_count": len(matches),
        "traffic_ok": traffic_ok,
        "ses_message_id": message_id,
    }))
    return {"status": "ok", "message_id": message_id}
```

## IAM permissions

These are the permissions the deployed resources need. Under SAM, most of these are generated for you (see the SAM template section) — this list is the source of truth for *what* access exists, so you can verify the generated roles match.

The Lambda execution role needs:

- `secretsmanager:GetSecretValue` on the single secret ARN (`calendar-digest/keys`). Expressed via SAM `Policies` inline statement.
- `ses:SendEmail` and `ses:SendRawEmail` on the verified SES identity ARN. Expressed via SAM `Policies` inline statement.
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` — via the `AWSLambdaBasicExecutionRole` policy template.

EventBridge Scheduler needs a role with `lambda:InvokeFunction` on the Lambda's ARN. **Under SAM this is auto-generated** by the `ScheduleV2` event source — you don't write it by hand.

## SAM template (`infra/template.yaml`)

SAM is CloudFormation with two conveniences that matter here: `sam build` packages the Lambda and its dependencies (handling native arm64 wheels for you), and `AWS::Serverless::Function` expands into the Lambda + execution role + log group + event-source wiring so you write far less YAML. The template below still produces all the same underlying CloudFormation resources described in the IAM permissions section above — SAM just generates the boilerplate ones.

The template requires the SAM transform header at the top:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `SecretsArn` | `String` | ARN of the single Secrets Manager secret (`calendar-digest/keys`) holding all three credentials as a JSON object |
| `UserEmail` | `String` | The user's email — used as SES sender, SES recipient, and Google Calendar impersonation subject |
| `SesIdentityArn` | `String` | ARN of the verified SES identity (e.g., `arn:aws:ses:us-west-2:ACCOUNT:identity/user@example.com`) |
| `CalendarId` | `String` | **Required, no default.** The secondary calendar holding events; do NOT pass `primary`. |
| `LookaheadDays` | `Number` | Default: `7` |
| `AnthropicModel` | `String` | Default: `claude-sonnet-4-5` |
| `LogRetentionDays` | `Number` | Default: `30` |

### Globals

Use a `Globals` section to set Lambda defaults once:

```yaml
Globals:
  Function:
    Runtime: python3.12
    Architectures: [arm64]
    MemorySize: 512
    Timeout: 60
```

### Resources

1. **`AWS::Serverless::Function` (DigestFunction)** — this single SAM resource expands into the Lambda function, its execution role, and (with `LogGroup` configured) the log group. Define:
   - **`CodeUri` and `Handler` layout** — the project structure puts `requirements.txt` at the repo root, so use `CodeUri: ..` (the repo root, relative to `infra/template.yaml`) and `Handler: src.handler.lambda_handler`. SAM's Python builder will find the root `requirements.txt` and package the `src/` tree. Verify the handler resolves with a deployed test invocation — a `CodeUri`/`Handler`/`requirements.txt` mismatch is the most common first-deploy error. (If you prefer the alternative of co-locating `requirements.txt` inside `src/` with `CodeUri: ../src/` and `Handler: handler.lambda_handler`, that also works — just keep all three consistent and update the project structure to match.)
   - `Policies` — SAM policy templates make least-privilege easy. Use:
     ```yaml
     Policies:
       - AWSLambdaBasicExecutionRole
       - Statement:
           - Effect: Allow
             Action: secretsmanager:GetSecretValue
             Resource: !Ref SecretsArn
           - Effect: Allow
             Action:
               - ses:SendEmail
               - ses:SendRawEmail
             Resource: !Ref SesIdentityArn
     ```
   - `Environment.Variables` — same set as the config.py section: `SECRETS_ARN` (`!Ref SecretsArn`), `USER_EMAIL`, `CALENDAR_ID`, `LOOKAHEAD_DAYS`, `TIMEZONE` (`America/Los_Angeles`), `ANTHROPIC_MODEL`, `LOG_LEVEL` (`INFO`), each via `!Ref` to the matching parameter where one exists.
   - `Events` — **this is where SAM shines.** Attach the schedule directly as an event source using `ScheduleV2` (which maps to EventBridge Scheduler, not the older CloudWatch Events rule):
     ```yaml
     Events:
       DailyDigest:
         Type: ScheduleV2
         Properties:
           ScheduleExpression: cron(0 5 * * ? *)
           ScheduleExpressionTimezone: America/Los_Angeles
     ```
     SAM auto-creates the EventBridge Scheduler schedule AND the IAM role that lets it invoke the Lambda. No hand-written scheduler role needed.
   - `LoggingConfig` or an explicit `AWS::Logs::LogGroup`: to control retention, define a separate log group resource and reference it, OR set the function's log group retention. Simplest reliable approach: define an explicit `AWS::Logs::LogGroup` named `!Sub /aws/lambda/${DigestFunction}` with `RetentionInDays: !Ref LogRetentionDays`. (Note the same potential circular-reference caveat as before — set the function name explicitly via `FunctionName` if needed, or accept SAM's generated name and skip custom retention for v1.)

2. **`AWS::SNS::Topic` (FailureTopic)** — plain CloudFormation resource (no SAM equivalent needed). Display name `Calendar Digest Failures`.

3. **`AWS::SNS::Subscription` (FailureSubscription)** — `Protocol: email`, `Endpoint: !Ref UserEmail`, `TopicArn: !Ref FailureTopic`.

4. **`AWS::CloudWatch::Alarm` (LambdaErrorsAlarm)** — plain CloudFormation resource:
   - `MetricName: Errors`, `Namespace: AWS/Lambda`
   - `Dimensions: [{ Name: FunctionName, Value: !Ref DigestFunction }]`
   - `Statistic: Sum`, `Period: 300`, `EvaluationPeriods: 1`, `Threshold: 1`, `ComparisonOperator: GreaterThanOrEqualToThreshold`
   - `TreatMissingData: notBreaching`
   - `AlarmActions: [!Ref FailureTopic]`

### Outputs

- `DigestFunctionArn: !GetAtt DigestFunction.Arn`
- `DigestFunctionName: !Ref DigestFunction`
- `FailureTopicArn: !Ref FailureTopic`

### Things NOT in the template (intentionally)

- **The Secrets Manager secret** (`calendar-digest/keys`) — created manually so secret material never lives in the template, parameters, or stack events. Its ARN is passed in as the `SecretsArn` parameter.
- **The SES verified identity** — created via `aws ses verify-email-identity` + clicking the link. ARN passed in as a parameter.
- **The deployment S3 bucket** — `sam deploy --guided` creates and remembers a managed bucket automatically (stored in `samconfig.toml`).

## SAM build and deploy

SAM replaces the hand-rolled build script entirely.

### `samconfig.toml`

After the first `sam deploy --guided`, SAM writes this file capturing your choices (stack name, region, parameter values, capabilities, the managed S3 bucket). Subsequent deploys are just `sam deploy`. The relevant settings:

```toml
version = 0.1

[default.deploy.parameters]
stack_name = "calendar-digest"
region = "us-west-2"
capabilities = "CAPABILITY_IAM"
resolve_s3 = true
parameter_overrides = """
SecretsArn=arn:aws:secretsmanager:us-west-2:ACCOUNT:secret:calendar-digest/keys-XXXXXX \
UserEmail=you@example.com \
SesIdentityArn=arn:aws:ses:us-west-2:ACCOUNT:identity/you@example.com
"""
```

Note: `samconfig.toml` ends up containing your ARNs and email but **no secret values** (those stay in Secrets Manager). ARNs aren't sensitive, but if you'd rather not commit them, gitignore this file and keep a `samconfig.example.toml` template instead. The spec's `.gitignore` lists `samconfig.toml` as optionally ignored for this reason.

### Build

```bash
cd infra
sam build --use-container
```

`--use-container` builds inside a Lambda-compatible Docker image, guaranteeing the arm64/manylinux wheels for `cryptography` (pulled in by Google's auth libs) are correct. This is the single most important reason we chose SAM — it makes the "works locally, breaks in Lambda" packaging failure mode essentially impossible. It requires Docker running locally. Without Docker, `sam build` (no flag) still works but builds with your local Python, which is fine only if your local platform matches arm64 Linux (it usually won't on a Mac/x86 dev box — so prefer `--use-container`).

### Deploy

First time:
```bash
sam deploy --guided
```
This prompts for stack name, region, parameter values, and confirms IAM capability creation, then writes `samconfig.toml`.

After that:
```bash
sam build --use-container && sam deploy
```

### `infra/README.md`

Document the workflow:

```
# Infrastructure (AWS SAM)

## Prerequisites
- AWS CLI configured with credentials for the target account
- AWS SAM CLI installed (`brew install aws-sam-cli`)
- Docker running (for `sam build --use-container`)
- The secret `calendar-digest/keys` created in Secrets Manager (see main README)
- SES sender email verified in us-west-2

## First deploy
1. cd infra
2. sam build --use-container
3. sam deploy --guided   # fill in the parameters when prompted; writes samconfig.toml
4. Confirm the SNS email subscription that arrives in your inbox
5. Test: aws lambda invoke --function-name calendar-digest-DigestFunction-XXXX --region us-west-2 /tmp/out.json && cat /tmp/out.json
   (get the exact function name from the stack outputs: `sam list stack-outputs --stack-name calendar-digest`)

## Subsequent deploys
sam build --use-container && sam deploy

## Local invoke (optional, requires Docker)
sam local invoke DigestFunction
(Note: real Secrets Manager / Google / WSDOT / Anthropic calls still go out unless mocked;
for pure offline testing use scripts/local_run.py with a .env file instead.)

## Tear down
sam delete --stack-name calendar-digest
(Does not delete the manually-created Secrets Manager secrets or the SES verified identity.)
```

### A note on the learning curve

Since this is partly a SAM learning exercise, the concepts worth internalizing as you build:
- **`template.yaml` is just CloudFormation** with the `Transform` header and `AWS::Serverless::*` shortcuts. You can run `sam build` and inspect `.aws-sam/build/template.yaml` to see exactly what the shortcuts expanded into — a great way to learn what SAM is doing for you.
- **`Events` of type `ScheduleV2`** is the SAM shorthand that generated the whole scheduler + invoke-role setup that was hand-written in the CloudFormation version.
- **`Policies`** with SAM policy templates and inline statements replace the hand-written execution role.
- **`sam build`** is the piece that replaces the `build.sh` packaging script.

## Local development

`scripts/local_run.py`:
- Loads secrets from environment variables OR a `.env` file (gitignored).
- Calls `lambda_handler({}, None)` locally.
- Useful for end-to-end smoke tests against real Google + WSDOT + Anthropic.

## Tests

Use `pytest`. All external calls (Google, WSDOT, Anthropic, SES, Secrets Manager) must be mocked in unit tests using `moto` (for AWS) and `responses` or `pytest-httpx` (for HTTP) or direct monkeypatching.

Required test coverage:
- `test_calendar_client.py`: parses timed events, all-day events, virtual events (Google Meet, Zoom, Teams), events with missing location.
- `test_wsdot_client.py`: parses `.NET` date format; filters out expired alerts; filters out alerts starting beyond the window; handles empty response.
- `test_relevance.py`: builds the correct tool-call request; parses the tool response into `RelevanceMatch` objects; returns `[]` when there are no events with locations or no alerts (without making an API call).
- `test_digest.py`: groups by day correctly; handles events spanning midnight; sorts within day.
- `test_email_renderer.py`: subject formatting; "TODAY"/"TOMORROW"/weekday day headings; day-with-no-events omission; traffic-unavailable banner; events with no matches; events with multiple ⚠️ lines; virtual events render with no 📍 line. At least one test should assert the renderer reproduces the structure of the canonical example digest (Option B) for a fixed input — the day headers, the 📍 location lines, and the ⚠️ traffic line all present and in the right order.
- `test_handler.py`: end-to-end with all deps mocked; verifies that WSDOT or Anthropic failures still produce an email with the unavailable banner.

The `fixtures/calendar_response.json` fixture should mirror the canonical example's events so the renderer test and the example stay in sync. At minimum include: the Sunday "Nosework Sniff and Go" event in Monroe, WA (the one that should match a southbound-I-405 weekend-closure WSDOT alert), a West Seattle event with a full street address, a virtual event with a Google Meet link (to exercise the no-📍 path), and the messy "Wellsprings-K9: ..." title (to exercise conservative title tidying). A companion `fixtures/wsdot_alerts.json` should contain the I-405 SB weekend closure alert that the relevance step matches to the Monroe event.

## Setup runbook (for the README)

The README should walk through one-time setup, in this order:

1. **Google Cloud setup**:
   - Create a GCP project (or use an existing one).
   - Enable the Google Calendar API on the project.
   - Create a service account and generate a JSON key.
     - **Org policy gotcha**: newer Workspace orgs enforce `iam.disableServiceAccountKeyCreation` (inherited from the org), which blocks key download. To create a key you must override this constraint for the project: as a Workspace super admin, first ensure your account holds both `roles/resourcemanager.organizationAdmin` and `roles/orgpolicy.policyAdmin` at the org node (grant via IAM scoped to the org — reach it through Manage Resources or the URL `console.cloud.google.com/iam-admin/iam?organizationId=<ORG_ID>` if the project picker hides the org). Then in IAM & Admin → Organization Policies, open the **legacy** `iam.disableServiceAccountKeyCreation` constraint, scope to the project, override the inherited policy, and set enforcement Off. Wait a few minutes for propagation, then download the JSON key. (Optional hygiene: remove `orgpolicy.policyAdmin` from your account afterward — it's only needed for this one-time toggle.)
   - **Calendar sharing prerequisite**: if the events live on a personal Gmail calendar, that calendar must be shared to the impersonated Workspace user with at least "See all event details." This is what lets domain-wide delegation read it. Verify the calendar is visible by listing calendars (needs the `calendar.readonly` scope, which is the scope we use anyway).
   - In Google Workspace Admin (admin.google.com, NOT the GCP console) → Security → Access and data control → API controls → Domain-wide delegation, authorize the service account's client ID with the scope `https://www.googleapis.com/auth/calendar.readonly`. The scope string must match the code exactly (a mismatch causes `403 unauthorized_client`), and domain-wide delegation changes can take up to ~20 minutes to propagate.
   - **Verify before proceeding**: fill in the placeholders in `scripts/verify_calendar.py` (KEY_FILE, IMPERSONATE, CALENDAR_ID) and run it locally. Those placeholders are intentionally generic in the committed copy; the real values stay only on your machine. Seeing events confirms the whole chain (key + delegation + scope + calendar sharing) before any AWS work.
2. **WSDOT API access**: request an access code at https://wsdot.wa.gov/traffic/api/.
3. **Anthropic API key**: get from console.anthropic.com.
4. **AWS Secrets Manager**: create one secret named `calendar-digest/keys` in `us-west-2`, as a single `SecretString` containing a JSON object with three snake_case keys:
   ```json
   {
     "google_service_account": "<<the entire service-account JSON key file, as a single JSON string>>",
     "wsdot_access_code": "<<your WSDOT access code>>",
     "anthropic_api_key": "sk-ant-..."
   }
   ```
   The `google_service_account` value is the full key file content as a string — when you paste it into the Secrets Manager console's plaintext editor inside the outer JSON, the inner braces and quotes must be preserved (it's a JSON string whose contents are themselves JSON). The code reads the outer object, then `json.loads()` the `google_service_account` field a second time. Note the secret's ARN for the deploy step.
5. **SES**: verify the sender email address in `us-west-2`. Confirm the verification email. Stay in sandbox — sender and recipient are the same address, so no production access needed.
6. **Deploy** (SAM):
   - Install the SAM CLI (`brew install aws-sam-cli`) and make sure Docker is running.
   - `cd infra && sam build --use-container`
   - `sam deploy --guided` — provide the `calendar-digest/keys` secret ARN (step 4), user email, and SES identity ARN (step 5) when prompted. This writes `samconfig.toml` so later deploys are just `sam build --use-container && sam deploy`.
7. **Subscribe to SNS** failure topic (confirm the email subscription from your inbox).
8. **Smoke test**: invoke the Lambda manually (`aws lambda invoke --function-name <name from stack outputs> --region us-west-2 /tmp/out.json`) or via the console with an empty test event. Verify an email arrives.

## Future-proofing for Slack

The `Digest` dataclass is the channel-agnostic intermediate representation. `renderers/slack_renderer.py` should exist as a stub with a clear TODO:

```python
def render_slack(digest: Digest) -> dict:
    """Renders the digest as a Slack Block Kit payload. Not implemented in v1."""
    raise NotImplementedError("Slack rendering planned for v2.")
```

To add Slack later: implement `render_slack`, add a `senders/slack_sender.py` that posts to an incoming webhook URL, add a config flag to select the channel, fetch the webhook URL from a new secret. No restructuring required.

## v1.5 — Reddit u/wsdot stretch goal

Defer to a follow-up iteration. Sketch only:

- Add `src/reddit_client.py` that fetches recent posts from `https://www.reddit.com/user/wsdot.json` (Reddit's JSON endpoint, no auth needed for public profiles; set a custom `User-Agent` to avoid rate limiting).
- Filter to posts from the last 14 days.
- Pass post titles + bodies as additional context into the `match_alerts_to_events` call, alongside the structured alerts. The Claude prompt should treat them as supplementary signals: a Reddit post about a weekend I-405 closure should be matched the same way as a structured WSDOT alert would be.
- This requires extending `Alert` (or adding a parallel `RedditPost` model) and updating the relevance tool schema to accept either source type.
- Build v1 first; verify the daily digest is useful for two weeks; then add this.

## Acceptance criteria for v1

1. `sam build --use-container && sam deploy` in `us-west-2` creates a stack containing the Lambda, the EventBridge Scheduler schedule (and its auto-generated invoke role), the Lambda execution role, the log group, the SNS topic + email subscription, and the CloudWatch errors alarm.
2. Manual Lambda invocation sends an email whose structure matches the canonical example digest (Option B) in the email renderer section: per-day sections with TODAY/TOMORROW/weekday headers, bold event titles, time ranges, 📍 full-address lines, and ⚠️ traffic lines where relevant.
3. The Sniff and Go fixture test passes: given the fixture calendar event in Monroe and a fixture WSDOT alert about an I-405 SB closure that weekend, the rendered email contains both the event details and the "⚠️" traffic note line.
4. Killing the WSDOT request (e.g., by setting an invalid access code) still results in an email being sent, with the "Traffic data unavailable today" banner.
5. All unit tests pass. Test coverage is >80% on `src/` (excluding `__init__.py` files).
6. The scheduled run at 5 AM Pacific the next morning produces an email without manual intervention.

## Out of scope for v1

- Slack delivery (stub only, see future-proofing section).
- Reddit u/wsdot ingestion (v1.5).
- SDOT data sources.
- Geocoding addresses or computing actual routes.
- Multi-user support.
- Web UI, configuration UI, or "preferences."
- Snooze / dismiss functionality.
- Anything that requires getting out of the SES sandbox.

## Open questions to confirm with the user before building

1. Confirm Workspace admin access to authorize the service account's client ID with the calendar scope.
2. Confirm SES sender email is verified in `us-west-2` before deploying.
3. Confirm the model choice (`claude-sonnet-4-5` or whatever is current). Haiku is cheaper but likely not as good at the geographic reasoning; Sonnet is the safe pick at this volume.
