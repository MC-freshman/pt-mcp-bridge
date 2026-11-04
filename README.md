# Packet Tracer 8.0 × MCP 桥

让 AI agent 通过 MCP 协议读写 Cisco Packet Tracer 8.0：枚举拓扑、还原连线、往 IOS CLI 注命令、读回终端输出与 running-config、读 AAA(ACS) 服务的用户与 client 表、查每台设备的协议进程、改终端 IP 与设备名。

难点不在 MCP，而在 **Packet Tracer 是完全封闭的目标**：没有命令行接口、没有 headless 模式、`.pkt` 工程文件全加密、随包 `.pts` 模块也全加密。本仓库给出**逆向出来的可用边界**，以及在这个边界内搭起来的一条稳定通路。

实测环境：Packet Tracer **8.0.0.0212** Win64 · Python **3.9.13**（只用标准库）· Windows 11 · 当前版本 **v0.4，11 个工具**。

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

### 注册不通的四种情况

| 现象 | 原因 | 处理 |
|---|---|---|
| 工具列表是空的 | 客户端没重载 MCP，或 `command` 路径不对 | 重启客户端；用绝对路径 |
| `pt_health` 回 `TIMEOUT` 且 `pt_process` 是"没开" | PT 没运行 | 开 PT |
| `pt_health` 回 `TIMEOUT` 但 `pt_process` 有 PID | PT 重启过，模块没跟着 Start（`Startup` 是 `On Demand`） | `Configure Script Modules` 里点 Start |
| `bad token` | JS 侧 `CFG.token` 和 `PT_BRIDGE_TOKEN` 不一致 | 两边改成同一个串 |
| `PRIVILEGE_DENIED` | 权限没随 Save→Export→Remove+Add 落进 `.pts` | 重走第一节第 3、5、6、7 步 |

---

## 四、功能清单（11 个工具，附实测返回）

| 工具 | 参数 | 作用 | 会动设备吗 |
|---|---|---|---|
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

```javascript
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
ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()      // 对象能拿到
```

### ❌ 做不到，只能 GUI 手点（每条都试到确认无路）

| 想做的 | 实测结论 |
|---|---|
| **创建连线** | `createLink(端口,端口,线型,int,int)` 被接受但**恒返回 `false`**（9 种线型名一样）；`autoConnectDevices(d,d)` 静默无效；`connectLink`/`addLink`/`connect` 在 `network()` 上不存在 |
| **插硬件模块** | `addModule` 试了 7 种参数形式全 `Invalid arguments`；`removeModule` 同样进不去 |
| **保存工程文件** | `appWindow.save/saveAs`、`network.saveFile`、`ipcManager.save`、`systemFileManager.saveFile` 等 12 个候选入口全 `undefined` |
| **改 Logical 视图设备坐标** | `getCanvasItemIds()` 返回空、`getCanvasItemX(uuid)` 返回哨兵 `-9999999`；这组 API 是配 Physical 视图（机柜/楼宇）的 |

> 曾经列在这里的"配 AAA Server 用户/client 表"**已被推翻**：真类名是 `AcsServerProcess` 而不是我一开始猜的 `RadiusServerProcess`，读写接口都在。误判原因见下一节。

### ⛔ 会直接把 PT 进程搞崩

`AssessmentModel.getRunningConfig(...)` —— 实测让 PT 换了一次进程 PID。读配置请改用
`consoleLine.enterCommand("show running-config")` + 自动翻页。

完整清单（PT CLI 的 8 条怪癖、权限枚举真名、为什么 `printDebug` 不出声、1841 插 `WIC-1ENET` 后新口叫 `Ethernet0/1/0`）见 **[PT实测API表.md](PT实测API表.md)**。

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
