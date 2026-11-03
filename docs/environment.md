# 运行环境（F1 + BlueStacks）

> 更新：2026-11-03
>
> 这份记**环境事实和踩过的坑**，不记行动计划。接手前先读
> [`handoff.md`](handoff.md) §3，再看这份。

## 1. 机器

| 项 | 值 |
|---|---|
| 主机 | 火影 F1 |
| CPU | AMD R5-7640HS（6C/12T） |
| 内存 | 24 GB 板载（可用约 19.8 GB） |
| 磁盘 | 512 GB NVMe，C 盘剩余约 414 GB |
| 系统 | Windows 11 Pro |
| 网络 | 仅 WiFi（Realtek 8852BE），另有 2.5GbE 未使用 |
| 远程 | Tailscale + OpenSSH + Windows App（RDP） |

## 2. 模拟器：BlueStacks 5

| 项 | 值 |
|---|---|
| 版本 | 5.22.286.1004 |
| 程序 | `C:\Program Files\BlueStacks_nxt` |
| 数据 | `C:\ProgramData\BlueStacks_nxt` |
| 配置 | `C:\ProgramData\BlueStacks_nxt\bluestacks.conf` |
| 日志 | `C:\ProgramData\BlueStacks_nxt\Logs\Player.log` |
| 管理器 | `C:\Program Files\BlueStacks_nxt\HD-MultiInstanceManager.exe` |
| adb | `C:\Program Files\BlueStacks_nxt\HD-Adb.exe` |

### 2.1 实例现状

| 实例（目录） | 显示名 | Android | abi_list | adb 端口 | LoR |
|---|---|---|---|---|---|
| **`Pie64`** | BlueStacks App Player | **9** | `x86,x64,arm,arm64` | **5555** | ✅ **能跑** |
| `Rvc64` | Lor Player | 11 | `x86,x64,arm,arm64` | 5555 | ❌ 闪退 |
| `Rvc64_2` | Lor Player ARM | 11 | `arm,arm64` | 5575 | ❌ 闪退 |

**结论：只有 `Pie64` 可用。** `Rvc64` / `Rvc64_2` 可以删掉
（在多开管理器里右键删除，让 BlueStacks 自己清理配置和磁盘）。

**不要删 `Pie64`。**

### 2.2 为什么 Android 11 不行（2026-11-03 实测）

同一份 APK、同一个 BlueStacks 版本，只改 Android 版本：

| 实例 | Android | 结果 |
|---|---|---|
| `Rvc64` | 11 | 启动约 0.6 秒后 `SIGSEGV`，进程死，回桌面 |
| `Rvc64_2`（ABI 选 `ARM`） | 11 | **同样** `SIGSEGV` |
| `Pie64` | 9 | 正常启动，登录页，可登录，下载资源 |

**换 ABI 配置不解决问题**——`Rvc64_2` 把 ABI 限制成 `arm,arm64` 后崩溃完全一样。
变量是 **Android 版本**，不是 ABI。

#### 崩溃细节（已确认的部分）

从 `dumpsys dropbox --print SYSTEM_TOMBSTONE` 取到完整记录：

```
signal 11 (SIGSEGV), code 2 (SEGV_ACCERR), fault addr 0x0
ABI: 'x86_64'
backtrace:
      #00 pc 0000000000000000  /dev/zero
```

对 `libart.so` 反汇编后确认：

| 项 | 内容 |
|---|---|
| 崩溃指令 | `libart.so + 0x170bda` 的 `call qword ptr [rdi + 0x20]` |
| 寄存器 | `rdi = 0` |
| 返回地址 | `0x170bdd`，与栈顶一致（字节对齐已验证） |
| `+0x20` 的含义 | ART `ArtMethod::entry_point_from_quick_compiled_code_` |
| 后续代码 | 判断返回类型 `'D'`/`'F'`，再 `lea r12,[r12+6]`（一条 35c invoke 的长度） |
| 附近同类模式 | `call [rdi+0x20]`、`cmp [rdi+0x20], rax` → 确认是 nterp 的 invoke 处理器 |

即：**ART 解释器执行 invoke 时，方法指针为空，跳到地址 0 取指**。
`SEGV_ACCERR`（不是 `MAPERR`）说明地址 0 所在页有映射但不可执行，
符合"读到 0 → 跳过去 → 取指失败"。

#### 还没确认的

- **哪个 Java 方法**：`r12` 指向 `[anon:dalvik-DEX data]`，那段字节解出来像
  `invoke-virtual {v12}, method@235`，但该字节序列在 `classes.dex` /
  `classes2.dex` 里**都不存在**，所以无法映射到具体方法。该区域可能属于
  另一个已加载的 DEX（崩溃前最后一条日志是 GMS `DynamiteModule` 选择）。
- **为什么方法指针为空**：nterp 处理器靠跳转表进入，线性反汇编在
  `0x170b80` 之前会失步，静态分析到此为止。要往下走需要 root
  （读 `/data/tombstones/` 和 LoR 自带的 Breakpad minidump）。

**不要再把这件事归因于"模拟器不支持 ARM"**——`Pie64` 也是 x86 主机 + ARM64
分包 + Houdini 翻译，一样能跑。日志里 `houdini: Initialize library ...
successfully` 在能跑和不能跑的实例上都出现过。

### 2.3 图形层的独立问题

`Player.log` 里两个实例都有大量：

```
E: Shader Compilation Failed, error = ERROR: 0:3: ...
E: translator::gles2::glLinkProgram: ...
 ERROR: Linking fragment stage: when more than one fragment shader output,
        all must have location qualifiers
```

这是**宿主机图形翻译层**的报错，与上面的 Java 崩溃不是同一件事。
`Pie64` 上也报，但 LoR 能正常渲染，所以目前不影响使用；如果以后出现画面异常，
先怀疑这里。

### 2.4 root

`bluestacks.conf` 里三个实例都是 `enable_root_access="0"`。
`adb root` 会回 `restarting adbd as root`，但 `id` 仍是 `uid=2000(shell)`——
**没有真正生效**。

要开 root：停实例 → 设置里开 root → **重启实例**（配置在重启时才落盘）。
开了以后才能读 `/data/tombstones/` 和 `/data/data/<pkg>/`。

## 3. LoR 安装包

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `C:\Windows\Temp\lor_base.apk` | 43,627,043 | `0256c2423751929f0a278a3ed984256214488b9530ef7305e65c74441256fce8` |
| `C:\Windows\Temp\lor_arm64.apk` | 50,296,413 | `34adc6f71de97ac61eda8ed0b49b8ceedf2a2ce2f6d25e615f92f030e404d59c` |

从用户的小米手机导出（`pm path` 得到 `base.apk` + `split_config.arm64_v8a.apk`）。

| 项 | 值 |
|---|---|
| 包名 | `com.riotgames.legendsofruneterra` |
| versionName | `07.10.013` |
| versionCode | `710013` |
| minSdk / targetSdk | 24 / **36** |
| primaryCpuAbi | `arm64-v8a` |

安装（split APK 必须用 `install-multiple`）：

```powershell
adb -s 127.0.0.1:5555 install-multiple -r `
  C:\Windows\Temp\lor_base.apk C:\Windows\Temp\lor_arm64.apk
```

单独装 `base.apk` 会报 `INSTALL_FAILED_MISSING_SPLIT`。

## 4. 屏幕

| 项 | 值 |
|---|---|
| 分辨率 | **1280 × 720** |
| density | 240 |

`Pie64` 建实例时选的就是 1280×720。想改 1080p 可以用
`adb shell wm size 1920x1080` + `wm density 240`，但**改完必须重新标定坐标和模板**。

## 5. ADB 的坑（Windows + SSH）

### 5.1 adb daemon 会随 SSH 会话消失

**每条 `ssh f1` 命令结束后，adb daemon 会被回收**，下一次连接时设备就"不见了"。

现象：

```
adb devices          → 空
adb -s 127.0.0.1:5555 shell ... → device '127.0.0.1:5555' not found
```

**修法：把 `start-server` / `connect` 和后续命令写在同一次调用里。**

```powershell
$a = (Get-Command adb.exe).Source
Get-Process adb -ErrorAction SilentlyContinue | Stop-Process -Force
& $a start-server
& $a connect 127.0.0.1:5555
# ↓ 后续命令必须和上面在同一个脚本里
& $a -s 127.0.0.1:5555 shell ...
```

### 5.2 同一个实例会以两个名字出现

`adb devices` 里可能同时有：

```
127.0.0.1:5555    device
emulator-5554     device
```

**是同一个实例**。不带 `-s` 会报 `more than one device/emulator`。
统一用 `-s 127.0.0.1:5555`。

### 5.3 实例必须先由人在 GUI 启动

从 SSH 会话用 `Start-Process HD-Player.exe` 启动的实例**会自己退出**
（Pie64 实测约 25 秒后消失）。模拟器需要交互式桌面会话。

**启动/关闭实例让用户在多开管理器里点**，不要试图从命令行拉起。

## 6. 迷你模式

BlueStacks 的「迷你模式」只改变**宿主窗口**的显示方式，
**不影响 ADB**：`screencap`、`shell`、`install` 在迷你模式下都正常
（本次 1280×720 的截图就是在迷你模式开启期间抓的）。

ADB 输入走的是 guest 内部输入栈，与宿主窗口状态无关；
不过**触摸注入没有在迷你模式下单独验证过**，第一次在迷你模式下跑动作时留意一下。

## 7. 当前进度（2026-11-03）

- `Pie64` 已装 LoR，**已登录**（账号信息不记录在本仓库）
- 首次进入需下载 **3278 MB** 游戏资源，正在下载
- **还没到主菜单**，因此以下都还没验证：
  - 英雄之路入口是否可达
  - 对局界面能否正常渲染
  - 1280×720 下的坐标标定

## 8. 复现环境的最短路径

1. 确认 `Pie64` 存在且 Android 9（`adb shell getprop ro.build.version.release`）
2. 起实例（用户点 GUI）→ `adb connect 127.0.0.1:5555`
3. `install-multiple` 两个 APK
4. 启动 `am start -n com.riotgames.legendsofruneterra/.LoRActivity`
5. 等资源下载完 → **手动登录**（程序不碰账号密码）
6. 从 `docs/handoff.md` §2 第 1 步开始
