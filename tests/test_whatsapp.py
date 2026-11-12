"""Tests for WhatsApp Cloud API client."""
import json
import httpx
import pytest

from app.whatsapp import WhatsAppClient, send_text, send_image, send_reply_buttons


def test_whatsapp_send_text_simulated(monkeypatch):
    client = WhatsAppClient(token="", phone_number_id="")
    res = client.send_text("919999900001", "Hello from bot!")
    assert res["simulated"] is True
    assert res["payload"]["to"] == "919999900001"
    assert res["payload"]["type"] == "text"
    assert res["payload"]["text"]["body"] == "Hello from bot!"


def test_whatsapp_send_image_payload():
    captured = {}

    def mock_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})

    client = WhatsAppClient(
        token="test_token",
        phone_number_id="12345",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})))
    )

    res = client.send_image(
        to="919999900001",
        image_url="https://cdn.example.com/car.jpg",
        caption="Maruti Brezza (2022) - ₹10.80L"
    )
    assert res == {"messages": [{"id": "wamid.123"}]}


def test_whatsapp_send_reply_buttons_formatting():
    captured_payload = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode())
        captured_payload.update(data)
        return httpx.Response(200, json={"messages": [{"id": "wamid.btn123"}]})

    client = WhatsAppClient(
        token="fake_token",
        phone_number_id="fake_phone_id",
        http_client=httpx.Client(transport=httpx.MockTransport(mock_handler)),
    )

    buttons = [
        {"id": "btn_test_drive", "title": "Book test drive"},
        {"id": "btn_see_more", "title": "See more cars that match my budget"},  # > 20 chars
        {"id": "btn_3", "title": "Contact us"},
        {"id": "btn_4", "title": "Extra button"},  # should be truncated to 3 buttons max
    ]

    res = client.send_reply_buttons(to="919999900001", text="Here are your options:", buttons=buttons)
    assert res == {"messages": [{"id": "wamid.btn123"}]}
    assert captured_payload["type"] == "interactive"
    action_buttons = captured_payload["interactive"]["action"]["buttons"]
    assert len(action_buttons) == 3
    assert action_buttons[0]["reply"]["title"] == "Book test drive"
    assert len(action_buttons[1]["reply"]["title"]) <= 20
    assert action_buttons[1]["reply"]["title"] == "See more cars that m"


def test_whatsapp_send_car_recommendations():
    sent_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode())
        sent_requests.append(data)
        return httpx.Response(200, json={"messages": [{"id": "wamid.rec"}]})

    client = WhatsAppClient(
        token="fake_token",
        phone_number_id="fake_phone_id",
        http_client=httpx.Client(transport=httpx.MockTransport(mock_handler)),
    )

    cars = [
        {
            "make": "Tata",
            "model": "Nexon EV Prime",
            "year": 2021,
            "price": 1250000,
            "image_url": "https://cdn.example.com/nexon.jpg",
            "promo_offer": "Free home charger",
        },
        {
            "make": "Maruti Suzuki",
            "model": "Brezza",
            "year": 2022,
            "price": 1080000,
            "image_url": None,  # no image url
            "promo_offer": None,
        },
    ]

    buttons = [
        {"id": "book_test_drive", "title": "Book test drive"},
        {"id": "see_more_cars", "title": "See more cars"},
    ]

    responses = client.send_car_recommendations(
        to="919999900001",
        text="Here are matching cars for you.",
        cars=cars,
        buttons=buttons,
    )

    assert len(responses) == 2  # 1 image + 1 interactive buttons
    assert sent_requests[0]["type"] == "image"
    assert sent_requests[0]["image"]["link"] == "https://cdn.example.com/nexon.jpg"
    assert "Tata Nexon EV Prime" in sent_requests[0]["image"]["caption"]
    assert "₹12.50L" in sent_requests[0]["image"]["caption"]
    assert "Free home charger" in sent_requests[0]["image"]["caption"]

    assert sent_requests[1]["type"] == "interactive"
    assert sent_requests[1]["interactive"]["body"]["text"] == "Here are matching cars for you."


def test_whatsapp_http_error_handling():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})

    client = WhatsAppClient(
        token="expired_token",
        phone_number_id="12345",
        http_client=httpx.Client(transport=httpx.MockTransport(mock_handler)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.send_text("919999900001", "test")
