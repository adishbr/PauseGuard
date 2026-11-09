# Free model matrix — verified listings on 9 November 2026

**Check availability again before connecting**. Model listings and quotas change; no API service is promised unlimited. Never enable paid billing or add credits without explicit owner approval.

| Model | Provider | Exact model identifier / route | Free status and caveat |
|---|---|---|---|
| NVIDIA Nemotron 3 Ultra | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` (select through OpenCode `/models`) | $0 model-priced free endpoint; account request caps and logging policy; **no confidential data** |
| GLM-5.3 Flash | NVIDIA Build | model in NVIDIA API sample: `z-ai/glm-5.3-flash` | free prototype listing; trial terms, may throttle/change; **not free production SLA** |
| DeepSeek V4.1 Flash | NVIDIA Build | find exact NVIDIA Build `/models` catalog ID, don't guess | free prototype listed; compatible endpoint and model ID must be checked in account before use |
| GPT-OSS 120B | GroqCloud | `openai/gpt-oss-120b` | free plan exists with org-level quotas; current base limits for this model: 30 RPM, 1K RPD, 8K TPM, 200K TPD, subject to account override |
| Gemini 3.8 Flash | Antigravity built-in | select **Gemini 3.8 Flash** in Antigravity | currently listed for Free tier, quota varies; separate Gemini API is **not presumed free** |

## Suggested role assignments for *coding models*, not people
- **Architect/security reviewer:** strongest available reasoning model; Plan/read-only; compare findings independently.
- **Bounded backend code:** GLM-5.3 Flash or DeepSeek V4.1 Flash after confirmed model/tool support; use tests.
- **Frontend implementation:** Antigravity Gemini 3.8 Flash while allowed; or verified OpenCode model.
- **Fast read-only debugging:** Groq GPT-OSS 120B, mindful 8K TPM may reject huge prompts.
- **Independent second opinion:** OpenRouter Nemotron free, keeping sensitive data out of prompts.

## Costs and privacy
OpenRouter free variants generally allow **20 requests/minute and 50/day without purchased credits**, rising to higher limits only after purchase; failures can count. NVIDIA Nemotron free page explicitly disallows confidential/personal data inputs and warns that prompts are logged. Do not send phone call recordings, real payment details, credentials or unredacted repo secrets to free model endpoints. For a student demo, use synthetic data only.

## Verified official links
- OpenRouter Nemotron: https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free
- OpenRouter free terms: https://openrouter.ai/collections/free-models
- NVIDIA GLM: https://build.nvidia.com/z-ai/glm-5-3-flash/build
- NVIDIA DeepSeek: https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash
- Groq models: https://console.groq.com/docs/models
- Groq free rate limits: https://console.groq.com/docs/rate-limits
- Antigravity models and entitlements: https://antigravity.google/docs/models/
- OpenCode providers: https://opencode.ai/docs/providers

**Distinguish** free access, trial API, OpenCode-specific free model, and genuinely free-local inference. The latter requires local GPU hardware and is not realistically equivalent to serving huge cloud LLMs on a typical laptop.
