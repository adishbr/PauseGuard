# PauseGuard Policy Lab — Fraud Policy Comparison & Benchmarking

**Author:** Gowtham KS (Member 3 — Fraud Intelligence & Policy Lab)<br/>
**Team:** VantaWard<br/>
**Project:** PauseGuard<br/>
**Status:** Implemented & Verified (Synthetic Evaluation Engine — V2 Canonical Benchmark)

---

## 1. Executive Summary & Objective

The **Policy Lab** is Member 3's dedicated simulation and comparative evaluation framework for PauseGuard. Its primary objective is to evaluate and compare fraud-prevention policy strategies against reproducible, multi-profile synthetic payment scenarios without modifying payment ledgers, overriding backend state machines, or exposing live user data.

Per [`docs/EXPERIMENT_PLAN_AND_METRICS.md`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/docs/EXPERIMENT_PLAN_AND_METRICS.md) and [`docs/POLICY_MATRIX_V2.md`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/docs/POLICY_MATRIX_V2.md), the Policy Lab benchmarks three distinct policy strategies:
1. **Baseline A:** Amount-only hard threshold.
2. **Baseline B:** Always warn on new beneficiary (familiarity heuristic).
3. **Policy C:** Profile-aware PauseGuard policy (behavioral deviation, customer profile context, velocity structuring, and transcript coercion indicators).

---

## 2. Strict Dataset Integrity & Anti-Leakage Architecture

All benchmark metrics are computed under strict anti-leakage invariants:

```
Full Synthetic Scenario Dataset (6 Categories, 4 Profiles, seed=42, count_per_category=20 -> 120 total)
                 │
                 ▼
      [split_dataset (seed=42)]
       ├── 70% Train (~84 scenarios, grouped by payer_id)
       ├── 15% Validation (~18 scenarios, grouped by payer_id)
       └── 15% Held-Out Test Split (FINAL EVALUATION ONLY: exactly 18 scenarios)
                           │
                           ├─► ScenarioFeatures (Anti-Leakage Extraction)
                           │    (amount, profile, baseline, new_payee,
                           │     velocity counts, transcript text)
                           │     *Excludes ground-truth, tiers, IDs*
                           │
                           └─► Evaluated by Policies
                                (Baseline A, Baseline B, Policy C)
```

### Guarantees
1. **Held-Out Test Split Enforcement:** Policy Lab strictly evaluates on `split="test"`. Running evaluations on `train` or `val` raises an explicit `ValueError`.
2. **Zero Payer Leakage:** Scenario partitioning groups records strictly by `payer_id`. Discrete payer-grouped allocation ensures zero payer overlap between partitions:
   $$\text{Train Payers} \cap \text{Test Payers} = \emptyset$$
   $$\text{Val Payers} \cap \text{Test Payers} = \emptyset$$
   With `count_per_category=20` (120 total scenarios across 6 categories), the held-out test split contains exactly **18 scenarios** (3 per category). (Note: with `count_per_category=30` / 180 total scenarios, payer-grouped partitioning produces exactly 24 test scenarios. Naive row-based splitting claiming 27 test scenarios is rejected because it causes payer leakage across splits).
3. **Feature/Target Disaggregation:** Policies receive strictly inference-time [`ScenarioFeatures`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/synthetic_data/generator.py#L46-L65). Ground-truth labels, expected policy tiers, scenario IDs, and direct registry labels are inaccessible to policies.
4. **All 6 Scenario Categories Preserved:** Test splits contain representative cohorts of `legitimate_personal`, `legitimate_business`, `app_coercion_fraud`, `benign_anomalous`, `mule_proximity`, and `velocity_structuring`.
5. **Full 4-Profile Coverage:** Covers `personal`, `professional`, `small_business`, and `enterprise` customer profiles.

---

## 3. Evaluated Policy Strategies

### Baseline A — Amount-Only Hard Threshold
* **Philosophy:** Intercepts any transaction whose `amount_paise` meets or exceeds an explicitly supplied threshold (e.g. ₹10,000 / 1,000,000 paise).
* **Configuration:** Requires an explicit `threshold_paise` parameter. **Does not invent a production threshold.** If unconfigured, reports as unavailable.
* **Trade-off:** High personal false negatives on low-value coercion scams, and massive business false positives on ordinary commercial payments.

### Baseline B — Always Warn on New Beneficiary
* **Philosophy:** Intercepts or warns whenever `is_new_beneficiary` is `True`.
* **Configuration:** Relies solely on payee history familiarity.
* **Trade-off:** Captures first-time mule transfers, but causes catastrophic **business disruption**, because legitimate businesses routinely add and pay new suppliers (40% of normal business payments). Per the experiment plan: *A new beneficiary alone must never be treated as proof of fraud.*

### Policy C — Profile-Aware PauseGuard Policy
* **Philosophy:** Evaluates contextual risk relative to customer profile and verified baseline median, corroborating risk across independent dimensions:
  1. **Behavioral Deviation:**
     * **Personal Profile:** Low baseline (median ₹400 - ₹1,500). High deviation (>5x) to a new payee triggers Tier 2 step-up; extreme deviation (>10x) triggers intervention.
     * **Business Profiles (Professional, Small Business, Enterprise):** High baseline (median ₹15,000 - ₹1Cr). Routine new vendor payments (1x - 3x deviation) are allowed without friction. Only extreme anomalous outflows (≥10x baseline) trigger intervention.
  2. **Coercion Transcript Analysis:** Evaluates consented audio transcripts for urgent threats, authority impersonation, and secrecy demands (Tier 3 restriction).
  3. **Configurable Velocity Structuring:** Evaluates payment frequency and smurfing indicators using an explicit, typed [`SyntheticVelocityThresholds`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/intelligence/policy_lab/policy_evaluator.py) configuration:
     * `structuring_threshold_attempts`: 4 (synthetic smurfing pattern: $\ge 4$ rapid transfers)
     * `structuring_threshold_amount_paise`: 3,000,000 paise (₹30,000 aggregate structuring limit)
     * `rolling_window_minutes`: 60 (1-hour observation window)
     * *Provenance:* Explicit synthetic experiment configuration. Not an approved production threshold or regulatory mandate.
     * *Integrity Invariant:* Without explicitly supplied velocity thresholds, structuring classification remains unknown (`structuring_suspected = None`). The system never fabricates `False` when thresholds or measurements are unconfigured.

---

## 4. Evaluation Metrics & Zero-Division Safety

Every calculated rate in Policy Lab exposes its exact **numerator and denominator** via [`MetricRate`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/intelligence/policy_lab/metrics.py#L22-L65).

### Mathematical Definitions
* **True Positive (TP):** Ground-truth fraud scenario correctly intercepted (`flagged=True`).
* **False Positive (FP):** Legitimate transaction receives harmful friction/restriction (`flagged=True`).
* **True Negative (TN):** Legitimate transaction allowed without friction (`flagged=False`).
* **False Negative (FN):** Fraud scenario proceeds unprotected (`flagged=False`).
* **Precision:** `TP / (TP + FP)`. Returns `rate=None` with `is_undefined=True` if `TP + FP == 0`.
* **Recall (Sensitivity):** `TP / (TP + FN)`. Returns `rate=None` with `is_undefined=True` if `TP + FN == 0`.
* **Specificity:** `TN / (TN + FP)`. Returns `rate=None` with `is_undefined=True` if `TN + FP == 0`.
* **False-Positive Rate (FPR):** `FP / (FP + TN)`. Returns `rate=None` with `is_undefined=True` if `FP + TN == 0`.
* **False-Negative Rate (FNR):** `FN / (FN + TP)`. Returns `rate=None` with `is_undefined=True` if `FN + TP == 0`.
* **Personal False-Positive Rate:** `FP_personal / Total_legitimate_personal`.
* **Business False-Positive Rate:** `FP_business / Total_legitimate_business`.
* **Business Disruption Rate:** Legitimate business payments requiring review / total legitimate business payments:
  $$\text{Business Disruption} = \frac{\text{FP}_{\text{business}}}{\text{Legitimate Business Total}}$$

### Zero-Denominator Handling Invariant
When a denominator is zero (e.g. no positive predictions in cohort for Precision, no fraud in cohort for Recall/FNR, no legitimate in cohort for Specificity/FPR, or no legitimate business payments for Business Disruption):
- Returns `rate=None` in Python.
- Serializes as JSON `null` (`"rate": null`).
- Sets `is_undefined=True` to explicitly indicate that the mathematical ratio is undefined.
- Preserves the exact `numerator` and `denominator=0` counts.
- **Never** raises `ZeroDivisionError` and **never** substitutes a fabricated `0.0` for an undefined rate.

---

## 5. Transparent Handling of Unavailable Metrics

Per [`docs/EXPERIMENT_PLAN_AND_METRICS.md`](file:///c:/Users/KSEAB/OneDrive/Desktop/PauseGuard-team/docs/EXPERIMENT_PLAN_AND_METRICS.md), three optional operational metrics are recognized. Policy Lab inspects available dataset fields and reports them as explicitly **unavailable** rather than fabricating ungrounded figures:

| Metric | Status | Reason / Explanation |
| :--- | :--- | :--- |
| **Payer Friction** | `unavailable` | Synthetic scenario fixtures model transaction risk attributes but do not simulate interactive user click duration, step timings, or call center logs. |
| **Guardian Workload** | `unavailable` | Synthetic dataset does not model time-series guardian alert queues, response latencies, or caregiver unanswered rates. |
| **Recovery Lag** | `unavailable` | Synthetic dataset models pre-execution intervention and does not simulate post-transaction fraud reporting or law enforcement fund recovery times. |

---

## 6. Canonical Comparative Benchmark Results

*Run on held-out test split (Canonical Benchmark: Seed=42, count_per_category=20, 120 total scenarios generated, 18 held-out test scenarios evaluated across 6 categories):*

| Metric | Baseline A (₹10,000 Hard Limit) | Baseline B (Always Warn New Payee) | Policy C (Profile-Aware PauseGuard) |
| :--- | :--- | :--- | :--- |
| **Test Scenarios Evaluated** | 18 | 18 | 18 |
| **True Positives (TP)** | 6 | 9 | **9** |
| **False Positives (FP)** | 6 | 5 | **1** |
| **True Negatives (TN)** | 3 | 4 | **8** |
| **False Negatives (FN)** | 3 | 0 | **0** |
| **Precision** | 50.00% (6/12) | 64.29% (9/14) | **90.00% (9/10)** |
| **Recall** | 66.67% (6/9) | 100.00% (9/9) | **100.00% (9/9)** |
| **Specificity** | 33.33% (3/9) | 44.44% (4/9) | **88.89% (8/9)** |
| **Overall FPR** | 66.67% (6/9) | 55.56% (5/9) | **11.11% (1/9)** |
| **Overall FNR** | 33.33% (3/9) | 0.00% (0/9) | **0.00% (0/9)** |
| **Personal FPR** | 25.00% (1/4) | 50.00% (2/4) | **25.00% (1/4)** |
| **Business FPR** | 100.00% (5/5) | 60.00% (3/5) | **0.00% (0/5)** |
| **Business Disruption Rate** | **100.00% (5/5)** | **60.00% (3/5)** | **0.00% (0/5)** |

### Held-Out Test Cohort Breakdown
* **Total Evaluated:** 18 scenarios ($TP + FP + TN + FN = 18$ across all policies).
* **Ground-Truth Fraud (9 scenarios):**
  * `velocity_structuring`: 3 scenarios
  * `app_coercion_fraud`: 3 scenarios
  * `mule_proximity`: 3 scenarios
* **Ground-Truth Legitimate (9 scenarios):**
  * `legitimate_personal`: 3 scenarios (personal cohort)
  * `legitimate_business`: 3 scenarios (business cohort)
  * `benign_anomalous`: 3 scenarios (1 personal, 2 business)
* **Cohort Denominators:**
  * Legitimate Personal Total: 4 scenarios
  * Legitimate Business Total: 5 scenarios

### Key Analytical Takeaways
1. **Business Disruption Elimination:**
   * Baseline A causes a **100.00% disruption rate (5/5)** because commercial payments routinely exceed ₹10,000.
   * Baseline B imposes a **60.00% disruption rate (3/5)** because businesses routinely onboard and pay new suppliers.
   * Policy C reduces commercial disruption to **0.00% (0/5)** by evaluating payments against business baseline medians rather than crude amount caps or beneficiary novelty.
2. **Coercion Sensitivity:**
   * Baseline A fails to detect low-value coercion scams under ₹10,000 (FN=3).
   * Policy C captures 100% of APP coercion fraud cases through consented transcript indicators without imposing blanket friction on ordinary transactions.
3. **Precision Superiority:**
   * Policy C achieves **90.00% precision (9/10)**, vastly outperforming Baseline A (50.00%, 6/12) and Baseline B (64.29%, 9/14).

---

## 7. Python API & Reproducibility Guide

### Running Canonical Benchmark via Code
```python
from synthetic_data.generator import generate_scenario_dataset
from intelligence.policy_lab import (
    PolicyLab,
    BaselineAPolicy,
    BaselineBPolicy,
    PolicyCPauseGuard,
)
from intelligence.policy_lab.policy_evaluator import (
    SyntheticVelocityThresholds,
    get_default_synthetic_velocity_thresholds,
)
from intelligence.advisory.types import get_default_scoring_config

# 1. Generate canonical deterministic synthetic scenario pool (120 scenarios across 6 categories)
dataset = generate_scenario_dataset(seed=42, count_per_category=20)

# 2. Run Policy Lab comparison on held-out test split (exactly 18 scenarios)
report = PolicyLab.run_comparison(
    scenarios=dataset,
    policies=[
        BaselineAPolicy(threshold_paise=1000000),  # ₹10,000 explicit synthetic threshold
        BaselineBPolicy(),
        PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            synthetic_velocity_thresholds=get_default_synthetic_velocity_thresholds(),
        ),
    ],
    seed=42,
    split="test",
)

# 3. Export structured report
print(report.to_json(indent=2))
```

### Reproducible Test Commands
```powershell
# Run Policy Lab unit tests (29 tests)
python -m unittest discover -s tests/intelligence -p "test_policy_lab.py" -v

# Run full intelligence regression suite (176 tests)
python -m unittest discover -s tests/intelligence -v
```

---

## 8. Safety Boundaries & Governance

* **Synthetic Data Caveat:** All benchmarks, confusion matrices, and metrics are derived strictly from synthetic laboratory scenarios. They **must not** be cited as real-world fraud accuracy, RBI compliance, or production efficacy.
* **Transcript Coercion Artifact Limitation:** The 100% recall observed on `app_coercion_fraud` scenarios is a known artifact of the 5 fixed synthetic template transcripts in `synthetic_data/generator.py` (`COERCION_TRANSCRIPTS`). Real-world coercion calls involve acoustic noise, dialectal variations, code-mixing (e.g. Hinglish), and subtle psychological pressure that static substring matchers will not detect with equal fidelity.
* **Advisory Invariant:** Policy Lab evaluations simulate decision logic. They provide advisory friction recommendations only and cannot authorize, block, or execute actual UPI transactions.
* **Separation of Roles:** Policy ownership and final payment execution gates remain under backend policy (Komal). Member 3 provides intelligence benchmarks, risk signals, and advisory simulations only.
