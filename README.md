# llmops-release-monitor

Proves: LLMOps release safety: eval-gated promotion, canary rollback, drift and cost monitoring, with a tamper-evident audit log. Verify in 60s: `python3 evaluate.py`.

## Business problem

A bank, drugmaker, utility or logistics firm changes its LLM app: a new prompt, a new model id, a vendor update. In a regulated setting, someone must later show that the change was tested before release, watched while live, rolled back when it got worse, and that nobody edited the record afterward. Quality, speed and cost can each get worse on their own. The inputs can shift. The automated judge that scores outputs can slowly stop agreeing with human reviewers. This repo is a small pipeline that checks all of these and proves each check works by planting a failure and requiring it to be caught.

## Run

```
python3 evaluate.py
python3 -m unittest discover -s tests
```

`evaluate.py` prints this (exit code 1 if any planted failure is missed or any control fails):

```
case                            kind     expected          observed          result
regressed version blocked       planted  blocked           blocked           OK
latency regression rolls back   planted  rollback:latency  rollback:latency  OK
cost blow-up rolls back         planted  rollback:cost     rollback:cost     OK
injected drift window           planted  alert             alert             OK
judge drifts from human labels  planted  alert             alert             OK
tampered audit entry            planted  tampered          tampered          OK
clean upgrade promoted          control  promoted          promoted          OK
stable production window        control  stable            stable            OK
judge agrees with humans        control  stable            stable            OK
untouched audit log             control  intact            intact            OK
6/6 planted failures caught, 4/4 controls passed
```

Tests: 14 in `tests/`, run with unittest. Seven are mutants: each one breaks a detector (gate, SLO check, PSI, judge drift, chain check), asserts `evaluate.py` goes RED, then restores it and asserts GREEN.

## How it works

- Registry (`releasemon.py`): a JSON file holds versions with a prompt hash, a model id string and offline eval scores. An audit log lives in the same file. Each entry stores the hash of the previous entry, so editing or deleting any entry breaks the chain from that point.
- Eval-gated promotion: a candidate moves on only if its offline quality is at least the baseline minus a 0.01 tolerance.
- Canary: 10% of simulated traffic goes to the candidate. A seeded generator makes labelled requests with latency and token counts. The pipeline computes quality, p95 latency, cost per 1k requests and token totals. A breach rolls back and writes the reason to the audit log. SLOs: quality drop over 0.03, p95 over 1.25x baseline, cost over 1.30x baseline.
- Drift monitor: population stability index (PSI, 10 bins from the reference window) on output scores. Above 0.20 is an alert. Judge-to-human agreement uses Cohen's kappa written by hand (observed agreement minus chance agreement, over one minus chance). It alerts if kappa falls under 0.70 or drops more than 0.15 from the reference.
- Planted failures: a regressed version, a latency regression, a cost blow-up, an injected drift window, a judge that grows lenient, and a tampered audit entry. Four clean controls must pass.

Everything is Python 3 standard library, seeded, with no network and no model calls. It runs in well under a second.

## Honesty statement

The traffic is synthetic. Latency, tokens, prices and quality labels come from seeded random generators. Nothing here is production data, nothing came from customers, and no real model was called. The pipeline is a simulation of the release process, not a deployed system. The numbers prove the detectors work on planted cases. They do not predict real traffic.

## Limitations

- Thresholds (0.01, 0.03, 1.25x, 1.30x, PSI 0.20, kappa 0.70) are illustrative. Real values need your own baselines.
- The hash chain shows edits and deletions in the middle. It cannot show that the newest entries were cut off, because there is no external anchor or signature.
- Canary runs once on a fixed sample. There is no staged ramp, no sequential test and no confidence interval on the SLO checks.
- Drift covers one score distribution and one binary judge. Input drift, multi-class labels and multiple judges are not covered.
- Cost uses a flat synthetic price per token.

Agent verification contract: [AGENTS.md](AGENTS.md)
