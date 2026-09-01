import logging
import httpx
import secrets

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from .config import settings
from .telegram import process_update
from . import services


logging.basicConfig(level=logging.INFO)
app = FastAPI(title="JnA Document Bot", docs_url=None, redoc_url=None)


def google_flow(state: str | None = None) -> Flow:
    if not (settings.google_client_id and settings.google_client_secret and settings.railway_public_domain):
        raise HTTPException(status_code=503, detail="Google OAuth variables are not configured")
    redirect_uri = f"https://{settings.railway_public_domain}/google/callback"
    config = {"web": {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri],
    }}
    flow = Flow.from_client_config(config, scopes=[services.DRIVE_SCOPE], state=state)
    flow.redirect_uri = redirect_uri
    return flow


@app.on_event("startup")
async def configure_webhook():
    if not (settings.telegram_token and settings.webhook_secret and settings.railway_public_domain):
        logging.warning("Webhook not configured: required Railway variables are missing")
        return
    url = f"https://{settings.railway_public_domain}/telegram/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_token}/setWebhook",
            data={"url": url, "secret_token": settings.webhook_secret,
                  "allowed_updates": '["message","callback_query"]'},
        )
        response.raise_for_status()
    logging.info("Telegram webhook configured")


@app.get("/")
async def health():
    return {"status": "ok", "service": "jna-document-bot"}


@app.get("/health")
async def railway_health():
    return {"status": "ok"}


@app.get("/google/connect", response_class=HTMLResponse)
async def google_connect_form():
    return """<h2>Connect JnA Google Drive</h2><form method='post'><label>Setup key</label><br><input name='key' type='password' required><br><br><button type='submit'>Connect Google Drive</button></form>"""


@app.post("/google/connect")
async def google_connect(key: str = Form(...)):
    if not settings.google_oauth_setup_key or not secrets.compare_digest(key, settings.google_oauth_setup_key):
        raise HTTPException(status_code=403, detail="Invalid setup key")
    flow = google_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent")
    services.store_oauth_state(state)
    return RedirectResponse(authorization_url)


@app.get("/google/callback", response_class=HTMLResponse)
async def google_callback(request: Request, state: str):
    if not services.consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="OAuth state is invalid or expired")
    flow = google_flow(state)
    authorization_response = f"https://{settings.railway_public_domain}/google/callback?{request.url.query}"
    flow.fetch_token(authorization_response=authorization_response)
    if not flow.credentials.refresh_token:
        raise HTTPException(status_code=400, detail="Google did not return a refresh token")
    services.save_google_refresh_token(flow.credentials.refresh_token)
    services.create_drive_root(flow.credentials)
    return "<h2>Google Drive connected</h2><p>The JnA Financial Documents folder was created. You may close this page and open the Telegram bot.</p>"


@app.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not settings.webhook_secret or x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    update = await request.json()
    try:
        await process_update(update)
    except Exception:
        logging.exception("Telegram update failed")
        raise HTTPException(status_code=500, detail="Update failed")
    return {"ok": True}
