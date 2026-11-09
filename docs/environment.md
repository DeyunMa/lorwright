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
| 原生分辨率 | 1280 × 720 |
| **实际使用的逻辑分辨率** | **1920 × 1080**（`adb shell wm size 1920x1080`） |
| density | 240 |

`Pie64` 建实例时选的是 1280×720。**原生 720p 下不可用**：手牌费用数字只有 ~10px，
字形读不出来。抬高到 1080p 后徽章数字约 15px、血量约 34px，才可读。

`wm size` 是**运行时覆盖**，2026-11-04 那次模拟器重启后**仍然保留**（`wm size` 显示
`Physical 1280x720 / Override 1920x1080`）。但不能假设它永远在——`lorwright doctor` 会核对。

改分辨率要重新标定：`config/settings.yaml` 的 `layout` 与 `assets/` 下的模板都按
**设计尺寸**（`config.screen`）标定，`perceive/normalize.py` 负责把实际截图归一化过去。

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

## 7. 当前进度（2026-11-04）

- `Pie64` 已装 LoR（`live_7-10-13`，区域 jpn/apac），能进主菜单、英雄之路、对局
- 账号密码在 `.env`（`LOR_USERNAME` / `LOR_PASSWORD`），`lorwright login` 可自动登录
- 1080p 标定完成，感知链路真机验证过（法力 / 血量 / 手牌费用 / UI 状态）
- **未完成**：出牌手势（issue #9）、场面识别（#10）

### 7.1 模拟器重启会清掉 LoR 登录态

重启实例后 LoR 回到 Riot 登入页，需要重新登录。所以：

- **不要**把「重启客户端」当作卡住时的恢复手段（见 `handoff.md` §4.7）
- 恢复流程要等自动登录接上之后再打开（`recovery.allow_client_restart`）

### 7.2 网络不可达会让登录页假死

现象：停在「登入以開始遊戲」，点任何按钮都没反应，画面**完全静止**。

真因（logcat）：

```
[BaconAuthenticationProvider] Waiting on client config to be loaded
Firestore: connect failed to firestore.googleapis.com:443 … ECONNREFUSED
```

Riot 自己的域名（`fe-apac-green.b.pvp.net:443`）通、Google 的域名不通时就会这样。
先修网络（代理 / TUN），再谈自动化。

### 7.3 游戏进程会冻死在启动页

现象同上但原因不同：进程无响应。判据：

```bash
# 连续两帧 0 差异（用 lorwright shot 连拍两张对比）
adb shell input keyevent 3        # HOME 能生效 → 系统正常，是游戏冻死
```

处理：`adb shell am force-stop com.riotgames.legendsofruneterra` + `lorwright launch`。

固化这条检查见 issue #12。

## 8. 复现环境的最短路径

1. 确认 `Pie64` 存在且 Android 9（`adb shell getprop ro.build.version.release`）
2. 起实例（用户点 GUI）→ `adb connect 127.0.0.1:5555`
3. `install-multiple` 两个 APK
4. 启动 `am start -n com.riotgames.legendsofruneterra/.LoRActivity`
5. 等资源下载完 → `lorwright login`（账号从 `.env` 读，或手动登录一次）
6. 从 `docs/handoff.md` §2 第 1 步开始

## 9. f1 上的独立看门狗

| 任务 | 频率/身份 | 职责 |
|---|---|---|
| `F1NetWatchdog` | 2 分钟 / SYSTEM | HTTP、DNS、Tailscale；Clash/TUN/WiFi/Tailscale 分级恢复 |
| `F1GameWatchdog` | 5 分钟 / SYSTEM | `HD-Player`、ADB、LoR `pidof`；最外层重启 |
| `F1StartPie64` | 手动/被调用 / Administrator + Interactive | 在交互桌面启动 Pie64；已在跑时只记日志 |

脚本在 `tools/f1/`，远端副本在 `C:\Windows\Temp\`，日志分别是
`netwatchdog.log`、`gamewatchdog.log`、`start-pie64.log`。

`F1GameWatchdog` 不判断游戏内 UI，也不点击；它只保证模拟器/ADB/LoR 进程活着。
网络看门狗关闭 TUN 后，会按“稳定 30 分钟试开 60 秒，失败关回并等 60 分钟”重试。
