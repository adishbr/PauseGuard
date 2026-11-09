# Evaluation plan — prevent inflated claims

## Synthetic study design
Create labeled scenarios for (a) legitimate personal, (b) legitimate business, (c) APP/coercion fraud, (d) benign anomalous, (e) compromised device, (f) attempted threshold bypass. Split sources before training or threshold tuning to reduce leakage. Never train/test on identical duplicate cases.

## Metrics and definitions
- True positive = fraud scenario correctly receives an intercepting intervention before execution.
- False positive = legitimate transaction receives harmful friction or restriction; distinguish **warn** from **blocked**.
- False negative = fraudulent scenario proceeds unprotected.
- Payer friction = count and duration of warnings, steps, review calls per 1000 payments.
- Guardian workload = alerts/day and unanswered rate for enrolled accounts.
- Business disruption = legitimate business payments requiring manual review divided by legitimate business payments.
- Recovery lag = simulated time from report to evidence generation; never equate with actual fund recovery.

## Required comparisons
Baseline A: amount-only hard threshold. Baseline B: always warn on new beneficiary. Policy C: profile-aware PauseGuard policy. Report trade-offs and confidence, not a single impressive number. Note that synthetic datasets don't establish real-world effectiveness.

## Model acceptance
Models may add signals, but cannot modify the payment DB or permissions. Compare rule-only versus rule + advisory model, including failures, prompt injection and unavailability. Every chart labels dataset synthetic, assumptions and thresholds.
