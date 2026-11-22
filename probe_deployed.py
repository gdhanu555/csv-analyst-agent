"""Probe the deployed agent: stream events for one turn so we see what it waits on."""
import asyncio
import json
import os
import sys
import time

from mistralai import agents

LINK = "https://drive.google.com/file/d/1JEDJPa4vboyoqkVkf4u_xQK7wKTivCLL/view?usp=drivesdk"


def show(ev):
    name = type(ev).__name__
    bits = {}
    for attr in ("kind", "id", "name", "status", "error", "title", "text", "content", "call", "requests", "tool", "input", "output", "message"):
        v = getattr(ev, attr, None)
        if v is None or callable(v):
            continue
        if isinstance(v, (str, int, float, bool)):
            bits[attr] = (v[:300] if isinstance(v, str) else v)
        else:
            try:
                bits[attr] = str(v)[:300]
            except Exception:
                pass
    print(f"[{time.strftime('%H:%M:%S')}] {name} {json.dumps(bits, default=str)[:700]}", flush=True)


async def main():
    async def maybe(t):
        return await t if asyncio.iscoroutine(t) else t

    agent = await maybe(agents.Agent.load_from(agent_name=os.environ.get("CSV_ANALYST_AGENT", "csv-analyst")))
    session = await maybe(agent.start_session())
    print("SESSION:", session.id, flush=True)

    question = sys.argv[1] if len(sys.argv) > 1 else f"Load this CSV from my Google Drive: {LINK}"
    turn = session.start_turn(question)
    turn = await turn if asyncio.iscoroutine(turn) else turn
    print("TURN:", turn, flush=True)

    deadline = time.time() + 120
    async for ev in session.iter_events():
        show(ev)
        name = type(ev).__name__
        if name in ("OpenSignIn", "OpenApproval", "OpenCallback"):
            print("=== WAITING ON CALLBACK ===", flush=True)
            reqs = getattr(ev, "requests", None)
            if reqs:
                for r in reqs:
                    print("   source:", getattr(r, "source", None), "id:", getattr(r, "id", None), "name:", getattr(r, "name", None), flush=True)
            req = getattr(ev, "request", None) or getattr(ev, "tool", None)
            if req:
                print("   request:", req, flush=True)
            break
        if name in ("TurnEnded", "TurnUpdated", "Completed", "Failed"):
            try:
                print("=== RESULT ===", flush=True)
                res = await turn.result(timeout=30)
                print("text:", getattr(res, "text", res), flush=True)
            except Exception as e:
                print("result error:", e, flush=True)
            break
        if time.time() > deadline:
            print("DEADLINE", flush=True)
            break


asyncio.run(main())
