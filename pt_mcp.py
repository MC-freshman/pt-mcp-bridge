"""pt-bridge MCP server v0.5.1 —— 服务读写打通、四个假阴性读通道入档、桥目录自动创建。

设计意图：**新会话的模型不该靠试错才知道这个 MCP 能干什么**。
  initialize.instructions  客户端通常会转成系统提示，是"开场就知道"的主通道
  resources                pt://guide（能力与坑）、pt://api（调用速查）、pt://live（实时快照）
  prompts                  三条现成工作流：建图 / 验收 / 排障
  pt_guide 工具            兜底：客户端不转发 instructions 或 resources 时，直接调它拿全文

传输：stdio，换行分隔 JSON-RPC 2.0，纯标准库。
通路：工具调用 -> pt_bridge/cmd.txt -> PT 桥模块求值 -> resp.txt -> 本服务回包。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptctl
import ptplus

SERVER_INFO = {"name": "pt-bridge", "version": "0.5.1"}
PROTOCOL = "2024-11-05"
CAPS = {"tools": {}, "resources": {}, "prompts": {}}

# ---------------------------------------------------------------- instructions
INSTRUCTIONS = """\
你在操作一台真实的 Cisco Packet Tracer 8.0（不是模拟器、不是只读快照）。这个 MCP 桥能**读也能写**该软件内部状态。

## 先决条件（每次都先确认）
PT 必须处于运行状态、且桥模块已 Start。任何调用报 TIMEOUT 就先调 `pt_health`：
  - pt_process="没开" → 让用户打开 Packet Tracer
  - 有 PID 但 TIMEOUT → 让用户在 Extensions→Scripting→Configure Script Modules 里点 Start
  - failure_class=PRIVILEGE_DENIED → 模块权限没落进 .pts，重走 Save→Export→Remove+Add

## 工具速查
读：  pt_devices(设备清单) · pt_wiring(连线表，只读安全) · pt_processes(协议进程)
      pt_running_config(整份配置) · pt_aaa_state(AAA 用户/client 表) · pt_command_log(命令计数)
写：  pt_cli(单条 IOS 命令) · pt_script(一整段命令，自动 enable/翻页，一次回汇总)
万能：pt_eval(求值任意 ECMAScript，用于放设备/连线/改名/改位置/取图等 IPC 调用)

## 三条最常用的 IPC 一行式（细节调 pt://api 或 pt_guide）
放设备+连线： lw.addDevice(0,"1841",x,y) → 返回名；lw.createLink(名,口,名,口,8100)
型号串来源：   ipc.appWindow().getNetworkComponentBox().getDeviceModels("Routers")
配 DHCP 作用域：getProcess("DhcpServerMainProcess").getDhcpServerProcessByPortName("FastEthernet0")
                .getPoolAt(0) 再 setStartIp/setMaxUsers/setDefaultRouter/setDnsServerIp，最后 sp.setEnable(true)

## 最容易踩的坑（都实测过）
1. 枚举必须传**数字**，传字符串一律返回 false 且不报错：
   CONNECT_TYPES 从 **8100** 起（ETHERNET_STRAIGHT=8100, CROSS=8101, AUTO=8107）
   DeviceType：eRouter=0 eSwitch=1 ePc=8 eServer=9 eDslModem=13
2. **型号串别凭名字猜**：先调 `ipc.appWindow().getNetworkComponentBox().getDeviceModels("Routers")`
   拿合法串（`1841/2911/ISR4331/Router-PT…`）。而 `getDeviceTypes()` 的**数组下标不是 addDevice 的第一参**——
   `addDevice(5,"PC-PT")` 返回空串不报错，必须用 ePc=8。
3. `deleteLink(设备, 口)` **只给一端**；给四段会 Invalid arguments。
4. `AssessmentModel.getRunningConfig` **会把 PT 弄崩**，绝不调用；读配置用 pt_running_config。
5. 写本机文件只有 `writePlainTextToFile(path,text)` 两参是干净的，别试别的签名。
6. 设备断电会**清空 running-config**（1841 实测），任何 setPower(false) 之前必须让用户先 Ctrl+S。
7. 新设备开机停在 `Would you like to enter the initial configuration dialog? [yes/no]:`。
   `no` 必须等这句真出现在 prompt 里再发；发早了后面**整段配置全被当回答吞掉**，
   而且每条都"成功"、提示符一直停在那句问话上——只能删设备重放。
8. **读数通道会骗你，"读不到"不等于"没配好"**（三条都造成过误判）：
   `HttpServer.getPage()` 返回内置模板，不反映用户编辑过的 index.html；
   `DnsServerProcess.getIpAddOfDomain()` 读缓存恒 0.0.0.0，记录要用 `getRrFromNameServerDbAt(0)` 读；
   `DhcpPool.getLeaseAt()` 的簿记与客户端实际采纳的地址不对齐。
   断言失败前先换一个独立通道，最好是应用自己的输出（浏览器、界面面板）。

## 它做不到（必须请用户手点，别绕圈子）
- **保存 .pkt**：官方 API 没有读写工程的接口 → 提醒用户 Ctrl+S
- **插硬件模块**：该型号槽位没通过 IPC 暴露 → 让用户在 Physical 页断电插模块再通电
- **DNS 加资源记录**：`DnsServerProcess` 只有 `setEnable` 可写 → Services→DNS 面板手填后点 Add
- **改 Web 页面正文**：`HttpServer` 只有 `getPage` 没有 `setPage` → Services→HTTP→index.html 的 (edit) 手改
- **让 PC 真的发 DHCP 请求**：`setDhcpClientFlag(true)` 只改标志，不发 Discover → GUI 点 Static→DHCP
- **清 CLI 缓冲区**：`TerminalLine` 没有清屏方法 → 只能 removeDevice + addDevice 重放
- 其余（放设备、连线、删线、改名、改位置、配 IP、IOS 配置、配 DHCP 作用域、开关服务、取拓扑图）都能编程完成

## 工作方式
用户说"配好/搭好/验一下"时：先用只读工具摸清现状（pt_devices + pt_wiring + pt_processes），
再写（pt_script 批量发命令），最后用 `pt_running_config` / `pt_cli show ip route` / ping 自证。
写入类工具会占用目标设备的 CLI，用户正在手敲那台时先问一句。
"""

# ---------------------------------------------------------------- resources
def _p_api():
    return """\
# Packet Tracer IPC 调用速查（实测）

## 拓扑
lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()
lw.addDevice(DeviceType, 型号串, x, y)      -> 新设备名
lw.removeDevice(名)
lw.createLink(设备A, 口A, 设备B, 口B, CONNECT_TYPES)
lw.deleteLink(设备, 口)                     // 只给一端
lw.getWorkspaceImage("PNG")                 -> vector<byte>（有符号，编码时 &255）
lw.addNote(x, y, layer, text)               -> uuid ; lw.changeNoteText(uuid, text)

## 设备 / 端口 / 模块
d.setName(名) d.getName() d.getPower() d.setPower(bool)
d.moveToLocation(x,y) d.moveToLocationCentered(x,y) d.getXCoordinate() d.getYCoordinate()
d.getPortCount() d.getPortAt(i) d.getPort(口名) d.getPorts() d.getSupportedModule()
d.getRootModule() -> Module: getModuleCount/getModuleAt/getSlotPath/getModuleType
d.addModule(slot, ModuleType, model)        // 1841 槽位未暴露，实测 false
p.setIpSubnetMask(ip,mask) p.setDefaultGateway(gw) p.setDnsServerIp(ip)
p.setDhcpClientFlag(bool) p.getName() p.getLink() p.getIpAddress()

## CLI / 服务
d.getConsoleLine() -> tl.enterCommand(cmd) / tl.getOutput() / tl.getPrompt() / tl.getMode()
d.enterCommand(cmd, true)                   // 设备级必须双参
d.getProcess("AcsServerProcess") ->
   isEnabled / getClientRecordsAsString / getUserRecordsAsString
   enableACSServerService / addToClientMap / addToUserMap
   deleteFromClientMap / deleteFromUserMap / removeAllUserRecords / removeAllClientRecords
ipc.commandLog().getEntryCount()   ipc.simulation().isSimulationMode()
ipc.systemFileManager() -> writePlainTextToFile(path,text) / getFileContents(path)

## 服务读写（11-04 钓鱼实验实测）
nb = ipc.appWindow().getNetworkComponentBox()
   -> getDeviceTypes()            17 个类别名（Routers/Switches/End Devices…）
   -> getDeviceModels("Routers")  该类别的合法型号串，别猜
   -> getConnectionTypes()        线型显示名
sp = d.getProcess("DhcpServerMainProcess").getDhcpServerProcessByPortName("FastEthernet0")
   sp.getPoolCount() / sp.getPoolAt(0)      // getPool("口名") 返回 null，只有 getPoolAt(0) 有池
   pool.setStartIp(ip) / setMaxUsers(n) / setDefaultRouter(gw) / setDnsServerIp(ip)
   // 没有 setSubnetMask；改 maxUsers 后 getEndIp() 会自己跟着变
   sp.setEnable(true) / sp.isEnable()
dns = d.getProcess("DnsServerProcess")
   -> setEnable(bool) / isEnabled() / getSizeOfNameServerDb()   // 记录条数看这个
   -> getRrFromNameServerDbAt(0) 得 data 对象：.name .ipAddress .pduType .ttl
   // 加 A 记录没有写接口，只能 GUI；getIpAddOfDomain() 读的是缓存，恒 0.0.0.0
http = d.getProcess("HttpServer")
   -> setEnable(bool) / isEnabled() / getPortNumber() / getPage("index.html")
   // getPage 返回内置模板，不反映用户在界面改过的页面；改正文只能 GUI

## 枚举
DeviceType: eRouter=0 eSwitch=1 eCloud=2 eBridge=3 eHub=4 eRepeater=5 eAccessPoint=7
  ePc=8 eServer=9 ePrinter=10 eWirelessRouter=11 eIpPhone=12 eDslModem=13 eCableModem=14
  eRemoteNetwork=15 eMultiLayerSwitch=16 eSwitch3650=17 eLaptop=18 eTabletPC=19 ePda=20
  eTV=23 eASA=27 eIoE=28 eCellTower=31 eWirelessLanController=41 eLightWeightAccessPoint=44
CONNECT_TYPES: ETHERNET_STRAIGHT=8100 ETHERNET_CROSS=8101 ETHERNET_ROLL=8102 FIBER=8103
  PHONE=8104 CABLE=8105 SERIAL=8106 AUTO=8107 CONSOLE=8108 WIRELESS=8109 COAXIAL=8110
ModuleType: eLineCard=0 eNetworkModule=1 eInterfaceCard=2 ePtRouterModule=3 eUSB=17

## 已知崩溃项
AssessmentModel.getRunningConfig —— 会让 PT 进程消失。用 CLI 读配置替代。
"""


def _p_live():
    """实时快照：设备数 / 链路数 / 前三台设备端口 / AAA 摘要。"""
    js = ("(function(){var n=ipc.network(),o={};"
          "o.devices=n.getDeviceCount();o.links=n.getLinkCount();"
          "var a=[];for(var i=0;i<n.getDeviceCount()&&i<6;i++){var d=n.getDeviceAt(i);"
          "var pc=0;try{pc=d.getPortCount()}catch(e){}a.push(d.getName()+'('+d.getClassName()+','+pc+'口)')}"
          "o.sample=a.join(', ');"
          "try{var s=n.getDevice('Server0');if(s){var p=s.getProcess('AcsServerProcess');"
          "if(p)o.aaa={enabled:String(p.isEnabled()),clients:String(p.getClientRecordsAsString())}}}catch(e){}"
          "return JSON.stringify(o)})()")
    r = ptctl.send(js, 25.0)
    if not r.get("ok"):
        return "# 实时快照取不到\n\n%s\n\n先调 `pt_health` 确认 PT 与桥模块状态。" % json.dumps(r, ensure_ascii=False)
    try:
        return "# 实时快照\n\n```json\n%s\n```\n" % json.dumps(json.loads(r["result"]),
                                                              ensure_ascii=True, indent=2)
    except Exception:
        return "# 实时快照\n\n%s" % str(r.get("result"))[:1500]


RESOURCES = [
    {"uri": "pt://guide", "name": "能力与坑（必读）", "mimeType": "text/markdown",
     "description": "这个 MCP 能做什么、做不到什么、必踩的坑、工作方式"},
    {"uri": "pt://api", "name": "IPC 调用速查", "mimeType": "text/markdown",
     "description": "拓扑/设备/端口/CLI/AAA 的实测可用调用与三组枚举值"},
    {"uri": "pt://live", "name": "实时快照", "mimeType": "text/markdown",
     "description": "当前 PT 的设备数、链路数、样例设备与 AAA 摘要（每次读取都重新采集）"},
]

PROMPTS = [
    {"name": "pt-build-topology",
     "description": "按描述在 PT 里放设备、连线、配 IP 与 IOS 配置，并自证结果",
     "arguments": [{"name": "requirement", "description": "要搭的网络，例如 两台PC接一台交换机再连1841",
                    "required": True}]},
    {"name": "pt-verify-lab",
     "description": "对现有拓扑做验收：读配置、看路由表、ping 关键地址、给逐项结论",
     "arguments": [{"name": "focus", "description": "关注点，例如 AAA 拨号认证 / RIP 收敛",
                    "required": False}]},
    {"name": "pt-diagnose",
     "description": "实验不通时的分诊：先 pt_health，再读配置与链路，给出根因假设与验证命令",
     "arguments": [{"name": "symptom", "description": "现象，例如 拨号失败 / ping 不通",
                    "required": True}]},
]

TOOLS = [
    {"name": "pt_guide",
     "description": "返回本 MCP 的能力说明、工具速查、必踩的坑、以及它做不到只能人手点的几件事。"
                    "新会话第一件事就该调它（或在客户端里直接读资源 pt://guide）。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_health",
     "description": "查桥和 PT 是否活着：模块心跳、PT 进程、以及最近一次失效属于哪一类"
                    "（TIMEOUT+没进程=PT没开；TIMEOUT+有PID=模块没Start；PRIVILEGE_DENIED=权限没落盘）。",
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
    {"name": "pt_processes",
     "description": "列某台设备装载了哪些协议进程（RoutingProcess、AcsServerProcess、"
                    "RadiusClientProcess、DhcpServerMainProcess 等）。只调 getProcess，不触发行为。",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}},
                     "required": ["device"], "additionalProperties": False}},
    {"name": "pt_aaa_state",
     "description": "读某台 Server 上 AAA(ACS) 服务的真实内容：是否启用、client 表（名称/IP/密钥/类型）、"
                    "user 表。以前误判成只能 GUI 手填的那块，实测可读。",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}},
                     "required": ["device"], "additionalProperties": False}},
    {"name": "pt_command_log",
     "description": "读 PT 记录的命令条数（含脚本注入的），用来核对注入是否落地。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "pt_cli",
     "description": "往指定设备 CLI 注一条命令，自动破 --More-- 分页，返回新增输出、结束时提示符和错误分型。"
                    "会占用那台设备的 CLI，别在你手敲它的时候调。模式切换（enable / configure terminal）也用它逐条发。",
     "inputSchema": {"type": "object",
                     "properties": {"device": {"type": "string"}, "command": {"type": "string"}},
                     "required": ["device", "command"], "additionalProperties": False}},
    {"name": "pt_script",
     "description": "一次调用把一整段 CLI 命令按顺序发完（内部逐条核对提示符层级、自动 enable、自动翻页），"
                    "只回一次汇总：总条数、被拒的哪几条、每条的最终提示符。"
                    "配整台路由器/交换机的首选工具；会占用该设备 CLI。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "device": {"type": "string", "description": "如 Router0"},
                         "lines": {"type": "array", "items": {"type": "string"},
                                   "description": "按顺序的命令列表，不含首行 enable 也行"},
                         "stop_on_reject": {"type": "boolean",
                                            "description": "true 时遇到第一条被拒就停"}},
                     "required": ["device", "lines"], "additionalProperties": False}},
    {"name": "pt_running_config",
     "description": "读某台设备整份 running-config（内部先确保 enable，再自动翻页）。",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}},
                     "required": ["device"], "additionalProperties": False}},
    {"name": "pt_eval",
     "description": "逃生舱：在 PT 脚本引擎里求值一段 ECMAScript（ES5，别用 let/箭头函数）。"
                    "放设备/连线/删线/改名/改位置/取拓扑图都走它；具体调用与枚举值见资源 pt://api 或 pt_guide。"
                    "黑名单：AssessmentModel.getRunningConfig 会把 PT 崩掉。",
     "inputSchema": {"type": "object",
                     "properties": {"expression": {"type": "string"},
                                    "timeout_sec": {"type": "number"}},
                     "required": ["expression"], "additionalProperties": False}},
]

DEVICES_JS = ("(function(){var n=ipc.network(),a=[];"
              "for(var i=0;i<n.getDeviceCount();i++){var d=n.getDeviceAt(i);"
              "a.push(d.getName()+':'+d.getClassName())}return a.join(', ')})()")


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
    if name == "pt_guide":
        return text_result(INSTRUCTIONS)

    if name == "pt_health":
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
                          "ok": r.get("ok"), "echoed": r.get("echoed")})
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
            return v if isinstance(v, list) else [x for x in str(v).split(",") if x]
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

    if name == "pt_eval":
        r = ptctl.send(ptctl.js_expr(args["expression"]),
                       float(args.get("timeout_sec", 15)))
        if not r.get("ok"):
            r["failure_class"] = ptplus.classify(r.get("error", ""), timed_out=not r.get("ok"))
        return text_result(r, not r.get("ok", False))

    if name == "pt_command_log":
        r = ptctl.send("String(ipc.commandLog().getEntryCount())", 15.0)
        return text_result(r, not r.get("ok", False))

    return text_result("unknown tool: " + str(name), True)


def prompt_get(name, args):
    req = (args or {}).get("requirement") or (args or {}).get("symptom") or ""
    focus = (args or {}).get("focus") or ""
    if name == "pt-build-topology":
        body = ("在已打开的 Packet Tracer 里搭建：%s\n\n"
                "步骤：1) pt_health 确认桥可用；2) pt_devices + pt_wiring 看现状，别覆盖已有拓扑；"
                "3) 型号串先向 NetworkComponentBox.getDeviceModels(\"Routers\"/\"Switches\"/\"End Devices\") 取，"
                "别凭名字猜；addDevice 第一参是 DeviceType 枚举（eRouter=0 eSwitch=1 ePc=8 eServer=9），"
                "**不是 getDeviceTypes() 的数组下标**；连线用 createLink(设备,口,设备,口,8100)，"
                "CONNECT_TYPES 从 8100 起、必须传数字，传字符串一律 false 且不报错；"
                "4) 新设备开机停在 initial configuration dialog，**等这句真出现在 prompt 里再答 no**，"
                "发早了后面整段配置会被当回答吞掉且每条都显示成功；放 1841 会附带一台 "
                "Power Distribution Device，删它不牵连路由器；"
                "5) IP 走 port.setIpSubnetMask/setDefaultGateway，IOS 走 pt_script 一次喂完；"
                "服务配置里 DHCP 作用域用 getPoolAt(0)（getPool(口名) 返回 null）+ 四个 setter + setEnable(true)；"
                "6) 以下只能用户手点，别绕圈子试：DNS 加 A 记录、改 Web 页面正文、让 PC 真的发 DHCP 请求、"
                "清 CLI 缓冲区、插硬件模块、保存 .pkt（提醒用户 Ctrl+S）；"
                "7) 往某台设备注命令前先问一句用户是否正在手敲那台；"
                "8) 用 pt_running_config / show ip route / ping 自证，并交一份逐设备命令台账，"
                "把\"我注的 / 应用自己打的 / 用户手点的\"分开列。" % req)
    elif name == "pt-verify-lab":
        body = ("验收当前拓扑%s。逐项给结论，每条都要有读回来的证据：\n"
                "1) pt_wiring 检查半截线与分段；2) pt_running_config 核关键配置；"
                "3) show ip route 对照预期；4) ping 关键地址（首包常因 ARP 掉到 60%%~80%%，"
                "重打一次再下结论）；5) 涉及 AAA 用 pt_aaa_state 核 client/user 表。\n"
                "⚠️ 四个读数通道会造成假阴性，别拿它们断言\"没配上\"："
                "HttpServer.getPage() 返回内置模板、不反映用户编辑过的页面；"
                "DnsServerProcess.getIpAddOfDomain() 读缓存恒 0.0.0.0，记录要用 getRrFromNameServerDbAt(0) 读、"
                "条数看 getSizeOfNameServerDb()；DhcpPool.getLeaseAt() 的簿记与客户端实际采纳的地址不对齐；"
                "dev.getHostName() 是型号默认名不是 IOS hostname。"
                "要下\"失败\"结论必须换一个独立通道——最好是应用自己的输出（面板、浏览器、PT 的 logs\\*.log）。"
                % ("（关注点：%s）" % focus if focus else ""))
    elif name == "pt-diagnose":
        body = ("现象：%s\n\n先按通道分诊，再按网络分诊：\n"
                "A) 工具报 Not Found 但 pt_health 有 PID → 是 MCP server 掉了、PT 还活着，"
                "改走 python ptctl.py js \"<ES5>\" 文件通道，能力等价；"
                "B) TIMEOUT 且 pt_process=\"没开\" → 让用户开 PT；有 PID 但 TIMEOUT → 让用户在 "
                "Configure Script Modules 点 Start；PRIVILEGE_DENIED → 重走 Save→Export→Remove+Add；"
                "C) ptctl 报 PermissionError cmd.txt.tmp → 桥目录被并发读走，等几秒重试，不是逻辑错；"
                "D) 调用\"不抛错但返回 false/空串\" → 九成是枚举值或参数顺序不对，不是 API 不支持，"
                "先查 pt://api 的三组枚举；"
                "E) 通道正常后再走 pt_wiring（链路）→ pt_running_config（配置）→ show ip route / ping（转发）"
                "→ 认证类用 pt_aaa_state 比对两端密钥与 client 表。\n"
                "⚠️ 任何 setPower(false) 之前先让用户 Ctrl+S——断电会清空 running-config。"
                "给出根因假设 + 一条能证伪的命令。" % req)
    else:
        body = "未知提示词：" + str(name)
    return {"description": "pt-bridge 工作流", "messages": [
        {"role": "user", "content": {"type": "text", "text": body}}]}


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
                "capabilities": CAPS,
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS}})
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
        elif method == "resources/list":
            reply({"jsonrpc": "2.0", "id": mid, "result": {"resources": RESOURCES}})
        elif method == "resources/read":
            uri = params.get("uri")
            if uri == "pt://guide":
                body = INSTRUCTIONS
            elif uri == "pt://api":
                body = _p_api()
            elif uri == "pt://live":
                body = _p_live()
            else:
                reply({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32602, "message": "unknown resource: %s" % uri}})
                continue
            reply({"jsonrpc": "2.0", "id": mid,
                   "result": {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": body}]}})
        elif method == "prompts/list":
            reply({"jsonrpc": "2.0", "id": mid, "result": {"prompts": PROMPTS}})
        elif method == "prompts/get":
            reply({"jsonrpc": "2.0", "id": mid,
                   "result": prompt_get(params.get("name"), params.get("arguments"))})
        elif mid is not None and method is not None:
            reply({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    main()
