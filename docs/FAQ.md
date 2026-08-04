# Attribution Desk — FAQ and Troubleshooting

## Why is an Overall campaign slower?

Overall requires four sequential UI queries: Online users, Offline users, Online
revenue and Offline revenue. Online or Offline rows require two. The automation is
sequential so filters from different campaigns cannot race and produce wrong values.

## Why are rows marked skipped?

Overwrite is off and all required destination values already exist. This is the
safe behavior for resuming after a crash or deployment.

## Why does the app say another job is running?

Only one browser automation job can safely control the MoEngage report page. Stop
the active run or wait for it to finish. The app now cancels the real background
task, not only the status label.

## Why can’t I switch or verify login during a run?

Changing the browser page while the job is entering filters would corrupt the query.
The login controls are locked until the current job finishes or is cancelled.

## What does “browser tab crashed” mean?

Chromium's renderer or CDP connection stopped responding. The app closes the failed
tab, reconnects, creates a clean automation tab and retries once. If failures repeat,
stop the job, restart `moengage-browser`, verify login and rerun with overwrite off.

## Why did the login button open `about:blank`?

An older frontend opened a placeholder tab while waiting for the backend to attach
to Chromium. If CDP was frozen, the placeholder remained blank. The login button now
opens the protected Railway browser URL directly. Hard-refresh the frontend after
deployment if the old behavior is cached.

## What does “query timed out after 180 seconds” mean?

MoEngage did not finish a single metric query within the safety limit. The row fails
instead of blocking all future work, and the automation tab is reset.

## What caused “Could not find the MoEngage workspace switcher”?

MoEngage hides the switcher on some report layouts. The application now recognizes
the workspace from its dashboard ID and can open the saved brand report directly.

## Why does the sheet look connected after a deployment but a request says it is not?

Google Sheet connection IDs and job history live in application memory. A deployment
creates a new process. Hard-refresh or click **Change**, then reconnect the same
sheet. Values already written to the sheet remain intact.

## Why did an invalid goal date not run?

This is deliberate. Unparseable goal dates now produce a row warning instead of
silently using the sent date and returning potentially wrong metrics. Correct the
`Track Goals for` cell and reconnect the sheet.

## Are currency-formatted existing values supported?

Yes. Values such as `₹4,99,279.00`, comma-separated numbers and parenthesized
negatives are parsed. Invalid nonblank values are reported instead of treated as
empty.

## Why do zero users and nonzero revenue fail?

That combination normally indicates a partially refreshed MoEngage result. The app
does not write inconsistent users/revenue pairs. Retry after the report finishes.

## What is written to AA–AF?

| Column | Value |
|---|---|
| AA | Total unique users |
| AB | Online unique users |
| AC | Offline unique users |
| AD | Total influenced revenue |
| AE | Online influenced revenue |
| AF | Offline influenced revenue |

## Does Retry Failed overwrite successful rows?

No. It builds a new job containing only rows marked failed in the selected terminal
job. After a deployment, use the original filters with overwrite off instead because
the old in-memory job history no longer exists.

## Can two people run it simultaneously?

They can open the frontend, but only one automation job may run. A second start is
rejected with HTTP 409 to protect query correctness.

## Should the Railway login browser stay open?

Only while logging in or diagnosing. Close that browser tab during campaign runs to
reduce video-streaming CPU and memory pressure.

## Where is the Railway browser password?

Railway project → `moengage-browser` service → Variables → `PASSWORD`. Do not paste
the active password into chat or documentation.

## Why can Railway show Online while a query is unhealthy?

The deployment healthcheck confirms the web process responds during deployment. It
is not continuous MoEngage monitoring. Attribution Desk separately reports whether
the persistent MoEngage session is connected.
