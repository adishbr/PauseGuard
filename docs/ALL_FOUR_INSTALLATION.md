# All Four Developers — One Verified Antigravity Installation Baseline

**Applies to every developer**, regardless of whether any teammate installed tools previously: **Member 1 Komal, Member 2 Adish, Member 3 Gowtham, Member 4 Jeevan**. Never infer one member's laptop state from another's.

## Step-by-step protocol (the AI must do ONE STEP PER MESSAGE)

1. Ask member number (unless already stated), device OS/terminal and whether Antigravity opens. Record **Unknown / Present / Missing / Broken**, not "installed" by assumption.
2. Open the latest shared project root in standalone Antigravity. Set Terminal > Select Default Profile > **PowerShell**; do not require WSL. If profile is absent, use Windows PowerShell separately.
3. In PowerShell, **check before installing**: `git --version`, `node --version`, `npm --version`, `python --version`, `opencode --version`. Some missing tools are fine at first. Do not print tokens/secrets.
4. `Ctrl+Shift+X` to open Antigravity's extension view. Each person independently checks these SIX baseline extension IDs: `ms-python.python`, `dbaeumer.vscode-eslint`, `esbenp.prettier-vscode`, `bradlc.vscode-tailwindcss`, `github.vscode-pull-request-github`, `ms-playwright.playwright`. Search by exact ID and verify publishers and supported installation channel. If already installed, skip. No automatic alternative extensions from unfamiliar publishers.
5. Restart/reload editor if it requests that. Verify all six appear in Installed. Optional if verified CLI is available: list extensions, but **do not assume a VS Code `code` CLI manages the standalone Antigravity instance**.
6. Confirm GitHub authentication using the IDE login UI. Each person gets **their own GitHub identity and repo collaborator invitation**. Use least-privilege permissions and no shared PAT/password.
7. Verify that `.vscode/extensions.json`, `.agents/`, `AGENTS.md`, `docs/` are present from the **same shared Git repository branch/commit**. Repo rules/skills follow Git; editor extensions are installed locally.
8. Optional ECC Minimal: install **ONCE INTO A BRANCH OF THE PROJECT**, review changes, merge; the resulting checked-in `.agents/` files appear for all on `git pull`. **Do not run the ECC installer independently on all four laptops against the same project**, causing conflicting files. Team lead approves installer package/version and diff first.
9. Optional OpenCode on each laptop: check `opencode --version` first; if missing, inspect official current installation and install only with user approval. In TUI, use `/connect` then `/models`, and verify genuinely free model endpoints per developer account. No central/shared API keys.
10. Test benign read-only AI task: ask for architecture summary (no edits), then a trivial isolated test task on a feature branch. Confirm Git branch, tests and merge process.

## Shared baseline extensions (all 4)
| Exact ID | Free editor utility | All four must check? |
|---|---|---|
| ms-python.python | Python support | YES |
| dbaeumer.vscode-eslint | Frontend lint | YES |
| esbenp.prettier-vscode | Consistent formatting | YES |
| bradlc.vscode-tailwindcss | Tailwind class support | YES |
| github.vscode-pull-request-github | Pull requests | YES |
| ms-playwright.playwright | Browser end-to-end tests | YES |

The editor's marketplace and compatibility determine install availability. If an extension is unavailable, mark **Not supported** and use an appropriate reviewed alternative; don't falsely check it as installed. VS Code extensions do not install Python packages, npm dependencies, Git, Node.js, or cloud account permissions.

## Optional, separately approved (not mandatory)
- **ECC Minimal:** project-level rules/skills. Only one reviewed install PR for team repo; do not stack with GSD/Ralph full setup.
- **OpenCode CLI:** each person can configure own model access; not a marketplace extension.
- **CodeRabbit:** a repository/GitHub app, not an editor requirement. Access reviewed by repo owner; free eligibility varies.
- **Supabase / telephony / gateways:** integrate only when relevant phase is approved, with sandbox credentials and restricted service roles.

## Evidence gate
Ask each developer to record six installed-extension statuses and five CLI version checks in `docs/setup/member-N.md` on their own branch (or report to chat). Do not commit API keys, access tokens, OS usernames, or personal paths. The team is "ready" only when **every person has independently verified the baseline**.

**Sources:** https://code.visualstudio.com/docs/configure/extensions/extension-marketplace ; https://antigravity.google/docs/skills/ ; https://opencode.ai/docs/providers ; https://github.com/affaan-m/ECC/blob/main/docs/ANTIGRAVITY-GUIDE.md
