"""离线协议自测：instructions / tools / resources / prompts 全都要在。不碰 PT。"""
import json
import os
import subprocess
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_mcp.py")
p = subprocess.Popen([sys.executable, P], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8")

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
    {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "pt://guide"}},
    {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": "pt://api"}},
    {"jsonrpc": "2.0", "id": 6, "method": "prompts/list", "params": {}},
    {"jsonrpc": "2.0", "id": 7, "method": "prompts/get",
     "params": {"name": "pt-diagnose", "arguments": {"symptom": "拨号失败"}}},
    {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "pt_guide", "arguments": {}}},
]
for m in REQS:
    p.stdin.write(json.dumps(m) + "\n")
p.stdin.flush()
p.stdin.close()

got = {}
for _ in range(8):
    line = p.stdout.readline()
    if not line:
        break
    g = json.loads(line)
    got[g.get("id")] = g.get("result", g.get("error"))

r1 = got.get(1, {})
print("initialize  caps:", list(r1.get("capabilities", {})))
ins = r1.get("instructions", "")
print("instructions 长度:", len(ins), "| 前 60 字:", ins[:60].replace("\n", " "))
print("tools:", len(got.get(2, {}).get("tools", [])), [t["name"] for t in got.get(2, {}).get("tools", [])][:4], "...")
print("resources:", [x["uri"] for x in got.get(3, {}).get("resources", [])])
print("guide 资源长度:", len(got.get(4, {}).get("contents", [{}])[0].get("text", "")))
print("api   资源长度:", len(got.get(5, {}).get("contents", [{}])[0].get("text", "")))
print("prompts:", [x["name"] for x in got.get(6, {}).get("prompts", [])])
print("prompt 渲染前 70 字:", got.get(7, {}).get("messages", [{}])[0].get("content", {}).get("text", "")[:70].replace("\n", " "))
print("pt_guide 工具返回长度:", len(got.get(8, {}).get("content", [{}])[0].get("text", "")))
err = p.stderr.read()
print("stderr:", err[:200])
p.wait(timeout=15)
print("退出码:", p.returncode)
