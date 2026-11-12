# WhatsApp Cloud API & Meta Webhook Setup Guide

This guide walks you through setting up your Meta Developer App, WhatsApp test phone number, local ngrok tunnel, and webhook registration for the Car Dealership WhatsApp Sales Assistant.

---

## 1. Create a Meta Developer App

1. Go to the [Meta for Developers Portal](https://developers.facebook.com/) and log in with your Facebook account.
2. Click **My Apps** in the top-right corner, then click **Create App**.
3. Select **Other** (or **Business**) as the app use case and click **Next**.
4. Select **Business** as the app type and click **Next**.
5. Enter an **App name** (e.g., `Cronoa Dealership Bot`), provide your contact email, and click **Create app**.

---

## 2. Add WhatsApp to Your App & Get Test Credentials

1. In the App Dashboard left sidebar, find **Add Product** and locate **WhatsApp**. Click **Set up**.
2. Go to **WhatsApp** -> **API Setup** in the left menu.
3. You will see:
   - **Temporary Access Token**: Click **Copy** (valid for 24 hours for sandbox testing; for permanent access, generate a System User token under Business Settings).
   - **Phone number ID**: Copy this ID.
   - **WhatsApp Business Account ID**: Copy this ID.
   - **From Test Number**: A pre-assigned test number provided by Meta.
4. **Add your real WhatsApp number as a recipient (Sandbox whitelist)**:
   - Under **To**, select **Manage phone number list**.
   - Add your personal WhatsApp phone number (with country code, e.g., `+91 98765 43210`).
   - Enter the verification code sent to your WhatsApp.

---

## 3. Retrieve Meta App Secret

1. In the App Dashboard left sidebar, go to **App settings** -> **Basic**.
2. Find **App secret** and click **Show** (you may need to re-enter your Facebook password).
3. Copy the **App Secret**.

---

## 4. Set Environment Variables

Update your `.env` file in the project root:

```env
# Database & OpenAI
DB_PATH=dealership.db
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
DEALER_NAME=Cronoa Dealership

# Meta Webhook & WhatsApp Cloud API
META_VERIFY_TOKEN=your_custom_verify_token_here
META_APP_SECRET=your_meta_app_secret_here
WHATSAPP_TOKEN=your_meta_access_token_here
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id_here
WHATSAPP_API_VERSION=v21.0

# Local Server
HOST=0.0.0.0
PORT=8000
```

---

## 5. Start the FastAPI Application

Start the local server with `uvicorn`:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 6. Expose Local Server via ngrok Tunnel

1. Download and install [ngrok](https://ngrok.com/) if not already installed.
2. In a separate terminal window, start an HTTPS tunnel on port 8000:

```powershell
ngrok http 8000
```

3. Copy the **HTTPS** forwarding URL from the ngrok output (e.g. `https://abc1-23-45-67.ngrok-free.app`).

---

## 7. Register Webhook in Meta Developer Dashboard

1. In the Meta App Dashboard, go to **WhatsApp** -> **Configuration** in the left menu.
2. Next to **Webhook**, click **Edit**.
3. Fill in:
   - **Callback URL**: `https://<YOUR-NGROK-DOMAIN>.ngrok-free.app/webhook` (e.g., `https://abc1-23-45-67.ngrok-free.app/webhook`)
   - **Verify token**: Must match `META_VERIFY_TOKEN` configured in your `.env`.
4. Click **Verify and save**. Meta will issue a `GET /webhook` request to verify the token.
5. Under **Webhook fields**, click **Manage** and subscribe to **`messages`**.

---

## 8. Test Your Webhook Locally

You can test the entire flow locally without Meta using the included test script and sample payloads:

### Test Webhook Verification Handshake
```powershell
python -m scripts.test_webhook --verify
```

### Post Sample Messages
```powershell
# Send standard text message
python -m scripts.test_webhook --file samples/text_message.json

# Send interactive button reply ("Book test drive")
python -m scripts.test_webhook --file samples/button_reply_test_drive.json

# Send custom text message
python -m scripts.test_webhook --text "Show me automatic petrol cars under 8 lakh" --phone 919999900001

# Send delivery status update (verified to be ignored)
python -m scripts.test_webhook --file samples/status_delivered.json
```

---

## 9. Live Test on WhatsApp

1. Send a WhatsApp message from your registered test phone to Meta's test phone number.
2. The bot will search dealership stock, reply with car details, send car images when recommendations match, and attach interactive buttons for test drive booking and more cars.
