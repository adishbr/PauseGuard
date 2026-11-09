# Curated GitHub reference repositories — **not** automatically trusted dependencies
These links are for reference and selective evaluation, not a request to clone and execute everything. The human approves each fetch when a task genuinely requires it. Verify the exact LICENSE, maintained release, known vulnerabilities, dependency scope and fetched commit SHA; record them in `docs/EXTERNAL_REFERENCE_LOCK.md`.

| Short name | GitHub URL | Purpose | Priority |
|---|---|---|---|
| `ecc` | https://github.com/affaan-m/ECC | Optional agent rules/skills reference for Antigravity | Optional install only after review |
| `fastapi` | https://github.com/fastapi/fastapi | Python API patterns and tests; install supported Python package rather than copying repo | Core documentation |
| `pydantic` | https://github.com/pydantic/pydantic | Validated request/response schemas | Core reference |
| `networkx` | https://github.com/networkx/networkx | Graph signal examples for Gowtham | Supporting feature |
| `scikit-learn` | https://github.com/scikit-learn/scikit-learn | Anomaly detection and evaluation examples | Supporting feature |
| `playwright` | https://github.com/microsoft/playwright | Browser E2E tests and scenarios | QA reference |
| `ui` | https://github.com/shadcn-ui/ui | Reusable React UI pattern ideas; adapt carefully | Optional Adish |
| `razorpay-python` | https://github.com/razorpay/razorpay-python | Official Python API SDK for *merchant test checkout*, never generic UPI P2P | Stretch only |
| `indic-asr` | https://github.com/AI4Bharat/IndicConformerASR | Speech recognition feasibility research; check model-weight/license terms | Research only |
| `gsd` | https://github.com/open-gsd/gsd-core | Alternative planning workflow, choose instead of stacking ECC | Optional, not installed |

## Action protocol an AI must follow
1. Read requested task; select only relevant reference.
2. Explain whether the official docs/package are sufficient. Many repositories are large; avoid cloning entire source without need.
3. Show URL and reason; get explicit owner approval for network action, package use and external source-license obligations.
4. If approved, fetch *read-only* into `.references/<shortname>` with `scripts/fetch_reference.ps1 -Name <shortname>` or browse official docs. Never replace the project's app with a fetched example.
5. Inspect `LICENSE`, last commits, dependency scripts and exact SHA; log in `EXTERNAL_REFERENCE_LOCK.md`.
6. Propose a bounded implementation using the canonical V2 API, run tests, present diff and source attribution. Do **not** run `npm install`, `pip install`, remote shell scripts or setup hooks from cloned projects without a separate review/approval.
7. Keep `.references/` out of the main repository; copy only specific, legally permitted patterns or snippets.

## Important distinctions
- ECC is a dev-agent framework, not a fraud-detection algorithm.
- NetworkX / Scikit-learn are libraries, not ready-made validated fraud datasets/models.
- Razorpay SDK supports payment gateway integration under provider conditions, not interception or recovery of arbitrary UPI P2P payments.
- Solana or Phantom cannot speed up or reverse normal UPI settlement; omit from the core.
- If a repo or license cannot be verified, treat it as research-only and do not copy code.
