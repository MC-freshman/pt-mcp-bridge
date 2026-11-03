"""探测 PT 的连线/端口/设备 API 实际存在哪些方法（不存在会抛异常，逐条记录）。"""
import sys

sys.path.insert(0, r"C:\Users\wk\pt_bridge")
import ptctl

# 注意：包装串里不要再放引号嵌套，之前把 " " 吃掉导致 JS 语法错
WRAP = ('(function(){try{var v=%s;return "OK:"+String(v).slice(0,60)}'
        'catch(e){return "NO:"+String(e).slice(0,70)}})()')

CAND = [
    ("net.getLinkCount", "ipc.network().getLinkCount()"),
    ("net.getLinkAt", "ipc.network().getLinkAt(0)"),
    ("dev.getPortCount", 'ipc.network().getDevice("Router0").getPortCount()'),
    ("dev.getPortAt", 'ipc.network().getDevice("Router0").getPortAt(0)'),
    ("dev.getPort", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0")'),
    ("port.getName", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getName()'),
    ("port.getState", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getState()'),
    ("port.getStatus", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getStatus()'),
    ("port.getLink", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getLink()'),
    ("port.isUp", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").isUp()'),
    ("port.getIpAddress", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getIpAddress()'),
    ("port.getOtherPort", 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0").getLink().getOtherPortConnectedTo(ipc.network().getDevice("Router0").getPort("FastEthernet0/0"))'),
    ("dev.getHostName", 'ipc.network().getDevice("Router0").getHostName()'),
    ("dev.getConfigRegister", 'ipc.network().getDevice("Router0").getConfigRegister()'),
    ("dev.getModuleCount", 'ipc.network().getDevice("Router0").getModuleCount()'),
    ("pc.getPort", 'ipc.network().getDevice("PC0").getPort("FastEthernet0")'),
]

for label, js in CAND:
    r = ptctl.send(WRAP % js, 12.0)
    print("%-18s %s" % (label, r.get("result", r.get("error", ""))[:100]))
