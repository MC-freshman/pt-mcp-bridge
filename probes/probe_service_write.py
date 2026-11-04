# -*- coding: utf-8 -*-
"""服务写接口探测：给定设备与进程名，列出可读字段、判断哪些 set*/add* 真的存在。

用法：
    python probe_service_write.py Server0 DnsServerProcess
    python probe_service_write.py Server0 DhcpServerMainProcess

为什么要它：PT 的 IPC 方法表（tools/ipc_map.py 从 exe 还原的那份）**不含全部方法**，
LogicalWorkspace 的 addDevice/createLink 就没在里面，靠它下"没有写接口"的结论会错。
判存在性的正确手段是**直接调用并分诊异常**：

  - 抛 `not a function`            → 方法真的不存在
  - 抛 `Invalid arguments`          → 方法存在，参数不对（继续换参数形式）
  - 不抛错但返回 false / 空串        → 方法存在但语义没成，八成是枚举值或参数顺序

⚠️ 本脚本默认只做**只读探测**（不调用任何 setter）。要真调用必须自己把 VALUES 填成
   合法目标值——传假值（如 'x'）会污染设备配置。

验证状态：**未实跑**。写它时 PT 已关闭，通道返回 TIMEOUT。
         它要验证的结论本身是实测过的（见 PT实测API表.md 第四节"配服务"与第七节），
         脚本只是把那套分诊手法固化下来，第一次用请先 `python ptctl.py ping` 确认桥活着。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
import ptctl  # noqa: E402

READERS = ["isEnabled", "isEnable", "getPoolCount", "getSizeOfNameServerDb",
           "getEntryCount", "getPortNumber", "getDhcpPoolName", "getStartIp",
           "getMaxUsers", "getDnsServerIp", "getDefaultRouter", "getEndIp"]
WRITERS = ["setEnable", "enable", "setStartIp", "setMaxUsers", "setDefaultRouter",
           "setDnsServerIp", "setSubnetMask", "setEndIp", "setPoolName",
           "addARecord", "addRecord", "addRR", "insertRecord",
           "addNameServerDbEntry", "setPage", "setPageContent", "addPage"]

DEV = sys.argv[1] if len(sys.argv) > 1 else "Server0"
PROC = sys.argv[2] if len(sys.argv) > 2 else "DnsServerProcess"

JS = (
    "(function(){var d=ipc.network().getDevice('%s');"
    "if(!d)return '设备不存在: %s';"
    "var p=null,how='';"
    "if('%s'==='DhcpServerMainProcess'){"
    "try{p=d.getProcess('DhcpServerMainProcess')"
    ".getDhcpServerProcessByPortName('FastEthernet0');how='Main->byPortName(FastEthernet0)';}"
    "catch(e){return 'DHCP 链式取进程失败: '+String(e).slice(0,60);}}"
    "}else{try{p=d.getProcess('%s');how='getProcess';}catch(e2){}}"
    "if(!p)return '拿不到进程对象 %s';"
    "var o=['对象='+p.getClassName()+' 取法='+how];"
    "var pool=null;"
    "try{pool=p.getPoolAt(0);}catch(e){}"
    "var R=%s;"
    "for(var i=0;i<R.length;i++){var host=p;"
    "if(['getDhcpPoolName','getStartIp','getMaxUsers','getDnsServerIp','getDefaultRouter',"
    "'getSubnetMask','getEndIp'].indexOf(R[i])>=0){if(!pool){o.push('read  '+R[i]+' : 无池');continue;}host=pool;}"
    "try{o.push('read  '+R[i]+' = '+String(host[R[i]]()));}"
    "catch(e){var m=String(e);o.push('read  '+R[i]+' : '+(m.indexOf('not a function')>=0?'无此方法':m.slice(0,40)));}}"
    "var W=%s;"
    "for(i=0;i<W.length;i++){var host2=pool&&W[i].indexOf('set')===0?pool:p;var f=null;"
    "try{f=host2[W[i]];}catch(e3){}"
    "if(typeof f!=='function'&&pool){try{f=p[W[i]];}catch(e4){}}"
    "o.push('write '+W[i]+' : '+(typeof f==='function'?'存在':'无此方法'));}"
    "return o.join('\\n');})()" % (DEV, DEV, PROC, PROC, PROC,
                                  __import__("json").dumps(READERS),
                                  __import__("json").dumps(WRITERS))
)

print(ptctl.send(JS, 45.0).get("result"))
