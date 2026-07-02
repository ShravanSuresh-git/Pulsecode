# PulseCode Counterfactual Validation Results

This is a small-corpus sanity check for counterfactual replay. It compares the replay-predicted direction of coupling pressure with a nearby real-history interval of similar churn. It is useful engineering evidence, not proof of causality.

## Before/After Summary

- Exact replay rate before: 3/30 (10%), after: 10/31 (32%)
- Sign agreement before: 17/30 (57%), after: 16/31 (52%)
- What changed: merge commits are now attempted with `git cherry-pick -m 1`, which increased exact replay coverage.
- Outcome: sign agreement did not improve meaningfully and remains below 65%, so the corpus-stats endpoint is intentionally skipped for this milestone.

## Current Results

- Repositories/events evaluated: 36
- Comparable events: 31
- Sign agreement: 16/31 (52%)

| repo | event | predicted_direction | nearby_real_history_direction | match | replay_status | causal_confidence |
| --- | --- | --- | --- | --- | --- | --- |
| itsdangerous | Dev architectural shift | coupling_down | coupling_down | True | approximate | 0.75 |
| itsdangerous | Dev becomes dependency hub | coupling_up | coupling_down | False | approximate | 0.75 |
| itsdangerous | Dev dependency expansion | coupling_up | coupling_up | True | approximate | 0.75 |
| markupsafe | Dependabot becomes dependency hub | coupling_up | coupling_down | False | approximate | 0.90 |
| markupsafe | Architecture modularization | coupling_up | coupling_down | False | approximate | 0.57 |
| markupsafe | Architecture modularization | coupling_down | coupling_up | False | approximate | 0.90 |
| markupsafe | Tests dependency expansion | coupling_up | coupling_up | True | exact | 0.66 |
| markupsafe | Architecture modularization | coupling_up | coupling_up | True | exact | 0.90 |
| markupsafe | Publish dependency expansion | coupling_up | coupling_down | False | approximate | 0.90 |
| markupsafe | Publish dependency expansion | coupling_up | coupling_up | True | approximate | 0.66 |
| python-dotenv | Test Cli becomes dependency hub | coupling_up | coupling_down | False | exact | 1.00 |
| python-dotenv | Test Cli becomes dependency hub | coupling_up | coupling_up | True | exact | 1.00 |
| python-dotenv | Setup becomes dependency hub | coupling_up | coupling_up | True | approximate | 1.00 |
| python-dotenv | Setup architectural shift | steady | coupling_up | unknown | exact | 1.00 |
| python-dotenv | Architecture modularization | coupling_down | coupling_up | False | exact | 1.00 |
| python-dotenv | Setup becomes dependency hub | coupling_up | coupling_up | True | approximate | 1.00 |
| python-dotenv | Setup architectural shift | steady | coupling_down | unknown | approximate | 0.94 |
| python-dotenv | Architecture modularization | coupling_down | coupling_down | True | approximate | 1.00 |
| python-dotenv | Setup dependency expansion | coupling_down | coupling_down | True | exact | 1.00 |
| python-dotenv | Setup dependency expansion | steady | coupling_down | unknown | approximate | 1.00 |
| flask-cors | Flask Cors becomes dependency hub | coupling_up | coupling_down | False | approximate | 0.99 |
| flask-cors | Flask Cors becomes dependency hub | coupling_up | coupling_down | False | approximate | 0.76 |
| flask-cors | Architecture modularization | coupling_down | coupling_down | True | approximate | 0.76 |
| flask-cors | Architecture modularization | coupling_down | coupling_down | True | approximate | 0.99 |
| flask-cors | Flask Cors dependency expansion | coupling_down | coupling_down | True | approximate | 0.99 |
| flask-cors | Flask Cors dependency expansion | coupling_down | coupling_down | True | exact | 0.99 |
| flask-cors | Flask Cors architectural shift | coupling_down | coupling_down | True | exact | 0.73 |
| flask-cors | Flask Cors becomes dependency hub | coupling_up | coupling_down | False | approximate | 0.99 |
| prettytable | Test Prettytable becomes dependency hub | coupling_up | coupling_down | False | approximate | 1.00 |
| prettytable | Prettytable coupling reduction | coupling_down | coupling_up | False | exact | 1.00 |
| prettytable | Prettytable becomes dependency hub | coupling_up | coupling_down | False | approximate | 1.00 |
| prettytable | Prettytable architectural shift | coupling_down | coupling_down | True | exact | 1.00 |
| prettytable | Prettytable architectural shift | steady | coupling_up | unknown | exact | 1.00 |
| prettytable | Prettytable dependency expansion | coupling_up | coupling_down | False | approximate | 0.96 |
| prettytable | Architecture modularization | coupling_down | coupling_up | False | approximate | 1.00 |
| prettytable | Architecture modularization | steady | coupling_up | unknown | exact | 0.96 |
