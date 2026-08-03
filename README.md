# Attribution Desk — MoEngage to Google Sheets

This is a live automation service. It does not require Excel uploads.

1. Connect the existing Google Sheet.
2. Open a MoEngage browser window and complete the normal SSO/password/MFA login.
3. Start the job from the React dashboard.
4. The backend reads each live sheet row, switches MoEngage workspace, applies the
   campaign filters, runs the Unique Users and Total Revenue queries, and writes
   both results directly back to Google Sheets.

## Live sheet mapping

| Input | Column | Use |
|---|---:|---|
| Channel | C | WhatsApp, SMS, or RCS |
| Brand | E | MoEngage workspace/environment |
| Campaign Channel Type | V | Online, Offline, or Overall |
| Track Goals for | Y | Query date range, using Column A for missing context |
| Campaign ID | Z | Readable Campaign ID filter |

| Campaign type | Unique Users | Total Revenue |
|---|---:|---:|
| Overall | AA | AD |
| Online | AB | AE |
| Offline | AC | AF |

The provided workbook was inspected only to establish this schema. Its `Mastersheet`
contains 2,294 processable campaigns and three rows with a blank Column V.

## 1. Google Sheets credentials

Create a Google Cloud service account, enable Google Sheets API and Google Drive API,
and download its JSON key to:

```text
Backend/credentials/google-service-account.json
```

Share the target Google Sheet with the JSON key's `client_email` as an Editor. This
allows scheduled/unattended runs without storing a personal Google password.

## 2. MoEngage login and selectors

The application launches a real local Chromium window. The frontend accepts a
Google email so multiple
Google/MoEngage identities can be kept separately. The original `default` session
stays under `Backend/storage/moengage-profile`; additional sessions are stored under
`Backend/storage/moengage-profiles/<profile-id>`. Previously used emails and their
Google browser sessions remain available in the profile picker. A password is
forwarded only to the local backend for the current login request and is never
written to disk. Use
**Clear profile & login** only when a selected profile has the wrong
Google account saved and its local cookies must be removed.

When the profile name is an email address, the login helper clicks the MoEngage
Google option, enters the request-scoped email and password, and leaves any MFA or
CAPTCHA to the user. It intentionally cannot read or copy credentials from the normal
Chrome profile: modern Chrome and Playwright do not support automating the default
user-data directory, particularly while that Chrome profile is already open.

MoEngage dashboard controls are workspace/account specific. Configure the actual
query-page URL and selectors in `MOENGAGE_UI_CONFIG_JSON` in `Backend/.env`. The
example file contains every required selector. These must be captured from the
logged-in dashboard before real queries can run.

The automation executes this sequence for each sheet row:

```text
Brand workspace → Online/Offline/Overall → WhatsApp/SMS/RCS
→ Readable Campaign ID → start/end date → Unique Users → run
→ Total Revenue → run → write the matching AA–AF cells
```

## 3. Run locally

```bash
cd Backend
cp .env.example .env
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --reload
```

```bash
cd Frontend
npm install
npm run dev
```

Open `http://localhost:5173` and follow the two connection cards.

## 4. Deploy to Railway

Railway deploys this repository as one service. The Docker build compiles the Vite
frontend and copies it into the FastAPI image, so the browser loads both the UI and
`/api` from the same public domain. No production `VITE_API_BASE_URL` is required,
and same-origin requests avoid CORS failures.

In the Railway service settings:

1. Keep **Root Directory** empty (repository root).
2. Keep **Build Command** and **Start Command** empty. `Dockerfile` supplies both.
3. Click **Generate Domain** under Public Networking.
4. Railway reads `railway.toml` and uses `/api/health` as the healthcheck.
5. Add the values from `railway.env.example` in the **Variables** tab. Seal
   `GOOGLE_SERVICE_ACCOUNT_JSON` and any variable containing API keys.
6. Attach a volume at `/data` if browser profiles, uploaded credentials, or output
   files must survive redeploys. The app automatically uses Railway's volume mount.

The complete Google service-account JSON belongs in the Railway
`GOOGLE_SERVICE_ACCOUNT_JSON` variable. Do not add it to Git. Share the spreadsheet
with the `client_email` from that JSON.

### MoEngage production requirement

The local `browser` mode opens a visible Chromium window for Google SSO/MFA. A
Railway container has no user-visible desktop, so that login flow cannot be completed
from the deployed web page. Use `MOENGAGE_MODE=api` with valid
`MOENGAGE_BRAND_CONFIG_JSON` endpoints for production. `MOENGAGE_MODE=mock` can be
used only to verify the deployment UI. Browser-mode production would require a
separate remote-browser/VNC login design and persistent storage.

If the frontend is later split into another service/domain, set `VITE_API_BASE_URL`
on that frontend to the backend's public URL plus `/api`, and set `CORS_ORIGINS` on
the backend to the exact frontend origin. Vite variables are public and build-time;
never put credentials in a `VITE_` variable.

## Verification

```bash
cd Backend
PYTHONPATH=. venv/bin/python -m unittest discover -s tests -v

cd ../Frontend
npm run lint
npm run build
```

Google credentials and the MoEngage browser profile are local secrets and must not
be committed to source control.
