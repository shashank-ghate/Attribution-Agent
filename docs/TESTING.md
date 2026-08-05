# Attribution Desk — Verification and Test Matrix

## Automated verification

Run from the repository root:

```bash
cd Backend
venv/bin/python -m unittest discover -s tests -v
venv/bin/pip check

cd ../Frontend
npm test
npm run lint
npm run build
npm audit --audit-level=high

cd ..
docker build -t attribution-agent:verification .
```

## Covered failure classes

| Area | Scenarios |
|---|---|
| Request safety | Missing brand/channel/date, conflicting date inputs, AGIPL target validation, overlapping job rejection |
| Date integrity | Cross-month ranges, typo normalization, ordinals, invalid nonblank range rejection |
| Metrics | Online/offline/overall AA–AF mapping, daily sums, revenue aggregation, inconsistent result rejection |
| Sheet data | Blank required inputs, formatted INR values, invalid values, scoped warnings, batch updates |
| Job lifecycle | Success, row failure, skip, retry failed, authentication-expiry abort, cancellation, shutdown cancellation, bounded history |
| Browser recovery | Startup wait, recovery timeout, mid-campaign restart, closed page, matching dashboard IDs, hidden switcher, repeated target crash, clean CDP reconnect, zero rows consumed on failed preflight |
| Frontend API | Success, JSON error, proxy error, network failure, payload construction, query encoding, endpoints |
| Frontend UI | Healthy startup, startup failure rendering, configured-sheet auto-reconnect |
| Supply chain | Python dependency consistency and npm vulnerability audit |
| Deployment | Multi-stage Railway builds, service-specific Dockerfiles, live health/session smoke checks |

## Production smoke test

This test writes real values, so perform it only with an approved campaign and
overwrite off:

1. Confirm both Railway services are Online.
2. Confirm `/api/health` returns `status=ok` and `moengage_connected=true`.
3. Connect the production sheet.
4. Select one already-reviewed campaign.
5. Run with overwrite off.
6. Verify the exact MoEngage result against the AA–AF cells.
7. For Overall, separately verify Online + Offline equals Total for users and revenue.
8. Download the CSV and compare the row with the sheet.

## Limits of automation testing

MoEngage is a third-party SPA and can change its DOM, authentication challenges and
report timing without a code deployment. Mocked failure injection validates the
application's recovery behavior, but a controlled single-campaign smoke test remains
required after MoEngage UI changes or browser-image updates.
