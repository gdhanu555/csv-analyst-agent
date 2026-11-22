"""Dump a deployed session's history in readable form."""
import asyncio
import json
import sys

from mistralai import agents

SID = sys.argv[1]


def brief(obj, n=500):
    try:
        return json.dumps(obj, default=str)[:n]
    except Exception:
        return str(obj)[:n]


def summarize(entry):
    name = type(entry).__name__
    role = getattr(entry, "role", None)
    kind = getattr(entry, "kind", None)
    text = getattr(entry, "text", None)
    tool = getattr(entry, "tool", None) or getattr(entry, "tool_name", None) or getattr(entry, "name", None)
    args = getattr(entry, "arguments", None) or getattr(entry, "input", None)
    out = getattr(entry, "output", None) or getattr(entry, "result", None)
    parts = [f"[{name}]"]
    for label, v in (("role", role), ("kind", kind), ("tool", tool)):
        if v:
            parts.append(f"{label}={v}")
    if text:
        parts.append(f"text={str(text)[:400]}")
    if args:
        parts.append(f"args={brief(args, 300)}")
    if out:
        parts.append(f"out={brief(out, 600)}")
    if len(parts) == 1:
        parts.append(brief(entry, 400))
    return " | ".join(parts)


async def main():
    sc = agents.Agent.load_session(SID)
    sc = await sc if asyncio.iscoroutine(sc) else sc

    print("STATE:", brief(sc.state, 800), flush=True)

    hist = sc.list_history()
    if asyncio.iscoroutine(hist):
        hist = await hist
    if hasattr(hist, "__aiter__"):
        entries = [e async for e in hist]
    elif isinstance(hist, dict):
        entries = hist.get("entries") or hist.get("items") or []
    else:
        entries = list(hist)

    print(f"HISTORY ({len(entries)} entries):", flush=True)
    for e in entries:
        print(" ", summarize(e), flush=True)


asyncio.run(main())
