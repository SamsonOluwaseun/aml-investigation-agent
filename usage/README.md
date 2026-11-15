# usage/

Token usage logging. Claude Code hooks read the session transcripts and write one row per agent run to `usage.jsonl`, linked to the case and the parent run. The agent never reports its own usage.

**Owner:** Claude Code · **Build plan:** item 7 · **Design:** Step 7

Costs worked out from this log are API-equivalent estimates, not money spent on a subscription.
