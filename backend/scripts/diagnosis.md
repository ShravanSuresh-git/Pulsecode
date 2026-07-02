# Counterfactual Replay Diagnosis

This diagnosis was written before changing the replay engine. It uses the existing
`backend/scripts/validation_results.md` corpus result plus a diagnostic validator run
against the same five repositories, same `--events 10`, and same `--snapshot-size 8`.

## Exact vs Approximate Sign Agreement

From the existing published validation artifact:

| replay_status | comparable rows | matching rows | sign agreement | unknown rows | total rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| exact | 3 | 2 | 67% | 1 | 4 |
| approximate | 27 | 15 | 56% | 6 | 33 |

Exact replay is slightly better, but the sample is too small to claim much. The
clearer issue is that only 4 of 37 reported rows are exact, so validation is mostly
measuring the approximate fallback rather than the Git replay engine.

## Replay Failure Reasons

I added `--debug-replay-failures` to `validate_counterfactuals.py` and reran the
same five-repo corpus into `/tmp/pulsecode-diagnosis-validation.md`. The diagnostic
run printed the replay fallback reason for every approximate/failed result.

Observed fallback classes:

| reason | count | examples |
| --- | ---: | --- |
| Merge commit rejected before replay because no mainline parent was selected | 16 | `merge commit 7443b9119b requires a parent selection`, `merge commit 9941bf2820 requires a parent selection`, `merge commit 6384b85846 requires a parent selection` |
| Ordinary cherry-pick failed after removing event commits | 15 | `git cherry-pick --quiet 672f44... returned non-zero`, `git cherry-pick --quiet 4a0745... returned non-zero`, `git cherry-pick --quiet 22f780... returned non-zero` |
| Empty kept interval / missing prior snapshot / deleted-renamed precondition | 0 | No diagnostic rows showed these as the first replay failure reason. |

The dominant failure is merge commits by a narrow margin. The current engine exits
before even trying these commits, so the first targeted fix should be `git
cherry-pick -m 1` for merge commits. Ordinary conflicts are also common, but fixing
merge commits is the smallest change directly supported by the diagnostics.

## False Row Audit

The validation target is noisy because it compares the counterfactual direction to a
nearby interval with similar churn, not to a true held-out alternate history.

1. `python-dotenv`, snapshot 1, `Test Cli becomes dependency hub`
   - Replay status: exact.
   - Predicted: coupling up; nearby interval says coupling down.
   - Event commits are early test coverage work around `tests/test_cli.py`.
   - The matched nearby interval is snapshot 4 -> 5, a later package refactor that
     converts `dotenv.py` into a package and touches `dotenv/cli.py`, `dotenv/main.py`,
     and tests. This is not a close architectural analogue, so the False row is more
     likely a weak validation proxy than an exact replay failure.

2. `itsdangerous`, snapshot 40, `Dev becomes dependency hub`
   - Replay status: approximate.
   - Predicted: coupling up; nearby interval says coupling down.
   - Event snapshot is mostly project-file/tooling and requirements churn, with
     affected modules such as `requirements/dev.txt` and GitHub workflow files.
   - The matched nearby interval is snapshot 19 -> 20, which includes removing
     deprecated JWS code plus requirements/tooling changes. The churn is similar,
     but the module set and architecture phase are different.

3. `markupsafe`, snapshot 1, `Dependabot becomes dependency hub`
   - Replay status: approximate.
   - Predicted: coupling up; nearby interval says coupling down.
   - Event snapshot is early requirements/dependabot/test workflow consolidation.
   - The matched nearby interval is snapshot 45 -> 46, much later release/runtime
     maintenance involving `src/markupsafe/_speedups.c`, publish workflow files,
     and Python-version workflow churn. This is a poor comparison despite similar
     churn magnitude.

4. `flask-cors`, snapshot 1, `Flask Cors becomes dependency hub`
   - Replay status: approximate.
   - Predicted: coupling up; nearby interval says coupling down.
   - Event snapshot introduces documentation and touches `flask_cors.py`, `setup.py`,
     and Sphinx files.
   - The matched nearby interval is snapshot 33 -> 34, later documentation cleanup
     and package-module edits around `flask_cors/core.py`, `decorator.py`, and
     `extension.py`. It is closer than the MarkupSafe case, but still not a true
     counterfactual baseline.

5. `prettytable`, snapshot 5, `Prettytable becomes dependency hub`
   - Replay status: approximate.
   - Predicted: coupling up; nearby interval says coupling down.
   - Event snapshot includes code and tests around `src/prettytable/prettytable.py`
     and `src/prettytable/colortable.py`.
   - The matched nearby interval is snapshot 1 -> 2, mostly workflow/dependabot and
     constructor annotation changes. Similar churn does not mean similar architectural
     pressure here.

## Assessment

The 57% number is low for two reasons:

1. Most comparable rows are approximate rows, so validation is dominated by the
   fallback model instead of by Git-backed replay.
2. Several False rows use a noisy nearby-history proxy whose module set and repo
   phase differ substantially from the event being judged.

The next fix should focus on increasing exact or Git-backed replay coverage by
handling merge commits with `git cherry-pick -m 1`. The validation methodology should
not be changed in this milestone.
