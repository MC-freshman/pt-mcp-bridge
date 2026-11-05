"""端到端测 7 个新工具（走 pt_mcp.py 子进程，真调），最后清理掉自建对象。"""
import json
import os
import subprocess
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_mcp.py")
p = subprocess.Popen([sys.executable, P], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8")
rid = [0]


def call(name, args=None):
    rid[0] += 1
    msg = {"jsonrpc": "2.0", "id": rid[0], "method": "tools/call",
           "params": {"name": name, "arguments": args or {}}}
    p.stdin.write(json.dumps(msg) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    g = json.loads(line)
    r = g.get("result", {})
    txt = r.get("content", [{}])[0].get("text", "")
    return r.get("isError"), txt


p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": -1, "method": "initialize", "params": {}}) + "\n")
p.stdin.flush()
p.stdout.readline()
rid[0] = 0
print("tools 数:", len(json.loads(call.__doc__ or "{}") or {})) if False else None

err, txt = call("pt_sim_state")
print("pt_sim_state   :", err, txt[:150])

err, txt = call("pt_service_state", {"device": "Server0"})
print("pt_service_state:", err, txt[:260])

err, txt = call("pt_xml", {"device": "PC0"})
print("pt_xml         :", err, txt[:170])

print()
print("=== 建 + 连 + 移 + 删 ===")
err, txt = call("pt_add_device", {"type": "switch", "model": "2960-24TT", "x": 200, "y": 520})
print("add switch :", err, txt[:120])
sw = json.loads(txt).get("device") if not err else None

err, txt = call("pt_add_device", {"type": "pc", "model": "PC-PT", "x": 120, "y": 620})
print("add pc     :", err, txt[:120])
pc = json.loads(txt).get("device") if not err else None

if sw and pc:
    err, txt = call("pt_add_link", {"a_device": pc, "a_port": "FastEthernet0",
                                    "b_device": sw, "b_port": "FastEthernet0/1", "kind": "straight"})
    print("add link   :", err, txt[:120])
    err, txt = call("pt_move", {"device": pc, "x": 140, "y": 700})
    print("move       :", err, txt[:100])
    err, txt = call("pt_delete", {"kind": "link", "device": pc, "port": "FastEthernet0"})
    print("del link   :", err, txt[:100])
    err, txt = call("pt_delete", {"kind": "device", "device": pc})
    print("del device1:", err, txt[:100])
    err, txt = call("pt_delete", {"kind": "device", "device": sw})
    print("del device2:", err, txt[:100])

err, txt = call("pt_devices")
print()
print("收尾设备:", txt[:200])

p.stdin.close()
errout = p.stderr.read()
if errout.strip():
    print("stderr:", errout[:300])
p.wait(timeout=20)
print("退出码:", p.returncode)
