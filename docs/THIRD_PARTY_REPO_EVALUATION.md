# Third-party GitHub repository audit before use

The previous kit has `docs/APPROVED_GITHUB_REFERENCES.md` and `scripts/fetch_reference.ps1`. Those sources are **candidates**, not fully security-approved dependencies.

## Required evaluation per repository
1. Exact URL and why its code is needed; prefer official libraries/docs, not social-media forks.
2. Project owner approves a read-only clone into `.references/` **after** inspecting the URL.
3. Record latest reviewed commit SHA (`git -C .references/<name> rev-parse HEAD`), license file, release date, open issues, maintainers and dependency install scripts.
4. Verify license permits copying/adapting intended code; some weights and sample data have separate licenses.
5. Review import-time actions, network calls, telemetry, authentication, file writes and scripts, especially package install hooks.
6. Prefer using published official package/API over copy-pasting thousands of lines from clone.
7. Select minimal code; test in isolated development environment and check contract compatibility.
8. Record source and attribution in `docs/EXTERNAL_REFERENCE_LOCK.md`.
9. A PR must show exactly what changed and how it was tested; never auto-merge.

## Usage guidance
- FastAPI, Pydantic, NetworkX, Scikit-learn, Playwright: use official packages and docs rather than cloning source into product.
- ECC Minimal: project customizations; use reviewed installer, inspect `.agents/` diff.
- Scam voice GitHub repos: evaluate proof, licensing, privacy, accuracy and how they handle false reassurance. Do not import third-party recorded calls or claim verified accuracy.
- `git clone` is code retrieval, **not** endorsement of the fetched code; do not execute it automatically.

## Sample intake record
```
Reference name: __________
Source URL: __________
Reviewed SHA: __________
License: __________
Files proposed to use: __________
Risk findings: __________
Approval by: __________
Tests executed: __________
```
