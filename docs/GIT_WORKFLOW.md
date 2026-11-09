# One repository, four feature branches
1. Repository admin creates a **private** team repo (example placeholder `ORG_OR_USER/PauseGuard`). Add the four GitHub collaborators through Settings > Collaborators and teams. Choose appropriate access; do not share personal account passwords or tokens.
2. Each teammate authenticates Git credential manager/GitHub PR extension in their own editor, clones the same repository and checks the current `main`.
3. For each bounded task create a descriptive branch e.g. `feature/komal-payment-core`, `feature/adish-guardian-ui`, `feature/gowtham-risk-advice`, `feature/jeevan-velocity-tests`. Avoid permanent long-lived branches when possible.
4. Changes -> unit tests -> integration tests -> `git status` -> commit -> push **own branch** -> pull request. No `git push --force` and no direct changes to `main`.
5. Require review of API/state/privacy changes by both core leads and a safety reviewer when feasible. Set branch protection as available on your GitHub plan. Never assume private repo access automatically confers merging authority.
6. Merge small PRs continuously. To update your work: `git fetch origin`, review `main`, then rebase/merge carefully with human conflict resolution.
7. Update `docs/PROGRESS.md`, `docs/DECISIONS.md`, and `docs/EXTERNAL_REFERENCE_LOCK.md` in relevant PRs.

## Shell basics (run only inside correct repo)
```powershell
git status
git switch main
git pull origin main
git switch -c feature/komal-payment-core
# implement and test in branch
git status
git add <specific-files>
git commit -m "Add bounded mock payment transition tests"
git push -u origin feature/komal-payment-core
```

## PR handoff template
- Owner and approved ticket:
- Inputs/outputs and contract compliance:
- Files changed (including generated):
- Tests *actually executed* with results:
- Security/privacy checks:
- New package/repo reference with license + SHA:
- Blockers and known limitations:
- Reviewer and merge decision:

## Chat/AI sharing is not repo syncing
Sharing a ChatGPT conversation shows background context only; it doesn't share local IDE files or other teammates' future agent actions. The latest reviewed GitHub commit is the authoritative implementation state.
