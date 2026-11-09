# Canonical policy matrix V2 (proposed)

**Policy ownership: Komal (backend) with Adish (UI), Gowtham (risk advisory) and Jeevan (test/safety).**
This table is for design and demos, **not** a validated anti-fraud risk model or RBI-mandated threshold table.

## Profiles
- `personal`: personal-scale behavioral baseline, optional guardian, notifications privately by default.
- `professional`: verified employment/payment context when available; no automatic business exemptions.
- `small_business`: expected supplier outflows and regular new beneficiaries, verified onboarding and separate staff roles if applicable.
- `enterprise`: formal maker-checker controls, managed keys and business audit privileges. Sole proprietor may instead use non-guardian verification.

The user's amount input is called **`notification_preference_paise`**, not a mandatory guardian threshold. Changes need reauthentication, alerts and a cooling-off period in production. The server retains an independent policy and verified baseline. A user-selected account type is not proof of a business identity.

## Rules ordered by priority
1. **Hard denial/restriction**: confirmed fictional registry hit, active Safe-Lock, invalid authorization, disallowed recipient, terminal payment. Never overridden by AI, user threshold, location, a phone call or an emergency purpose.
2. **Behavioral and contextual risk**: unusual amount *relative to verified baseline*, new recipient frequency, beneficiary verification, credential/device changes, structuring velocity, corroborated coercion.
3. **User preference**: customer-chosen notification threshold influences warnings/UX but never removes hard security checks.
4. **Optional review**: minimal guardian contact, secure independent authorization, fallback. 30 seconds is a demo first-response window, not a universal banking rule.
5. **Final payer confirmation** and live policy recheck before mock execution or gateway checkout.

## 12 example decisions
| Scenario | Tier / decision | Why |
|---|---|---|
| Personal ₹100 to familiar merchant | T0 | normal pattern |
| Personal ₹500 new payee, no indicators | T0 or T1 | 500 isn't intrinsically fraud |
| Personal ₹55k new payee, coerced KYC purpose | T3, review/restrict | combined deviation + coercion |
| Business ₹50k new supplier, normal device | T0 or T1 | ordinary baseline, verify payee as needed |
| Business ₹20L anomalous payee and new device | T2/T3 | combined independent risks |
| Previously trusted payee, suddenly changed account details | T2/T3 | beneficiary substitution |
| Verified hospital with independently verified destination | T0/T2 based on context | high value alone insufficient |
| Unverified 'hospital' personal UPI ID claimed by caller | T2/T3 | label is untrusted |
| Known flagged recipient for any profile | Hard reject/restrict | strongest verified signal |
| Guardian absent for 30 seconds, moderate risk | T2 alternative verification if allowed | no automatic pass |
| Guardian absent for 30 seconds, critical risk | T3 hold/restrict | AI cannot approve |
| User raises alert threshold while under pressure | cooling-off + reauth | defense against coercion |

## Calibration and fairness
Different profiles can have different baselines, but evaluate false-positive and false-negative rates separately across personal/professional/business, new users, seniors and languages. Profile selection alone must not silently lower risk. Models trained only on synthetic cases should never claim real efficacy.
