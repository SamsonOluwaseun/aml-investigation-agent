# rules/

Typology engine. Plain Python rules that flag suspicious customers and write alerts to the queue. No AI is used here.

**Owner:** Codex · **Build plan:** items 3 and 4 · **Design:** Step 3

Typologies for v1: structuring, rapid pass-through, fan-in/fan-out, high-risk link. Thresholds are demo values, not regulatory ones.

Planned commands:

```bash
python rules/run_rules.py   # write alerts to the alerts table
pytest rules/tests
```
