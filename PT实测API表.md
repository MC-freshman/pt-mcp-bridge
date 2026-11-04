# Packet Tracer 8.0 脚本模块 API 实测表

本机实测来源：`<PT 安装目录>\bin\PacketTracer.exe`
（8.0.0.0212，补丁版免登录）+ 随包 `help\default\*.htm` + 桥模块实跑。
每条都标了"实测"还是"文档说的"。**别再凭名字猜。**

## 一、模块生命周期（全实测）

| 事项 | 结论 |
|---|---|
| 新建入口 | `Extensions → Scripting → New PT Script Module` |
| 改动生效链 | 编辑器改完 → `Info` 页 **Save** → **Export** 成 `.pts` → `Configure Script Modules` 里 **Remove + Add** → **Start**。少一环都不生效 |
| 分发时那个弹窗 | 选 **No** 保持 `#include` 开发态（改磁盘 JS 后只要 Stop→Start）；选 Yes 会把代码内联进 `.pts`，之后每次改代码都要重导出 |
| 第三方模块要不要签名 | **不要**。`Publisher Signing` 留 `None Selected` 也能导出、注册、运行 |
| 权限授予 | `General` 页 Security 11 格勾满，且必须走完上面的生效链。实测默认只落进 `Application` + `IPC` 两档 |
| 权限枚举真名 | `APPLICATION` `GET_NETWORK_INFO` `CHANGE_NETWORK_INFO` `SIMULATION_MODE` `MISC_GUI` `CHANGE_PREFERENCES` `CHANGE_GUI` `ACTIVITY_WIZARD` `MULTIUSER`（9 个，**没有文件权限这一档**） |
| 运行中改代码 | 不生效，必须 Stop→Start |
| 模块存哪 | 用户数据树 `%USERPROFILE%\Cisco Packet Tracer 8.0\extensions\`，`PT.conf` 加密，`.pts` 也加密（搜不到任何明文片段） |
| PT 自己的日志 | `%USERPROFILE%\Cisco Packet Tracer 8.0\logs\*.log`，**GBK 编码**，明文记录模块起停和**每一条设备 CLI 命令**（`Router1: router1# ...`），可当崩溃判据和命令留痕 |

## 二、输出通道（踩出来的）

| 通道 | 结论 |
|---|---|
| `dprint(s)` | **唯一进 Debug 对话框的函数**。`printDebug` 不是全局，挂在 `AssessmentModel` 上，用错就一片安静 |
| Debug 对话框 | **自带输入框 = REPL**，敲一条求值一条，不用 Save/Export/Start。排查首选 |
| `writePlainTextToFile(path, text)` | **2 参，唯一写出干净原文的**（实测 19 字节原文一字不差） |
| `writeTextToFile(path, text)` | 不抛错但写出 U+FFFD 乱码（走了加密路径） |
| `writeBinaryToFile(path, text)` | 同上，12 字节乱码 |
| 上面两个的 3 参形式 | 抛异常 |
| `getFileContents(path)` | 读通道干净 |
| 结论 | **别取"第一个不抛错的签名"**，要用同一已知串各写一份比字节 |

## 三、能用的调用（全部实测通过）

```javascript
ipc.network().getDeviceCount()
ipc.network().getDeviceAt(i).getName() / .getClassName()
ipc.network().getDevice("Router0")
ipc.network().getLinkCount() / getLinkAt(i).getObjectUuid()   // Link 上只有 uuid 和 className
dev.getPortCount() / getPortAt(i) / getPort("FastEthernet0/0")
port.getName() / getClassName() / getLink() / getIpAddress() / setIpSubnetMask(ip, mask)
port.setDefaultGateway(gw) / setDnsServerIp(ip) / setDhcpClientFlag(b) / setPower(bool) / getMtu()
dev.getConsoleLine() / getIpcTerminalLine() / getVtyLine() / getLine()
consoleLine.enterCommand("show version")          // 单参
consoleLine.getOutput() / getPrompt() / getMode()
dev.enterCommand("cmd", true)                     // 必须双参，单参报 Invalid arguments
ipc.commandLog().getEntryCount()
ipc.simulation().isSimulationMode()
ipc.systemFileManager()                            // 需 File Operations 档
ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()
dev.setName("Switch0")                            // 改 PT 对象名，实测可用
dev.getPower() / setPower(bool)
dev.getModel()                                    // 返回 "1841"
ipc.options() / ipc.multiUserManager() / ipc.hardwareFactory()   // 对象能拿到，但方法名没探全
```

## 四、能力边界（2026-11-04 用官方在线文档纠正）

官方 Doxygen 文档：<https://tutorials.ptnetacad.net/help/default/IpcAPI/>
**先查文档再猜。** 我最初只靠 exe 字符串表 + `typeof` 扫描，把三个枚举的基值全猜错，
导致"放设备 / 连线 / 改位置"被误判成"做不到"，还在公开 README 里挂了一版。

### 能编程完成（实测）

| 事项 | 签名 | 实测记录 |
|---|---|---|
| 放设备 | `addDevice(DeviceType, string 型号, double x, double y)` → 新设备名 | `(8,"PC-PT",900,900)` → `"PC6"`，设备 20→21 |
| 删设备 | `removeDevice(QString)` | `true`，21→20 |
| 连线 | `createLink(设备A, 口A, 设备B, 口B, CONNECT_TYPES)` | `(…,8100)` → `true`，链路 18→19，口上出现 `Cable` |
| 删线 | `deleteLink(QString 设备, string 口)` | `true`，19→18；**只给一端**，给四段报 Invalid arguments |
| 改位置 | `moveToLocation(int,int)` / `moveToLocationCentered(int,int)` | PC5 +20px 再挪回，坐标精确 |
| 查支持模块 | `getSupportedModule()` → `vector<string>` | 1841 返回 12 个，含 `WIC-1ENET`、`HWIC-4ESW` |
| 枚举槽位 | `getRootModule()` → `Module.getModuleCount/getModuleAt/getSlotPath` | 插模块的槽名从这里取，别猜 |
| AAA 用户/client | `AcsServerProcess` 的 `addToClientMap` / `addToUserMap` / `deleteFrom*Map` / `removeAll*Records` | 读已实测；写接口存在 |
| **配 DHCP 作用域** | `getProcess("DhcpServerMainProcess").getDhcpServerProcessByPortName("FastEthernet0")` → `getPoolAt(0)` → `setStartIp/setMaxUsers/setDefaultRouter/setDnsServerIp` | 11-04 钓鱼实验：写进去回读 `start=192.168.1.10 max=60 dns=192.168.2.6 end=192.168.1.69`，面板如实显示。**`getPool("口名")` 返回 null，只有 `getPoolAt(0)` 有池；没有 `setSubnetMask`** |
| **开/关服务** | 各进程上的 `setEnable(bool)`：`DhcpServerProcess` / `DnsServerProcess` / `HttpServer` 都有 | 三台服务器实测 `isEnable/isEnabled` 从 false 翻成 true |
| **写服务器地址** | `port.setIpSubnetMask(ip, mask)` + `port.setDefaultGateway(gw)` | 界面 Config 页如实显示 `192.168.2.254`；**Port 上没有网关 getter，只能靠肉眼看界面确认** |
| **取拓扑图** | `getWorkspaceImage("PNG")` → `vector<byte>`，字节转 hex 走文本通道 | 已打通（见提交 3420393），参数是格式串不是路径 |

### 取值正门：`ipc.appWindow().getNetworkComponentBox()`

**先调这三个方法拿合法取值，别猜字符串。** 11-04 又白猜了一轮（`'Router-PT'`、`'Router1841'`、`'1841'` 当第一参）才想起它们：

| 方法 | 返回 | 实测内容 |
|---|---|---|
| `getDeviceTypes()` | 17 个类别名 | `Routers, Switches, Hubs, Wireless Devices, Boards, End Devices, Security, WAN Emulation, Home, Smart City, Industrial, Power Grid, Actuators, Sensors, Miscellaneous, Structured Cabling, Custom Made Devices` |
| `getDeviceModels(类别名)` | 该类别的型号串 | `Routers` → `1841, 1941, 2620XM, 2621XM, 2811, 2901, 2911, 819HG-4G-IOX, 819HGW, 829, CGR1240, ISR4321, ISR4331, Router-PT, Router-PT-Empty`；`Switches` → `2960-24TT, 2950-24, 2950T-24, Switch-PT, 3560-24PS, 3650-24PS, IE-2000, Bridge-PT`；`End Devices` → `PC-PT, Laptop-PT, Server-PT, Meraki-Server, NetworkController, Printer-PT, 7960, …, Sniffer` |
| `getConnectionTypes()` | 线型显示名 | `Console, Copper Straight-Through, Copper Cross-Over, Fiber, Phone, Coaxial, Serial DCE, Serial DTE, Octal, IoT Custom Cable, USB`（每项出现两次） |

**注意两个坑：**

1. `getDeviceTypes()` 的**数组下标不是 `addDevice` 的第一参**。第一参是 `DeviceType` 枚举：
   `1841` 用 `eRouter=0`、`2960-24TT` 用 `eSwitch=1`、`PC-PT` 用 `ePc=8`、`Server-PT` 用 `eServer=9`。
   实测 `addDevice(5,"PC-PT",…)`（5 是 `End Devices` 的下标）**返回空串不放设备**，必须用 8。
2. 传字符串当第一参时，纯数字串（`"1841"`）被当整数解析、静默返回空串；含字母的（`"Router"`）直接 `Invalid arguments`。
   两种都表现为"没放出来"，别据此判 API 不通。

### 三个枚举（**必须传数字，传字符串一律 false 且不报错**）

`DeviceType`（0–51）：
```
eRouter=0 eSwitch=1 eCloud=2 eBridge=3 eHub=4 eRepeater=5 eCoAxialSplitter=6
eAccessPoint=7 ePc=8 eServer=9 ePrinter=10 eWirelessRouter=11 eIpPhone=12
eDslModem=13 eCableModem=14 eRemoteNetwork=15 eMultiLayerSwitch=16 eSwitch3650=17
eLaptop=18 eTabletPC=19 ePda=20 eWirelessEndDevice=21 eWiredEndDevice=22 eTV=23
eHomeVoip=24 eAnalogPhone=25 eMultiUser=26 eASA=27 eIoE=28 eHomeGateway=29
eWirelessRouterNewGeneration=30 eCellTower=31 eCentralOfficeServer=32
eCiscoAccessPoint=33 eEmbeddedCiscoAccessPoint=34 eSniffer=35 eMCU=36 eSBC=37
eThing=38 eMCUComponent=39 eEmbeddedServer=40 eWirelessLanController=41 eCluster=42
eGeoIcon=43 eLightWeightAccessPoint=44 ePowerDistributionDevice=45 ePatchPanel=46
eWallMount=47 eSecurityAppliance=48 eMerakiServer=49 eNetworkController=50 ePLC=51
```

`CONNECT_TYPES`（**从 8100 起，不是 0**）：
```
FIRST_TYPE=8100 ETHERNET_STRAIGHT=8100 ETHERNET_CROSS=8101 ETHERNET_ROLL=8102
FIBER=8103 PHONE=8104 CABLE=8105 SERIAL=8106 AUTO=8107 CONSOLE=8108
WIRELESS=8109 COAXIAL=8110 OCTAL=8111 CELLULAR=8112 USB=8113 CUSTOM_IO=8114
BLUETOOTH_PAIRED=8115 BLUETOOTH_BROADCAST=8116
```

`ModuleType`（0–19），`addModule` 的参数顺序是 `(slot, ModuleType, model)`：
```
eLineCard=0 eNetworkModule=1 eInterfaceCard=2 ePtRouterModule=3 ePtSwitchModule=4
ePtCloudModule=5 ePtRepeaterModule=6 ePtHostModule=7 ePtModemModule=8 ePtLaptopModule=9
ePtTVModule=10 eIpPhonePowerAdapter=11 ePtTabletPCModule=12 ePtPdaModule=13
ePtWirelessEndDeviceModule=14 ePtWiredEndDeviceModule=15 eTrs35=16 eUsb=17
eNonRemovableModule=18 eASAPowerAdapter=19
```

> 教训一句话：**"不抛错但返回 false" 最容易被误读成"API 不支持"**，
> 实际往往是枚举值或参数顺序不对。遇到 false 先查文档里的枚举，别急着下否定结论。

### 真的做不到 / 会出事

| 想做的事 | 结论 |
|---|---|
| **保存 .pkt** | 官方文档原话："The API lacks project load/save functions"。`Options.saveFile(QString)` 只存偏好设置 |
| `AssessmentModel.getRunningConfig` | **崩 PT**（实测换 PID）。改用 `consoleLine.enterCommand("show running-config")` + 翻页 |
| `enterChar(...)` | 字符串和数字两种形态都 `Invalid arguments`；翻页用 `enterCommand(" ")` |
| `getDeviceNames()` | 不存在；循环 `getDeviceAt(i).getName()` |
| **DNS 加资源记录** | `DnsServerProcess` 上只有 `setEnable` 可写，`addARecord/addRecord/addRR/insertRecord/addNameServerDbEntry` 全不存在 → 只能 Services→DNS 面板手填 + 点 `Add` |
| **改 Web 页面正文** | `HttpServer` 只有 `getPage`，没有 `setPage/setPageContent/addPage` → 只能 Services→HTTP→`index.html` 的 `(edit)` 手改 |
| **让 PC 真的去取地址** | `port.setDhcpClientFlag(true)` 只改配置标志，**不发 Discover**；`DhcpClientProcess` 只有 `getDataOfPort/isConfigured/isPortExisted` 三个读方法，没有 start。翻转开关也不行 → 必须 GUI 点 Static→DHCP |
| **清 CLI 缓冲区** | `TerminalLine` 只有 `getOutput/getPrompt/getMode/getCommandPrompt/getRs232Port`，**没有清屏方法**。CLI 被报错行和重复命令搞脏时，唯一干净办法是 `removeDevice` + `addDevice` 重放（实测删 PDU 不牵连路由器配置） |

## 五、PT 的 CLI 怪癖（每条都坑过我）

1. **`--More--` 挂着时，下一条输入的首字符被分页器吃掉** → `terminal length 0` 变成 `erminal length 0`。破法：先发一个空格翻到干净。
2. **设备刚被访问时第一条命令常无回显** → 必须比对回显里有没有命令本身，没有就重发。
3. **设备会自己掉回用户模式**（`router1>`），配置类命令静默被拒 → 每段配置前补 `enable`。
4. **用户模式下敲 `no shutdown` 会触发 DNS 解析**（`Translating "no"...domain server`），CLI 会卡住几秒。
5. **`getHostName()` 返回的是 PT 型号默认名（`Router`），不是 IOS 的 hostname**。判 hostname 看提示符 `router1#`，别用这个方法。
6. **1841 插 `WIC-1ENET` 后新口叫 `Ethernet0/1/0`**，不是 `FastEthernet1/0`。
7. **1841 的模块列表里没有 `NM-2FE`**（那是 2600/2800 的），要加可路由 FE 口选 `WIC-1ENET`；`HWIC-4ESW` 是设备内二层交换机，不能当 PPPoE 三层口。
8. `write memory` 在 PT 的 1841 上会回 `Building configuration... [OK]`，但它**不影响 `.pkt` 文件**——文件还是要 Ctrl+S。
9. **新设备开机停在 `Would you like to enter the initial configuration dialog? [yes/no]:`**。`no` 必须等这行文本真出现在 `getPrompt()` 里再发；发早了（boot 没完成）后面**整段配置命令全被当对话框回答吞掉**，而且每条都"执行成功"、只是提示符一直停在那句问话上。11-04 实测 18 条命令白发自救方式只有删设备重来。
10. **设备可能留在全局配置模式**，此时 `show running-config` 和 `terminal length 0` 都回 `% Invalid input detected at '^' marker.`。读配置前先发 `end` 再 `enable`。
11. **`%LINK-5-CHANGED: Interface … changed state to up` 不是报错**。用"输出里有 `%` 就算被拒"当判据会误杀；只认 `%Invalid / %Incomplete / %Ambiguous / %Error / %Unknown`。
12. **`addDevice(0,"1841",x,y)` 会顺带放出一台 `Power Distribution Device`**（`DeviceType ePowerDistributionDevice=45`），设备计数 +2。删它实测**不牵连**路由器的 IOS 配置。

## 六、还没验的

- ExApp/CEP 通道：PT 在 `127.0.0.1` 开了 **38000 / 39000**（日志 `CPtmpServer started at port ...`），`ipc.ipcManager().getListeningPort()` 有权限可调；ExApp 清单字段含 `EXECUTABLE_PATH` / `INTEGRITY_FILE_HASH` / `CERTIFICATE` / `--no-ssl-enforce`。
- **已排除的猜测**：`LogicalWorkspace` 的 `addDevice/createLink` **不需要 ExApp 身份**，普通 Script Module 勾满权限即可调用（11-04 钓鱼实验全程用 Script Module 放设备连线，未接 ExApp）。
- `ipc.options()` / `ipc.hardwareFactory()` / `ipc.appWindow()` 上的方法名没扫全（我只测了自己猜的那批）。

## 七、读数会骗你的四个通道（11-04 实测，都造成过假阴性）

| 通道 | 它说什么 | 真相 |
|---|---|---|
| `DnsServerProcess.getIpAddOfDomain("www.test.com")` | `0.0.0.0` | **读的是缓存**。记录其实已在库里，要用 `getRrFromNameServerDbAt(0)` 取 data 对象，字段是 `name / ipAddress / pduType / ttl`（实测 `www.test.com → 192.168.2.5, DnsRrA, 86400`）。`getEntryCount()` 也是缓存数（恒 0），记录条数看 `getSizeOfNameServerDb()` |
| `HttpServer.getPage("index.html")` | 恒 369 字符的内置默认页 | **不反映设备上编辑过的页面**。用户把 `Cisco Packet Tracer` 改成 `Forged Web Server` 之后它仍返回原文，我据此误判"你没提交"。唯一判据是浏览器实际响应 |
| `DhcpPool.getLeaseAt(i)` | 两台 DHCP 的表里都记 `192.168.1.11(PC0 的 MAC)` | 而 PC0 实际用的是 `.10`。**PT 的租约簿记与客户端采纳的地址不对齐**，不能拿它判"哪台应答了"。判据换成"下发的 DNS 字段值"（`192.168.3.1` 只存在于伪造池） |
| `dev.getHostName()` | 型号默认名 `Router` | 不是 IOS hostname，判 hostname 看提示符（第五节第 5 条） |

> 共同教训：**"读不到"要先怀疑通道，再怀疑事实。** 尤其当一个方法返回 `0` / `0.0.0.0` / 空串 / 恒定值时，
> 它可能是另一张表的接口，而不是当前对象的 getter。断言"没配好"之前，换一个独立通道（最好是应用自己的输出）复核。

## 八、MCP server 挂了怎么办（11-04 实测）

| 现象 | 判据 | 退路 |
|---|---|---|
| `mcp_call` 一律回 `Streamable HTTP error: Error POSTing to endpoint: Not Found` | **先查 PT 进程**：`Get-Process -Id <PID>` 有返回且 `Responding=True`、窗口标题还在 → PT 活着，是 MCP server 自己掉了 | 直接走 `python ptctl.py js "<ES5 表达式>"`，文件通道（`cmd.txt`/`resp.txt`）照常工作，能力与 `pt_eval` 完全等价 |
| `pt_health` 回 `TIMEOUT` 且 PID 变了 | PT 重启过，桥模块没再 Start | 让用户 `Extensions → Scripting → Configure Script Modules` 点 Start |
| `ptctl.py` 报 `PermissionError: [WinError 5] … cmd.txt.tmp -> cmd.txt` | 桥目录被并发读走（多会话共用同一目录） | 等 1–3 秒重试即可，不是逻辑错误 |
| 长 JS 用 `python -c` 内联报 `SyntaxError: Parse error` | shell 吃引号/反斜杠 | 写成 `.py` 文件再跑，JS 放 raw string 里 |
