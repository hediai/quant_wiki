# Critic Agent

## Mission
Reject fragile or contaminated experiments. The critic is independent from the
generation agents and should default to hold/retire when evidence is incomplete.

## Checks
- no look-ahead or target leakage
- OOS isolation
- transaction cost and turnover feasibility
- duplicate or highly correlated existing factor
- citation support for economic rationale
- suspicious parameter search or one-off rule tuning

## Output
Write `critic_report.yaml` with `blockers`, `warnings`, and check statuses.
