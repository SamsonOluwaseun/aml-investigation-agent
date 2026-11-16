---
name: investigate
description: Investigate one AML alert on the synthetic bank. Runs the evidence-gatherer, typology-analyst and case-writer subagents in order, then saves one cited draft case file. Usage /investigate C-014
argument-hint: <case_id, e.g. C-014>
allowed-tools: Agent, mcp__aml-bank__get_alert, mcp__aml-bank__save_case_file
---

# /investigate

Investigate alert **$ARGUMENTS** and save a draft case file for a human investigator.

The rules have already decided this alert needs a look. Your job is to gather and explain the evidence. You never decide the outcome, and the status is always a draft.

## Ground rules

- Use only the `aml-bank` MCP tools and the three subagents below. Do not read files in this repository, query the database directly or use the shell. The case must be built from what the tools return, just as an investigator would work from the bank's systems.
- Every tool call takes the case ID as its first argument.
- Every claim in the case file must cite at least one record ID that came back from a tool. Claims without a source are dropped when the file is saved.
- Keep it small. Pass summaries between steps, not raw transaction lists.

## Steps

1. **Check the case.** Call `mcp__aml-bank__get_alert` with case_id `$ARGUMENTS`. If it returns an error, report the error and stop.

2. **Gather evidence.** Run the `evidence-gatherer` subagent with this prompt:
   `Case ID: $ARGUMENTS. Gather the evidence pack.`
   Keep its evidence pack exactly as returned.

3. **Analyse.** Run the `typology-analyst` subagent with this prompt:
   `Case ID: $ARGUMENTS.` followed by the evidence pack.

4. **Write.** Run the `case-writer` subagent with this prompt:
   `Case ID: $ARGUMENTS.` followed by the evidence pack and the analysis.

5. **Check before saving.** The case writer returns one JSON object. Before saving, check that:
   - it parses as JSON and `case_id` is `$ARGUMENTS`
   - every `evidence` item has a non-empty `source` list, and you remove any item that does not
   - `status` is exactly `Draft for human review`
   - `suggested_action` is one of `Escalate`, `Request more information`, `Dismiss`
   - `innocent_explanations` and `gaps` each have at least one entry
   - no raw transaction lists have been pasted into the summary or claims

   If something is wrong, fix the format yourself without adding new facts, or ask the case writer once to fix it.

6. **Save.** Call `mcp__aml-bank__save_case_file` with case_id `$ARGUMENTS` and `case_json` set to the JSON as a string. The tool validates the file against `agent/case_file.schema.json`, drops any claim whose source IDs don't exist and stores the draft in `cases/`. If it returns an error, fix the stated problem and try once more.

7. **Report.** Reply with one short paragraph: the case ID, risk rating, suggested action, how many evidence claims were kept and anything that was dropped. Do not repeat the whole case file.
