# Packet Tracer 8.0 × MCP 桥

让 AI agent 通过 MCP 协议驱动 Cisco Packet Tracer 8.0：读设备配置、往 IOS CLI 注命令、枚举拓扑与连线、改设备名、配终端 IP。

做成这件事的难点不在 MCP，而在 **Packet Tracer 是一个完全封闭的目标**：没有命令行接口、没有 headless 模式、`.pkt` 工程文件全加密、随包的 `.pts` 模块也全加密。本仓库记录的是**逆向出来的可用边界**，以及在这个边界内搭起来的一条稳定通路。

实测环境：Packet Tracer **8.0.0.0212** Win64（免登录补丁版）· Python **3.9.13**（仅标准库）· Windows 11。

---

## 架构

```
AI agent  ──stdio JSON-RPC──▶  pt_mcp.py  ──写──▶  cmd.txt
   ▲                              │                    │ 每 400ms 轮询
   │                              │                    ▼
   └──── resp.txt ◀──写───────────┴────  PT 进程内的 Script Module（ECMAScript/QtScript）
                                              │
                                              ▼  ipc.* / AssessmentModel / consoleLine
                                        模拟网络里的设备（CLI、路由、拓扑）
```

传输层刻意选了**共享目录里的两个文件**，不是 HTTP、不是命名管道：因为 PT 的脚本引擎能直接读写本机文件（`ipc.systemFileManager()`），这条路零依赖、零端口、崩溃后不留残留连接。

PT 侧的载体是 **Script Module**——PT 自带的扩展机制，JS 跑在 PT 进程内，能拿到 `ipc.*` 这套内部接口。第三方模块**不需要签名**就能加载（实测）。

---

## 快速开始

### 1. PT 侧装模块

| 步 | 操作 | 关键判据 / 坑 |
|---|---|---|
| 1 | `Extensions → Scripting → New PT Script Module` | 标题栏出现 `Scripting - New PT Script Module0 (Stopped)` |
| 2 | `General` 页：填 `Name`、`ID`（层级式如 `com.yourcompany.ptbridge`）；`Publisher Signing` 留 `None Selected`；密码留空；`Startup` 选 `On Demand` | 设了密码的话，你自己回来看脚本也要输密码 |
| 3 | `General` 页底部 **Security 11 格全勾** | ⚠️ 只勾 `Application`+`IPC` 的话，`ipc.network()` 和 `systemFileManager()` 全部 `PRIVILEGE_DENIED` |
| 4 | `Script Engine` 页 → `+` 新建脚本文件 → 粘 `bridge/module_entry.js` 的那一行 `#include` | 用 `#include` 而不是粘全文：以后改磁盘 JS 只要 Stop→Start 就生效 |
| 5 | `Info` 页 → **Save** | 不点这个 Save，改动不落盘 |
| 6 | `Info` 页 → **Export** → 存成 `.pts`；弹窗 *"resolve and expand them inline?"* 选 **No** | 选 Yes 会把代码烧进 `.pts`，之后每次改代码都得重新导出 |
| 7 | `Extensions → Scripting → Configure Script Modules ...` → 选中该模块 → **Remove** → 再 **Add Script Module** 选同一个 `.pts` → 权限列表核对 → 允许 → **Start` | ⚠️ Remove+Add 不能省：PT 把权限快照记在自己的选项里，只覆盖 `.pts` 不重注册，旧条目仍按老权限跑 |

PT 的用户数据目录在 `%USERPROFILE%\Cisco Packet Tracer 8.0\`，模块落它的 `extensions\`，**明文 GBK 日志**落 `logs\*.log`——里面逐条记录了每一条设备 CLI 命令，是排查和留痕的免费通道。

### 2. 适配你的机器

Python 侧走环境变量，不用改代码：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `PT_BRIDGE_DIR` | `C:\pt_bridge` | 桥目录（`cmd.txt`/`resp.txt`/`log.txt`/`alive.txt` 所在处） |
| `PT_BRIDGE_TOKEN` | `CHANGE_ME` | 与 PT 侧模块的口令配对 |

JS 侧**必须手改三处**——PT 的 QtScript 引擎读不到环境变量，这是它的硬限制：

| 文件 | 常量 | 说明 |
|---|---|---|
| `bridge/bridge_module.js` | `CFG.bridge` | 要和 `PT_BRIDGE_DIR` 指到同一个目录 |
| `bridge/bridge_module.js` | `CFG.token` | 要和 `PT_BRIDGE_TOKEN` 一致，不一致时模块会回 `bad token` 并拒绝执行 |
| `bridge/module_entry.js` | `#include` 的路径 | 指向 `bridge_module.js` 的绝对路径 |

桥目录**建议用纯 ASCII、不带空格**的路径：PT 的文件接口和 Python 在中文路径上都有已知的坑。

### 3. 注册进 MCP 客户端

```
command: python
args:    ["<绝对路径>/pt_mcp.py"]
```

### 4. 验证

```bash
python ptctl.py status          # 看心跳与自检日志
python test_offline.py          # 离线自测（不连 PT）
python test_mcp_live.py         # 端到端：MCP -> 文件队列 -> PT -> 设备 CLI
```

`test_offline.py` 不需要 PT 在跑；`test_mcp_live.py` 需要模块处于 Start 状态。

---

## MCP 工具（11 个）

| 工具 | 作用 | 会不会动设备 |
|---|---|---|
| `pt_health` | 桥与 PT 健康检查，把"模块没 Start / PT 重启过 / 权限被拒"三种失效**分开报** | 只发一次 `1+1` |
| `pt_status` | 桥目录各产物文件的字节数与内容片段 | 否 |
| `pt_devices` | 设备清单 `名称:类型` | 只读 |
| `pt_wiring` | **连线表**：每台交换机挂了哪些端点、哪条是半截线、哪些链路不经交换机 | 只读，实验途中可安全调 |
| `pt_cli` | 注一条 IOS 命令，自动破 `--More--` 分页，回新增输出 + 结束时提示符/模式 | 是 |
| `pt_script` | **一次调用喂一整段命令**，逐条核对提示符层级、自动补 `enable`、带 MCP progress 通知 | 是 |
| `pt_running_config` | 整份 running-config（内部先确保 enable） | 是 |
| `pt_command_log` | PT 记录的命令条数，用来核对注入是否落地 | 只读 |
| `pt_aaa_state` | **读 AAA(ACS) 服务的真实内容**：是否启用、client 表（名称/IP/密钥/类型）、user 表 | 只读 |
| `pt_processes` | 列某台设备装载了哪些协议进程（112 个候选名逐个 `getProcess`） | 只读，不触发行为 |
| `pt_eval` | 逃生舱：求值任意 ECMAScript。工具描述里点名了会崩 PT 的调用 | 看代码 |

所有失败带 `failure_class`：`PRIVILEGE_DENIED / INVALID_ARGS / IPC_ERROR / TIMEOUT / NO_ECHO`，agent 不用靠猜分诊。

参考用量：一台 1841 路由器 34 条配置命令，`pt_script` 一次调用完成；此前逐条 `pt_cli` 是 34 次往返、每次 0.4–1.5 秒。

---

## 能做到什么、做不到什么

### ✅ 已实测可用

```javascript
ipc.network().getDeviceCount() / getDeviceAt(i) / getDevice("Router0")
dev.getPortCount() / getPortAt(i) / getPort(name) / setName("Switch0") / getPower() / setPower(bool)
port.getName() / getClassName() / getLink() / getIpAddress()
port.setIpSubnetMask(ip, mask) / setDefaultGateway(gw) / setDnsServerIp(ip) / setDhcpClientFlag(b)
dev.getConsoleLine() → enterCommand("show version") / getOutput() / getPrompt() / getMode()
dev.enterCommand("cmd", true)                    // 注意：设备级必须双参
ipc.commandLog().getEntryCount()
ipc.simulation().isSimulationMode()
ipc.systemFileManager() → writePlainTextToFile(path, text) / getFileContents(path)
ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()   // 对象能拿到
```

### ❌ 做不到，只能 GUI 手点（每条都试到确认无路）

| 想做的 | 实测结论 |
|---|---|
| **创建连线** | `createLink(端口,端口,线型,int,int)` 被接受但**恒返回 `false`**（9 种线型名都一样）；`autoConnectDevices(d,d)` 静默无效；`connectLink`/`addLink`/`connect` 在 `network()` 上不存在 |
| **插硬件模块** | `addModule` 试了 7 种参数形式全 `Invalid arguments`；`removeModule` 同样进不去 |
| **保存工程文件** | `appWindow.save/saveAs`、`network.saveFile`、`ipcManager.save`、`systemFileManager.saveFile` 等 12 个候选入口全 `undefined` |
| **配 AAA Server 的用户/client 表** | ⚠️ **本条已被推翻**：`getProcess("AcsServerProcess")` 上实测有 `isEnabled` / `getClientRecordsAsString` / `getUserRecordsAsString`（读）与 `enableACSServerService` / `addToClientMap` / `addToUserMap` / `deleteFromClientMap` / `deleteFromUserMap` / `removeAllUserRecords` / `removeAllClientRecords`（写）。早前判成"只能手填"是因为只按猜的名字扫了 `RadiusServerProcess`，没扫到真类名 `AcsServerProcess`。已封装成 `pt_aaa_state` 工具 |
| **改 Logical 视图的设备坐标** | `getCanvasItemIds()` 返回空、`getCanvasItemX(uuid)` 返回哨兵 `-9999999`；这组 API 是配 Physical 视图（机柜/楼宇）的 |

### ⛔ 会直接把 PT 进程搞崩

`AssessmentModel.getRunningConfig(...)` —— 实测让 PT 换了一次 PID。读配置请改用
`consoleLine.enterCommand("show running-config")` + 自动翻页。

完整清单（含 PT CLI 的 8 条怪癖、权限枚举真名、为什么 `printDebug` 不出声）见
**[PT实测API表.md](PT实测API表.md)**。

---

## 这些结论是怎么来的

1. **抽字符串表**：`python tools/strings_probe.py <PacketTracer.exe> strings.txt`。
   PT 把 `.pki` 接口声明编译进 exe，每个接口块都以 `getClassName / getObjectUuid / registerObjectEvent / unregisterObjectEvent` 开头。以 `registerObjectEvent` 为锚点向前找类名、向后收方法名，本机还原出 **201 个接口块**——`TerminalLine` 有 103 个方法、`ConsolePort.getTerminalLine()`、`CiscoDevice.enterCommand()` 这些关键事实全是从这里来的。
2. **`typeof` 扫描**：把候选方法名拼成 `String(typeof obj.method)` 通过桥投进去，区分"存在但参数不对"和"根本不存在"，零副作用。见 `probes/probe_names.py`。
3. **同串比字节**：同一个已知字符串用所有可疑签名各写一份，再比字节——**不要取"第一个不抛错的"**。实测 `writeTextToFile` / `writeBinaryToFile` 不抛错但写出 U+FFFD 乱码，只有 `writePlainTextToFile(path, text)` 两参是干净的。见 `probes/probe_cable.py`。
4. **投一条比一次宿主 PID**：入口钩子里不放任何危险调用，可疑调用由外部逐条投，每投一条检查进程是否还在，崩点自己就浮出来。见 `probes/probe_ws.py`。

---

## 目录

```
pt_mcp.py              MCP server（stdio JSON-RPC，纯标准库）
ptctl.py               命令行驱动 + 传输层（也被 server 复用）
ptplus.py              纯逻辑：错误五分类、连线表解析、批量汇总、验收断言
bridge/
  bridge_module.js     跑在 PT 进程里的桥（改它只需 Stop→Start）
  module_entry.js      PT 里只需粘这一行 #include
probes/                API 探测脚本（typeof 扫描 / 签名字节比对 / 崩点定位）
tools/strings_probe.py 从 exe 还原 IPC 接口表
tools/ipc_map.py       接口地图 + 全设备进程扫描 + 服务数据收割（两阶段：先列存在性再取数据）
test_offline.py        离线自测，不连 PT
test_mcp_live.py       端到端自测
PT实测API表.md         全部实测结论
```

---

## 安全警告

这条桥的语义是：**本机任何进程往 `cmd.txt` 写一下，就能在 Packet Tracer 进程里执行任意 JavaScript**。

- `CFG.token` 只能挡住误投和其它工具乱写，**挡不住同一用户的其它进程**（口令就存在该用户的目录里）。
- 仓库里发的是占位符 `CHANGE_ME`：**上手第一件事**是把它换成你自己的随机串（JS 侧一处 + `PT_BRIDGE_TOKEN` 一处）。不改就直接用 `CHANGE_ME` 的话，任何本机进程知道这个默认值就能驱动 PT。
- 别把桥目录放进共享目录或网盘。
- 桥目录建议保持纯 ASCII 绝对路径，且不要带空格。

## License

MIT —— 见 [LICENSE](LICENSE)。逆向得到的 API 结论本身不受版权保护，但请注意 Packet Tracer 是 Cisco 的闭源软件，本仓库不含它的任何二进制或文件。
