"""离线自测：不向 PT 发任何命令。只测纯逻辑 + JSON-RPC 握手 + tools/list。"""
import json
import subprocess
import sys

sys.path.insert(0, r"C:\Users\wk\pt_bridge")
import ptplus

print("== classify 五分类 ==")
cases = [
    ('IPC Call ERROR: IPC - does not have the necessary privilege for IPC call "network"', None, "PRIVILEGE_DENIED"),
    ('IPC Call ERROR: Router - Invalid arguments for IPC call "enterCommand"', None, "INVALID_ARGS"),
    ('IPC Call ERROR: LogicalWorkspace - something else', None, "IPC_ERROR"),
    ('超时无回包', True, "TIMEOUT"),
    ('', False, False, "NO_ECHO"),
]
print("  privilege ->", ptplus.classify(cases[0][0]))
print("  invalidargs ->", ptplus.classify(cases[1][0]))
print("  ipcerror ->", ptplus.classify(cases[2][0]))
print("  timeout ->", ptplus.classify(cases[3][0], timed_out=True))
print("  noecho ->", ptplus.classify("", echoed=False))

print()
print("== parse_wiring（用今天真实读到的那张表当输入）==")
raw = ("links=4;Router0:FastEthernet0/0|Switch6:FastEthernet0/2;"
       "PC3:FastEthernet0|Switch3:FastEthernet0/1;"
       "Switch0:FastEthernet0/4;"
       "PC0:FastEthernet0|DSL Modem0:Port 1")
p = ptplus.parse_wiring(raw)
print("  links=", p["links"])
print("  segments=", json.dumps(p["segments"], ensure_ascii=False))
print("  dangling(半截线)=", p["dangling"])
print("  不经交换机的线=", p["non_switch_links"])

print()
print("== parse_script_result ==")
steps = [
    {"cmd": "enable", "prompt": "router1#", "added": "enable\nrouter1#", "ok": True},
    {"cmd": "configure terminal", "prompt": "router1#", "added": "% Invalid input detected", "ok": True},
]
s = ptplus.parse_script_result(["enable", "configure terminal"], steps)
print("  ok=", s["ok"], "被拒=", s["rejected"], "总=", s["total"])

print()
print("== check_expect ==")
cfg = "hostname router0\nradius-server key key0\nip local pool a1 192.168.1.1 192.168.1.14\n"
print("  满足:", json.dumps(ptplus.check_expect(cfg, ["hostname router0", "key0"], ["key router0"])))
print("  缺项:", json.dumps(ptplus.check_expect(cfg, ["vpdn enable"], [])))

print()
print("== MCP 握手 + tools/list（不碰 PT）==")
proc = subprocess.Popen([sys.executable, r"C:\Users\wk\pt_bridge\pt_mcp.py"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8")
for m in [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
          {"jsonrpc": "2.0", "method": "notifications/initialized"},
          {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]:
    proc.stdin.write(json.dumps(m) + "\n")
proc.stdin.flush()
proc.stdin.close()
for _ in range(2):
    line = proc.stdout.readline()
    if not line:
        break
    g = json.loads(line)
    if g.get("id") == 1:
        print("  server:", g["result"]["serverInfo"], "caps:", list(g["result"]["capabilities"]))
    else:
        print("  tools:", [t["name"] for t in g["result"]["tools"]])
err = proc.stderr.read()
if err.strip():
    print("  stderr:", err[:300])
proc.wait(timeout=15)
print("  退出码:", proc.returncode)
