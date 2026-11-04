"""pt-bridge MCP server v0.3 —— 加了 P0 的批量/快照/分型/进度通知。

传输：stdio，换行分隔 JSON-RPC 2.0，纯标准库。
通路：工具调用 -> pt_bridge/cmd.txt -> PT 桥模块求值 -> resp.txt -> 本服务回包。

P0 新增：
  pt_wiring   只读还原连线表（不碰任何设备 CLI，实验途中可安全调用）
  pt_script   一次调用喂一整段命令，内部逐条核对提示符层级，带 progress 通知
  pt_health   桥与 PT 进程健康检查，三种失效分开报
  错误分型    PRIVILEGE_DENIED / INVALID_ARGS / IPC_ERROR / TIMEOUT / NO_ECHO
  progress    尊重 tools/call 的 _meta.progressToken，长任务推进度，避免 agent 侧超时

注意：pt_script / pt_cli / pt_running_config 会往目标设备的 CLI 注字符。
      你正在 PT 里手敲那台设备时别调，会互相打断。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptctl
import ptplus

SERVER_INFO = {"name": "pt-bridge", "version": "0.4.0"}
PROTOCOL = "2024-11-05"

DEVICES_JS = ("(function(){var n=ipc.network(),a=[];"
              "for(var i=0;i<n.getDeviceCount();i++){var d=n.getDeviceAt(i);"
              "a.push(d.getName()+':'+d.getClassName())}return a.join(', ')})()")

TOOLS = [
    {"name": "pt_health",
     "description": "查桥和 PT 是否活着：模块心跳、PT 进程、以及最近一次失效属于哪一类。先调这个。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_status",
     "description": "看桥目录里各产物文件的字节数与内容片段（排查传输层用）。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_devices",
     "description": "列出当前拓扑的设备，格式 名称:类型。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_wiring",
     "description": "只读还原整张连线表：每台交换机挂了哪些端点、哪条是半截线、哪些链路不经过交换机。"
                    "不发任何 CLI 命令，实验途中可安全调用。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_cli",
     "description": "往指定设备 CLI 注一条命令，自动破 --More-- 分页，返回新增输出、结束时提示符和错误分型。"
                    "会占用那台设备的 CLI，别在你手敲它的时候调。",
     "inputSchema": {"type": "object",
                     "properties": {"device": {"type": "string"}, "command": {"type": "string"}},
                     "required": ["device", "command"], "additionalProperties": False}},
    {"name": "pt_script",
     "description": "一次调用把一整段 CLI 命令按顺序发完（内部逐条核对提示符层级、自动 enable、自动翻页），"
                    "只回一次汇总：总条数、被拒的哪几条、每条的最终提示符。"
                    "会占用该设备的 CLI，别在你手敲它的时候调。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "device": {"type": "string", "description": "如 Router0"},
                         "lines": {"type": "array", "items": {"type": "string"},
                                   "description": "按顺序的命令列表，不含首行 enable 也行，工具会自动补"},
                         "stop_on_reject": {"type": "boolean",
                                            "description": "true 时遇到第一条被拒就停"}},
                     "required": ["device", "lines"], "additionalProperties": False}},
    {"name": "pt_running_config",
     "description": "读某台设备整份 running-config（内部先确保 enable，再自动翻页）。",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}},
                     "required": ["device"], "additionalProperties": False}},
    {"name": "pt_eval",
     "description": "逃生舱：在 PT 脚本引擎里求值一段 ECMAScript（ES5，别用 let/箭头函数）。"
                    "能用上面专用工具就别用它——现编 JS 容易踩实测表里那些坑。"
                    "黑名单：AssessmentModel.getRunningConfig 会把 PT 崩掉。",
     "inputSchema": {"type": "object",
                     "properties": {"expression": {"type": "string"},
                                    "timeout_sec": {"type": "number"}},
                     "required": ["expression"], "additionalProperties": False}},
    {"name": "pt_command_log",
     "description": "读 PT 记录的命令条数（含脚本注入的），用来核对注入是否落地。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_aaa_state",
     "description": "读某台 Server 上 AAA(ACS) 服务的真实内容：是否启用、client 表（名称/IP/密钥/类型）、"
                    "user 表。以前误判成只能 GUI 手填的那块，实测可读。",
     "inputSchema": {"type": "object",
                     "properties": {"device": {"type": "string", "description": "如 Server0"}},
                     "required": ["device"], "additionalProperties": False}},
    {"name": "pt_processes",
     "description": "列某台设备装载了哪些协议进程（RoutingProcess、AcsServerProcess、"
                    "RadiusClientProcess、DhcpServerMainProcess 等）。只调 getProcess，不触发行为。",
     "inputSchema": {"type": "object",
                     "properties": {"device": {"type": "string"}},
                     "required": ["device"], "additionalProperties": False}},
]


def text_result(obj, is_error=False):
    return {"content": [{"type": "text",
                         "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=True)}],
            "isError": is_error}


def pt_pid():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-Process PacketTracer -ErrorAction SilentlyContinue | "
                              "Select-Object -ExpandProperty Id"],
                             capture_output=True, text=True, timeout=15).stdout.split()
        return out[0] if out else None
    except Exception:
        return None


def handle(name, args, notify):
    if name == "pt_health":
        import time
        alive = ptctl.read_raw(ptctl.ALIVE) if hasattr(ptctl, "ALIVE") else None
        p = pt_pid()
        probe = ptctl.send("1+1", 8.0)
        code = "OK" if probe.get("ok") else ptplus.classify(probe.get("error", ""),
                                                            timed_out=not probe.get("ok"))
        return text_result({"pt_process": p or "没开", "bridge_roundtrip": probe.get("ok", False),
                            "failure_class": code,
                            "hint": "OK 就能用；PRIVILEGE_DENIED 说明模块权限没落进 .pts；"
                                    "TIMEOUT 且 pt_process 变了说明 PT 重启过、模块没再 Start"})

    if name == "pt_status":
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            ptctl.do_status()
        finally:
            sys.stdout = old
        return text_result(buf.getvalue())

    if name == "pt_devices":
        r = ptctl.send(DEVICES_JS, 15.0)
        return text_result(r, not r.get("ok", False))

    if name == "pt_wiring":
        r = ptctl.send(ptplus.WIRING_JS, 20.0)
        if not r.get("ok"):
            return text_result(r, True)
        parsed = ptplus.parse_wiring(r.get("result"))
        return text_result(parsed, not parsed.get("ok", False))

    if name == "pt_cli":
        res = ptctl.cli_run(args["device"], args["command"])
        if not res.get("ok"):
            res["failure_class"] = ptplus.classify(res.get("error", ""))
        return text_result(res, not res.get("ok", False))

    if name == "pt_script":
        dev = args["device"]
        lines = list(args["lines"])
        if not lines[0].startswith("enable"):
            lines = ["enable"] + lines
        total = len(lines)
        steps, stopped = [], False
        for i, c in enumerate(lines):
            notify(i + 1, total, "%s: %s" % (dev, c))
            r = ptctl.cli_run(dev, c)
            steps.append({"cmd": c, "prompt": r.get("prompt"), "added": r.get("added"),
                          "ok": r.get("ok")})
            if not r.get("ok"):
                steps[-1]["failure_class"] = ptplus.classify(r.get("error", ""),
                                                             timed_out=not r.get("ok"))
                if args.get("stop_on_reject"):
                    stopped = True
                    break
            blob = r.get("added") or ""
            if any(k in blob for k in ptplus.REJECT_MARKS) and args.get("stop_on_reject"):
                stopped = True
                break
        summary = ptplus.parse_script_result(lines, steps)
        summary["stopped_early"] = stopped
        return text_result(summary, not summary.get("ok", False))

    if name == "pt_running_config":
        dev = args["device"]
        st = ptctl.cli_read(dev)
        if st and st.get("mode") != "enable":
            ptctl.cli_run(dev, "enable")
        res = ptctl.cli_run(dev, "show running-config")
        if not res.get("ok"):
            res["failure_class"] = ptplus.classify(res.get("error", ""))
        return text_result(res, not res.get("ok", False))

    if name == "pt_eval":
        r = ptctl.send(ptctl.js_expr(args["expression"]),
                       float(args.get("timeout_sec", 15)))
        if not r.get("ok"):
            r["failure_class"] = ptplus.classify(r.get("error", ""), timed_out=not r.get("ok"))
        return text_result(r, not r.get("ok", False))

    if name == "pt_command_log":
        r = ptctl.send("String(ipc.commandLog().getEntryCount())", 15.0)
        return text_result(r, not r.get("ok", False))

    if name == "pt_aaa_state":
        r = ptctl.send(ptplus.aaa_state_js(args["device"]), 20.0)
        if not r.get("ok"):
            r["failure_class"] = ptplus.classify(r.get("error", ""), timed_out=True)
            return text_result(r, True)
        raw = r.get("result")
        if raw == "NO_PROCESS":
            return text_result({"ok": False, "error": "%s 上没有 AcsServerProcess（不是服务器或型号不对）"
                                          % args["device"]}, True)
        try:
            d = json.loads(raw)
        except Exception:
            return text_result({"ok": False, "raw": str(raw)[:300]}, True)
        def split(v):
            if isinstance(v, list):
                return v
            return [x for x in str(v).split(",") if x]
        return text_result({"ok": True, "device": args["device"], "enabled": d.get("enabled"),
                            "clients": split(d.get("clients")), "users": split(d.get("users"))})

    if name == "pt_processes":
        r = ptctl.send(ptplus.processes_js(args["device"]), 60.0)
        if not r.get("ok"):
            r["failure_class"] = ptplus.classify(r.get("error", ""), timed_out=True)
            return text_result(r, True)
        got = [x for x in str(r.get("result", "")).split(",") if x]
        if got == ["NO_DEVICE"]:
            return text_result({"ok": False, "error": "设备不存在: %s" % args["device"]}, True)
        return text_result({"ok": True, "device": args["device"], "processes": got,
                            "count": len(got)})

    return text_result("unknown tool: " + str(name), True)


def reply(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main():
    token = None

    def notify(progress, total, message):
        if token is None:
            return
        reply({"jsonrpc": "2.0", "method": "notifications/progress",
               "params": {"progressToken": token, "progress": progress,
                          "total": total, "message": message}})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            reply({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO}})
        elif method == "ping":
            reply({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "tools/list":
            reply({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            meta = params.get("_meta") or {}
            token = meta.get("progressToken")
            res = handle(params.get("name"), params.get("arguments") or {}, notify)
            token = None
            reply({"jsonrpc": "2.0", "id": mid, "result": res})
        elif mid is not None and method is not None:
            reply({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    main()
