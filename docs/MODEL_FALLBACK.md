# AI model failover after Antigravity trial or quota changes

Do NOT assume that a claimed trial expiration disables the entire IDE. Check the account's model selector and actual entitlement. As of 9 Nov 2026, Antigravity docs show Gemini 3.8 Flash in the Free tier, while certain Claude and GPT-OSS model options are marked for 18 Nov 2026 removal. User-reported 13 Nov access change is account-specific; verify locally.

## Stable workspace architecture
Git repository + contracts **never move** when the model changes.
```
Antigravity editor + Git repository
   ├── Antigravity built-in Gemini (where accessible)
   └── Integrated PowerShell terminal
          └── OpenCode CLI
                ├── OpenRouter Nemotron 3 Ultra :free
                ├── NVIDIA Build GLM-5.3 Flash / DeepSeek V4.1 Flash
                └── Groq GPT-OSS 120B
```

## Failover procedure (one step at a time)
1. Save current files and note `git status`; commit or stash only after human instruction. Do not close active AI session while uncommitted work is unsaved.
2. Record current branch and last passing test results in `docs/PROGRESS.md`.
3. Confirm provider quota and account is still free; reject upgrade/billing prompts.
4. Open new PowerShell in same repo. Verify `opencode --version`; install only if missing.
5. Launch `opencode`; use `/connect` to configure a verified provider, then `/models` to select a verified free model. Never infer free status from a friendly model name alone.
6. Use Plan/read-only mode; load `AGENTS.md`, V2 contracts and member prompt; request a **plan for next small task**.
7. Test tiny harmless message with no private data; only after response succeeds should model undertake approved repo task.
8. Check new model output conforms to exact API/state contracts, run tests, review diff; do not merge without human review.

## Model-specific cautions
- **OpenRouter**: prefer exact `:free` suffix; know 50/day quota at uncredited free access, data logging rules and no sensitive input.
- **NVIDIA Build**: free prototype endpoints are for testing, may go away; model IDs must be selected from official model listing/API example, not invented.
- **Groq**: high throughput but TPM/RPD apply; use shorter task prompts if context too large.
- **Antigravity Gemini**: IDE access is not the same as direct API access inside OpenCode.
- **FreeLLMAPI/Claude proxy**: gateway slot names can mask underlying model; distinguish router from genuine Anthropic model; the local gateway must be running.

## When every external provider is down
Stop AI requests, do normal local editing/testing. Maintain progress and docs in Git. No dependency on a model provider is allowed in the actual payment authorization process.
