"""Tests for FastAPI WhatsApp Webhook endpoints and background message processing."""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import config, main
from app.db import Base, Customer, Message, save_message
from app.llm import Reply
from app.main import app, verify_meta_signature


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture()
def client():
    return TestClient(app)


def test_verify_meta_signature_helper():
    secret = "secret_12345"
    body = b'{"test": "data"}'
    sig = _sign(secret, body)

    assert verify_meta_signature(body, sig, secret) is True
    assert verify_meta_signature(body, "sha256=wrong", secret) is False
    assert verify_meta_signature(body, None, secret) is False
    assert verify_meta_signature(body, "invalid_prefix", secret) is False
    assert verify_meta_signature(body, None, "") is True  # secret unset allows verification


def test_root_health_check(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_webhook_verification_success(client, monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", "my_secret_verify_token")
    monkeypatch.setattr(main, "META_VERIFY_TOKEN", "my_secret_verify_token")

    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "my_secret_verify_token",
        "hub.challenge": "1234567890",
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "1234567890"


def test_get_webhook_verification_failure(client, monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", "correct_token")
    monkeypatch.setattr(main, "META_VERIFY_TOKEN", "correct_token")

    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "1234567890",
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 403


def test_post_webhook_signature_required(client, monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", "supersecret")
    payload = {"object": "whatsapp_business_account", "entry": []}
    body = json.dumps(payload).encode("utf-8")

    # Missing signature header
    res = client.post("/webhook", content=body)
    assert res.status_code == 403

    # Invalid signature header
    res = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=bad"})
    assert res.status_code == 403

    # Valid signature header
    valid_sig = _sign("supersecret", body)
    res = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": valid_sig})
    assert res.status_code == 200
    assert res.json() == {"status": "ignored", "reason": "no entries"}


def test_post_webhook_status_update_ignored(client, monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", "")
    with open("samples/status_delivered.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    with patch("app.main.process_incoming_message") as mock_proc:
        res = client.post("/webhook", json=payload)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
        mock_proc.assert_not_called()


def test_post_webhook_text_message_dispatches_background_task(client, monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", "")
    with open("samples/text_message.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    with patch("app.main.handle_message") as mock_handle, patch("app.main.get_whatsapp_client") as mock_get_wa:
        mock_wa_client = MagicMock()
        mock_get_wa.return_value = mock_wa_client
        mock_handle.return_value = Reply(text="Here are our petrol SUVs under ₹10 lakh.")

        res = client.post("/webhook", json=payload)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

        mock_handle.assert_called_once_with(
            phone="919999900001",
            text="Hi, I am looking for a petrol SUV under 10 lakh",
            wa_message_id="wamid.HBgMOTE5OTk5OTAwMDAxFQIAERgSMTAwMDAwMDAwMDAwMDAxAA==",
        )
        mock_wa_client.send_text.assert_called_once_with(
            to="919999900001",
            text="Here are our petrol SUVs under ₹10 lakh.",
        )


def test_post_webhook_button_reply_and_car_recommendation_dispatches_images_and_buttons(client, monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", "")
    with open("samples/button_reply_test_drive.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    with patch("app.main.handle_message") as mock_handle, patch("app.main.get_whatsapp_client") as mock_get_wa:
        mock_wa_client = MagicMock()
        mock_get_wa.return_value = mock_wa_client
        cars_list = [
            {
                "make": "Maruti Suzuki",
                "model": "Brezza",
                "year": 2022,
                "price": 1080000,
                "image_url": "https://cdn.example.com/brezza.jpg",
                "promo_offer": "Free warranty",
            }
        ]
        mock_handle.return_value = Reply(
            text="Found Brezza 2022.",
            cars=cars_list,
        )

        res = client.post("/webhook", json=payload)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

        mock_handle.assert_called_once_with(
            phone="919999900001",
            text="Book test drive",
            wa_message_id="wamid.HBgMOTE5OTk5OTAwMDAxFQIAERgSMTAwMDAwMDAwMDAwMDAyAA==",
        )
        mock_wa_client.send_car_recommendations.assert_called_once()
        call_kwargs = mock_wa_client.send_car_recommendations.call_args.kwargs
        assert call_kwargs["to"] == "919999900001"
        assert call_kwargs["text"] == "Found Brezza 2022."
        assert call_kwargs["cars"] == cars_list
        assert len(call_kwargs["buttons"]) == 2
        assert call_kwargs["buttons"][0]["title"] == "Book test drive"
        assert call_kwargs["buttons"][1]["title"] == "See more cars"


def test_post_webhook_deduplication(client, monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", "")
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    from app import db
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", lambda: Session(engine))

    wa_id = "wamid.DUPLICATE_ID_123"

    with Session(engine) as s:
        cust = Customer(phone="919999900001")
        s.add(cust)
        s.flush()
        save_message(s, cust.id, "user", "Old message", wa_message_id=wa_id)
        s.commit()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919999900001",
                                    "id": wa_id,
                                    "text": {"body": "Repeat message"},
                                    "type": "text",
                                }
                            ]
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    with patch("app.main.handle_message") as mock_handle:
        res = client.post("/webhook", json=payload)
        assert res.status_code == 200
        # Should be filtered out by deduplication check
        mock_handle.assert_not_called()
