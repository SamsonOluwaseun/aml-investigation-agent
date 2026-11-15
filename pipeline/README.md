# pipeline/

Daily batch run. Picks up the day's file from `incoming/`, validates it against its control file, loads it, runs the rules over a rolling 30-day window, creates or updates alerts, runs the agent on new alerts within a token budget, and writes a run summary.

**Owner:** Claude Code · **Build plan:** item 8 · **Design:** How this maps to production

Planned command:

```bash
python pipeline/run_daily.py --day 2026-11-16
```

Try it with the sample file in `data/sample/`.
