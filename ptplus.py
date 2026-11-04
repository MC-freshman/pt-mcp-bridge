"""P0 新增能力（纯 Python 侧，不改桥模块、不需要重启模块）。

被 ptctl.py / pt_mcp.py 复用。所有函数都只做两件事：拼一段只读 JS、解析回包。
"""
import json
import re

# ---------- 错误分型：五种失效分开报，别再混着猜 ----------
CODES = [
    ("PRIVILEGE_DENIED", "privilege for IPC call"),
    ("INVALID_ARGS", "Invalid arguments for IPC call"),
    ("HOST_GONE", None),          # 由调用方用进程检查判定
    ("TIMEOUT", "超时"),
    ("NO_ECHO", None),            # 由回显比对判定
]


def classify(err_text, timed_out=False, echoed=None):
    """把一次失败归到五类之一。err_text 是 PT 返回的错误串或空。"""
    s = str(err_text or "")
    if "privilege" in s:
        return "PRIVILEGE_DENIED"
    if "Invalid arguments" in s:
        return "INVALID_ARGS"
    if "IPC Call ERROR" in s:
        return "IPC_ERROR"
    if timed_out or "超时" in s:
        return "TIMEOUT"
    if echoed is False:
        return "NO_ECHO"
    if not s:
        return "UNKNOWN"
    return s[:80]


# ---------- 连线快照：按 link 的 uuid 还原整张表（只读，不碰任何 CLI）----------
WIRING_JS = (
    "(function(){var n=ipc.network(),g={},order=[];"
    "for(var i=0;i<n.getDeviceCount();i++){var d=n.getDeviceAt(i),pc=0;"
    "try{pc=d.getPortCount()}catch(e){continue}"
    "for(var j=0;j<pc;j++){var p;try{p=d.getPortAt(j)}catch(e2){continue}"
    "var L;try{L=p.getLink()}catch(e3){continue}if(!L)continue;"
    "var u;try{u=String(L.getObjectUuid())}catch(e4){continue}"
    "if(!g[u]){g[u]=[];order.push(u)}"
    "g[u].push(d.getName()+':'+p.getName())}}"
    "var out=[];for(var k=0;k<order.length;k++){out.push(g[order[k]].join('|'))}"
    "return 'links='+order.length+';'+out.join(';')})()"
)


def parse_wiring(raw):
    """把 WIRING_JS 的返回解析成 {links, pairs, segments, dangling, orphan_switches}"""
    s = str(raw or "")
    m = re.match(r"links=(\d+);(.*)$", s, re.S)
    if not m:
        return {"ok": False, "error": "PARSE_FAIL", "raw": s[:120]}
    links = int(m.group(1))
    pairs = []
    for chunk in m.group(2).split(";"):
        if not chunk:
            continue
        ends = [x for x in chunk.split("|") if x]
        pairs.append(ends)
    seg, dangling, no_switch = {}, [], []
    for ends in pairs:
        if len(ends) != 2:
            dangling.append(ends)          # 只有端点数不足 2 才算半截线
            continue
        sw = None
        for e in ends:
            if e.split(":")[0].startswith("Switch"):
                sw = e.split(":")[0]
        if sw is None:
            no_switch.append(ends)         # 两端齐全但不经过交换机（PC-Modem-Cloud 这类）
            continue
        seg.setdefault(sw, [])
        for e in ends:
            if not e.split(":")[0].startswith("Switch"):
                seg[sw].append(e)
    return {"ok": True, "links": links, "segments": seg, "dangling": dangling,
            "non_switch_links": no_switch}


# ---------- 批量配置：一次调用喂一整段，逐条核对提示符层级 ----------
NEST = {
    "enable": r"^[A-Za-z0-9_.\-]+#\s*$",
    "configure terminal": r"^[A-Za-z0-9_.\-]+\(config\)#\s*$",
}
REJECT_MARKS = ("Invalid input", "Incomplete", "Unknown command", "Translating")


def parse_script_result(lines, steps):
    """steps: [{cmd, prompt, added, ok}] -> 汇总（哪条被拒、最终层级对不对）"""
    out, rejected = [], []
    for st in steps:
        blob = st.get("added") or ""
        bad = any(k in blob for k in REJECT_MARKS)
        out.append({"cmd": st["cmd"], "prompt": st.get("prompt"), "rejected": bad,
                    "echo": blob.replace("\n", " | ")[:90]})
        if bad:
            rejected.append(st["cmd"])
    return {"ok": not rejected, "total": len(lines), "rejected": rejected, "steps": out}


# ---------- AAA Server：实测可达的读写口（以前误判成 GUI-only）----------
AAA_JS = ("(function(){var p=ipc.network().getDevice(%s).getProcess('AcsServerProcess');"
          "if(!p)return 'NO_PROCESS';"
          "return JSON.stringify({enabled:p.isEnabled(),clients:p.getClientRecordsAsString(),"
          "users:p.getUserRecordsAsString()})})()")


def aaa_state_js(device):
    return AAA_JS % json.dumps(device)


# ---------- 每台设备装了哪些进程（只调 getProcess，不触发任何行为）----------
# 进程名全集：从 exe 串表里所有 *Process 字面量抽出（112 个），本仓库 tools/ipc_map.py 可重新生成
PROC_NAMES = [
    "Aclv6Process", "AcsServerProcess", "AnalogPhoneProcess", "AsaAclProcess", "AsaAclv6Process",
    "AsaFwProcess", "AsaNatProcess", "AsaNatv6Process", "BnepProcess", "CBridgeProcess",
    "CCMEProcess", "CDhcpSnoopingProcess", "CapwapAcProcess", "CapwapProcess", "CbacProcess",
    "ChapProcess", "CsmaCaProcess", "CsmaCdProcess", "CustomBluetoothProcess", "CustomTcpProcess",
    "CustomUdpProcess", "DNSResolverProcess", "DhcpClientProcess", "DhcpServerMainProcess",
    "DhcpServerProcess", "Dhcpv6ClientProcess", "Dhcpv6MainProcess", "Dhcpv6ServerMainProcess",
    "Dhcpv6ServerProcess", "DnsServerProcess", "EapolClientMainProcess", "EapolClientProcess",
    "EapolMainProcess", "EapolServerMainProcess", "EapolServerProcess", "EapolWirelessMainProcess",
    "EapolWirelessServerMainProcess", "EapolWirelessServerProcess", "EigrpMainProcess",
    "EigrpProcess", "Eigrpv6MainProcess", "Eigrpv6Process", "EthernetEncapProcess", "FirewallProcess",
    "Firewallv6Process", "FowardingProcess", "FrameRelayProcess", "H323Process", "HdlcProcess",
    "HsrpProcess", "Hsrpv6Process", "IPCPProcess", "IcmpProcess", "Icmpv6Process", "InvArpProcess",
    "IoeClientProcess", "IoeServerProcess", "IpFragmentationProcess", "IpsecProcess",
    "Ipv6FragmentationProcess", "Ipv6IpProcess", "JsTcpProcess", "L2NatProcess", "LLDPProcess",
    "LWWirelessServerProcess", "LacpProcess", "NFCollectorProcess", "NatV6Process", "NetflowProcess",
    "Netflowv6Process", "NtpClientProcess", "NtpPTProcess", "OspfMainProcess", "OspfProcess",
    "Ospfv3MainProcess", "Ospfv3Process", "PMTUDiscoveryProcess", "PagpProcess", "PhoneMediaProcess",
    "PingProcess", "PingTcpProcess", "PortKeepAliveProcess", "PortMappedProcess", "QueueProcess",
    "RadiusClientProcess", "RadiusEapServerProcess", "RadiusServerProcess", "RepeaterProcess",
    "ReverseTelnetProcess", "Ripv6MainProcess", "Ripv6Process", "RoutingProcess",
    "RoutingProcessv6Process", "SshClientProcess", "SshServerProcess", "StpMainProcess",
    "TacacsClientProcess", "TacacsServerProcess", "TacasClientProcess", "TacasServerProcess",
    "TcpUserTrafficProcess", "TelnetClientProcess", "TelnetServerProcess", "TraceRouteProcess",
    "UdpTraceRouteProcess", "WLCServerProcess", "WirelessClientProcess", "WirelessServerProcess",
    "Zfwv6Process",
]


def processes_js(device, names=None):
    names = names or PROC_NAMES
    return ("(function(){var d=ipc.network().getDevice(%s);if(!d)return 'NO_DEVICE';"
            "var ps=[%s],hit=[];for(var i=0;i<ps.length;i++){var p=null;"
            "try{p=d.getProcess(ps[i])}catch(e){}if(p)hit.push(ps[i])}"
            "return hit.join(',')})()"
            % (json.dumps(device), ",".join(json.dumps(x) for x in names)))
def check_expect(config_text, must_contain, must_absent):
    have = [l.strip() for l in str(config_text or "").split("\n") if l.strip()]
    joined = "\n".join(have)
    miss = [x for x in (must_contain or []) if x not in joined]
    extra = [x for x in (must_absent or []) if x in joined]
    return {"ok": not miss and not extra, "missing": miss, "unexpected": extra,
            "lines_checked": len(have)}
