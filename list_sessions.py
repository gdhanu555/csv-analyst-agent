"""List the deployed agent's sessions, newest first, with status and preview."""
import asyncio
import json

from mistralai import agents


async def main():
    client = agents.Client()
    res = client.list_sessions()
    if asyncio.iscoroutine(res):
        res = await res
    items = getattr(res, "items", None) or res
    for s in items if isinstance(items, (list, tuple)) else [items]:
        d = s.model_dump() if hasattr(s, "model_dump") else s
        keep = {k: d.get(k) for k in ("id", "status", "created_at", "updated_at", "title", "preview", "agent_name") if isinstance(d, dict) and k in d}
        print(json.dumps(keep, default=str)[:400])


asyncio.run(main())
