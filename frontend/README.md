# PauseGuard frontend · Phase 2

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
4. Try **Everyday purchase** for a routine confirmation or **Unfamiliar supplier** for a warning before confirmation. Try **Flagged recipient** for an immediate simulated safety block. These cases skip guardian review.

`npm run build` and `npm run preview` also support the local demo. The Vite fixture keeps state in memory. A server restart clears its requests. Browser reloads on the same server recover the selected request. An unavailable payer reference can be cleared from the status screen.

## Phase 2 experience

- The payer can follow Prepare, Review and Outcome, read verification guidance, copy a request reference and confirm separately after approval.
- The guardian sees a limited alert, the server-set deadline and practical ways to verify the request. Separate browser profiles can paste the reference.
- English, Kannada, Hindi and Telugu catalogs cover the demo UI. The language selector remembers the choice in the browser. Amount entry accepts ASCII and the three regional digit sets and sends integer paise. The [bundled Noto script fonts](public/noto-font-license.txt) load locally. Native-speaker review is pending for the translations.
- Status reads back off during network failures and refresh on reconnect. Actions pause while the latest state is unavailable. If a mutation response is lost, the UI fetches status before another action. A create retry reuses its original idempotency key.

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

Komal should verify the fixture's guardian decision and confirmation payloads against the backend's eventual OpenAPI schema. The fixture advances the deadline on payment reads and applicable actions using server time. It models an execution state without a ledger. The browser polls active requests and refreshes on reconnect. The shared contract leaves event delivery for later integration. The client validates the response before rendering it and rejects guardian responses containing extra fields. The browser fixture tokens are public synthetic identifiers. Keep the server local.

## Checks

```sh
npm run build
npm run lint
npm test
```

With the demo server running and Playwright plus Chromium available, run `npm run test:browser`. Set `PLAYWRIGHT_MODULE` to the installed Playwright module path when using shared tooling. Optionally set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` for an existing Chromium binary or `PAUSEGUARD_TEST_ORIGIN` for a different local port.

The browser cases cover the original two-window flows, mobile validation and focus, reduced motion, local fonts, warning acknowledgement, lost confirmation responses, malformed guardian payloads and blocked recipients. Fixture and client tests cover state transitions, authorization, expiry, replay, paise conversion and response validation.

## Phase 3 integration

1. Confirm the `/api/v2` OpenAPI schema with Komal, including identity-scoped access, exact action payloads, errors, deadlines and idempotency. Exercise the same tests against the agreed backend fixture.
2. Connect authenticated payer and guardian sessions and verified guardian enrollment. Keep the guardian payload limited and preserve authorization on every read and action.
3. Agree on the privacy-safe event or notification contract. Re-fetch authoritative status on reconnect and keep expiry and fallback decisions on the backend.
4. Integrate independent verification and any additional review-window options only after the backend supports them. Review the localized safety copy and test it on target devices.
