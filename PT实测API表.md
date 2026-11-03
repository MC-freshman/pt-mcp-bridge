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

## 四、不可用 / 会出事（GUI-only 清单）

| 想做的事 | 为什么不行 | 只能怎么办 |
|---|---|---|
| **连线** | `createLink(p,p,线型,int,int)` 被接受但**恒返回 false**（9 种线型名都一样）；`autoConnectDevices(d,d)` 静默无效；`connectLink`/`addLink`/`connect` 在 `network()` 上不存在 | GUI 闪电图标手连 |
| **插模块** | `addModule` 7 种参数形式全 `Invalid arguments`；`removeModule` 同样进不去 | Physical 页断电→拖模块→通电 |
| **存盘** | `appWindow.save/saveAs`、`network.saveFile`、`ipcManager.save`、`systemFileManager.saveFile` 等 12 个入口全 undefined | `Ctrl+S` |
| **AAA Server 用户/client 表** | `addAAAClient`/`addAAAUser` 只是 GUI 控件槽函数名；`getProcess("RadiusServerProcess")` 上只有 `getPort`/`setPort` | Services→AAA 面板手填 |
| **Logical 视图设备坐标** | `getCanvasItemIds()` 返回空、`getCanvasItemX(uuid)` 返回哨兵 `-9999999`；这组 API 是配 Physical 视图（机柜/楼宇）的 | 手拖 |
| **`AssessmentModel.getRunningConfig`** | **直接把 PT 进程搞崩**（实测换 PID） | 用 `consoleLine.enterCommand("show running-config")` + 翻页替代 |
| **`enterChar(...)`** | 字符串和数字两种形态都 `Invalid arguments` | 翻页用 `enterCommand(" ")` |
| **`getDeviceNames()`** | 不存在 | 循环 `getDeviceAt(i).getName()` |

## 五、PT 的 CLI 怪癖（每条都坑过我）

1. **`--More--` 挂着时，下一条输入的首字符被分页器吃掉** → `terminal length 0` 变成 `erminal length 0`。破法：先发一个空格翻到干净。
2. **设备刚被访问时第一条命令常无回显** → 必须比对回显里有没有命令本身，没有就重发。
3. **设备会自己掉回用户模式**（`router1>`），配置类命令静默被拒 → 每段配置前补 `enable`。
4. **用户模式下敲 `no shutdown` 会触发 DNS 解析**（`Translating "no"...domain server`），CLI 会卡住几秒。
5. **`getHostName()` 返回的是 PT 型号默认名（`Router`），不是 IOS 的 hostname**。判 hostname 看提示符 `router1#`，别用这个方法。
6. **1841 插 `WIC-1ENET` 后新口叫 `Ethernet0/1/0`**，不是 `FastEthernet1/0`。
7. **1841 的模块列表里没有 `NM-2FE`**（那是 2600/2800 的），要加可路由 FE 口选 `WIC-1ENET`；`HWIC-4ESW` 是设备内二层交换机，不能当 PPPoE 三层口。
8. `write memory` 在 PT 的 1841 上会回 `Building configuration... [OK]`，但它**不影响 `.pkt` 文件**——文件还是要 Ctrl+S。

## 六、还没验的

- ExApp/CEP 通道：PT 在 `127.0.0.1` 开了 **38000 / 39000**（日志 `CPtmpServer started at port ...`），`ipc.ipcManager().getListeningPort()` 有权限可调；ExApp 清单字段含 `EXECUTABLE_PATH` / `INTEGRITY_FILE_HASH` / `CERTIFICATE` / `--no-ssl-enforce`。**带 `createLink`/`addDevice` 的 `LogicalWorkspace` 是否只对 ExApp 开放，未知。**
- `ipc.options()` / `ipc.hardwareFactory()` / `ipc.appWindow()` 上的方法名没扫全（我只测了自己猜的那批）。
