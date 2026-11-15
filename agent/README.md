# agent/

Case file schema and notes for the investigation agent. The agent itself lives in `.claude/`:

- `.claude/skills/investigate/SKILL.md`, the `/investigate` skill
- `.claude/agents/evidence-gatherer.md`
- `.claude/agents/typology-analyst.md`
- `.claude/agents/case-writer.md`

**Owner:** Claude Code · **Build plan:** item 6 · **Design:** Step 5

Planned usage:

```bash
claude                               # then type: /investigate C-014
claude -p "/investigate C-014"       # headless, for the daily pipeline
```
