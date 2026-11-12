"""Simulate Meta WhatsApp Webhook events locally without Meta.

Usage:
    # 1. Test GET /webhook verification handshake:
    python -m scripts.test_webhook --verify

    # 2. Post default sample payload:
    python -m scripts.test_webhook

    # 3. Post a specific sample file:
    python -m scripts.test_webhook --file samples/button_reply_test_drive.json
    python -m scripts.test_webhook --file samples/status_delivered.json

    # 4. Post a custom message:
    python -m scripts.test_webhook --text "I want a diesel SUV under 12 lakh" --phone 919999900001

    # 5. Simulate button click:
    python -m scripts.test_webhook --button "Book test drive" --phone 919999900001
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

from app.config import (
    META_APP_SECRET,
    META_VERIFY_TOKEN,
    PORT,
)

load_dotenv()


def calculate_signature(body_bytes: bytes, secret: str) -> str:
    """Generate Meta's sha256=<hex_digest> signature."""
    sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def build_text_payload(phone: str, text: str, wa_message_id: str | None = None) -> dict:
    msg_id = wa_message_id or f"wamid.{uuid.uuid4().hex}"
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789012345",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "100000000000001",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": msg_id,
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def build_button_payload(phone: str, button_title: str, button_id: str = "btn_custom") -> dict:
    msg_id = f"wamid.{uuid.uuid4().hex}"
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789012345",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "100000000000001",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": msg_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": button_id,
                                            "title": button_title,
                                        },
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_verification(base_url: str, verify_token: str) -> None:
    webhook_url = f"{base_url.rstrip('/')}/webhook"
    challenge = "1158201444"
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": verify_token,
        "hub.challenge": challenge,
    }
    print(f"Testing GET {webhook_url} with verify_token={verify_token}...")
    try:
        response = httpx.get(webhook_url, params=params, timeout=10.0)
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        if response.status_code == 200 and response.text == challenge:
            print("SUCCESS: Webhook verification challenge passed!")
        else:
            print("FAILURE: Webhook verification did not match challenge.")
    except Exception as exc:
        print(f"ERROR connecting to {webhook_url}: {exc}")


def post_webhook(url: str, payload: dict, secret: str | None = None) -> None:
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Hub-Signature-256"] = calculate_signature(body_bytes, secret)

    print(f"POSTing to {url}...")
    print(f"Payload:\n{json.dumps(payload, indent=2)}")
    if secret:
        print(f"Header X-Hub-Signature-256: {headers['X-Hub-Signature-256']}")

    try:
        response = httpx.post(url, content=body_bytes, headers=headers, timeout=10.0)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text}")
    except Exception as exc:
        print(f"ERROR connecting to {url}: {exc}")


def main() -> None:
    default_url = f"http://127.0.0.1:{PORT}/webhook"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=default_url, help=f"Webhook URL (default: {default_url})")
    parser.add_argument("--verify", action="store_true", help="Test GET /webhook verification handshake")
    parser.add_argument("--verify-token", default=META_VERIFY_TOKEN, help="Verify token for --verify check")
    parser.add_argument("--file", help="Path to sample JSON payload file")
    parser.add_argument("--text", help="Custom text message to send")
    parser.add_argument("--button", help="Button title to simulate clicking")
    parser.add_argument("--phone", default="919999900001", help="Sender phone number")
    parser.add_argument("--secret", default=META_APP_SECRET, help="Meta App Secret for HMAC signature")

    args = parser.parse_args()

    if args.verify:
        base_url = args.url.replace("/webhook", "")
        test_verification(base_url, args.verify_token)
        return

    if args.file:
        if not os.path.isfile(args.file):
            sys.exit(f"File not found: {args.file}")
        with open(args.file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    elif args.button:
        payload = build_button_payload(args.phone, args.button)
    elif args.text:
        payload = build_text_payload(args.phone, args.text)
    else:
        # Default fallback to samples/text_message.json or synthesized message
        sample_path = os.path.join("samples", "text_message.json")
        if os.path.isfile(sample_path):
            with open(sample_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = build_text_payload(args.phone, "Hi, I am looking for a petrol SUV under 10 lakh")

    post_webhook(args.url, payload, secret=args.secret)


if __name__ == "__main__":
    main()
