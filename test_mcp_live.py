"""隔着真实 PT 驱动 pt_mcp.py，验整条链：MCP -> 文件队列 -> PT 脚本引擎 -> 设备 CLI。"""
import json
import subprocess
import os
import sys

p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_mcp.py")],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8")

reqs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pt_devices", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "pt_command_log", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "pt_cli", "arguments": {"device": "Router0", "command": "show version | include Router"}}},
]

for m in reqs:
    p.stdin.write(json.dumps(m) + "\n")
p.stdin.flush()

for _ in range(5):
    line = p.stdout.readline()
    if not line:
        break
    g = json.loads(line)
    i = g.get("id")
    if i == 2:
        print("tools:", [t["name"] for t in g["result"]["tools"]])
    elif i == 1:
        print("initialize:", g["result"]["serverInfo"])
    else:
        r = g["result"]
        print("id=%s isError=%s text=%s" % (i, r["isError"], r["content"][0]["text"][:260]))

p.stdin.close()
p.wait(timeout=30)
print("server 退出码:", p.returncode)
