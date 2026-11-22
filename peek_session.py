"""Peek at a deployed session: status + full history (paged)."""
import asyncio
import json
import sys

from mistralai import agents

SID = sys.argv[1]


def brief(o, n=700):
    try:
        return json.dumps(o, default=str)[:n]
    except Exception:
        return str(o)[:n]


async def main():
    sc = agents.Agent.load_session(SID)
    sc = await sc if asyncio.iscoroutine(sc) else sc
    st = sc.state
    print("status:", getattr(st, "status", None) or brief(st, 300), flush=True)
    print("preview:", (getattr(st, "preview", "") or "")[:400], flush=True)

    cursor = None
    total = 0
    while True:
        page = sc.list_history(cursor=cursor) if cursor else sc.list_history()
        if asyncio.iscoroutine(page):
            page = await page
        items = getattr(page, "items", None)
        if items is None and isinstance(page, tuple) and len(page) == 2:
            items = page[1]
        items = items or []
        for e in items:
            total += 1
            t = getattr(e, "type", type(e).__name__)
            role = getattr(e, "role", "")
            line = f"#{total} {t} {role}".strip()
            # message text
            content = getattr(e, "content", None)
            if content:
                for b in content:
                    txt = getattr(b, "text", None)
                    if txt:
                        line += " :: " + str(txt)[:300].replace("\n", " ")
            for attr in ("tool", "tool_name", "name", "arguments", "output", "error"):
                v = getattr(e, attr, None)
                if v:
                    line += f" | {attr}={brief(v, 250)}"
            print(line, flush=True)
        cursor = getattr(page, "next_cursor", None) or getattr(page, "cursor", None)
        if not cursor or not items:
            break


asyncio.run(main())
