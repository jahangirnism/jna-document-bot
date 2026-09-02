from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from sqlalchemy import (BigInteger, Column, DateTime, Integer, MetaData,
                        String, Table, Text, create_engine, delete, select, update)
from sqlalchemy.dialects.postgresql import JSONB, insert

from .config import settings


database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(database_url, pool_pre_ping=True)
metadata = MetaData()

conversations = Table(
    "conversations", metadata,
    Column("user_id", BigInteger, primary_key=True), Column("step", String(40), nullable=False),
    Column("data", JSONB, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
counters = Table(
    "document_counters", metadata, Column("code", String(10), primary_key=True),
    Column("value", Integer, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False),
)
documents = Table(
    "documents", metadata, Column("document_number", String(40), primary_key=True),
    Column("status", String(20), nullable=False), Column("data", JSONB, nullable=False),
    Column("drive_file_id", String(255)), Column("drive_link", Text),
    Column("sha256", String(64), nullable=False), Column("created_at", DateTime(timezone=True), nullable=False),
)
app_settings = Table(
    "app_settings", metadata, Column("key", String(80), primary_key=True),
    Column("value", Text, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False),
)
oauth_states = Table(
    "oauth_states", metadata, Column("state", String(255), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
metadata.create_all(engine)


def utcnow():
    return datetime.now(timezone.utc)


def get_session(user_id: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(conversations).where(conversations.c.user_id == user_id)).mappings().first()
    return dict(row) if row else None


def set_session(user_id: int, step: str, data: dict | None = None) -> None:
    stmt = insert(conversations).values(user_id=user_id, step=step, data=data or {}, updated_at=utcnow())
    stmt = stmt.on_conflict_do_update(index_elements=[conversations.c.user_id],
                                      set_={"step": step, "data": data or {}, "updated_at": utcnow()})
    with engine.begin() as conn:
        conn.execute(stmt)


def clear_session(user_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(conversations).where(conversations.c.user_id == user_id))


def update_session(user_id: int, step: str, **values) -> dict:
    current = get_session(user_id) or {"data": {}}
    data = dict(current.get("data") or {}); data.update(values)
    with engine.begin() as conn:
        conn.execute(update(conversations).where(conversations.c.user_id == user_id)
                     .values(step=step, data=data, updated_at=utcnow()))
    return data


def claim_confirmation(user_id: int) -> dict | None:
    with engine.begin() as conn:
        row = conn.execute(update(conversations)
                           .where(conversations.c.user_id == user_id, conversations.c.step == "confirm")
                           .values(step="processing", updated_at=utcnow())
                           .returning(conversations.c.data)).first()
    return dict(row[0]) if row else None


def allocate_document_number(data: dict) -> str:
    # JnA uses only three numbering series, regardless of the selected title:
    # Sales, Rent, and Acknowledgement Receipt.
    if data["document_type"] == "acknowledgement":
        key = "ACK"
    else:
        key = "S" if data["transaction_type"] == "sales" else "R"
    initial = 0
    with engine.begin() as conn:
        row = conn.execute(select(counters.c.value).where(counters.c.code == key).with_for_update()).first()
        if row:
            next_value = row[0] + 1
            conn.execute(update(counters).where(counters.c.code == key)
                         .values(value=next_value, updated_at=utcnow()))
        else:
            next_value = initial + 1
            conn.execute(insert(counters).values(code=key, value=next_value, updated_at=utcnow()))
    return f"JNA_{key}_{next_value:04d}"


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def set_app_setting(key: str, value: str) -> None:
    stmt = insert(app_settings).values(key=key, value=value, updated_at=utcnow())
    stmt = stmt.on_conflict_do_update(index_elements=[app_settings.c.key],
                                      set_={"value": value, "updated_at": utcnow()})
    with engine.begin() as conn: conn.execute(stmt)


def get_app_setting(key: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).first()
    return row[0] if row else None


def store_oauth_state(state: str) -> None:
    with engine.begin() as conn:
        conn.execute(insert(oauth_states).values(state=state, created_at=utcnow()))


def consume_oauth_state(state: str) -> bool:
    with engine.begin() as conn:
        row = conn.execute(delete(oauth_states).where(oauth_states.c.state == state)
                           .returning(oauth_states.c.created_at)).first()
    return bool(row and (utcnow() - row[0]).total_seconds() <= 900)


def _fernet() -> Fernet:
    if not settings.data_encryption_key: raise RuntimeError("DATA_ENCRYPTION_KEY is not configured")
    return Fernet(settings.data_encryption_key.encode())


def save_google_refresh_token(refresh_token: str) -> None:
    set_app_setting("google_refresh_token", _fernet().encrypt(refresh_token.encode()).decode())


def google_credentials() -> Credentials:
    encrypted = get_app_setting("google_refresh_token")
    if not encrypted: raise RuntimeError("Google Drive is not connected")
    refresh_token = _fernet().decrypt(encrypted.encode()).decode()
    return Credentials(token=None, refresh_token=refresh_token,
                       token_uri="https://oauth2.googleapis.com/token",
                       client_id=settings.google_client_id,
                       client_secret=settings.google_client_secret,
                       scopes=[DRIVE_SCOPE])


def create_drive_root(credentials: Credentials) -> str:
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    body = {"name": "JnA Financial Documents", "mimeType": "application/vnd.google-apps.folder"}
    folder_id = service.files().create(body=body, fields="id").execute()["id"]
    set_app_setting("drive_folder_id", folder_id)
    return folder_id


def _drive():
    return build("drive", "v3", credentials=google_credentials(), cache_discovery=False)


def _find_or_create_folder(service, parent_id: str, name: str) -> str:
    safe = name.replace("'", "\\'")
    query = f"name='{safe}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    result = service.files().list(q=query, fields="files(id,name)", supportsAllDrives=True,
                                  includeItemsFromAllDrives=True).execute()
    if result.get("files"): return result["files"][0]["id"]
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    return service.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"]


def upload_pdf(pdf_path: Path, data: dict) -> tuple[str, str]:
    drive_folder_id = get_app_setting("drive_folder_id")
    if not drive_folder_id: raise RuntimeError("Google Drive folder is not configured")
    service = _drive(); now = datetime.now(ZoneInfo(settings.timezone_name))
    year = _find_or_create_folder(service, drive_folder_id, str(now.year))
    month = _find_or_create_folder(service, year, now.strftime("%B"))
    type_name = {"tax_invoice":"Tax Invoices", "invoice":"Invoices", "receipt":"Receipts",
                 "acknowledgement":"Acknowledgement Receipts"}[data["document_type"]]
    target = _find_or_create_folder(service, month, type_name)
    safe_client = "-".join(data["client_name"].split())[:60]
    safe_user = data.get("username") or str(data["created_by"])
    filename = f"{now:%Y-%m-%d}_{data['document_number']}_{safe_client}_@{safe_user}.pdf"
    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=False)
    result = service.files().create(body={"name": filename, "parents": [target]}, media_body=media,
                                    fields="id,webViewLink", supportsAllDrives=True).execute()
    return result["id"], result.get("webViewLink", "")


def create_audit_record(data: dict, pdf_path: Path, drive_file_id: str, drive_link: str) -> None:
    clean_data = dict(data)
    with engine.begin() as conn:
        conn.execute(insert(documents).values(document_number=data["document_number"], status="active",
            data=clean_data, drive_file_id=drive_file_id, drive_link=drive_link,
            sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(), created_at=utcnow()))


def recent_documents(limit: int = 10, created_by: int | None = None) -> list[dict]:
    with engine.connect() as conn:
        query = select(documents)
        if created_by is not None:
            query = query.where(documents.c.data["created_by"].astext == str(created_by))
        rows = conn.execute(query.order_by(documents.c.created_at.desc()).limit(limit)).mappings().all()
    return [dict(row["data"], status=row["status"], drive_link=row["drive_link"],
                 created_at=row["created_at"]) for row in rows]


def _get_document(document_number: str):
    with engine.connect() as conn:
        return conn.execute(select(documents).where(documents.c.document_number == document_number)).mappings().first()


def mark_void(document_number: str, admin_id: int, reason: str) -> bool:
    row = _get_document(document_number)
    if not row: return False
    data = dict(row["data"]); data.update({"voided_by": admin_id, "void_reason": reason,
                                          "voided_at": utcnow().isoformat()})
    with engine.begin() as conn:
        conn.execute(update(documents).where(documents.c.document_number == document_number)
                     .values(status="void", data=data))
    return True


def delete_document(document_number: str, admin_id: int, reason: str) -> bool:
    row = _get_document(document_number)
    if not row: return False
    if row["drive_file_id"]:
        _drive().files().update(fileId=row["drive_file_id"], body={"trashed": True},
                                supportsAllDrives=True).execute()
    data = dict(row["data"]); data.update({"deleted_by": admin_id, "delete_reason": reason,
                                          "deleted_at": utcnow().isoformat()})
    with engine.begin() as conn:
        conn.execute(update(documents).where(documents.c.document_number == document_number)
                     .values(status="deleted", data=data))
    return True
