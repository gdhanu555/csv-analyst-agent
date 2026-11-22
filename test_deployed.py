"""End-to-end test against the deployed managed agent."""
import asyncio
import inspect
import json
import os

from mistralai import agents

AGENT_NAME = os.environ.get("CSV_ANALYST_AGENT", "csv-analyst")
LINK = "https://drive.google.com/file/d/1JEDJPa4vboyoqkVkf4u_xQK7wKTivCLL/view?usp=drivesdk"

QUESTIONS = [
    f"Here is a CSV in my Google Drive: {LINK}\nLoad it and tell me how many rows and which columns it has.",
    "What is the total Actual_Supplier_Payments_GBP across all rows?",
    "Now only for days where Actual_CFD_Payments_GBP was above 10,000,000: what is the sum of Actual_CFD_Payments_GBP and the average Actual_Eligible_Demand_MWh?",
    # follow-up that depends on remembering the file + the earlier filter
    "And of those same high-payment days, which single day had the highest Actual_CFD_Payments_GBP?",
]


def text_of(turn):
    for attr in ("text", "output", "answer", "content"):
        v = getattr(turn, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    try:
        d = turn.model_dump()
        return json.dumps(d)[:4000]
    except Exception:
        return repr(turn)[:4000]


async def call_maybe(t):
    return await t if inspect.isawaitable(t) else t


async def main():
    agent = await call_maybe(agents.Agent.load_from(agent_name=AGENT_NAME))
    session = await call_maybe(
        agent.start_session(on_approval=lambda ctx, req: agents.AllowApproval(scope="session"))
    )
    print("SESSION:", session.id, flush=True)

    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n=== Q{i} ===", flush=True)
        turn = await call_maybe(session.run(q, timeout=600))
        print("A:", text_of(turn), flush=True)

    print("\nDONE. session_id =", session.id)


asyncio.run(main())
