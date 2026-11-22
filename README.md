# csv-analyst — conversational CSV data analyst (Mistral Agents SDK, managed deployment)

A conversational data analyst you reach from **Mistral Vibe**. Paste a Google Drive link to a CSV,
ask questions in plain language, and keep asking follow-ups: the session remembers the file and the
whole discussion. Answers come from **four fixed tools** — no code execution.

- **Managed deployment:** `csv-analyst` — `01a20258-d1ff-7168-b24e-b86686a75628` (Mistral Cloud, hardened)
- **Current agent version:** `01a20271-7a29-7796-ac91-c4211a2601ed`
- **Model:** `mistral-large-latest`
- **Source:** https://github.com/gdhanu555/csv-analyst-agent

## How it works

```
You (Vibe chat) ──MCP stdio──▶ analyst_mcp.py ──Session API──▶ deployed agent `csv-analyst`
                                                                  │  google_drive_mcp connector (your Google OAuth)
                                                                  ▼
                                                    4 fixed tools operating on in-session pandas state
```

| Tool | What it does |
|---|---|
| `load_csv(drive_link, csv_text="", max_rows=100000)` | Extracts the Drive file id, downloads through the `google_drive_mcp` connector, parses and stores the dataset **for this session** |
| `describe_columns()` | Per column: dtype, nulls, distinct count, min/max/mean/median (numeric) or top values (text), samples |
| `filter_rows(column, operator, value, limit=50)` | `eq, ne, gt, gte, lt, lte, contains, in, not_in, is_null, not_null`; returns matched count + rows |
| `group_by_aggregate(group_by, value_column, agg, limit=50)` | `count, sum, mean, median, min, max, std, nunique`; grouped or overall |

Column names are free-form strings from the conversation, validated against `describe_columns`
output. Aggregate functions and filter operators are fixed enums. There is no shell, no Python
evaluation, and the dataframe never enters the model context — the model can only call the tools.

## Interacting through Vibe

`~/.vibe/config.toml` registers a local MCP server (already added; backup at `config.toml.bak`):

```toml
[[mcp_servers]]
name = "csv-analyst"
transport = "stdio"
command = "E:\\AppData\\Local\\Programs\\Python\\Python314\\python.exe"
args = ["E:\\work\\mistral1\\2\\csv-analyst\\analyst_mcp.py"]
```

Restart Vibe (or run `/reload` if supported for MCP changes; otherwise restart the app) and check
with `/mcp` that `csv-analyst` is listed. Then just talk:

> Load https://drive.google.com/file/d/<id>/view and tell me what's in it.
> What is the total `Actual_Supplier_Payments_GBP`?
> And only for days where `Actual_CFD_Payments_GBP` > 10,000,000?
> Which of those days had the highest value?

The assistant forwards each message to `analyst_ask`, which reuses the saved session
(`.analyst_state.json`), so the file and history persist across Vibe restarts. `analyst_new_session`
starts a fresh conversation; `analyst_status` shows the current session.

You can also talk to it directly:

```bash
cd csv-analyst
agents chat csv-analyst          # terminal chat against the deployed agent
```

or use the hosted UI printed at deploy time (`https://chat.mistral.ai/managed-agents/csv-analyst`).

## Files

| File | Role |
|---|---|
| `main.py` | The agent: instructions, 4 tools, connector, `Builtins(programmatic_tool_calling=True, skills=False, subagents=False)` |
| `analyst_mcp.py` | Stdio MCP server exposing `analyst_ask` / `analyst_new_session` / `analyst_status` to Vibe |
| `Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` | Build inputs used by `agents deploy` |
| `test_tools_local.py` | Calls the four tools directly on `sample/in_period_tracking.csv` |
| `test_deployed.py` | Multi-turn end-to-end test against the deployed agent |
| `test_mcp.py` | Drives `analyst_mcp.py` over stdio like an MCP client |

## Redeploying after a change

```bash
cd csv-analyst
git add -A && git commit -m "..."     # deploy builds the pushed commit
git push origin master                # repo must stay public unless the Mistral GitHub App is granted access
agents deploy --name csv-analyst -y
```

## Notes

- **Connector auth**: the agent uses the `google_drive_mcp` connector as the session user (hardened
  deployment). If a session cannot reach Drive, the tool says so and the agent falls back to the
  connector's `download_file_content`.
- **Programmatic tool calling is on** because Mistral Cloud requires it when an agent has connectors.
  The dataset lives inside the tool state, so this does not add any way to compute answers outside
  the four tools; the instructions forbid doing data work in code.
- **Repo visibility**: `gdhanu555/csv-analyst-agent` is public because the workspace's GitHub App
  could not read it while private. Grant the app access to the repo and flip it back to private if
  you prefer (`gh repo edit --visibility private`).
