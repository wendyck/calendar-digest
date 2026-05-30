# calendar-digest

A daily 5 AM Pacific email digest of your Google Calendar for the next 7 days,
with WSDOT highway alerts flagged against events whose locations would put
them on an affected route. Runs as a single AWS Lambda on a schedule.

See `calendar-digest-spec.md` for the full design.

## One-time setup

### 1. Google Cloud

1. Create a GCP project.
2. Enable the Google Calendar API.
3. Create a service account, generate a JSON key, and download it.
4. In Google Workspace Admin → Security → Access and data control → API
   controls → Domain-wide delegation, authorize the service account's
   client ID with scope:
   `https://www.googleapis.com/auth/calendar.events.readonly`

### 2. WSDOT API access

Request an access code at https://wsdot.wa.gov/traffic/api/.

### 3. Anthropic API key

Generate at https://console.anthropic.com.

### 4. AWS Secrets Manager

In `us-west-2`, create one secret named `calendar-digest/keys` containing a
JSON object:

```json
{
  "google_service_account": "<<entire service-account JSON key, as a single JSON string>>",
  "wsdot_access_code": "<<your WSDOT access code>>",
  "anthropic_api_key": "sk-ant-..."
}
```

The `google_service_account` value is the full service-account JSON file
encoded as a string (the inner braces and quotes are preserved inside the
outer JSON). The Lambda reads the outer object and then `json.loads()` that
field a second time.

### 5. SES

Verify the sender email in `us-west-2`:

```bash
aws ses verify-email-identity --email-address you@example.com --region us-west-2
```

Confirm the link in your inbox. Stays in sandbox — sender == recipient.

### 6. Deploy

```bash
cd infra
sam build --use-container
sam deploy --guided   # first time only; writes samconfig.toml
```

When prompted, provide:
- `SecretsArn` — ARN of `calendar-digest/keys`
- `UserEmail` — the recipient/sender/calendar-impersonation address
- `SesIdentityArn` — e.g. `arn:aws:ses:us-west-2:ACCOUNT:identity/you@example.com`

Subsequent deploys: `sam build --use-container && sam deploy`.

### 7. SNS failure topic

Confirm the email subscription that arrives in your inbox after the first
deploy.

### 8. Smoke test

```bash
aws lambda invoke --function-name <DigestFunctionName from stack outputs> \
  --region us-west-2 /tmp/out.json
cat /tmp/out.json
```

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

For a real end-to-end run locally (uses your AWS creds and the real secret),
populate `.env` with `SECRETS_ARN` and `USER_EMAIL` and run:

```bash
python scripts/local_run.py
```
