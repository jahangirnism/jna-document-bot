# JnA House Telegram Document Bot - Railway

Creates Tax Invoices, Invoices, Receipts and Acknowledgement Receipts from Telegram, saves PDFs to Google Drive, and preserves an audit register in Railway PostgreSQL.

## Locked configuration

- Telegram bot: `@Jnadoc_bot`
- Administrator: Telegram ID `1124582593` (`@jahangirdxb`)
- Access: administrator only
- Stamp: not used
- Numbering uses only three shared series: Sales begins at `JNA_S_0001`; Rent at `JNA_R_0001`; Acknowledgement Receipt at `JNA_ACK_0001`. No `INV` or `REC` numbering series are generated.

## Railway services

1. One application service built from this Dockerfile.
2. One Railway PostgreSQL service.
3. A Railway public domain for the bot service.

Railway detects the root `Dockerfile` and builds it automatically. Add PostgreSQL from the Railway project's **New** menu. Railway exposes its database connection as `DATABASE_URL`; reference it from the bot service instead of copying the password.

## Required Railway variables

| Variable | Value |
|---|---|
| `ADMIN_USER_ID` | `1124582593` |
| `AUDIT_CHAT_ID` | `1124582593` initially |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `GOOGLE_CLIENT_ID` | Google OAuth Web Client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Web Client secret |
| `GOOGLE_OAUTH_SETUP_KEY` | Random secret used only when connecting Drive |
| `DATA_ENCRYPTION_KEY` | Fernet-compatible key used to encrypt the Google refresh token |
| `TELEGRAM_BOT_TOKEN` | Regenerated token; never commit it or paste it in chat |
| `TIMEZONE` | `Asia/Dubai` |
| `WEBHOOK_SECRET` | A random 32+ character secret |

Run `python generate_secrets.py` once to generate the webhook, OAuth setup and encryption keys. Seal `TELEGRAM_BOT_TOKEN`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_SETUP_KEY`, `DATA_ENCRYPTION_KEY`, and `WEBHOOK_SECRET` in Railway after saving them. Railway automatically supplies `RAILWAY_PUBLIC_DOMAIN`; the app uses it to register the Telegram webhook on every successful deployment.

## Google Drive access

For a normal personal Gmail account, use Google OAuth:

1. In Google Cloud project `jna-document-bot`, enable **Google Drive API**.
2. Open **Google Auth Platform** and create the app branding as `JnA Document Bot`.
3. Set the audience to **External** and add your Gmail address as a test user.
4. Add only the Google Drive `drive.file` scope. This lets the bot manage the folder and PDFs it creates, not unrelated Drive files.
5. After Railway generates the public domain, create an OAuth Client of type **Web application**.
6. Add this exact authorised redirect URI: `https://YOUR-RAILWAY-DOMAIN/google/callback`.
7. Put the Client ID and Client Secret into Railway.
8. Redeploy, then visit `https://YOUR-RAILWAY-DOMAIN/google/connect`.
9. Enter `GOOGLE_OAUTH_SETUP_KEY`, sign in to Google and approve access.
10. The bot automatically creates `JnA Financial Documents` in your personal Drive and stores only the encrypted refresh token in PostgreSQL.

Before relying on the automation permanently, move the OAuth app from **Testing** to **Production**. Google limits refresh-token lifetime for apps that remain in Testing.

## Deploy

1. Push this folder to a private GitHub repository.
2. In Railway, choose **New Project → Deploy from GitHub repo** and select it.
3. Add a PostgreSQL service.
4. Add the required variables above to the bot service.
5. In **Settings → Networking**, select **Generate Domain**.
6. Set the health-check path to `/health`.
7. Redeploy after the variables and domain exist.
8. Open `@Jnadoc_bot` and send `/start`.

No persistent volume is required.

## Bot workflow

`/new` asks for document type, client name, address, TRN, Sales/Rent, description, note, amount and VAT. After confirmation, the PDF is generated, stored in dated Google Drive folders, registered with its SHA-256 hash in PostgreSQL and returned in Telegram.

## Commands

- `/start` - home menu
- `/new` - create a document
- `/history` - recent audit records
- `/void JNA_S_0001 reason` - void while retaining the archive
- `/delete JNA_S_0001 reason` - move the Drive copy to Trash while retaining the audit record

Telegram users can delete messages from their own chats. Google Drive and PostgreSQL remain the authoritative record; only the configured admin ID can invoke void or delete actions.

## Local PDF check

Install the dependencies and run `python create_sample.py`. The generated `sample_output_no_stamp.pdf` uses the approved production layout with test data and contains no stamp. Run `python -m unittest discover -s tests` for the PDF calculation and render checks.
