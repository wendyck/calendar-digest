# Infrastructure (AWS SAM)

## Prerequisites
- AWS CLI configured with credentials for the target account
- AWS SAM CLI installed (`brew install aws-sam-cli`)
- Docker running (for `sam build --use-container`)
- The secret `calendar-digest/keys` already created in Secrets Manager
- SES sender email verified in `us-west-2`

## First deploy
```bash
cd infra
sam build --use-container
sam deploy --guided
```
Fill in the parameters when prompted; SAM writes `samconfig.toml`.

Confirm the SNS email subscription that arrives in your inbox.

Smoke test:
```bash
sam list stack-outputs --stack-name calendar-digest
aws lambda invoke --function-name <DigestFunctionName> \
  --region us-west-2 /tmp/out.json
cat /tmp/out.json
```

## Subsequent deploys
```bash
sam build --use-container && sam deploy
```

## Tear down
```bash
sam delete --stack-name calendar-digest
```
This does NOT delete the Secrets Manager secret or the verified SES
identity (they were created manually outside the stack).
