# Member 3 — Gowtham (Gautam) | Fraud intelligence and Policy Lab
You own advisory intelligence services, synthetic datasets and simulation analytics, separate from payment authorization.

**Scope:** behavioral baselines for personal/business, anomaly scores with calibration caveats, graph proximity on synthetic nodes, coercion-text signals from explicitly available transcripts (never spy on phone calls), structured advisory service, failure/timeout handling, policy scenario evaluation and honest false-positive/negative tables.

**Do not:** modify ledger or states, claim real-world accuracy from synthetic cases, treat vocal pitch/anger as reliable proof of fraud, retrieve live phone GPS or record user calls without consent, auto-deploy large models or assume free inference is unlimited.

**First task to propose:** inspect V2 docs and create typed `RiskSignals` contract proposal compatible with Komal; generate held-out synthetic personal and business cases and tests. Return advisory only.

**Required tests:** schema validation; reproducible synthetic data; business vs personal false positives; model unavailable/slow; prompt-injected transcript; strong registry hit not overridden; provenance and model version fields present.

**Handoff:** `RiskSignals` JSON shape, feature definitions, model provenance, metrics, dependencies, reproducible test commands and safety limitations.
