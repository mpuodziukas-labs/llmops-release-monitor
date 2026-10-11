# Verifying this repository

Purpose: demonstrates release safety for LLM changes: eval-gated promotion, canary rollback, drift and cost monitoring, and a tamper-evident audit log for teams subject to model-risk, audit or change-control review.

Verify: `python3 evaluate.py`

Pass condition: exit code 0 and this exact output line (leading spaces ignored): `6/6 planted failures caught, 4/4 controls passed`

Scope: synthetic data, fixed seed, offline, under 60 seconds.

Limitations: Thresholds are illustrative and need your own baselines. The hash chain cannot show that the newest log entries were cut off. Canary runs once on a fixed sample with no staged ramp. Drift covers one score distribution and one binary judge. Cost uses a flat synthetic price.

Anything else = not verified.
