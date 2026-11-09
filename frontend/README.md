# PauseGuard frontend · Phase 1

A local V2 payment simulation with a payer workspace and a privacy-limited guardian inbox. Use the synthetic recipient and purpose options. The two fixture accounts are pre-enrolled for the demo.

## Run locally

Use Node.js 24 and the locked frontend dependencies.

```sh
npm ci
npm run dev
```

1. Open the local URL shown by Vite. Select **Open guardian window** and keep the payer and guardian windows side by side.
2. In the payer workspace, select **Coerced KYC transfer** and **Check payment**. In the guardian workspace, select **Open review**. In a separate browser profile, open `/guardian` and paste the request reference from the payer screen.
3. Reject the request to stop the transfer, or approve the review to return control to the payer for a separate **Confirm simulated payment** action. If the 30-second review window closes first, both screens show the hold. The payer can stop the request.
4. Try **Everyday purchase** for a routine confirmation or **Unfamiliar supplier** for a warning before confirmation. These cases skip guardian review.

`npm run build` and `npm run preview` also support the local demo. The Vite fixture keeps state in memory. A server restart clears its requests. Browser reloads on the same server recover the selected request. An unavailable payer reference can be cleared from the status screen.

## API handoff

The browser uses the documented `/api/v2` payment paths with separate synthetic bearer identities. Browser storage shares only the guardian request reference across windows. The guardian always loads the authorized view from HTTP. That view contains only `id`, `status`, `tier`, `guardian_deadline`, and a generic `message`. In a separate profile the reference is entered manually.

| Action | Request |
|---|---|
| Create | `POST /payments` with `beneficiary_id`, integer `amount_paise`, `purpose`, and `idempotency_key` |
| Reload | `GET /payments/{id}` with the payer or guardian demo bearer token |
| Warning acknowledgement | `POST /payments/{id}/warning/acknowledge` with an empty JSON object |
| Guardian review | `POST /payments/{id}/guardian/decision` with `{"decision":"approve"}` or `{"decision":"reject"}` |
| Cancel | `POST /payments/{id}/cancel` with an empty JSON object |
| Confirm | `POST /payments/{id}/confirm` with `{"idempotency_key":"confirm:<payment-id>"}` |

Komal should verify the fixture's guardian decision and confirmation payloads against the backend's eventual OpenAPI schema. The fixture advances the deadline on payment reads and applicable actions using server time. It models an execution state without a ledger. The browser polls active requests and refreshes on reconnect. The shared contract does not specify an event stream yet. The browser fixture tokens are public synthetic identifiers. Keep the server local.

## Checks

```sh
npm run build
npm run lint
npm test
```

With the demo server running and Playwright plus Chromium available, run `npm run test:browser`. Set `PLAYWRIGHT_MODULE` to the installed Playwright module path when using shared tooling. Optionally set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` for an existing Chromium binary or `PAUSEGUARD_TEST_ORIGIN` for a different local port.

The browser cases cover approval and separate confirmation, rejection from an isolated browser profile, review expiry, reconnect after a failed status request, mobile keyboard entry and a retry after a lost creation response. The fixture tests cover role and field isolation, paise conversion, replay, terminal states and the server deadline.
