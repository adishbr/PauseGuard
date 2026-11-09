# Provider setup playbook: exact UI steps, no billing

**For AI coaches:** complete one provider at a time. Show one numbered step per reply, verify screenshot/output without secrets, then continue. Never ask for API key in chat.

## OpenRouter: Nemotron 3 Ultra
1. User opens https://openrouter.ai/settings/keys and signs in.
2. Verify current free-model listing and limit. Create scoped key; set any available spending safeguards; do not add credits unless explicitly chosen.
3. In OpenCode run `/connect`, choose OpenRouter, paste key into **local terminal prompt** only.
4. Run `/models`, select `nvidia/nemotron-3-ultra-550b-a55b:free` if displayed. Do not select a similarly named paid model.
5. If reasoning effort option exists use High; otherwise don't fabricate settings.
6. Send safe test prompt and confirm non-error response; record success and quota.

## NVIDIA Build: GLM-5.3 Flash
1. Open https://build.nvidia.com/z-ai/glm-5-3-flash/build ; confirm **Free Endpoint Available** and current trial terms.
2. Generate NVIDIA API key; configure locally via OpenCode `/connect` → NVIDIA.
3. In `/models`, choose provider-supported GLM. Official NVIDIA sample uses `z-ai/glm-5.3-flash`. If it doesn't appear, use official OpenCode custom-provider docs; do not guess configuration or paid alternate.
4. Check trial quota and test once with synthetic text.

## NVIDIA Build: DeepSeek V4.1 Flash
1. Open https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash ; verify free endpoint on your own account.
2. Reuse NVIDIA key if supported; OpenCode `/models` list may require refresh/restart.
3. Select exact NVIDIA-catalog ID, not DeepSeek paid API by mistake. A URL label is not a guarantee of the identifier used in OpenCode.
4. Test tiny request; if not available, record that provider as unavailable and use another verified free option.

## Groq: GPT-OSS 120B
1. Visit https://console.groq.com/keys and review Free plan and quotas first.
2. Generate scoped key; OpenCode `/connect` → Groq.
3. Select model with official ID `openai/gpt-oss-120b` if listed.
4. Verify account limits at https://console.groq.com/docs/rate-limits ; avoid a long prompt if TPM is 8K.
5. Send a harmless test message; confirm response.

## Antigravity built-in Gemini
1. Open Antigravity agent model menu. Select Gemini 3.8 Flash if your account offers it.
2. Set thinking effort for task; check remaining usage and trial status.
3. Do not attempt to reuse an Antigravity account's model access as a separate OpenCode API key without documented authorization.

## Failure handling
`401/403`: credentials/permission. `429`: usage cap. `404/model not found`: wrong ID/endpoint. Network refused: verify local proxy/Gateway process before changing models. Stop at the first error; diagnose; preserve logs with keys redacted.
