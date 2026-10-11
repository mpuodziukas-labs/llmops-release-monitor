# llmops-release-monitor

A regulated company ships an LLM change (new prompt or model) and needs proof it was gated, canaried, monitored for drift and cost, and audited.

## Run it in 60 seconds

```
python3 -m pip install pytest
python3 evaluate.py
python3 -m pytest -q
```

## Results

| bad caught | good passed |
|---|---|
| 1/1 | 1/1 |

## Honesty Statement

Synthetic data. Not production, not client data.

## Limitations

Small synthetic corpus. Replace before drawing conclusions.
