# csv-analyst — User Guide

Ask questions about a CSV in your Google Drive in plain language, and get answers computed from the
real data. No formulas, no coding, no spreadsheets to wrangle.

---

## 1. What it is

A conversational analyst that runs as a managed agent on Mistral Cloud. You paste a Google Drive link
to a CSV once, ask whatever you like, and keep asking follow-ups — it remembers the file and the whole
conversation.

It answers by running **four fixed tools** over your data:

| Tool (in plain words) | What it does for you |
|---|---|
| **Load** | Fetches the CSV from your Google Drive and keeps it in the conversation |
| **Describe** | Tells you what columns exist, their types, how many values are missing, min/max/average, most common values |
| **Filter** | Finds the rows that match a condition ("only where X > 10,000,000") |
| **Group & aggregate** | Totals, averages, counts, medians, lowest/highest per group |

Every number in an answer comes from one of those tools. It cannot make numbers up, and it cannot run
code — it can only query your data through those four operations.

---

## 2. Quick start (Vibe)

1. **Restart Vibe Desktop.** The connection to the agent is registered in `~/.vibe/config.toml` and is
   read at startup.
2. Type `/mcp` and confirm `csv-analyst` is listed (three tools: `analyst_ask`, `analyst_new_session`,
   `analyst_status`).
3. Paste a Drive link and ask your first question:

   > Load https://drive.google.com/file/d/<file-id>/view and tell me what's in it.

4. Keep asking — no need to repeat the link or the context:

   > What's the total `Actual_Supplier_Payments_GBP`?
   > And only for days where `Actual_CFD_Payments_GBP` > 10,000,000?
   > Which of those had the highest value?

That's the whole workflow.

### Getting the Drive link

In Google Drive: right-click the file → **Share** → make sure your account can open it → **Copy link**.
Both work:

- a **file link** — `https://drive.google.com/file/d/<id>/view?usp=drivesdk`
- a **Google Sheets link** — `https://docs.google.com/spreadsheets/d/<id>/edit` (exported as CSV)

---

## 3. The three ways to talk to it

| Where | How | When to use |
|---|---|---|
| **Vibe Desktop** | Just chat; your message goes to `analyst_ask` | Day-to-day use, next to your other work |
| **Terminal** | `cd csv-analyst && agents chat csv-analyst` | Quick check without opening Vibe |
| **Browser** | https://chat.mistral.ai/managed-agents/csv-analyst | Share with someone, or from a machine without Vibe |

All three talk to the same deployed agent, but each conversation is its own session — a file loaded in
Vibe is not automatically loaded in the terminal.

---

## 4. How conversations work

- **One conversation, remembered.** The Vibe connection keeps a single session (id in
  `csv-analyst/.analyst_state.json`). It survives Vibe restarts, and it survives redeploys of the agent —
  after a redeploy it re-loads your file from the link already in the conversation.
- **Switching files.** Paste a different Drive link and say so ("now use this one instead"). The new
  file becomes the active dataset; the old one stays in the history.
- **Starting over.** Ask for `analyst_new_session` (or say "start a new conversation"). That clears the
  loaded file and the discussion. Useful when a conversation gets long or you want a clean slate.
- **Checking where you are.** `analyst_status` shows which agent and which session your questions go to.

---

## 5. What you can ask

**Explore the file**

- "How many rows and columns does it have?"
- "What does each column mean / what's the date range?"
- "Which columns have missing values?"
- "Summarise this file for me before I dig in."

**Look at specific rows**

- "Show me the 10 rows with the highest `Revenue`."
- "What were the rows for 2026-10-10?"
- "Which rows have `Status` equal to 'cancelled'?"
- "Show rows where `Region` contains 'north' and `Sales` above 5000."
- "How many rows have a missing `Discount`?"

**Totals and averages**

- "What's the total `Actual_Supplier_Payments_GBP`?"
- "Average demand per day, ignoring blanks?"
- "How many distinct customers are there?"
- "Median order value?"
- "Lowest and highest `Temperature`?"

**Grouped answers**

- "Total revenue by region."
- "Top 10 products by units sold."
- "Average order value per month."
- "Count of rows per status."
- "Which group has the widest spread in `Latency`?" (std)

**Chained reasoning** — the part that makes it useful

- "Which region had the highest total revenue, and what was that number?"
- "Of the days where X was above the 10 million mark, which single day was the biggest?"
- "Compare the average of `Initial_Forecast_...` against `Actual_...`."
- "Now exclude the outliers you just found and give me the total again."

Combining `filter_rows` and `group_by_aggregate` across several messages is exactly the intended use.

---

## 6. What it can't do (and what to ask instead)

| Not supported | Ask this instead |
|---|---|
| Charts, graphs, images | "Give me the numbers as a table" — then chart them yourself |
| Joining two files, or comparing two files at once | Ask for each file's numbers separately and compare manually |
| Writing results back to Drive / creating files | Copy the table out of the answer |
| Recomputing things you didn't ask for (e.g. "what would happen if…") | It reports what's in the data, not projections |
| Free-form Python/pandas on the file | Use the four operations; if a question needs something exotic, it will tell you what it can approximate |
| Files over ~50 MB, or more than 100,000 rows loaded | Export a smaller slice, or ask for a segment of the data |
| Emailing/scheduling/sharing | Outside this agent's scope |

If a column name is ambiguous (e.g. two similar columns), it asks one short clarifying question rather
than guessing — answer with the exact name from `describe_columns`.

---

## 7. Speed expectations

| Action | Typical time |
|---|---|
| First load of a file | up to ~2 minutes (Google Drive connector cold start) |
| Follow-up question | 30–90 seconds |
| Reloading the same file in the same worker | instant (cached) |
| New conversation startup | ~50 seconds |

Long questions that need several tool calls take longer than short ones. If a turn feels stuck beyond
a few minutes, ask again — the session keeps its state, so you won't lose the loaded file.

---

## 8. Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| Vibe doesn't show `csv-analyst` in `/mcp` | MCP server not loaded | Restart Vibe Desktop; confirm `[[mcp_servers]] name = "csv-analyst"` in `~/.vibe/config.toml` |
| "No CSV is loaded in this session yet" | The conversation was reset, or this is a new session | Paste the Drive link again |
| "Could not fetch … through the google_drive_mcp connector" | Google Drive access wasn't granted for this session | Re-authorize the Google Drive connector, or check the file is shared with your account |
| "Unknown column 'X'. Available columns: …" | Name mismatch | Use a name exactly as listed in the error / from `describe_columns` |
| "Column is not numeric; cannot compute sum" | Aggregating text with sum/mean | Wrap with count, or pick a numeric column |
| Answer looks stale after you edited the file | Same file id served from cache in this worker | Paste the link again with "reload this file", or start a new session |
| `analyst_ask` returns "agent is still answering" | A previous question is still running | Wait for it, then retry |
| Session seems to have forgotten everything | `.analyst_state.json` is missing or holds a dead session id | `analyst_new_session`, then reload your link |

---

## 9. Privacy and where your data goes

- The CSV is fetched **server-side** by Mistral Cloud using **your** Google Drive connection
  (the same `google_drive_mcp` connector Vibe uses). Nothing is downloaded to your laptop to answer.
- The parsed rows live **inside the agent session**, not in the model's context. The model sees column
  statistics and the rows your questions actually return — not the whole file.
- The session (messages, tool calls, results) is stored by Mistral for the session's lifetime, and is
  visible under **Studio → Deployments → csv-analyst**. Treat it as a record of the questions you asked.
- The deployment is **hardened**: it runs only for pinned identities, acting as the user who opened the
  session.

---

## 10. For the operator (when you need to change something)

| Task | Command / file |
|---|---|
| Redeploy after editing `main.py` | `git commit && git push`, then `agents deploy --name csv-analyst -y` (≈1 minute) |
| Change the model | `main.py` → `agents.Agent(model=...)`, then redeploy |
| See worker logs | `agents logs csv-analyst` |
| Confirm it's running | `agents list` |
| Reset the Vibe conversation | delete `csv-analyst/.analyst_state.json` or call `analyst_new_session` |
| Make the GitHub repo private | grant the Mistral GitHub App access to `gdhanu555/csv-analyst-agent`, then `gh repo edit gdhanu555/csv-analyst-agent --visibility private` |
| Run the tool tests locally | `python test_tools_local.py` |

Details of the build and internals are in [README.md](README.md).

---

## 11. FAQ

**Do I have to paste the link every time?** No — once per conversation. Only when you switch files.

**Can it read Google Sheets?** Yes: paste the Sheets link and it exports the sheet as CSV.

**Can two people share one conversation?** A session is one conversation with one history. Share the
browser link (chat.mistral.ai/managed-agents/csv-analyst) for colleagues to start their own sessions.

**Does it remember numbers it computed earlier?** It remembers the conversation, but it recomputes
when you ask again — so answers stay consistent with the file, not with an old printout.

**What if I want the raw rows for a filter?** Ask for them: "show me those rows" returns up to 50 by
default (200 max).

**Why does the first load take two minutes?** The Google Drive connector is cold-started per session.
Subsequent questions are much faster.
