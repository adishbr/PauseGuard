# Recover sessions, prevent data loss, diagnose common failures

## Before closing a working AI terminal
Stop new tasks; wait for currently running output where practical. Save changes, inspect `git status`, and note the current branch. A saved chat session is not a running background job.

## Resume Claude Code
From its original working directory with correct gateway config, use the product's `/resume` session picker or `claude --resume`; gateway may need its local proxy process restarted. The apparent Opus slot may be routed to a third-party free model; verify actual backend.

## Resume OpenCode
Use `opencode --continue` for latest or OpenCode's session list; ensure same project directory and provider credentials. No new chat should silently assume earlier work was merged.

## WSL window when opening Antigravity terminal
Check terminal profile and select PowerShell. Updating WSL is optional when native Windows tools work. Avoid changing Windows features merely to remove a popup.

## Typical errors
| Error | Meaning | Next safe check |
|---|---|---|
| `ECONNREFUSED` | no process listening at target socket | local gateway/server status, URL/port |
| 401/403 | invalid key or access | provider login/scope, never print token |
| 429 | rate limit | account quota, wait/switch verified free provider |
| 404 model | wrong model ID or route | official model catalog and `/models` |
| CLI command not found | PATH/install | `Get-Command`, version check, restart terminal |
| failing tests | implementation incorrect/missing deps | inspect logs/changed files; no fabricated pass |
| Git conflict | concurrent edit | preserve both changes and get owner review |

## Agent coach rule
For troubleshooting, present **one diagnostic at a time**, ask for redacted output, then provide the next command only after evidence. Never recommend bypassing security or using `--force` without justification.
