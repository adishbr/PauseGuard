# PauseGuard V2 — Reporting Guidance

**Owner:** Member 4 — Safety, Privacy, Recovery and QA  
**Status:** Proposed reporting and incident-handling guidance

## 1. Purpose

This document defines how PauseGuard V2 security concerns, suspicious payment attempts, safety-policy violations and technical failures should be reported.

The goal is to support responsible investigation while protecting user privacy and avoiding unsupported claims.

## 2. What Should Be Reported?

Report the following situations:

- Suspected coercion, impersonation, threats or suspicious payment instructions.
- Repeated or potentially automated payment attempts.
- Unauthorized access or role/IDOR violations.
- Safe-Lock policy violations.
- Guardian timeout or unexpected guardian workflow behavior.
- Duplicate payment attempts or inconsistent payment states.
- Audit-chain verification failures.
- Sensitive information exposed in logs, alerts or evidence exports.
- Authentication, authorization or transport-security failures.
- Unexpected backend or frontend behavior during a payment flow.

## 3. Severity Classification

| Severity | Description                                                                          | Example                                         |
| -------- | ------------------------------------------------------------------------------------ | ----------------------------------------------- |
| Critical | Possible unauthorized payment execution or serious exposure of sensitive information | Unauthorized execution or credential leakage    |
| High     | Major security control failure                                                       | Authorization bypass or audit integrity failure |
| Medium   | Safety workflow malfunction without confirmed unauthorized execution                 | Guardian timeout handled incorrectly            |
| Low      | Minor issue or documentation problem                                                 | Incorrect non-sensitive localization text       |

Severity should be updated if investigation reveals greater or lower impact.

## 4. Information to Include in a Report

A report should include:

- Unique incident or case reference.
- Date and time, including timezone.
- Environment: local, test or approved staging.
- A short description of the issue.
- Expected behavior.
- Actual observed behavior.
- Reproduction steps, if safe and possible.
- Relevant event IDs or redacted audit references.
- Test results and error messages.
- Severity and current investigation status.

Do not include passwords, API keys, authentication tokens, full bank details or unnecessary personal information.

## 5. Privacy and Evidence Handling

- Use case IDs and event IDs instead of personal identifiers wherever possible.
- Redact phone numbers, email addresses and UPI-like identifiers before sharing evidence.
- Do not include full payment details in guardian-facing reports.
- Share evidence only with authorized reviewers through approved channels.
- Keep the original evidence protected when an investigation requires it.
- Record who accessed or exported sensitive evidence where supported.
- Review every export before sharing it externally.

Redaction reduces exposure but does not guarantee anonymity.

## 6. Reporting Suspicious Payment Attempts

When a suspicious payment attempt is identified:

1. Record the relevant case and event references.
2. Preserve the available audit information.
3. Record the indicators that triggered concern.
4. Confirm the backend payment state.
5. Escalate suspected authorization or execution failures to the responsible backend owner.
6. Avoid claiming that a payment was blocked, reversed or recovered unless verified by an authoritative system.

PauseGuard cannot independently reverse a settled UPI transaction or freeze a bank account.

## 7. Escalation and Ownership

| Issue                                   | Responsible team                                     |
| --------------------------------------- | ---------------------------------------------------- |
| Purpose challenge or coercion detection | Member 4 / Safety                                    |
| Rolling anti-smurfing behavior          | Member 4 / Safety                                    |
| Safe-Lock policy concerns               | Member 4 with backend owner                          |
| Audit integrity failure                 | Member 4 / Backend owner                             |
| Authorization or IDOR issue             | Backend owner / Security                             |
| Guardian workflow failure               | Backend owner / Member 4                             |
| Transport-security issue                | Backend / Infrastructure owner                       |
| Payment-state inconsistency             | Backend owner and designated state-machine approvers |

Changes to canonical payment states or core payment APIs require the project's established approval process.

## 8. External Reporting and User Guidance

For suspected financial fraud in India:

- Contact the relevant bank or payment service provider promptly through its official support channel.
- Report suspected cyber financial fraud through the official National Cyber Crime Reporting Portal: https://cybercrime.gov.in/
- The national cybercrime helpline is **1930**.
- Preserve transaction references and official communications for the investigation.
- Follow instructions from the bank and relevant authorities.

PauseGuard may provide guidance but must not automatically submit a police or cybercrime report on behalf of a user.

## 9. Incident Closure

An incident should be closed only after:

1. The issue has been investigated.
2. Relevant evidence has been reviewed.
3. The root cause or known limitation has been documented.
4. Required corrective action has been completed or assigned.
5. Relevant tests have passed, where applicable.
6. An authorized reviewer has accepted the resolution.

If the issue cannot be reproduced or fully resolved, record that limitation rather than claiming success.

## 10. Important Safety Rules

- AI-generated risk advice is advisory only.
- A guardian call connection or DTMF input alone is not payment approval.
- A 30-second guardian timeout is not approval.
- Only the authorized backend state machine may perform permitted payment-state transitions.
- Safe-Lock and hard-risk checks must not be bypassed.
- Terminal payment states must remain irreversible.
- Reports and evidence exports must not expose unnecessary financial or personal data.

## 11. QA Acceptance Checklist

- [ ] Reports contain a case or event reference.
- [ ] Sensitive values are redacted before sharing.
- [ ] Guardian-facing information is privacy-safe.
- [ ] Audit verification failures can be escalated.
- [ ] Severity and ownership are recorded.
- [ ] External reporting guidance is accurate.
- [ ] No report claims payment recovery without authoritative confirmation.
- [ ] Incident closure includes review and evidence.

**Final note:** This document provides reporting guidance. It does not implement an incident-management platform, submit external complaints or guarantee recovery of financial losses.
