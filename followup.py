"""Follow-up questions on an existing deployed session (memory test)."""
import asyncio
import sys

from mistralai import agents

SID = sys.argv[1]


def text_of(turn):
    for attr in ("text", "output", "answer"):
        v = getattr(turn, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    return str(turn)


async def main():
    agent = agents.Agent.load_from(agent_name="csv-analyst")
    if asyncio.iscoroutine(agent):
        agent = await agent
    session = agent.session(SID, on_approval=lambda ctx, req: agents.AllowApproval(scope="session"))
    if asyncio.iscoroutine(session):
        session = await session

    questions = [
        "What is the total Actual_Supplier_Payments_GBP across all rows?",
        "Now only for days where Actual_CFD_Payments_GBP was above 10,000,000: what is the sum of Actual_CFD_Payments_GBP and the average Actual_Eligible_Demand_MWh?",
        "Which of those same high-payment days had the highest Actual_CFD_Payments_GBP?",
    ]
    for i, q in enumerate(questions, 1):
        print(f"\n=== Q{i}: {q}", flush=True)
        turn = session.run(q, timeout=420)
        turn = await turn if asyncio.iscoroutine(turn) else turn
        print("A:", text_of(turn), flush=True)


asyncio.run(main())
