#!/usr/bin/env python
"""MCP stdio server that exposes the deployed `csv-analyst` managed agent to Mistral Vibe.

Vibe talks to this server over stdio (JSON-RPC 2.0, newline-delimited). The server keeps
one conversation session alive on the deployed agent, so every question — including
follow-ups — lands in the same session, which remembers the loaded CSV and the discussion.

Tools exposed to Vibe:
  analyst_ask(question)   ask the agent; returns its answer with the numbers it computed
  analyst_new_session()   start a fresh conversation (forget the loaded file)
  analyst_status()        deployment + current session id
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import traceback

AGENT_NAME = os.environ.get("CSV_ANALYST_AGENT", "csv-analyst")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".analyst_state.json")

_loop = asyncio.new_event_loop()


def _run_loop() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


threading.Thread(target=_run_loop, daemon=True, name="analyst-async").start()


def _submit(coro, timeout: float = 900.0):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #

def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


_state = _load_state()
_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        from mistralai import agents

        _agent = agents.Agent.load_from(agent_name=AGENT_NAME)
        if asyncio.iscoroutine(_agent):
            _agent = await _agent
    return _agent


def _answer_text(turn) -> str:
    for attr in ("text", "output", "answer"):
        v = getattr(turn, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    try:
        return json.dumps(turn.model_dump(), default=str)[:8000]
    except Exception:
        return str(turn)


async def _ensure_session():
    """Return the saved session, creating one when there is none."""
    from mistralai import agents

    agent = await _get_agent()
    on_approval = lambda ctx, req: agents.AllowApproval(scope="session")  # noqa: E731
    sid = _state.get("session_id")
    if sid:
        try:
            sess = agent.session(sid, on_approval=on_approval)
            return (await sess) if asyncio.iscoroutine(sess) else sess, sid
        except Exception:
            pass  # stale id: fall through and start a new session
    session = agent.start_session(on_approval=on_approval)
    if asyncio.iscoroutine(session):
        session = await session
    _state["session_id"] = session.id
    _save_state(_state)
    return session, session.id


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #

async def _a_ask(question: str) -> dict:
    from mistralai import agents

    session, sid = await _ensure_session()
    turn = session.run(question, timeout=840)
    turn = await turn if asyncio.iscoroutine(turn) else turn
    if type(turn).__name__ == "Busy":
        return {"session_id": sid, "answer": "The agent is still answering the previous question; try again in a moment."}
    return {"session_id": sid, "agent": AGENT_NAME, "answer": _answer_text(turn)}


async def _a_new_session() -> dict:
    agent = await _get_agent()
    session = agent.start_session()
    if asyncio.iscoroutine(session):
        session = await session
    _state["session_id"] = session.id
    _save_state(_state)
    return {"session_id": session.id, "note": "New conversation started. Load a CSV link to begin."}


async def _a_status() -> dict:
    return {
        "agent": AGENT_NAME,
        "session_id": _state.get("session_id"),
        "state_file": STATE_PATH,
        "hint": "Ask a question with analyst_ask; paste a Google Drive CSV link in the question to load a file.",
    }


TOOLS = {
    "analyst_ask": {
        "description": (
            "Ask the deployed 'csv-analyst' agent a question about the CSV loaded in this conversation. "
            "Reuse this for every question and follow-up: the session remembers the loaded file and everything "
            "discussed. To load a file, include the Google Drive link in the question. Returns the agent's answer "
            "with the real numbers computed from the data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question in plain language, including a Google Drive CSV link when loading a new file.",
                }
            },
            "required": ["question"],
        },
        "handler": lambda args: _a_ask(str(args.get("question", "")).strip()),
    },
    "analyst_new_session": {
        "description": "Start a fresh conversation with csv-analyst (forgets the loaded CSV and prior discussion).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda args: _a_new_session(),
    },
    "analyst_status": {
        "description": "Show which deployed agent and conversation session the current questions are going to.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda args: _a_status(),
    },
}


# --------------------------------------------------------------------------- #
# MCP stdio protocol
# --------------------------------------------------------------------------- #

def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _result(req_id, result) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _handle_call(params: dict) -> None:
    req_id = params.get("_id")
    name = params.get("name")
    args = params.get("arguments") or {}
    tool = TOOLS.get(name)
    if tool is None:
        _error(req_id, -32602, f"Unknown tool: {name}")
        return
    try:
        result = _submit(tool["handler"](args))
        _result(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}], "isError": False})
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=3)
        _result(req_id, {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}\n{tb}"}], "isError": True})


def main() -> None:
    if not (os.environ.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_CLIENT_API_KEY")):
        _send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "error", "data": "MISTRAL_API_KEY is not set in this process"}})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            _error(None, -32700, "Parse error")
            continue

        method = msg.get("method")
        req_id = msg.get("id")

        if method == "initialize":
            _result(req_id, {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "csv-analyst", "version": "1.0.0"},
            })
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "ping":
            _result(req_id, {})
        elif method == "tools/list":
            _result(req_id, {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                    for n, t in TOOLS.items()
                ]
            })
        elif method == "tools/call":
            params = dict(msg.get("params") or {})
            params["_id"] = req_id
            _handle_call(params)
        elif method is not None and req_id is not None:
            _error(req_id, -32601, f"Method not found: {method}")
        # notifications (no id) are ignored


if __name__ == "__main__":
    main()
