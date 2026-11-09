# One shared GitHub repository — zero-to-first-PR

## Repository owner checklist
1. Decide an actual repo name. **Example only:** `VantaWard/PauseGuard`; don't assume it exists.
2. Create private GitHub repo through GitHub UI; avoid inserting secrets or real customer data. Confirm pre-build hackathon rules before coding.
3. Extract V3 documentation pack to the root (compare with existing docs first); never replace a working repo blindly.
4. Add Komal, Adish, Gowtham and Jeevan as collaborators with minimum permissions. Each person accepts invite through their own account.
5. Require PR review and passing tests for `main`; record branch protections in `docs/GIT_WORKFLOW.md`.
6. Do not paste personal access tokens into ChatGPT or commit them.

## Teammate safe local workflow
```powershell
git --version
# After owner shares ACTUAL repo URL:
git clone <actual-approved-repo-url>
cd <cloned-folder>
git status
```
Replace `<...>` with real values; do not literally run placeholders. A coach should give one command per turn and verify it.

## Development workflow
- Start from `main`; `git pull --ff-only` on clean working tree; branch for bounded feature.
- Avoid editing another member's owned module; shared contract changes require Komal + Adish review.
- Write tests, run relevant checks, document what passed or failed, then PR.
- CodeRabbit is optional and does not replace human review.
- Never force push or rewrite other's commits without explicit review.

## Sharing ChatGPT
Shared chat ≠ synced Git workspace. Each teammate supplies latest docs and declares member number in their own session. Record progress and decisions in Git for others to see.
