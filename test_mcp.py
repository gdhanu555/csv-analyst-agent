"""Drive analyst_mcp.py over stdio like an MCP client would: initialize, list tools, call one."""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
proc = subprocess.Popen(
    [sys.executable, "-u", os.path.join(HERE, "analyst_mcp.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE,
)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def read_until(req_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == req_id:
            return msg
    return None


send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}})
print("INIT:", json.dumps(read_until(1)))

send({"jsonrpc": "2.0", "method": "notifications/initialized"})

send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
res = read_until(2)
print("TOOLS:", json.dumps(res)[:600] if res else None)

send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "analyst_status", "arguments": {}}})
res = read_until(3)
print("STATUS:", json.dumps(res)[:600] if res else None)

if len(sys.argv) > 1:
    q = " ".join(sys.argv[1:])
    send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "analyst_ask", "arguments": {"question": q}}})
    res = read_until(4, timeout=600)
    print("ASK:", json.dumps(res)[:2000] if res else None)

proc.stdin.close()
proc.terminate()
