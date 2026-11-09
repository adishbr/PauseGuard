# Extensions vs agents vs services — what to install, what to skip

**Key vocabulary:** IDE *extension* adds editor features; *agent skills* customize model behavior; *API provider* supplies remote inference; *Git repository* contains source code (not automatically a plugin); *cloud service* hosts app/data. No need to install all of them.

## Install now (verify publisher in Extensions UI)
| Item | Type | Why | Permission |
|---|---|---|---|
| Python `ms-python.python` | editor extension | Python language services, debugging | workspace-only |
| ESLint `dbaeumer.vscode-eslint` | editor extension | TS/JS diagnostics | workspace-only |
| Prettier `esbenp.prettier-vscode` | editor extension | formatting | workspace-only |
| Tailwind CSS IntelliSense `bradlc.vscode-tailwindcss` | editor extension | frontend class support | workspace-only |
| GitHub Pull Requests `github.vscode-pull-request-github` | extension | PR review | intended GitHub account/repo scope |
| Playwright `ms-playwright.playwright` | extension | UI test runner | controlled repo only |
| OpenCode CLI | terminal app, **not extension prerequisite** | alternative multi-model agent | explicitly authorized file/terminal access |

## Optional after a clean Git commit
- **Everything Claude Code (ECC) Minimal**, official https://github.com/affaan-m/ECC. Antigravity 2.0 supports `.agents/` setup, but review generated files to avoid overwriting our rules. Use only one primary agent framework.
- **CodeRabbit** GitHub review service for eligible public OSS or approved trial; not automatic/unlimited private-repo free access.
- **21st.dev** for UI components/inspiration, not unrestricted installation of unknown package trees.

## Do not install by default
- **GSD** and **Ralph Loop** on top of ECC; may conflict or cause uncontrolled changes. Choose one workflow manager only if needed.
- **Solana/Phantom** for UPI core: separate crypto ecosystem, no speed boost to INR UPI bank rails.
- **Gamma/Slidefy/Same.new/NotebookLM** as IDE extensions; these are separate web services.
- Random Instagram 'free unlimited API' gateways; verify ownership, terms, privacy and actual model routing.

## Permission matrix
| Action | Initial status | Why |
|---|---|---|
| Read code in PauseGuard folder | Allow after workspace selection | needed for work |
| Run tests/lint in workspace | Ask once per approved task | safe-ish but scripts execute code |
| Clone official reference repo into `.references/` | Ask per repo/URL | license/supply-chain risk |
| Install dependency / npm global | Ask each time | scripts and environment mutations |
| Modify contracts, payment logic, security rules | Human approval + PR | safety-critical |
| Network request to unknown endpoint | Deny until reviewed | data exfiltration |
| Git push/merge/deploy | Human approval | external effects |
| Read secrets, copy credentials, enable paid billing | Deny | privacy/cost risk |

A GitHub URL in docs is a curated **candidate**, not a standing grant to fetch/run its contents. Read `docs/THIRD_PARTY_REPO_EVALUATION.md`.
