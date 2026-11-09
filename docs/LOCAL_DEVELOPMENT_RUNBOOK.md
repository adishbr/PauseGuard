# Local development and troubleshooting runbook

**The documentation pack does not itself include a finished frontend/backend application.** Commands below are guidance for after the real project has been created and dependencies documented/locked. Never claim success before executing them.

## Verify environment (one at a time)
`git --version` → `node --version` → `npm --version` → `python --version` → `opencode --version`.
Windows: `py -V` can help when `python` path is missing.

## Backend (after Komal's backend skeleton exists)
1. Open PowerShell in `backend/`.
2. Create venv with `py -m venv .venv` if necessary and approved.
3. Activate `./.venv/Scripts/Activate.ps1` only if allowed by local policy; otherwise run `.venv/Scripts/python.exe` explicitly (no unrestricted execution policy change).
4. Install only dependencies pinned in repo's requirements/lock file. Do not invent requirements here.
5. Test using repo's documented command, typically `python -m pytest`; record results.
6. Run FastAPI with documented app import path, e.g. `uvicorn app.main:app --reload` only when that file exists.

## Frontend (after Adish's frontend exists)
1. Open PowerShell in `frontend/`.
2. Run `npm ci` if lockfile exists; `npm install` only if no lockfile and project lead approves.
3. Run `npm run dev` if package scripts define it; inspect `package.json` first.
4. Run `npm run build` and lint/test scripts if defined.

## Integration
- Confirm backend and frontend origin/cors configuration, API base `/api/v2`, and JSON schema.
- Use two incognito/authenticated browser sessions for payer and guardian. Check 30-second review, late rejection, refresh, network disconnect, Safe-Lock.
- Do not expose demo server publicly until network permissions and auth are reviewed.

## Common Windows issues
- **WSL popup:** PowerShell default terminal via Terminal dropdown, not forced WSL update.
- **Port in use:** identify owner with `Get-NetTCPConnection` (where available), don't kill random processes.
- **Python path spaces:** quote paths like `C:\Users\...`.
- **Failed extension:** check exact publisher and required IDE version.
- **Claude proxy ECONNREFUSED:** check gateway running + configured local port, don't disable firewall or print secrets.
