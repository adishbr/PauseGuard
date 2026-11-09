# Free-tier, credential and privacy safeguards

## Financial policy
- No paid billing, trial conversion, card entry, credit top-up, or metered production deployment without explicit user approval.
- Free providers commonly have request/token limits and may log user submissions. Use **synthetic/fictional** payments, bank identifiers, phone calls and locations. Never send real PINs, OTPs, keys, real account history or user voice recordings to free LLM services.
- Separate development credentials per person; when a person leaves, revoke their key and role.
- Recheck official billing dashboards weekly and before demos; model listed does not guarantee free API.

## Key management
- `.env`, `.env.local`, `.ssh`, auth stores, cloud token files must remain out of Git and out of agent chat output.
- Store only safe placeholders in `.env.example`.
- Never log webhook secrets or print full environment variables. Rotate exposed keys immediately.
- Use the least privilege GitHub token or OAuth scopes, workspace-only agent permissions and protected main branch.

## Privacy for Guardian/AI review
- Guardians opt in and only receive the minimum required information.
- Recording caller speech requires consent, feasible audio access and retention limits; voicemail/call metadata isn't a license to wiretap a third party.
- A browser cannot locate another person simply from their phone number. The payer may consent to device geolocation; treat it as weak evidence.
- **AI can advise only**; its suggestions don't override hard fraud restrictions or authorize money movement.

## Terms and logging references
- OpenRouter free models & quotas: https://openrouter.ai/collections/free-models
- Nemotron free data rules: https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free
- NVIDIA free endpoint terms: https://build.nvidia.com/
- Groq limits: https://console.groq.com/docs/rate-limits
