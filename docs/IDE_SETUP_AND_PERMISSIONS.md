# Antigravity IDE setup — Windows team guide
Read **`docs/ALL_FOUR_INSTALLATION.md` first**. Each of Komal, Adish, Gowtham and Jeevan performs an independent local setup; no assumption that Adish's installations apply to anyone else. Project-level ECC is installed once as a reviewed PR, not four independent conflicting installations.

## A. Prerequisites
- Git, Python (supported version), Node.js LTS, Windows PowerShell, Antigravity IDE, GitHub account.
- Open a workspace folder containing only the approved PauseGuard project. Use PowerShell as terminal default (`Terminal: Select Default Profile > PowerShell`) if WSL continually prompts for updates.
- Confirm `git --version`, `python --version`, `node --version`, `npm --version` in PowerShell. Keep all four on compatible runtime versions and store them in README / lockfiles.

## B. Free recommended editor extensions (search `Ctrl+Shift+X`)
| Extension ID | Name/publisher | Need |
|---|---|---|
| `ms-python.python` | Python — Microsoft | **All four** (mandatory shared baseline) |
| `dbaeumer.vscode-eslint` | ESLint — Microsoft | **All four** (mandatory shared baseline) |
| `esbenp.prettier-vscode` | Prettier — Prettier | **All four** (mandatory shared baseline) |
| `bradlc.vscode-tailwindcss` | Tailwind CSS IntelliSense — Tailwind Labs | **All four** (mandatory shared baseline) |
| `github.vscode-pull-request-github` | GitHub Pull Requests — GitHub | **All four** (mandatory shared baseline) |
| `ms-playwright.playwright` | Playwright Test — Microsoft | **All four** (mandatory shared baseline) |

Extensions are suggestions (`.vscode/extensions.json`) and may not be available in every Antigravity IDE build/marketplace. Verify publisher, permissions and compatibility in your installed editor; do not install a similarly named untrusted extension. Installing extensions does not install npm/Python runtime libraries.

## C. Optional ECC Minimal (ONE reviewed team installation into repo; four pull the same committed files)
Official: https://github.com/affaan-m/ECC ; guide: https://github.com/affaan-m/ECC/blob/main/docs/ANTIGRAVITY-GUIDE.md .
1. Make clean Git backup/commit and review ECC source and package publisher.
2. From **project root**, on PowerShell, first inspect `npm view ecc-universal version` (online). The ECC guide provides pinned example `npx ecc-universal@2.2.3 install --profile minimal --target antigravity` as a published official example; use a reviewed published version and preserve existing project rules rather than overwriting them.
3. Inspect `git status`, `.agents/rules/`, `.agents/skills/` after installation. Restart the agent conversation to refresh skill inventory.
4. Do not stack full ECC, GSD, Ralph Loop and unrelated MCP servers. Do not use an unverified automatic installer script.

## D. Agent access and permissions
- Open Settings > Agent/Permissions (wording varies by version). Start with **Ask / Request Review / Default**, not unrestricted Turbo. Approve only *specific* safe actions.
- Workspace code access is limited to PauseGuard folder. Keep `.env`, `.ssh`, private notes and unrelated local drives outside the agent's scope.
- Allow **read-only fetching** of trusted docs and GitHub metadata per request. Approve any repo clone/network request; never blanket-allow arbitrary URLs or shell commands.
- GitHub extension: sign in yourself, authorize only the intended account/repository scopes. Use branch protections; never supply passwords or PATs in chat.
- Do not grant production Supabase, payment gateway, email/call provider or cloud deployment credentials while building the mock prototype. Use per-developer sandbox test credentials only when the integration phase is approved.
- Enable diff review before applying AI edits. All merges and deploys require human approval.
- On some Antigravity Windows versions the permission settings differ from Linux/macOS; use the locally available review mode rather than copying unsupported advanced rule syntax blindly.

## E. How to access approved GitHub reference code
`docs/APPROVED_GITHUB_REFERENCES.md` lists **candidates**. The AI should identify the one relevant repo, ask permission for read-only fetch, then optionally run `./scripts/fetch_reference.ps1 -Name <shortname>` on the owner's machine. The script never executes third-party code. Review retrieved `LICENSE`, README, release and SHA before any adaptation. Store in `.references/` (gitignored).

## F. No automatic purchases
All editor extensions above are free to install. ECC is open source, but third-party API quotas, GitHub AI service billing, telephony minutes, model inference and cloud hosting may cost money. Check pricing before enabling anything that calls a paid service.

## Verified free model follow-up
Do not confuse editor extensions with model providers. For OpenCode checks and no-billing model fallback see `docs/INSTALL_OPENCODE_WINDOWS.md`, `docs/PROVIDER_SETUP_PLAYBOOK.md`, `docs/MODEL_FALLBACK.md`. The earlier pasted installation prompt says OpenCode is not installed; this is not necessarily true for the current device. Run `opencode --version` first.
