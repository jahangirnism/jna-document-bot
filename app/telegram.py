from __future__ import annotations

import html
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .config import settings
from .pdf_generator import generate_pdf
from . import services


API = f"https://api.telegram.org/bot{settings.telegram_token}"


async def api(method: str, payload: dict | None = None, files: dict | None = None):
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{API}/{method}", data=payload or {}, files=files)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"): raise RuntimeError(result)
        return result["result"]


def keyboard(rows):
    import json
    return json.dumps({"inline_keyboard": rows})


async def send(chat_id, text, rows=None):
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if rows: payload["reply_markup"] = keyboard(rows)
    return await api("sendMessage", payload)


async def answer_callback(callback_id):
    await api("answerCallbackQuery", {"callback_query_id": callback_id})


async def send_pdf(chat_id, pdf_path: Path, caption: str):
    with pdf_path.open("rb") as stream:
        await api("sendDocument", {"chat_id": str(chat_id), "caption": caption,
                                   "parse_mode": "HTML"}, {"document": (pdf_path.name, stream, "application/pdf")})


def is_admin(user_id: int) -> bool:
    return user_id == settings.admin_user_id


def is_allowed(user_id: int) -> bool:
    return is_admin(user_id) or user_id in settings.allowed_user_ids


async def unauthorized(chat_id):
    await send(chat_id, "Access denied. Please contact the JnA House administrator for access.")


async def start(chat_id, user):
    services.clear_session(user["id"])
    await send(chat_id, "Welcome to <b>JnA House Documents</b>.\n\nCreate and securely archive invoices, receipts and acknowledgement receipts.",
               [[{"text":"Create document", "callback_data":"new"}],
                [{"text":"Recent documents", "callback_data":"history"}]])


async def begin(chat_id, user_id):
    services.set_session(user_id, "document_type", {})
    await send(chat_id, "Select the document type:", [[
        {"text":"Tax Invoice", "callback_data":"doctype:tax_invoice"}],
        [{"text":"Invoice", "callback_data":"doctype:invoice"}],
        [{"text":"Receipt", "callback_data":"doctype:receipt"}],
        [{"text":"Acknowledgement Receipt", "callback_data":"doctype:acknowledgement"}],
        [{"text":"Cancel", "callback_data":"cancel"}]])


async def history(chat_id, user_id):
    records = services.recent_documents(created_by=None if is_admin(user_id) else user_id)
    if not records: return await send(chat_id, "No documents have been created yet.")
    lines = ["<b>Recent documents</b>"]
    for r in records:
        lines.append(f"• <b>{html.escape(r['document_number'])}</b> — {html.escape(r['client_name'])} — {r.get('status','active').upper()}")
    await send(chat_id, "\n".join(lines))


async def ask_confirmation(chat_id, user, vat_rate: int):
    data = services.update_session(user["id"], "confirm", vat_rate=vat_rate,
                                   username=user.get("username", ""), created_by=user["id"],
                                   creator_name=" ".join(filter(None, [user.get("first_name"),
                                                                        user.get("last_name")])) )
    title = {"tax_invoice":"Tax Invoice", "invoice":"Invoice", "receipt":"Receipt",
             "acknowledgement":"Acknowledgement Receipt"}[data["document_type"]]
    return await send(chat_id, f"<b>Confirm document</b>\n\nType: {title}\nClient: {html.escape(data['client_name'])}"
                      f"\nTransaction: {data['transaction_type'].title()}\nAmount: AED {Decimal(data['amount']):,.2f}"
                      f"\nVAT: {data['vat_rate']}%\n\nGenerate and archive this document?",
                      [[{"text":"Confirm & Generate", "callback_data":"confirm"}],
                       [{"text":"Cancel", "callback_data":"cancel"}]])


async def handle_callback(query):
    user, chat_id, value = query["from"], query["message"]["chat"]["id"], query["data"]
    await answer_callback(query["id"])
    if not is_allowed(user["id"]): return await unauthorized(chat_id)
    if value == "new": return await begin(chat_id, user["id"])
    if value == "history": return await history(chat_id, user["id"])
    if value == "cancel":
        services.clear_session(user["id"]); return await send(chat_id, "Document creation cancelled.")
    if value.startswith("doctype:"):
        services.update_session(user["id"], "client_name", document_type=value.split(":",1)[1])
        return await send(chat_id, "Enter the <b>client name</b>:")
    if value == "trn:skip":
        services.update_session(user["id"], "transaction_type", client_trn="")
        return await ask_transaction(chat_id)
    if value.startswith("transaction:"):
        services.update_session(user["id"], "description", transaction_type=value.split(":",1)[1])
        return await send(chat_id, "Enter the <b>description</b>:")
    if value == "note:skip":
        services.update_session(user["id"], "amount", note="")
        return await send(chat_id, "Enter the <b>amount before VAT</b> in AED:\nExample: <code>27088.00</code>")
    if value.startswith("vat:"):
        return await ask_confirmation(chat_id, user, int(value.split(":",1)[1]))
    if value == "confirm": return await create_document(chat_id, user)


async def ask_transaction(chat_id):
    await send(chat_id, "Select the transaction type:", [[
        {"text":"Sales", "callback_data":"transaction:sales"},
        {"text":"Rent", "callback_data":"transaction:rent"}]])


async def handle_message(message):
    user, chat_id = message["from"], message["chat"]["id"]
    if not is_allowed(user["id"]): return await unauthorized(chat_id)
    text_value = (message.get("text") or "").strip()
    if text_value in ("/start", "/help"): return await start(chat_id, user)
    if text_value in ("/new", "/create_document"): return await begin(chat_id, user["id"])
    if text_value == "/history": return await history(chat_id, user["id"])
    if text_value.startswith("/void "):
        if not is_admin(user["id"]): return await send(chat_id, "Only the administrator can void documents.")
        parts = text_value.split(maxsplit=2)
        if len(parts) < 3: return await send(chat_id, "Usage: <code>/void JNA_S_0001 reason</code>")
        ok = services.mark_void(parts[1], user["id"], parts[2])
        return await send(chat_id, "Document marked VOID. Audit record retained." if ok else "Document not found.")
    if text_value.startswith("/delete "):
        if not is_admin(user["id"]): return await send(chat_id, "Only the administrator can delete documents.")
        parts = text_value.split(maxsplit=2)
        if len(parts) < 3: return await send(chat_id, "Usage: <code>/delete JNA_S_0001 reason</code>")
        ok = services.delete_document(parts[1], user["id"], parts[2])
        return await send(chat_id, "Drive copy moved to Trash. Audit record retained." if ok else "Document not found.")

    session = services.get_session(user["id"])
    if not session: return await start(chat_id, user)
    step = session["step"]
    if step == "client_name":
        if not text_value: return await send(chat_id, "Please enter the client name.")
        services.update_session(user["id"], "address", client_name=text_value)
        return await send(chat_id, "Enter the <b>client address</b>:")
    if step == "address":
        if not text_value: return await send(chat_id, "Please enter the client address.")
        services.update_session(user["id"], "client_trn", address=text_value)
        return await send(chat_id, "Enter the <b>client TRN</b>, or select No TRN:",
                          [[{"text":"No TRN", "callback_data":"trn:skip"}]])
    if step == "client_trn":
        services.update_session(user["id"], "transaction_type", client_trn=text_value)
        return await ask_transaction(chat_id)
    if step == "description":
        if not text_value: return await send(chat_id, "Please enter the description.")
        services.update_session(user["id"], "note", description=text_value)
        return await send(chat_id, "Enter a <b>note</b>, or skip:",
                          [[{"text":"Skip note", "callback_data":"note:skip"}]])
    if step == "note":
        services.update_session(user["id"], "amount", note=text_value)
        return await send(chat_id, "Enter the <b>amount before VAT</b> in AED:\nExample: <code>27088.00</code>")
    if step == "amount":
        try:
            amount = Decimal(text_value.replace(",", ""))
            if amount <= 0 or amount > Decimal("9999999999"): raise InvalidOperation
        except (InvalidOperation, ValueError):
            return await send(chat_id, "Enter a valid positive amount, for example <code>27088.00</code>.")
        services.update_session(user["id"], "vat", amount=str(amount.quantize(Decimal("0.01"))))
        return await send(chat_id, "Select VAT:", [[{"text":"5%", "callback_data":"vat:5"},
                                                    {"text":"0%", "callback_data":"vat:0"}]])
    await send(chat_id, "Please use the buttons shown in the previous message, or send /new to restart.")


async def create_document(chat_id, user):
    data = services.claim_confirmation(user["id"])
    if not data: return await send(chat_id, "This request expired or is already processing. Send /new to restart.")
    await send(chat_id, "Generating and securely archiving the document…")
    data["document_number"] = services.allocate_document_number(data)
    now = datetime.now(ZoneInfo(settings.timezone_name))
    data["date"] = now.strftime("%d-%b-%Y")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp); pdf = tmpdir / f"{data['document_number']}.pdf"
        generate_pdf(data, pdf)
        drive_id, drive_link = services.upload_pdf(pdf, data)
        services.create_audit_record(data, pdf, drive_id, drive_link)
        caption = f"<b>{data['document_number']}</b>\n{html.escape(data['client_name'])}\nSaved to the JnA document register."
        await send_pdf(chat_id, pdf, caption)
        if settings.audit_chat_id and str(settings.audit_chat_id) != str(chat_id):
            await send_pdf(settings.audit_chat_id, pdf, caption)
    services.clear_session(user["id"])


async def process_update(update: dict):
    if "callback_query" in update: return await handle_callback(update["callback_query"])
    if "message" in update: return await handle_message(update["message"])
