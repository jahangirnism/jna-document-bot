import base64
import os
import secrets

print("WEBHOOK_SECRET=" + secrets.token_urlsafe(32))
print("GOOGLE_OAUTH_SETUP_KEY=" + secrets.token_urlsafe(32))
print("DATA_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
