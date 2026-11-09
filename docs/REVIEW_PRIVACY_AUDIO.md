# AI Guardian voice, telephone and privacy review

## Important architecture distinction
The **guardian's automated call** and the **scammer's original incoming call** are different communication channels. Our app can optionally place a guardian call using an approved telephony provider; this gives no automatic access to the original cellular/WhatsApp call or caller location.

## Audio evidence sources (only when consented and technically accessible)
1. Customer manually describes the call; low-trust self-report.
2. Customer uploads a lawful recording/transcript; label provenance and require consent.
3. A call intentionally initiated through an approved VoIP/telephony service may expose recording/transcription features under its terms; permissions and retention apply.

## Do not claim
- Exact scammer location from their phone number.
- Reliable lie detection from speaking tone/emotion.
- A voice model can prove fraud or eliminate coercion.
- An ordinary website can access arbitrary phone call audio.

## Safer classifier goals
Recognize phrases of authority impersonation, threats, urgency, secrecy demands, OTP requests, unusual destination changes, and instruction to bypass safeguards. Return uncertainty and *evidence snippets*, not a fabricated 'fraud certainty' percentage.

## Timers
Choose 30/45/60-second **review-window preferences**, not security overrides. Call delivery, ring time and authentication may exceed 30 seconds. A no-answer event only changes review route; never grants authorization.

## Consent/security requirements
Separate recording consent from ordinary app consent; ensure deletion/retention rules. Guardians get minimal information by default and approve in authenticated app, not solely through caller ID, keypad or voicemail. Ensure no raw voice data is sent to free model APIs with incompatible data terms.
