"""FastAPI application for WhatsApp Cloud API Webhook."""
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.config import (
    META_APP_SECRET,
    META_VERIFY_TOKEN,
)
from app.db import get_session, init_db, message_seen
from app.llm import handle_message
from app.whatsapp import get_whatsapp_client

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema is initialized on startup."""
    try:
        init_db()
        log.info("Database initialized successfully.")
    except Exception as exc:
        log.warning("Database init warning: %s", exc)
    yield


app = FastAPI(
    title="Car Dealership WhatsApp Bot",
    description="FastAPI webhook service integrating WhatsApp Cloud API with AI car sales assistant",
    lifespan=lifespan,
)


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Validate X-Hub-Signature-256 header using HMAC-SHA256."""
    if not app_secret:
        # If no secret configured, signature verification is bypassed
        return True
    if not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    expected_signature = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    received_signature = signature_header[len(prefix):]
    return hmac.compare_digest(received_signature, expected_signature)


def process_incoming_message(phone: str, text: str, wa_message_id: str | None = None) -> None:
    """Background task to run conversation orchestrator and dispatch WhatsApp reply."""
    try:
        log.info("Processing message in background for phone %s (msg_id=%s)", phone, wa_message_id)
        client = get_whatsapp_client()
        if wa_message_id:
            try:
                client.send_typing_indicator(message_id=wa_message_id)
            except Exception as exc:
                # A typing indicator is best-effort; still process and answer the customer.
                log.warning("Could not show typing indicator for %s: %s", phone, exc)

        reply = handle_message(phone=phone, text=text, wa_message_id=wa_message_id)
        if reply is None:
            log.info("No reply produced (duplicate or empty message)")
            return

        if reply.cars:
            # Each recommendation includes its own test-drive button.
            client.send_car_recommendations(
                to=phone,
                text=reply.text,
                cars=reply.cars,
            )
        else:
            client.send_text(to=phone, text=reply.text)

    except Exception as exc:
        log.exception("Error processing background message for %s: %s", phone, exc)


@app.get("/")
def root():
    return {"status": "ok", "service": "Cronoa Car Dealership WhatsApp Assistant"}


@app.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """Verification endpoint requested by Meta during webhook registration."""
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        log.info("Meta webhook verification succeeded")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    log.warning("Meta webhook verification failed: token mismatch or invalid mode")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
):
    """Receive incoming WhatsApp webhook notifications."""
    raw_body = await request.body()

    # 1. Verify Meta HMAC-SHA256 signature
    if META_APP_SECRET and not verify_meta_signature(raw_body, x_hub_signature_256, META_APP_SECRET):
        log.warning("Invalid X-Hub-Signature-256 header")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 2. Parse payload entries and changes
    entries = payload.get("entry", [])
    if not entries:
        return {"status": "ignored", "reason": "no entries"}

    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # 3. Ignore delivery/read status updates
            if "statuses" in value and "messages" not in value:
                log.info("Ignoring status update: %s", value.get("statuses"))
                continue

            messages = value.get("messages", [])
            if not messages:
                continue

            for msg in messages:
                wa_message_id = msg.get("id")
                from_phone = msg.get("from")
                msg_type = msg.get("type")

                # 4. Deduplicate before background task if wa_message_id is present
                if wa_message_id:
                    with get_session() as session:
                        if message_seen(session, wa_message_id):
                            log.info("Duplicate message %s ignored at webhook layer", wa_message_id)
                            continue

                # Extract text content
                text = ""
                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        text = interactive.get("button_reply", {}).get("title", "")
                    elif interactive.get("type") == "list_reply":
                        text = interactive.get("list_reply", {}).get("title", "")
                elif msg_type == "button":
                    text = msg.get("button", {}).get("text", "")

                text = text.strip()
                if from_phone and text:
                    # 5. Process in background task and return 200 immediately
                    background_tasks.add_task(
                        process_incoming_message,
                        phone=from_phone,
                        text=text,
                        wa_message_id=wa_message_id,
                    )

    return {"status": "ok"}
