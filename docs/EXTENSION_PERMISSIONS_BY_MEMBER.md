# Access Matrix — All Four, Least Privilege

| Capability | All Four | Additional rules |
|---|---|---|
| Read project source/docs | Allowed in scoped PauseGuard folder | All four need same repository contract |
|---|---|---|
| Edit own branch/module | With reviewed diffs | Never directly to main |
| GitHub PR actions | Own identity | Review before merge; protect main |
| Network fetch GitHub references | Ask per repository | Clone read-only into `.references/`, check licenses, commit SHA |
| Run `npm install` or `pip install` | Ask before execution | Inspect package lists/lockfiles |
| AI shell commands | Review required | Deny unrelated filesystem and credential access |
| Read `.env`, credentials, browser profiles | Denied by default | No access to production secrets |
| Deployment and payment provider access | Denied by default | App owner may authorize sandbox scoped by role later |
| ECC installation | One approved team PR | No independent repeated installers overwriting shared `.agents/` |
| Model provider API key | Individual only | Check free quota and costs; never share keys |

No claim of 'unhackable' or fully automatic zero-risk agent; treat third-party code as untrusted until reviewed and tested.
