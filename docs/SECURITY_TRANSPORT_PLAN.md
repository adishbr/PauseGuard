# Security Transport Plan — PauseGuard V2

**Owner:** Member 4 — Safety, Privacy, Recovery and QA  
**Status:** Security plan / proposed controls  
**Scope:** Transport security, API communication, webhook verification and sensitive-data handling.

## 1. Purpose

This document defines the transport-security controls recommended for PauseGuard V2.

The goal is to protect data while it travels between the frontend, backend and approved external service providers.

This is a security plan. It does not claim that these controls are already implemented or that production infrastructure has been configured.

## 2. HTTPS and TLS Requirements

All production communication containing application data must use HTTPS.

Recommended requirements:

- TLS 1.3 should be preferred.
- TLS 1.2 is the minimum supported version.
- TLS 1.0 and TLS 1.1 must not be enabled.
- Production HTTP requests should redirect to HTTPS where appropriate.
- HTTP Strict Transport Security (HSTS) should be enabled for production domains after HTTPS deployment is verified.
- Invalid, expired or untrusted certificates must cause the connection to fail.
- Certificate validation must never be disabled to bypass connection errors.
- Certificate renewal and rotation must be planned before expiry.

**Fail-closed rule:** If a secure connection cannot be established, the request must not continue over an insecure connection.

## 3. API Authentication and Token Handling

- API authentication must use trusted backend-validated credentials.
- Authentication tokens must be sent in secure request headers, not URL query parameters.
- Tokens, passwords and secret keys must never be written to application logs.
- Frontend-provided role or user ID values must not be trusted as proof of identity.
- Backend authorization must verify the authenticated actor and requested resource.
- Production authentication should use an approved identity provider or secure session/token system.
- Local demo authentication must not be treated as production authentication.

## 4. Webhook Security

External provider callbacks must be verified before their contents are trusted.

Recommended controls:

1. Verify the webhook signature using a provider-approved signing method.
2. Where HMAC-SHA256 is supported, calculate the signature over the exact raw request body.
3. Compare signatures using a constant-time comparison function.
4. Validate the webhook timestamp and reject requests outside the configured replay-protection window.
5. Reject missing or invalid signatures.
6. Use idempotency keys or unique event identifiers to prevent duplicate processing.
7. Rotate webhook signing secrets securely.
8. Keep webhook secrets outside source code and frontend bundles.
9. Record verification failures without logging secret values or unnecessary personal data.

A successful webhook signature verifies message integrity and origin under the provider's signing arrangement. It does not independently prove that the underlying real-world event is true.

## 5. Secret Management

The following must never be committed to Git:

- API keys
- Authentication tokens
- Database passwords
- Webhook signing secrets
- Private keys
- Production credentials

Recommended practices:

- Use environment variables for local development secrets.
- Use an approved secrets manager for production deployments.
- Keep local environment files out of version control.
- Provide safe example configuration files containing placeholders only.
- Rotate credentials if they are accidentally exposed.
- Never place secrets in frontend code, screenshots, public documentation or test fixtures.

## 6. Privacy and Logging

Transport security must be combined with data minimization.

- Collect and transmit only information needed for the operation.
- Avoid logging full payment details, phone numbers, UPI IDs, authentication tokens or private personal information.
- Use case references or event IDs where possible.
- Guardian alerts must remain privacy-safe and must not expose full payment details by default.
- Evidence exports must use approved redaction and allowlisted fields.
- Access to security logs must be restricted and auditable.
- Retention periods must be defined by the project privacy policy.

Redaction reduces exposure but does not guarantee anonymity. Exported evidence must still be reviewed before sharing.

## 7. Rate Limiting and Failure Handling

Production API endpoints should have appropriate rate limits.

Additional controls:

- Limit repeated authentication failures.
- Limit repeated webhook verification failures.
- Reject malformed or oversized requests.
- Apply request timeouts.
- Do not retry sensitive operations without idempotency protection.
- Fail closed when authentication, authorization or signature verification fails.
- Do not allow transport errors to bypass Safe-Lock or other backend policy checks.

A network timeout or failed response must never be interpreted as payment approval.

## 8. Security Test Plan

The following checks should be completed before production deployment:

| Test                                    | Expected result                                             |
| --------------------------------------- | ----------------------------------------------------------- |
| HTTP request to a production endpoint   | Redirect to HTTPS or reject, according to deployment policy |
| TLS version below 1.2                   | Connection rejected                                         |
| Invalid or expired certificate          | Connection rejected                                         |
| Missing webhook signature               | Callback rejected                                           |
| Incorrect webhook signature             | Callback rejected                                           |
| Replayed webhook outside allowed window | Callback rejected                                           |
| Duplicate webhook event                 | Not processed twice                                         |
| Secret accidentally added to a log      | Test fails; secret must be redacted                         |
| Token placed in URL                     | Test fails; token must be moved to a secure header          |
| Unauthorized resource access            | Request rejected                                            |
| Transport or verification failure       | No fail-open behavior                                       |

These are acceptance requirements, not claims that the tests have already been executed.

## 9. PauseGuard-Specific Safety Requirements

Transport security must not weaken the payment safety architecture.

- AI components remain advisory only.
- No AI response may directly authorize or execute a payment.
- Guardian call connection or DTMF input alone must not count as approval.
- Guardian timeout remains 30 seconds and is not approval.
- Backend state transitions must remain authorized, atomic and idempotent.
- Safe-Lock and hard-risk checks must be re-evaluated by the backend before any permitted execution path.
- Terminal payment states must remain irreversible.
- No transport failure may cause a payment to execute.
- This plan does not authorize real bank or UPI integration.

## 10. Implementation Dependencies

The following require coordination with the relevant project owners before production integration:

- Backend API middleware and TLS deployment configuration.
- Production authentication and authorization.
- Provider-specific webhook signature verification.
- Secrets manager and credential rotation.
- Infrastructure-level rate limiting and monitoring.
- Security review of deployment configuration.

This document does not modify canonical payment states, shared API contracts, payment execution logic or production configuration.

## 11. Review and Acceptance

Before production release, the team should:

1. Review this plan against the final API and architecture.
2. Confirm the TLS configuration in the deployed environment.
3. Verify authentication and webhook controls.
4. Execute the security tests listed above.
5. Review logs and evidence exports for sensitive-data leakage.
6. Record unresolved risks and obtain the required approvals.

**Final note:** This document describes proposed security controls. Production readiness must be established through implementation, configuration review and successful security testing.
