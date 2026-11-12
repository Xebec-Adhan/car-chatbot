"""WhatsApp Cloud API client for sending text, images, and interactive reply buttons."""
import logging
from typing import Any

import httpx

from app.config import (
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_TOKEN,
)

log = logging.getLogger(__name__)


class WhatsAppClient:
    """Client for Meta's WhatsApp Business Cloud API."""

    def __init__(
        self,
        token: str | None = None,
        phone_number_id: str | None = None,
        api_version: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.token = token if token is not None else WHATSAPP_TOKEN
        self.phone_number_id = (
            phone_number_id if phone_number_id is not None else WHATSAPP_PHONE_NUMBER_ID
        )
        self.api_version = api_version or WHATSAPP_API_VERSION
        self._http_client = http_client

    @property
    def api_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _get_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=15.0)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON payload to Meta's WhatsApp Cloud API endpoint."""
        if not self.token or not self.phone_number_id:
            log.warning(
                "WhatsApp credentials not configured (WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID missing). "
                "Simulating outbound message: %s",
                payload,
            )
            return {"simulated": True, "payload": payload}

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        close_needed = self._http_client is None
        try:
            response = client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            log.info("WhatsApp message sent successfully: %s", result)
            return result
        except httpx.HTTPStatusError as exc:
            log.error(
                "WhatsApp API HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except Exception as exc:
            log.error("Failed to send WhatsApp message: %s", exc)
            raise
        finally:
            if close_needed:
                client.close()

    def send_text(self, to: str, text: str, preview_url: bool = False) -> dict[str, Any]:
        """Send a standard plain text message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }
        return self._post(payload)

    def send_typing_indicator(self, message_id: str) -> dict[str, Any]:
        """Mark an inbound message as read and ask WhatsApp to show typing."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }
        return self._post(payload)

    def send_image(
        self, to: str, image_url: str, caption: str | None = None
    ) -> dict[str, Any]:
        """Send an image with an optional caption."""
        image_data: dict[str, Any] = {"link": image_url}
        if caption:
            image_data["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": image_data,
        }
        return self._post(payload)

    def send_reply_buttons(
        self,
        to: str,
        text: str,
        buttons: list[dict[str, str]] | list[tuple[str, str]],
        header_image_url: str | None = None,
    ) -> dict[str, Any]:
        """Send an interactive reply buttons message (max 3 buttons, max 20 chars per button title).

        If header_image_url is given, the image is shown on top of the same bubble as the
        body text and the buttons (one single message, like a promotional card).
        Body text limit is 1024 characters.
        """
        formatted_buttons = []
        for i, item in enumerate(buttons[:3]):
            if isinstance(item, dict):
                btn_id = str(item.get("id", f"btn_{i + 1}"))
                btn_title = str(item.get("title", ""))[:20]
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                btn_id = str(item[0])
                btn_title = str(item[1])[:20]
            else:
                btn_id = f"btn_{i + 1}"
                btn_title = str(item)[:20]

            formatted_buttons.append(
                {
                    "type": "reply",
                    "reply": {
                        "id": btn_id,
                        "title": btn_title,
                    },
                }
            )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": text,
                },
                "action": {
                    "buttons": formatted_buttons,
                },
            },
        }
        if header_image_url:
            payload["interactive"]["header"] = {
                "type": "image",
                "image": {"link": header_image_url},
            }
        return self._post(payload)

    def send_car_recommendations(
        self,
        to: str,
        text: str,
        cars: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Send each car as one card: image header, details, and its own test-drive button."""
        responses: list[dict[str, Any]] = []

        for car in cars:
            title = f"{car.get('make', '')} {car.get('model', '')} ({car.get('year', '')})".strip()
            price_lakh = car.get("price", 0) / 100_000
            description = (
                f"*{title}* - \u20b9{price_lakh:.2f}L\n"
                f"{car.get('km_driven', 0):,} km \u00b7 {car.get('fuel_type', '')} \u00b7 "
                f"{car.get('transmission', '')}"
            )
            if car.get("promo_offer"):
                description += f"\nOffer: {car['promo_offer']}"

            # Include the car id so the reply tells us WHICH car was tapped.
            button_id = f"book_test_drive:{car['id']}" if car.get("id") else "book_test_drive"

            # One single message: image header + details + its own button.
            try:
                res = self.send_reply_buttons(
                    to=to,
                    text=description[:1024],
                    buttons=[{"id": button_id, "title": "Book test drive"}],
                    header_image_url=car.get("image_url"),
                )
                responses.append(res)
            except Exception as exc:
                log.warning("Failed to send recommendation for %s to %s: %s", title, to, exc)

        # Keep the browsing action available without sharing a test-drive button card.
        if cars:
            try:
                responses.append(
                    self.send_reply_buttons(
                        to=to,
                        text=text,
                        buttons=[{"id": "see_more_cars", "title": "See more cars"}],
                    )
                )
            except Exception as exc:
                log.warning("Failed to send see-more button to %s: %s", to, exc)

        return responses


# Module-level default instance and helper functions
_default_client: WhatsAppClient | None = None


def get_whatsapp_client() -> WhatsAppClient:
    global _default_client
    if _default_client is None:
        _default_client = WhatsAppClient()
    return _default_client


def send_text(to: str, text: str, preview_url: bool = False) -> dict[str, Any]:
    return get_whatsapp_client().send_text(to=to, text=text, preview_url=preview_url)


def send_image(to: str, image_url: str, caption: str | None = None) -> dict[str, Any]:
    return get_whatsapp_client().send_image(to=to, image_url=image_url, caption=caption)


def send_reply_buttons(
    to: str, text: str, buttons: list[dict[str, str]] | list[tuple[str, str]]
) -> dict[str, Any]:
    return get_whatsapp_client().send_reply_buttons(to=to, text=text, buttons=buttons)
