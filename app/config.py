import os
from dataclasses import dataclass


def _user_ids(value: str) -> frozenset[int]:
    return frozenset(int(item.strip()) for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    admin_user_id: int = int(os.getenv("ADMIN_USER_ID", "1124582593"))
    allowed_user_ids: frozenset[int] = _user_ids(os.getenv("ALLOWED_USER_IDS", "8671901070"))
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_oauth_setup_key: str = os.getenv("GOOGLE_OAUTH_SETUP_KEY", "")
    data_encryption_key: str = os.getenv("DATA_ENCRYPTION_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/jna")
    audit_chat_id: str = os.getenv("AUDIT_CHAT_ID", "1124582593")
    timezone_name: str = os.getenv("TIMEZONE", "Asia/Dubai")
    railway_public_domain: str = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")


settings = Settings()
