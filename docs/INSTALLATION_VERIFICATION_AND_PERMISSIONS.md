# Installation verification and permissions — current-source correction

**Important correction to earlier V4:** npm package names for OpenCode have changed between published documentation versions. Main official page https://opencode.ai/docs/ (checked 9 Nov 2026) lists **`npm install -g @opencode/cli`** for its current release, whereas older versions mention `opencode-ai`. Do not uninstall a working OpenCode installation or blindly run both commands. Check the official page on each teammate's install date; verify `opencode --version` before taking action. The provider workflow `/connect` → `/models` is documented at https://opencode.ai/docs/providers/.

Antigravity's official rules guide confirms the workspace `AGENTS.md`, `.agents/rules/*.md` discovery, and separate `.agents/skills/` skill directory: https://antigravity.google/docs/rules/ and https://antigravity.google/docs/skills/ . The project files follow Git; local editor extensions and API keys do **not**.

Official VS Code documentation confirms that `.vscode/extensions.json` contains **recommendations**, not installed extensions: https://code.visualstudio.com/docs/configure/extensions/extension-marketplace . Every person installs/checks the same six extensions locally in Antigravity with publisher and compatibility checks.

ECC official project: https://github.com/affaan-m/ECC . The universal package installs a capability-limited Antigravity adapter. The official pinned 2.2.3 example is `npx ecc-universal@2.2.3 install --profile minimal --target antigravity`, only after reviewing the version and applying it in **one branch**, then diff/review/merge. This is NOT a mandatory install; no blind agent execution.

**Safe permissions:** ask/review for edits and terminals; permit project-doc reads; external network, GitHub fetching, key access, dependency installs, global changes and pushes require review or specific approvals. Keep credentials private. Each team member chooses and validates their own free API endpoints; free does not mean unlimited.
