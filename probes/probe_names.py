"""用 typeof 批量探方法存在性，找出创建连线的入口。"""
import sys

sys.path.insert(0, r"C:\Users\wk\pt_bridge")
import ptctl

T = 'String(typeof %s)'

NET = "ipc.network()"
PORT = 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0")'

CANDS = [
    # ipc 根上还有什么
    ("ipc.workspace", "ipc.workspace"),
    ("ipc.canvas", "ipc.canvas"),
    ("ipc.gui", "ipc.gui"),
    ("ipc.appWindow()", "ipc.appWindow"),
    ("ipc.logical", "ipc.logical"),
    # network 上的方法
    ("net.createLink", NET + ".createLink"),
    ("net.addLink", NET + ".addLink"),
    ("net.addDevice", NET + ".addDevice"),
    ("net.connect", NET + ".connect"),
    ("net.connectDevices", NET + ".connectDevices"),
    ("net.autoConnectDevices", NET + ".autoConnectDevices"),
    ("net.getWorkspace", NET + ".getWorkspace"),
    ("net.getLogicalWorkspace", NET + ".getLogicalWorkspace"),
    ("net.getDevice", NET + ".getDevice"),
    ("net.getDeviceAt", NET + ".getDeviceAt"),
    ("net.getLinkCount", NET + ".getLinkCount"),
    ("net.getLinkAt", NET + ".getLinkAt"),
    # appWindow 上
    ("aw.getWorkspace", "ipc.appWindow().getWorkspace"),
    ("aw.getLogicalWorkspace", "ipc.appWindow().getLogicalWorkspace"),
    ("aw.createLink", "ipc.appWindow().createLink"),
    ("aw.addDevice", "ipc.appWindow().addDevice"),
    # 设备对象上
    ("dev.addModule", NET + '.getDevice("Router0").addModule'),
    ("dev.getPort", NET + '.getDevice("Router0").getPort'),
    ("dev.setName", NET + '.getDevice("Router0").setName'),
    ("dev.getSerialNumber", NET + '.getDevice("Router0").getSerialNumber'),
    # 端口对象上
    ("port.connectTo", PORT + ".connectTo"),
    ("port.setLink", PORT + ".setLink"),
    ("port.linkTo", PORT + ".linkTo"),
    ("port.connect", PORT + ".connect"),
    ("port.getLink", PORT + ".getLink"),
    ("port.setPower", PORT + ".setPower"),
    ("port.setDuplex", PORT + ".setDuplex"),
    ("port.setSpeed", PORT + ".setSpeed"),
    ("port.setIpSubnetMask", PORT + ".setIpSubnetMask"),
    ("port.setDefaultGateway", PORT + ".setDefaultGateway"),
    ("port.setDnsServerIp", PORT + ".setDnsServerIp"),
    ("port.setDhcpClientFlag", PORT + ".setDhcpClientFlag"),
    ("port.getDevice", PORT + ".getDevice"),
]

for label, expr in CANDS:
    r = ptctl.send(T % expr, 10.0)
    print("%-24s %s" % (label, r.get("result", r.get("error", ""))[:40]))
