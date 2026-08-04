# Attribution Desk — Production SOP

Last reviewed: 4 August 2026

## Purpose

This SOP covers the Railway-hosted Attribution Desk that reads campaign rows from
Google Sheets, obtains attribution metrics through the persistent MoEngage browser,
and writes results to columns AA–AF.

## Production services

| Service | Purpose | Public access |
|---|---|---|
| `Attribution-Agent` | Frontend, API, jobs and Google Sheets writes | `https://attribution-agent-production.up.railway.app` |
| `moengage-browser` | Persistent Chromium login and MoEngage session | Protected Railway browser URL |

The application talks to Chromium through Railway private networking. The browser's
`/config` volume stores the login profile across restarts and deployments.

## Before every run

1. Open Attribution Desk and hard-refresh once (`Cmd+Shift+R` on macOS).
2. Confirm **Backend online**.
3. Confirm the Google Sheet card displays **CONNECTED**.
4. Click **Verify login**. MoEngage must display **CONNECTED**.
5. If login is required, open the Railway login browser, complete login/MFA, return
   to Attribution Desk, and click **Verify login** again.
6. Close the Railway login-browser tab after verification. Leaving the streamed
   desktop open consumes browser CPU and memory during automation.
7. Select at least one brand, one channel, and a bounded sent-date range.
8. Review the exact matching campaign count and preview.
9. Keep **Overwrite existing values** off for normal reruns. Enable it only when
   replacing values is intentional and approved.
10. For a new configuration, run one campaign first. After it succeeds, run the
    remaining selection.

## Run and monitor

1. Click **Run N campaigns** once.
2. Do not open or manipulate the Railway MoEngage browser while a run is active.
3. Do not start a second run. The backend blocks overlapping jobs by design.
4. A normal Online or Offline row performs two MoEngage queries. An Overall row
   performs four sequential queries and therefore takes longer.
5. Watch **processed**, **successful**, **failed** and **skipped** counts.
6. A successful row is written immediately to Google Sheets. A later failure does
   not undo earlier successful writes.

## Stop, retry and resume

- **Stop run** cancels the underlying task and marks the in-progress row retryable.
- **Retry failed** is appropriate when the original run reached a terminal state
  and only its failed rows should run again.
- After a deployment or app restart, job history is intentionally empty. Reconnect
  the sheet and run the same filters with overwrite off. Existing complete rows
  will be skipped and remaining rows will run.
- Never repeatedly press Retry while a job is processing.

## Controlled incident recovery

### Browser tab crashed or query timed out

1. Allow the current row to finish its automatic recovery.
2. If later rows proceed, let the job finish and use **Retry failed** once.
3. If several consecutive rows fail immediately, stop the run.
4. Restart only the browser service:

   ```bash
   railway restart --service moengage-browser --yes
   ```

5. Wait until Railway shows it Online, hard-refresh Attribution Desk, and click
   **Verify login**.
6. Rerun with overwrite off.

### Application is unavailable or returns 502

1. Check the latest `Attribution-Agent` deployment and logs in Railway.
2. Confirm the app listens on Railway's injected `PORT`.
3. Confirm `/api/health` returns HTTP 200.
4. Restart the app service if the latest deployment is healthy but unresponsive:

   ```bash
   railway restart --service Attribution-Agent --yes
   ```

5. Reconnect the Google Sheet after a process restart.

### Login expired

1. Ensure no job is running; stop it if necessary.
2. Open the protected Railway login browser.
3. Complete Google/MoEngage login and MFA inside that browser only.
4. Return to Attribution Desk and click **Verify login**.
5. Close the login-browser tab before running campaigns.

## Deployment procedure

1. Confirm there is no active automation job.
2. Run the full verification suite in [TESTING.md](TESTING.md).
3. Review `git diff` and confirm no `.env`, Google key or password is staged.
4. Commit and push `main`.
5. Wait for both Railway services to report success.
6. Verify `/api/health`, MoEngage connected status, frontend loading, and zero
   active jobs.
7. Perform a single-campaign controlled run with overwrite off before a large run.

Railway configuration is tracked in `/railway.toml` for the app and
`/RailwayBrowser/railway.toml` for Chromium. The app uses a deployment healthcheck,
On Failure restarts, zero overlap, and a graceful shutdown window.

## Security rules

- Never paste the Railway browser password, Google private key, cookies or API keys
  into chat, source code, screenshots or issue descriptions.
- Store secrets only in Railway Variables or ignored local `.env`/credentials files.
- Retrieve the browser password from Railway's `moengage-browser` Variables page.
- Rotate a credential immediately if it appears in logs, Git history or chat.

## Escalation information to capture

When reporting a failure, include:

- Date and time with timezone.
- Job ID and sheet row.
- Brand, channel and Online/Offline/Overall type.
- Exact red error text.
- Whether the Railway login-browser tab was open.
- App and browser deployment IDs.
- The last relevant app/browser log lines, with secrets removed.

