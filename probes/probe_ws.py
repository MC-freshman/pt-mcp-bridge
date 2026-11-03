"""验 LogicalWorkspace 能不能拿到，以及 createLink/addDevice 的真实签名。"""
import sys

sys.path.insert(0, r"C:\Users\wk\pt_bridge")
import ptctl

W = ('(function(){try{var v=%s;return "OK:"+String(v).slice(0,70)}'
     'catch(e){return "NO:"+String(e).slice(0,90)}})()')

STEPS = [
    ("aw.getActiveWorkspace 是函数?", 'String(typeof ipc.appWindow().getActiveWorkspace)'),
    ("getActiveWorkspace() 返回", 'String(ipc.appWindow().getActiveWorkspace())'),
    ("ws.getLogicalWorkspace 是函数?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace)'),
    ("拿 LogicalWorkspace", 'String(ipc.appWindow().getActiveWorkspace().getLogicalWorkspace())'),
    ("lw.createLink 是函数?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().createLink)'),
    ("lw.addDevice 是函数?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().addDevice)'),
    ("lw.autoConnectDevices?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().autoConnectDevices)'),
    ("lw.getDeviceCount?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().getDeviceCount)'),
    ("lw.getWorkspaceImage?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().getWorkspaceImage)'),
    ("lw.getName?", 'String(typeof ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().getName)'),
    ("试 createLink(端口,端口)", 'ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().createLink('
     'ipc.network().getDevice("Router0").getPort("FastEthernet0/0"),'
     'ipc.network().getDevice("Switch6").getPort("FastEthernet0/1"))'),
    ("createLink 后链路数", "String(ipc.network().getLinkCount())"),
]

for label, js in STEPS:
    r = ptctl.send(W % js, 12.0)
    print("%-30s %s" % (label, r.get("result", r.get("error", ""))[:100]))
