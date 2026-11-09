# OpenCode on Windows PowerShell — verify before install

**Do not repeat installation if OpenCode already works.** The official OpenCode documentation is the sole authority for the current installation package. On 9 November 2026 its main installation guide lists `npm install -g @opencode/cli` for the latest CLI; some older pages list `opencode-ai`. **Check https://opencode.ai/docs/ immediately before installing.** Never run both installers blindly. See `docs/INSTALLATION_VERIFICATION_AND_PERMISSIONS.md`.

## Single-step coached setup
1. In Antigravity, **File > Open Folder**: choose the authorized PauseGuard folder.
2. **Terminal > New Terminal**; if WSL opens, select Terminal > Select Default Profile > PowerShell; create a new terminal.
3. Run `node --version` and `npm --version`; record results. Ask for help before installing Node if either missing.
4. Run `opencode --version`. If it succeeds, **skip installation**.
5. If missing, read the official docs and verify the package (`npm view @opencode/cli version`). Only after reviewing source/provider and permission, run `npm install -g @opencode/cli`. Don't use `--force` or run random shell scripts copied from videos.
6. Run `opencode --version`; then `opencode` inside the project folder. Check that the project path is correct.
7. In OpenCode, `/connect` selects an external provider; `/models` selects a model; `Tab` may switch agent mode depending on installed version. Use Plan/read-only when analyzing specs, Build only for approved bounded task.

## Safety
- On Windows, OpenCode documentation recommends WSL for optimal compatibility but also lists native Windows installation choices. WSL is not mandatory if native CLI works.
- Never commit API keys or paste them into a chat. Provider keys stay in OS/user secure storage via supported login procedure.
- OpenCode is a CLI agent, **not** the Antigravity built-in model provider; selecting Gemini in Antigravity does not automatically make it available inside OpenCode.
- Starting a second terminal does not stop a first session; closing an active terminal may interrupt a running answer, though saved sessions normally remain.
- To continue an OpenCode session: `opencode --continue` or session picker as shown in your installed version; verify saved history first.

## Troubleshooting
`opencode: command not found` → inspect `npm` installation, PATH and terminal restart; do not reinstall blindly. `401` → provider credential issue; `429` → account rate limit; `model not found` → check provider picker and exact model; `ECONNREFUSED` → local gateway/port process may be stopped. Do not disable firewall globally.
