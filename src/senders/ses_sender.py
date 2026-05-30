from __future__ import annotations

import boto3


def send_email(
    sender: str,
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> str:
    client = boto3.client("ses", region_name="us-west-2")
    response = client.send_email(
        Source=sender,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html_body, "Charset": "UTF-8"},
                "Text": {"Data": text_body, "Charset": "UTF-8"},
            },
        },
    )
    return response["MessageId"]
