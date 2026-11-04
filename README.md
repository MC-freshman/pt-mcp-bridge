# Packet Tracer 8.0 × MCP 桥

让 AI agent 通过 MCP 协议读写 Cisco Packet Tracer 8.0：枚举拓扑、还原连线、**放设备与连线**、往 IOS CLI 注命令、读回终端输出与 running-config、改设备名与端口地址、**配 DHCP 作用域并开关服务**、读 AAA(ACS) 服务的用户与 client 表、查每台设备的协议进程、导出画布拓扑图。

难点不在 MCP，而在 **Packet Tracer 是完全封闭的目标**：没有命令行接口、没有 headless 模式、`.pkt` 工程文件全加密、随包 `.pts` 模块也全加密。本仓库给出**逆向出来的可用边界**，以及在这个边界内搭起来的一条稳定通路。

实测环境：Packet Tracer **8.0.0.0212** Win64 · Python **3.9.13**（只用标准库）· Windows 11 · 当前版本 **v0.5.1，12 个工具**。

---

## 架构

```
AI agent  ──stdio JSON-RPC──▶  pt_mcp.py  ──写──▶  cmd.txt
   ▲                              │                    │ 每 400ms 轮询
   │                              │                    ▼
   └──── resp.txt ◀──写───────────┴──── PT 进程内的 Script Module（ECMAScript / QtScript）
                                              │
                                              ▼  ipc.* / consoleLine / getProcess()
                                        模拟网络里的设备（CLI、路由、AAA、拓扑）
```

传输层刻意选了**共享目录里的两个文件**，不是 HTTP、不是命名管道：PT 的脚本引擎能直接读写本机文件（`ipc.systemFileManager()`），这条路零依赖、零端口、崩溃后不留残留连接。

PT 侧的载体是 **Script Module**——PT 自带的扩展机制，JS 跑在 PT 进程内，能拿到 `ipc.*` 这套内部接口。第三方模块**不需要签名**就能加载（实测）。

---

## 一、PT 侧装模块（一次性，7 步）

| 步 | 操作 | 关键判据 / 坑 |
|---|---|---|
| 1 | `Extensions → Scripting → New PT Script Module` | 标题栏出现 `Scripting - New PT Script Module0 (Stopped)` |
| 2 | `General` 页填 `Name`、`ID`（层级式，如 `com.yourcompany.ptbridge`）；`Publisher Signing` 留 `None Selected`；密码留空；`Startup` 选 `On Demand` | 设了密码的话以后回看脚本也要输密码 |
| 3 | `General` 页底部 **Security 11 格全勾** | ⚠️ 只勾 `Application`+`IPC` 的话，`ipc.network()` 和 `systemFileManager()` 全部 `PRIVILEGE_DENIED` |
| 4 | `Script Engine` 页 → `+` 新建脚本 → 粘 `bridge/module_entry.js` 里那一行 `#include` | 用 `#include` 而不是粘全文：以后改磁盘 JS 只要 Stop→Start 就生效 |
| 5 | `Info` 页 → **Save** | 不点 Save，改动不落盘 |
| 6 | `Info` 页 → **Export** → 存成 `.pts`；弹窗 *"resolve and expand them inline?"* 选 **No** | 选 Yes 会把代码烧进 `.pts`，之后每次改代码都要重新导出 |
| 7 | `Extensions → Scripting → Configure Script Modules ...` → 选中该模块 → **Remove** → 再 **Add Script Module** 选同一个 `.pts` → 核对权限列表 → 允许 → **Start** | ⚠️ Remove+Add 不能省：PT 把权限快照记在自己的选项里，只覆盖 `.pts` 不重注册，旧条目仍按老权限跑 |

**Start 成功的判据**：PT 用户数据目录 `%USERPROFILE%\Cisco Packet Tracer 8.0\logs\` 里最新的 `.log`（GBK 编码）出现 `Script Module starting: <你的 ID>`。这份日志还**逐条记录每一条设备 CLI 命令**，是免费的留痕通道。

---

## 二、配置本机路径与口令

Python 侧走环境变量，不用改代码：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `PT_BRIDGE_DIR` | `C:\pt_bridge` | 桥目录（`cmd.txt` / `resp.txt` / `log.txt` / `alive.txt` 所在处） |
| `PT_BRIDGE_TOKEN` | `CHANGE_ME` | 与 PT 侧模块的口令配对 |

**桥目录不用手工创建**：`ptctl.py` 在 import 时 `os.makedirs(BRIDGE, exist_ok=True)`，第一次调用会自动建好。
（v0.5.1 之前不会——目录不存在时 `python ptctl.py ping` 直接抛 `FileNotFoundError: ...\cmd.txt.tmp`，
退出码 1，报错里也不提"你缺个目录"，照 README 走的人第一条命令就会撞上。）

JS 侧**必须手改三处**——PT 的 QtScript 引擎读不到环境变量，这是硬限制：

| 文件 | 常量 | 要求 |
|---|---|---|
| `bridge/bridge_module.js` | `CFG.bridge` | 和 `PT_BRIDGE_DIR` 指到同一个目录 |
| `bridge/bridge_module.js` | `CFG.token` | 和 `PT_BRIDGE_TOKEN` 一致；不一致时模块回 `bad token` 并拒绝执行 |
| `bridge/module_entry.js` | `#include` 的路径 | 指向 `bridge_module.js` 的绝对路径 |

桥目录**用纯 ASCII、不带空格**的路径：PT 的文件接口和 Python 在中文路径上都有已知坑。

---

## 三、注册

### Qoder Desktop

设置 → **MCP / 连接器** → 添加自定义服务，填一个名字（如 `pt-bridge`）和启动命令。落盘后的配置项形状就是（实测读回的结构，字段只有 `command` 和 `args`）：

```json
{
  "pt-bridge": {
    "command": "D:/python3.9/python.exe",
    "args": ["C:/yourpath/pt_mcp.py"]
  }
}
```

两个注意点：

- `command` 建议写 **python 解释器的绝对路径**，不要写 `python`——MCP 子进程不一定继承你 shell 里的 PATH 顺序（本机 `where python` 有三个候选，写裸名会撞上 `WindowsApps` 那个假 python）。
- `args` 里是 `pt_mcp.py` 的**绝对路径**。如果 `PT_BRIDGE_DIR` / `PT_BRIDGE_TOKEN` 不是默认值，需要在客户端的环境变量设置里一起给。

**确认加载成功**：MCP 列表里该服务应显示 **11 个工具**（`pt_health`、`pt_status`、`pt_devices`、`pt_wiring`、`pt_cli`、`pt_script`、`pt_running_config`、`pt_eval`、`pt_command_log`、`pt_aaa_state`、`pt_processes`）。然后让 agent 调一次 `pt_health`，看到 `"failure_class": "OK"` 就算通了。

### 其它 MCP 客户端（Claude Desktop / Cursor / 任何 stdio 客户端）

协议就是 stdio + 换行分隔的 JSON-RPC 2.0，配置同上：`command` 指向 python，`args` 指向 `pt_mcp.py`。没有第三方依赖，不需要 `pip install`。

### 不想接 MCP：直接用命令行

```bash
python ptctl.py status                        # 桥目录产物概览
python ptctl.py ping                          # 探活：让 PT 算 1+1
python ptctl.py js "ipc.network().getDeviceCount()"
python ptctl.py cli Router0 "show version"    # 自动破 --More-- 分页
python ptctl.py runconf Router0               # 整份 running-config
```

### 注册后自检

```bash
python test_offline.py     # 不连 PT：纯逻辑 + JSON-RPC 握手 + tools/list
python test_mcp_live.py    # 连 PT：MCP -> 文件队列 -> PT -> 设备 CLI 全链
```

### 注册不通的几种情况

| 现象 | 原因 | 处理 |
|---|---|---|
| 工具列表是空的 | 客户端没重载 MCP，或 `command` 路径不对 | 重启客户端；用绝对路径 |
| `pt_health` 回 `TIMEOUT` 且 `pt_process` 是"没开" | PT 没运行 | 开 PT |
| `pt_health` 回 `TIMEOUT` 但 `pt_process` 有 PID | PT 重启过，模块没跟着 Start（`Startup` 是 `On Demand`） | `Configure Script Modules` 里点 Start |
| `bad token` | JS 侧 `CFG.token` 和 `PT_BRIDGE_TOKEN` 不一致 | 两边改成同一个串 |
| `PRIVILEGE_DENIED` | 权限没随 Save→Export→Remove+Add 落进 `.pts` | 重走第一节第 3、5、6、7 步 |
| MCP 工具调用一律回 `Streamable HTTP error: ... Not Found`，但 PT 窗口还在、`Get-Process` 查得到 PID | **MCP server 自己掉了，PT 没事** | 别重启 PT。直接 `python ptctl.py js "<ES5 表达式>"` 走文件通道，能力与 `pt_eval` 等价（11-04 实测整场实验都是这么跑完的） |
| `PermissionError: [WinError 5] ... cmd.txt.tmp -> cmd.txt` | 桥目录被并发读走（多个会话共用同一个 `PT_BRIDGE_DIR`） | 等 1–3 秒重试即可，不是逻辑错误 |

---

## 四、功能清单

### 让新会话的模型一上来就知道有这些能力

光靠 tool description 不够——新会话的模型经常根本不知道自己有这个 MCP。所以 v0.5 在 MCP 的四个层面都铺了信息：

| 层面 | 内容 | 作用 |
|---|---|---|
| `initialize.instructions` | 1442 字的操作简报：先决条件、工具速查、**五个必踩的坑**、做不到的两件事、工作方式 | 客户端通常把它转成系统提示，是"开场就知道"的主通道 |
| `resources` | `pt://guide`（能力与坑）、`pt://api`（调用速查＋三组枚举）、`pt://live`（设备数/链路数/AAA 摘要，每次读取实时采集） | 可按需细读，不占常驻上下文 |
| `prompts` | `pt-build-topology` / `pt-verify-lab` / `pt-diagnose` | 三条现成工作流，带参数渲染成完整指令 |
| `tools` | 新增 `pt_guide`：直接把上面那份简报作为工具返回 | **兜底**——客户端不转发 instructions、也不支持 resources 时，模型调一次就有 |

`instructions` 里的坑是挑出来的最高代价项（现 8 条）：枚举传数字（`CONNECT_TYPES` 从 8100 起）、**型号串从 `getDeviceModels()` 取而不是猜**、`deleteLink` 只给一端、`AssessmentModel.getRunningConfig` 崩 PT、只有 `writePlainTextToFile` 两参写文件干净、断电会清 running-config、**新设备的 initial-config dialog 要等它真出现再答 `no`**、**三个读数通道会骗你**（详见下面第七节）。

"做不到"清单也从 2 条扩到 6 条：存盘、插模块之外，**DNS 加 A 记录、改 Web 页面正文、让 PC 真的发 DHCP 请求、清 CLI 缓冲区**都只能人手点。

自测：`python test_protocol.py`（不连 PT，检查 caps、instructions、12 工具、3 资源、3 提示词都在）。

### MCP 工具（12 个）

| 工具 | 参数 | 作用 | 会动设备吗 |
|---|---|---|---|
| `pt_guide` | — | **返回能力说明、工具速查、五个必踩的坑、做不到的两件事**。新会话第一件事就该调它 | 否（纯文本） |
| `pt_health` | — | 桥与 PT 健康检查，三种失效分开报 | 只发一次 `1+1` |
| `pt_status` | — | 桥目录各产物文件的字节数与内容片段 | 否 |
| `pt_devices` | — | 设备清单 `名称:类型` | 只读 |
| `pt_wiring` | — | **连线表**：每台交换机挂了哪些端点、哪条半截线、哪些线不经交换机 | 只读 |
| `pt_processes` | `device` | 该设备装载了哪些协议进程 | 只读，不触发行为 |
| `pt_aaa_state` | `device` | AAA(ACS) 服务：是否启用、client 表、user 表 | 只读 |
| `pt_command_log` | — | PT 记录的命令条数，核对注入是否落地 | 只读 |
| `pt_cli` | `device`, `command` | 注一条 IOS 命令，自动破分页，回新增输出 + 结束时提示符/模式 | **是** |
| `pt_script` | `device`, `lines[]`, `stop_on_reject` | **一次调用喂一整段命令**，逐条核对提示符层级、自动补 `enable`、带 progress 通知 | **是** |
| `pt_running_config` | `device` | 整份 running-config（内部先确保 enable） | **是** |
| `pt_eval` | `expression`, `timeout_sec` | 逃生舱：求值任意 ECMAScript（ES5） | 看代码 |

### 实测返回样例

`pt_health`

```json
{"pt_process": "28520", "bridge_roundtrip": true, "failure_class": "OK"}
```

`pt_processes(Router0)` —— 一台 1841 上 34 个协议进程，不用点任何界面：

```json
{"ok": true, "device": "Router0", "count": 34,
 "processes": ["RoutingProcess", "RadiusClientProcess", "CbacProcess", "IpsecProcess",
               "OspfMainProcess", "EigrpMainProcess", "StpMainProcess", "SshServerProcess",
               "TelnetServerProcess", "DhcpServerProcess", "TacacsClientProcess", "..."]}
```

`pt_aaa_state(Server0)` —— 以前判成"只能 GUI 手填"的那张表，现在直接读得出来：

```json
{"ok": true, "device": "Server0", "enabled": true,
 "clients": ["192.168.2.1::R:router0,1,192.168.2.1,key",
             "192.168.2.2::R:router1,1,192.168.2.2,key"],
 "users":   ["User1:User1,password1,", "User2:User2,password2,", "..."]}
```

`pt_cli(Router0, "show version")` / `pt_running_config`

```json
{"ok": true, "prompt": "router0#", "mode": "enable",
 "added": "show running-config\nBuilding configuration...\nCurrent configuration : 704 bytes\n!\nversion 12.4\nhostname router0\n...\nend\n\nrouter0#",
 "echoed": true, "resent": false}
```

`pt_wiring` —— 按 link 的 uuid 分组还原，能识别半截线（下面是本机 AAA 实验拓扑的真实输出，节选）：

```json
{"ok": true, "links": 18,
 "segments": {
   "Switch0": ["Router0:FastEthernet0/1", "Router1:Ethernet0/0/0", "Router2:FastEthernet0/0"],
   "Switch5": ["PC4:FastEthernet0", "Server0:FastEthernet0", "Server1:FastEthernet0",
               "Router2:FastEthernet0/1"],
   "Switch6": ["Cloud0:Ethernet6", "PC5:FastEthernet0", "Router0:FastEthernet0/0"]},
 "dangling": [],
 "non_switch_links": [["PC0:FastEthernet0", "DSL Modem0:Port 1"],
                      ["Cloud0:Modem4", "DSL Modem0:Port 0"]]}
```

`dangling` 非空就是**只接了一端的线**；`non_switch_links` 是两端齐全但不经过交换机的线（PC↔ModemCloud 这类）。
上面这条输出还能直接看出 `Router1:Ethernet0/0/0` 这种新插模块后的口名，不用去界面里数。

所有失败都带 `failure_class`：`PRIVILEGE_DENIED / INVALID_ARGS / IPC_ERROR / TIMEOUT / NO_ECHO`，agent 不用靠猜分诊。

参考用量：一台 1841 路由器 34 条配置命令，`pt_script` 一次调用完成；逐条 `pt_cli` 是 34 次往返、每次 0.4–1.5 秒。

---

## 五、能做到什么、做不到什么

### ✅ 已实测可用的调用

**搭拓扑**（全部实测通过，含枚举基值——**这是之前判错的关键**）：

```javascript
lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()

// 放设备：DeviceType 是枚举 0..51，不是字符串！
// eRouter=0 eSwitch=1 eCloud=2 eHub=4 eAccessPoint=7 ePc=8 eServer=9
// eWirelessRouter=11 eIpPhone=12 eDslModem=13  eMultiLayerSwitch=16
// eLaptop=18  eASA=27  eIoE=28 eCellTower=31 eWLC=41 eLightWeightAP=44
lw.addDevice(8, "PC-PT", 900, 900)          // → "PC6"（返回新设备名）
lw.removeDevice("PC6")                       // → true

// 连线：CONNECT_TYPES 是枚举，值从 8100 起，不是 0！
// ETHERNET_STRAIGHT=8100 ETHERNET_CROSS=8101 FIBER=8103 PHONE=8104
// CABLE=8105 SERIAL=8106 AUTO=8107 CONSOLE=8108 WIRELESS=8109 COAXIAL=8110
lw.createLink("Switch0","FastEthernet0/20","Switch3","FastEthernet0/20", 8100)  // → true
lw.deleteLink("Switch0","FastEthernet0/20")  // 只给一端；给四段会 Invalid arguments
```

**改位置 / 查模块 / 设备与端口**：

```javascript
dev.moveToLocation(x, y) / moveToLocationCentered(x, y) / getXCoordinate() / getYCoordinate()
dev.getSupportedModule()                     // 1841 返回 12 个，含 WIC-1ENET / HWIC-4ESW
dev.serializeToXml()                         // 整台设备状态导成 XML
ipc.network().getDeviceCount() / getDeviceAt(i) / getDevice("Router0")
dev.getPortCount() / getPortAt(i) / getPort(name) / setName("Switch0")
dev.getProcess("AcsServerProcess") / getPower() / setPower(bool) / getModel()
port.getName() / getClassName() / getLink() / getIpAddress()
port.setIpSubnetMask(ip, mask) / setDefaultGateway(gw) / setDnsServerIp(ip) / setDhcpClientFlag(b)
dev.getConsoleLine() → enterCommand(cmd) / getOutput() / getPrompt() / getMode()
dev.enterCommand(cmd, true)                       // 设备级必须双参
ipc.commandLog().getEntryCount()
ipc.simulation().isSimulationMode()
ipc.systemFileManager() → writePlainTextToFile(path, text) / getFileContents(path)
acs = dev.getProcess("AcsServerProcess")
   → isEnabled() / getClientRecordsAsString() / getUserRecordsAsString()
   → enableACSServerService() / addToClientMap() / addToUserMap()
   → deleteFromClientMap() / deleteFromUserMap() / removeAllUserRecords() / removeAllClientRecords()
```

**配服务（11-04 钓鱼实验实测，这一组以前被误判成"只能 GUI"）**：

```javascript
// 取值正门：型号串和线型名都从这里拿，别猜
nb = ipc.appWindow().getNetworkComponentBox()
nb.getDeviceTypes()              // 17 个类别名：Routers, Switches, End Devices, …
nb.getDeviceModels("Routers")    // → 1841, 1941, 2911, ISR4331, Router-PT, …
nb.getConnectionTypes()          // → Copper Straight-Through, Serial DCE, …

// DHCP 作用域：注意 getPool("口名") 返回 null，只有 getPoolAt(0) 有池
sp = dev.getProcess("DhcpServerMainProcess")
      .getDhcpServerProcessByPortName("FastEthernet0");
pool = sp.getPoolAt(0);
pool.setStartIp("192.168.1.10"); pool.setMaxUsers(60);
pool.setDefaultRouter("192.168.1.254"); pool.setDnsServerIp("192.168.2.6");
sp.setEnable(true);
// 没有 setSubnetMask；改完 maxUsers 后 pool.getEndIp() 自己变成 192.168.1.69

// 开关服务：三类进程都有 setEnable
dev.getProcess("DnsServerProcess").setEnable(true);   // isEnabled() 读回 true
dev.getProcess("HttpServer").setEnable(true);         // getPortNumber() → 80
```

实测一次钓鱼实验的用量：12 台设备、11 根线、两台路由器共 33 条 IOS 命令、三台服务器地址 + 两个作用域 + 三个服务开关，全部由桥完成，人只点了 DNS 记录和一处网页文本。

### ❌ 做不到 / 还没打通

| 想做的 | 实测结论 |
|---|---|
| **保存工程文件** | 官方文档原话：**"The API lacks project load/save functions"**。`Options.saveFile(QString)` 实测只是"保存偏好设置到文件"，不是 `.pkt`。这条是 API 层没有接口，只能 Ctrl+S |
| **插硬件模块** | 签名 `addModule(string slot, ModuleType type, string model)` 已确认，但槽位名要从 `dev.getRootModule()` 的 `getSlotPath()` 取；实测 1841 的模块树只暴露一个 `eNonRemovableModule`、槽路径为空，断电后 `addModule` 仍全部 `false` → **该型号的槽位没通过 IPC 暴露**，插模块只能 GUI |
| **DNS 加资源记录** | `DnsServerProcess` 上只有 `setEnable` 可写；`addARecord / addRecord / addRR / insertRecord / addNameServerDbEntry` 全部不存在 → Services→DNS 面板手填后**还要点 `Add`**，只填不点表里不会多一行 |
| **改 Web 页面正文** | `HttpServer` 只有 `getPage`，没有 `setPage / setPageContent / addPage`；`IoeServerProcess.getFiles` 在 Server 上也不存在 → Services→HTTP→`index.html` 的 `(edit)` 手改 |
| **让 PC 真的去取地址** | `port.setDhcpClientFlag(true)` 只改配置标志，**不发 Discover**；`DhcpClientProcess` 只有 `getDataOfPort / isConfigured / isPortExisted` 三个读方法。翻转开关也无效 → 必须 GUI 点 Static→DHCP |
| **清 CLI 缓冲区** | `TerminalLine` 只有 `getOutput / getPrompt / getMode / getCommandPrompt / getRs232Port`，**没有清屏方法**；IOS 也没有 `clear`。CLI 被报错行和重复命令搞脏时唯一干净的办法是 `removeDevice` + `addDevice` 重放（实测删设备不丢别的设备配置，删 `Power Distribution Device` 也不牵连路由器） |

> **取拓扑图已打通**（不再算做不到）：`getWorkspaceImage("PNG")` 返回 `vector<byte>`——**参数是格式串不是路径**。
> 拿到字节后在 JS 里 hex 编码，走已验证干净的 `writePlainTextToFile` 落盘，Python 侧 `unhexlify` 还原成 PNG。
> 实测本机 AAA 拓扑导出 **1523×568 / 38267 字节**的合法 PNG（文件头 `89 50 4e 47`）。注意 `vector<byte>` 在 QtScript 里是**有符号数**，编码时要 `& 255`。

> **早期这里的"创建连线/放设备/改坐标做不到"是错的**，已移到上面的"能做到"。原因是三个枚举的基值没查：`CONNECT_TYPES` 从 **8100** 起、`DeviceType` 是 **0–51**、`ModuleType` 是 **0–19**；按 0 起猜、或把枚举当字符串传，全部 `false` 且不报错——**"不抛错但返回 false"最容易误判成"API 不支持"**。

> 曾经列在这里的"配 AAA Server 用户/client 表"**已被推翻**：真类名是 `AcsServerProcess` 而不是我一开始猜的 `RadiusServerProcess`，读写接口都在。误判原因见下一节。

### 从零搭一张图（全链实测）

```javascript
lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()

// 1) 放设备：DeviceType 枚举 + 型号串 + 坐标
var r  = lw.addDevice(0,  "1841",      300, 100);   // → "Router0"
var sw = lw.addDevice(1,  "2960-24TT", 300, 200);   // → "Switch0"
var pc = lw.addDevice(8,  "PC-PT",     300, 300);   // → "PC0"

// 2) 连线：CONNECT_TYPES 枚举，ETHERNET_STRAIGHT=8100
lw.createLink(r,  "FastEthernet0/0", sw, "FastEthernet0/1", 8100);
lw.createLink(sw, "FastEthernet0/2", pc, "FastEthernet0",   8100);

// 3) 改名 / 位置 / 端口地址
ipc.network().getDevice(r).setName("R1");
ipc.network().getDevice(r).moveToLocation(120, 80);
ipc.network().getDevice("R1").getPort("FastEthernet0/0")
   .setIpSubnetMask("192.168.10.1", "255.255.255.0");
ipc.network().getDevice("PC0").getPort("FastEthernet0")
   .setIpSubnetMask("192.168.10.10", "255.255.255.0")
   .setDefaultGateway("192.168.10.1");     // 注意：setIpSubnetMask 返回 void，别链式

// 4) IOS 配置：getDevice(名).getConsoleLine().enterCommand("...")
// 5) 校验：getPort().getLink() / getIpAddress() / commandLog / CLI 读回
```

撤掉也有对称接口：`lw.removeDevice(name)`、`lw.deleteLink(device, port)`（只给一端）。

### 官方 IPC API 文档（本仓库结论的一手依据）

这套接口有在线 Doxygen 文档，比猜方法名可靠得多：

- [IpcManager](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_ipc_manager.html) —— ExApp/Script Module 的入口，`getListeningPort()`
- [LogicalWorkspace](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_logical_workspace.html) —— `addDevice` / `createLink` / `deleteLink` / `removeDevice` / `getWorkspaceImage` / `addNote`
- [Device](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_device.html) —— `addModule` / `getSupportedModule` / `moveToLocation` / `getProcess` / `serializeToXml`
- [Link](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_link.html) —— `CONNECT_TYPES` 枚举值
- [Module](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_module.html) —— `getModuleCount` / `getModuleAt` / `getSlotPath`
- [Options](https://tutorials.ptnetacad.net/help/default/IpcAPI/class_options.html) —— 明确"没有 .pkt 读写"

早前没人告诉我有这套文档，靠 exe 字符串表 + `typeof` 扫描硬猜，代价是三个枚举基值和两个参数顺序全猜错，把"能做到"误判成"做不到"。**先查文档，再猜。**

上面六个链接是本仓库实际引用过的类页。`getDeviceTypes / getDeviceModels / getConnectionTypes` 这三个取值方法属于 `NetworkComponentBox` 类，页名请以 [IpcAPI 首页的类列表](https://tutorials.ptnetacad.net/help/default/IpcAPI/) 为准——本仓库没验证过它的直达 URL，不在此处瞎给。

### ⛔ 会直接把 PT 进程搞崩

`AssessmentModel.getRunningConfig(...)` —— 实测让 PT 换了一次进程 PID。读配置请改用
`consoleLine.enterCommand("show running-config")` + 自动翻页。

### 读数会骗你的四个通道（11-04 新增，每一条都造成过一次假阴性）

这一节的意义不是"少四个方法"，而是**防止 agent 拿错误的读通道去断言"用户没配好"**：

| 通道 | 它返回 | 实际含义 |
|---|---|---|
| `HttpServer.getPage("index.html")` | 恒 369 字符的内置默认页 | **不反映用户在界面编辑过的页面**。今天据此误判了一次"你还没提交"，而浏览器实际已经吐出改好的页面 |
| `DnsServerProcess.getIpAddOfDomain(域名)` | `0.0.0.0` | 读的是**缓存**。记录要用 `getRrFromNameServerDbAt(0)` 取 data 对象（`.name / .ipAddress / .pduType / .ttl`）；条数看 `getSizeOfNameServerDb()`，不是 `getEntryCount()` |
| `DhcpPool.getLeaseAt(i)` | 两台 DHCP 都记同一个 MAC | PT 的租约簿记**与客户端实际采纳的地址不对齐**（表里 `.11`、客户端用 `.10`）。判"哪台应答了"要看下发的字段值（如 DNS 指向谁），不能看租约表 |
| `dev.getHostName()` | 型号默认名 `Router` | 不是 IOS hostname，判 hostname 看 CLI 提示符 |

> 规则一句话：**返回 `0` / `0.0.0.0` / 空串 / 恒定值时，先怀疑通道，再怀疑事实。**
> 要下"没配上"的结论，必须换一个独立通道——最好是应用自己的输出（浏览器、面板、PT 自己的日志）。

完整清单（PT CLI 的 12 条怪癖、权限枚举真名、为什么 `printDebug` 不出声、1841 插 `WIC-1ENET` 后新口叫 `Ethernet0/1/0`、MCP server 掉线时的退路）见 **[PT实测API表.md](PT实测API表.md)**。

---

## 六、这些结论是怎么来的

1. **抽字符串表**：`python tools/strings_probe.py <PacketTracer.exe> pt_strings.txt`。
   PT 把 `.pki` 接口声明编译进 exe，每个接口块都以 `getClassName / getObjectUuid / registerObjectEvent / unregisterObjectEvent` 开头。以 `registerObjectEvent` 为锚点向前找类名、向后收方法名，本机还原出 **252 个接口类**。
   ⚠️ 类名归属要往前多看几行并排除裸通用词：真类名（`AcsServerProcess`）离锚点往往隔着十几条常量串，而紧邻锚点的是裸词 `Process`——只看 8 行会把整块错归成 `Process`，方法表也就空了。**我一开始就是这么漏掉 AAA 接口的。**
2. **`typeof` 扫描**：把候选方法名拼成 `String(typeof obj.method)` 通过桥投进去，区分"存在但参数不对"和"根本不存在"，零副作用。见 `probes/probe_names.py`。
3. **同串比字节**：同一个已知字符串用所有可疑签名各写一份再比字节——**不要取"第一个不抛错的"**。实测 `writeTextToFile` / `writeBinaryToFile` 不抛错但写出 U+FFFD 乱码，只有 `writePlainTextToFile(path, text)` 两参干净。见 `probes/probe_cable.py`。
4. **投一条比一次宿主 PID**：入口钩子里不放任何危险调用，可疑调用由外部逐条投，每投一条检查进程是否还在，崩点自己浮出来。见 `probes/probe_ws.py`。
5. **两阶段扫描**：先只调 `getProcess(名字)` 列存在性（零副作用），再对存在的东西调零参 `get*/is*`。见 `tools/ipc_map.py` 的 `map` / `exists` / `sweep` 三种模式。

---

## 七、目录

```
pt_mcp.py              MCP server（stdio JSON-RPC，纯标准库，11 个工具）
ptctl.py               命令行驱动 + 传输层（也被 server 复用）
ptplus.py              纯逻辑：错误五分类、连线表解析、批量汇总、验收断言、AAA/进程 JS 构造器
bridge/
  bridge_module.js     跑在 PT 进程里的桥（改它只需 Stop→Start）
  module_entry.js      PT 里只需粘这一行 #include
probes/                API 探测脚本（typeof 扫描 / 签名字节比对 / 崩点定位）
tools/strings_probe.py 从 exe 还原 IPC 接口表
tools/ipc_map.py       接口地图 + 全设备进程扫描 + 服务数据收割
test_offline.py        离线自测，不连 PT
test_mcp_live.py       端到端自测
PT实测API表.md         全部实测结论
```

---

## 八、安全警告

这条桥的语义是：**本机任何进程往 `cmd.txt` 写一下，就能在 Packet Tracer 进程里执行任意 JavaScript**。

- `CFG.token` 只挡误投和其它工具乱写，**挡不住同一用户的其它进程**（口令就存在该用户的目录里）。
- 仓库发的是占位符 `CHANGE_ME`：**上手第一件事**是换成你自己的随机串（JS 侧一处 + `PT_BRIDGE_TOKEN` 一处）。沿用默认值的话，任何知道该默认值的本机进程都能驱动 PT。
- 别把桥目录放进共享目录或网盘。

## License

MIT —— 见 [LICENSE](LICENSE)。逆向得到的 API 结论本身不受版权保护，但 Packet Tracer 是 Cisco 的闭源软件，本仓库不含它的任何二进制或文件。
