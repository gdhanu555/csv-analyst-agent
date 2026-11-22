"""Conversational CSV data-analyst agent.

The user pastes a Google Drive link to a CSV and asks plain-language questions.
The agent retrieves the file through the workspace's ``google_drive_mcp`` connector
(the user's own Google connection) and answers using exactly four fixed tools —
there is deliberately no code-execution tool.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from typing import Any

import pandas as pd
from mistralai import agents

CONNECTOR_NAME = "google_drive_mcp"

# Per-session dataset registry, keyed by session id. The harness runs one worker
# process per session in practice; keying by session id keeps sessions isolated.
_DATA: dict[str, pd.DataFrame] = {}
_META: dict[str, dict[str, Any]] = {}
# File-id -> (name, csv_text); a reload of the same file costs nothing.
_CACHE: dict[str, tuple[str, str]] = {}

MAX_BYTES = 50_000_000

INSTRUCTIONS = """You are a conversational data analyst. The user gives you a link to a CSV file in their
Google Drive and asks questions about it in plain language. You answer with real numbers computed
from their data — never invent or estimate numbers.

WORKFLOW
1. When the user shares a Google Drive link to a CSV, call `load_csv` with `drive_link` set to that
   link — call it directly, without searching for connector tools first. The tool retrieves the file
   through the user's Google Drive connection (`google_drive_mcp` connector) and loads it into this
   session. Do not ask the user to paste the file contents.
2. Before answering a question about the data, call `describe_columns` to learn the exact column
   names and types. Always use column names exactly as `describe_columns` reports them.
3. Answer questions with `filter_rows` (inspect matching rows) and `group_by_aggregate` (totals,
   averages, counts per group). Quote the exact numbers the tools return.

TOOLS — these four are all you need for data work:
- `load_csv(drive_link=...)`: fetch and load a CSV from a Drive link. Optionally pass `csv_text`
  only if `load_csv` reports it cannot reach Drive and you have already fetched the text yourself
  with the connector's `download_file_content`.
- `describe_columns()`: schema and statistics of the loaded dataset.
- `filter_rows(column, operator, value, limit)`: rows matching a condition.
  operator ∈ {eq, ne, gt, gte, lt, lte, contains, in, not_in, is_null, not_null}.
- `group_by_aggregate(group_by, value_column, agg, limit)`: grouped aggregates.
  agg ∈ {count, sum, mean, median, min, max, std, nunique}. `value_column` is required unless agg is count.

MEMORY
The loaded dataset and our whole conversation stay in this session. Follow-up questions refer to the
same file — do not reload it unless the user gives a new link or explicitly asks to switch files.

CODE TOOLS
You may use `run_typescript` only to call tools (for example the Google Drive connector's
`download_file_content` when `load_csv` cannot reach Drive itself). Never compute, filter or aggregate
data in code: the dataset lives inside the four data tools above, and every number you report must come
from their output.

STYLE
Be concise. Give the direct answer first with the real numbers, then a small markdown table or bullet
list when it helps. If a question is ambiguous (which column, which filter), ask one short clarifying
question instead of guessing. If a tool reports an error (unknown column, file too large, access
denied), surface it and propose the closest valid alternative.
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sid(ctx: agents.ToolCallbackContext) -> str:
    return ctx.session.id


def _df(ctx: agents.ToolCallbackContext) -> pd.DataFrame:
    sid = _sid(ctx)
    if sid not in _DATA:
        raise agents.ToolError(
            "No CSV is loaded in this session yet. Call load_csv with the user's Google Drive link first."
        )
    return _DATA[sid]


def _clean(value: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-safe Python values."""
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _records(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.head(limit).to_dict(orient="records")]


def _extract_drive_id(link: str) -> str:
    link = link.strip()
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", link)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", link):
        return link
    raise agents.ToolError(
        f"Could not extract a Google Drive file id from {link!r}. "
        "Expected a link like https://drive.google.com/file/d/<id>/view or a bare file id."
    )


def _extract_text(resp: Any) -> str:
    """Pull text out of a connector tool-call response, whatever its shape."""
    if isinstance(resp, str):
        return resp
    dump = resp.model_dump() if hasattr(resp, "model_dump") else resp
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("text", "content", "result", "output"):
                v = node.get(key)
                if isinstance(v, str):
                    texts.append(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and len(node) > 40:
            texts.append(node)

    walk(dump)
    # The CSV itself is the longest string; connector wrappers add short status strings.
    if not texts:
        raise agents.ToolError(f"Connector returned no text content: {str(dump)[:300]}")
    return max(texts, key=len)


async def _connector_client() -> Any:
    """A Mistral client that can call connector tools with the current session's identity."""
    try:
        from mistralai.vibe_agents.sdk.assembly.connectors import RunAs, get_workflow_mistral_client

        return get_workflow_mistral_client(RunAs("auto"))
    except Exception:
        from mistralai.vibe_agents.sdk.assembly.local_mistral import local_mistral_client

        return local_mistral_client("csv-analyst drive fetch").client


async def _call_connector(tool_name: str, arguments: dict[str, Any]) -> Any:
    client = await _connector_client()
    resource = getattr(client, "beta", client).connectors
    return await resource.call_tool_async(
        tool_name=tool_name,
        connector_id_or_name=CONNECTOR_NAME,
        arguments=arguments,
    )


async def _fetch_drive_csv(file_id: str) -> tuple[str, str]:
    """Return (file_name, csv_text) fetched through the user's Google Drive connection."""
    if file_id in _CACHE:
        return _CACHE[file_id]
    content = await asyncio.wait_for(
        _call_connector("download_file_content", {"file_id": file_id}), timeout=120
    )
    name = file_id
    if isinstance(content, dict):
        name = content.get("title") or name
    elif hasattr(content, "title"):
        name = getattr(content, "title") or name
    text = _extract_text(content)
    _CACHE[file_id] = (name, text)
    return name, text


def _parse_csv(text: str, max_rows: int) -> tuple[pd.DataFrame, bool]:
    truncated = False
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    if len(df) > max_rows:
        df = df.head(max_rows)
        truncated = True
    return df, truncated


# --------------------------------------------------------------------------- #
# the four fixed tools
# --------------------------------------------------------------------------- #

@agents.tool(model_access="direct", annotations=agents.ToolAnnotations(read_only_hint=True))
async def load_csv(
    ctx: agents.ToolCallbackContext,
    /,
    drive_link: str = "",
    csv_text: str = "",
    max_rows: int = 100_000,
) -> dict[str, Any]:
    """Load a CSV into this session. Give the user's Google Drive link as `drive_link`; the file is
    fetched through the user's Google Drive connection. Only pass `csv_text` if you already fetched
    the file text yourself with the connector's download_file_content. Returns the file name, row
    and column counts, and the column list."""
    sid = _sid(ctx)
    name, text = "(pasted text)", csv_text
    if drive_link.strip():
        file_id = _extract_drive_id(drive_link)
        try:
            name, text = await _fetch_drive_csv(file_id)
        except Exception as exc:
            raise agents.ToolError(
                f"Could not fetch {drive_link!r} through the {CONNECTOR_NAME} connector: {exc}. "
                "If the connection is not authorized for this session, call the connector tool "
                "google_drive_mcp.download_file_content yourself with the file id, then call "
                "load_csv again passing the returned text as csv_text."
            )
    if not text.strip():
        raise agents.ToolError("Nothing to load: pass a Drive link as drive_link (or csv_text).")
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
        raise agents.ToolError(
            f"File is larger than {MAX_BYTES} bytes; refusing to load. Ask the user for a smaller export."
        )
    try:
        df, truncated = _parse_csv(text, max_rows)
    except Exception as exc:
        raise agents.ToolError(f"Could not parse the file as CSV: {exc}")
    _DATA[sid] = df
    _META[sid] = {"name": name, "rows_loaded": int(len(df)), "truncated": truncated}
    return {
        "file": name,
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "column_count": int(df.shape[1]),
        "truncated_to_max_rows": truncated,
        "note": "Dataset is loaded in this session. Call describe_columns next.",
    }


@agents.tool(model_access="direct", annotations=agents.ToolAnnotations(read_only_hint=True))
def describe_columns(ctx: agents.ToolCallbackContext, /) -> dict[str, Any]:
    """Describe every column of the loaded CSV: name, type, nulls, distinct values, and for numeric
    columns min/max/mean/median, for text columns the most frequent values, plus a few sample values."""
    df = _df(ctx)
    cols: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        entry: dict[str, Any] = {
            "name": str(col),
            "dtype": str(s.dtype),
            "null_count": int(s.isna().sum()),
            "distinct_count": int(s.nunique(dropna=True)),
            "samples": [_clean(v) for v in s.dropna().head(3).tolist()],
        }
        if pd.api.types.is_numeric_dtype(s):
            entry["min"] = _clean(s.min())
            entry["max"] = _clean(s.max())
            entry["mean"] = _clean(s.mean())
            entry["median"] = _clean(s.median())
        elif s.dtype == object or str(s.dtype).startswith("str"):
            top = s.value_counts(dropna=True).head(5)
            entry["top_values"] = [{ "value": _clean(k), "count": int(v)} for k, v in top.items()]
        cols.append(entry)
    return {"file": _META.get(_sid(ctx), {}).get("name"), "rows": int(len(df)), "columns": cols}


_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "not_in", "is_null", "not_null"}


def _coerce_like(series: pd.Series, value: str) -> Any:
    if pd.api.types.is_bool_dtype(series):
        return str(value).strip().lower() in ("true", "1", "yes", "y")
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(value)
        except ValueError:
            return value
    if pd.api.types.is_datetime64_any_dtype(series):
        ts = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(ts) else ts
    return value


@agents.tool(model_access="direct", annotations=agents.ToolAnnotations(read_only_hint=True))
def filter_rows(
    ctx: agents.ToolCallbackContext,
    /,
    column: str,
    operator: str,
    value: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Return rows of the loaded CSV matching a condition. operator ∈ {eq, ne, gt, gte, lt, lte,
    contains, in, not_in, is_null, not_null}. For `in`/`not_in` pass a comma-separated list or JSON
    array in `value`. `limit` caps the rows returned (max 200)."""
    df = _df(ctx)
    if column not in df.columns:
        raise agents.ToolError(
            f"Unknown column {column!r}. Available columns: {', '.join(map(str, df.columns))}"
        )
    if operator not in _OPERATORS:
        raise agents.ToolError(f"Unknown operator {operator!r}. Use one of: {sorted(_OPERATORS)}")
    s = df[column]
    if operator == "is_null":
        mask = s.isna()
    elif operator == "not_null":
        mask = s.notna()
    elif operator == "contains":
        mask = s.astype(str).str.contains(str(value), case=False, regex=False, na=False)
    elif operator in ("in", "not_in"):
        raw = value.strip()
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            values = [v.strip() for v in raw.split(",") if v.strip() != ""]
        coerced = [_coerce_like(s, str(v)) for v in values]
        mask = s.isin(coerced)
        if operator == "not_in":
            mask = ~mask
    else:
        v = _coerce_like(s, value)
        if v is None:
            raise agents.ToolError(f"Value {value!r} is not valid for column {column!r} ({s.dtype}).")
        if operator == "eq":
            mask = s == v
        elif operator == "ne":
            mask = s != v
        elif operator == "gt":
            mask = s > v
        elif operator == "gte":
            mask = s >= v
        elif operator == "lt":
            mask = s < v
        else:
            mask = s <= v
    matched = df[mask.fillna(False)]
    limit = max(1, min(int(limit), 200))
    return {
        "column": column,
        "operator": operator,
        "value": value,
        "matched": int(len(matched)),
        "returned": int(min(len(matched), limit)),
        "rows": _records(matched, limit),
    }


_AGGS = {"count", "sum", "mean", "median", "min", "max", "std", "nunique"}


@agents.tool(model_access="direct", annotations=agents.ToolAnnotations(read_only_hint=True))
def group_by_aggregate(
    ctx: agents.ToolCallbackContext,
    /,
    group_by: list[str] | None = None,
    value_column: str | None = None,
    agg: str = "count",
    limit: int = 50,
) -> dict[str, Any]:
    """Compute a grouped aggregate over the loaded CSV. `group_by` is a list of column names (empty
    for an overall aggregate). `agg` ∈ {count, sum, mean, median, min, max, std, nunique};
    `value_column` is required unless agg is `count`. `limit` caps the groups returned (max 500)."""
    df = _df(ctx)
    group_by = [g for g in (group_by or []) if g]
    for g in group_by:
        if g not in df.columns:
            raise agents.ToolError(
                f"Unknown group_by column {g!r}. Available columns: {', '.join(map(str, df.columns))}"
            )
    if agg not in _AGGS:
        raise agents.ToolError(f"Unknown agg {agg!r}. Use one of: {sorted(_AGGS)}")
    if agg != "count":
        if not value_column:
            raise agents.ToolError(f"value_column is required when agg is {agg!r}.")
        if value_column not in df.columns:
            raise agents.ToolError(
                f"Unknown value_column {value_column!r}. Available columns: {', '.join(map(str, df.columns))}"
            )
        if agg in ("sum", "mean", "median", "std") and not pd.api.types.is_numeric_dtype(df[value_column]):
            raise agents.ToolError(
                f"Column {value_column!r} is not numeric ({df[value_column].dtype}); cannot compute {agg}."
            )

    if not group_by:
        if agg == "count":
            result = pd.DataFrame([{"agg": int(len(df)), "agg_name": "count"}])
        else:
            s = df[value_column]
            val = {"sum": s.sum, "mean": s.mean, "median": s.median, "min": s.min,
                   "max": s.max, "std": s.std, "nunique": s.nunique}[agg]()
            result = pd.DataFrame([{"agg": _clean(val), "agg_name": agg, "value_column": value_column}])
    else:
        if agg == "count":
            g = df.groupby(group_by, dropna=False).size().reset_index(name="agg")
            g = g.rename(columns={"size": "agg"}) if "size" in g.columns else g
            g["agg_name"] = "count"
        else:
            s = df[value_column]
            grouped = df.groupby(group_by, dropna=False)[value_column]
            val = {"sum": grouped.sum, "mean": grouped.mean, "median": grouped.median,
                   "min": grouped.min, "max": grouped.max, "std": grouped.std,
                   "nunique": grouped.nunique}[agg]()
            g = val.reset_index(name="agg")
            g["agg_name"] = agg
        asc = agg == "min"
        g = g.sort_values("agg", ascending=asc, na_position="last").reset_index(drop=True)
        result = g

    limit = max(1, min(int(limit), 500))
    total_groups = int(len(result))
    return {
        "group_by": group_by,
        "value_column": value_column,
        "agg": agg,
        "group_count": total_groups,
        "returned": int(min(total_groups, limit)),
        "truncated": total_groups > limit,
        "rows": _records(result, limit),
    }


agent = agents.Agent(
    model="mistral-large-latest",
    name="csv-analyst",
    description="Conversational data analyst for CSV files in the user's Google Drive.",
    instructions=INSTRUCTIONS,
    tools=[load_csv, describe_columns, filter_rows, group_by_aggregate],
    connectors=[agents.connector(CONNECTOR_NAME)],
    # The platform requires programmatic tool calling when the agent has connectors.
    # All data lives inside the four tools' state, so the model can only orchestrate
    # tool calls — it cannot compute or read the dataset any other way.
    builtins=agents.Builtins(programmatic_tool_calling=True, skills=False, subagents=False),
    temperature=0.2,
)
