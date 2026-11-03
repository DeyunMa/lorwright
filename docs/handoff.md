# 交接文档（给 F1 上继续开发的 agent）

> 这份是**入口**。先读完这份，再按 §7 的索引深入。

---

## 0. 30 秒速览

**这是什么**：用视觉自动化打《符文大地传说》英雄之路（PoC）周本的工具。
纯截图 → 决策 → adb 输入，不碰游戏内存、不接游戏 API（PoC 没有 API）。

**目标牌组**：伊莉絲（Elise）蜘蛛快攻，18 张（9 种 × 2）。牌表已核实。

**现在卡在哪**：`Engine._build_state()` **只填了 `ui_state`**，手牌恒为空，
所以策略永远只会「结束回合」。**这是 P0，不修则下游全部无法验证。**

**核心设计一句话**：能穷举的穷举（战斗），穷举不了的按分数排（出牌），
分数分不清的交给 JEV，连界面都不认识的交给 LLM 做**分类**——
但任何一层都不允许「自由文本 → 直接点屏幕」。

### 先花 5 分钟确认环境

```bash
git clone git@github.com:DeyunMa/lorwright.git   # 分支 main
cd lorwright
pip install -e ".[dev]"
pytest                    # 必须看到 90 passed
ruff check src tests tools  # 必须 All checks passed
```

跑不到 90 passed 就是环境不对（不是代码不对），先修环境再往下读。

> 本仓库主分支 `main`。工作目录：F1（Windows）。

---

## 1. 现在的真实状态

### 能跑（有测试或真机验证）

| 能力 | 状态 |
|---|---|
| ADB 设备发现 / 截图 / 点击 / 拖拽 | ✅ 真机验证 |
| UI 状态颜色探针（我方优先权） | ✅ 真机 77% vs 11% vs 0%，区分度极高 |
| 拖拽出牌 | ✅ 真机验证（`input swipe` 从手牌拖到场上真的打出了牌） |
| 战斗求解器（格挡分配 / 攻击声明 / 斩杀） | ✅ 6v6 穷举 17–24ms，18 个单测 |
| 伊莉絲牌表 + 评分 + buff 优先排序 | ✅ 16 个单测 |
| 分层路由 + 覆盖率统计 | ✅ 单测 |
| 恢复状态机 `RecoveryPolicy` | ⚠️ 有实现有单测，**但没接进 engine** |
| 90 个单测 / ruff 全绿 | ✅ |

### 不能跑（缺东西）

| 缺什么 | 后果 | 优先级 |
|---|---|---|
| `_build_state` 不解析法力/血量/手牌/场面 | 策略永远走「手牌为空 → END_TURN」 | **P0** |
| 卡牌识别没有模板 | 手牌认不出来 | **P0** |
| 起手换牌「確定」按钮无模板 | 换牌界面被误判成「我方优先权」，开局会乱点 | **P0** |
| 攻击手势未真机验证 | 「拖到敌方水晶」这个手势没确认过 | P1 |
| 挑战者 / 击晕图标未解析 | 求解器拿到的 `challenger`/`stunned` 永远是 False | P1 |
| JEV 未接（没有 key） | L2 层空转 | P2 |
| LLM 兜底未接 | L3 层空转 | P2 |

---

## 2. 你要做的第一件事

**不要先碰 JEV、不要先碰 LLM、不要先做插件化。** 按这个顺序：

### 第 1 步：起手换牌模板（半天）

现在 `ui_state` 只有两个判据：动作按钮蓝色占比、几个模板。
起手换牌界面的「確定」按钮和动作按钮**位置重叠**，会被判成 `MY_TURN_IDLE`。
开局第一秒机器人就会去点牌。

```
lorwright shot --out logs/mulligan.png     # 手动截一张换牌界面
lorwright crop --rect x,y,w,h --name mulligan_confirm --src logs/mulligan.png
```

然后在 `perceive/ui_state.py` 里把 `mulligan` 的匹配**排到颜色探针之前**。

### 第 2 步：`_build_state` 解析（关键路径）

`loop/engine.py:_build_state()` 现在长这样：

```python
def _build_state(self, frame) -> GameState:
    ui = self.ui_detector.detect(frame)
    # TODO(#4): 从截图解析手牌、场面、法力、血量
    return GameState(ui_state=ui)
```

**最小可用版本**（先只做这三个，其他留空）：

1. `mana` / `max_mana` —— 右侧法力数字
2. `nexus_hp` / `enemy_nexus_hp` —— 水晶旁数字
3. `hand[].cost` —— 手牌卡面左上数字

有了这三个，`rank_playable()` 就能工作，出牌逻辑就能跑。

**做法建议**：先不要求全自动。用 `lorwright shot` 存一批真实对局截图，
对着截图手写解析，用这些截图做回归测试（见 §5）。

### 第 3 步：卡牌模板（9 张）

只有 9 种牌，这是选这套牌做 PoC 的最大好处。每张裁一张卡面图放 `assets/cards/`。

### 第 4 步：端到端打一局

`lorwright run --max-ticks 100`，看日志里 `ui=` / `layer=` / `action=` 是否符合预期。

---

## 3. F1 上的环境准备

> **环境细节全在 [`environment.md`](environment.md)。** 下面只写要点。

### 3.1 模拟器：BlueStacks 5 的 `Pie64`（Android 9）

**只有 `Pie64` 能跑 LoR。** 已实测：Android 11 的实例（`Rvc64` / `Rvc64_2`，
包括 ABI 选 `ARM` 的那个）启动 LoR 都会在 0.6 秒内 `SIGSEGV`；
Android 9 的 `Pie64` 正常。**换 ABI 不解决问题，变量是 Android 版本。**

- 分辨率 **1280×720**，density 240
- 登录**必须手动做**，程序不碰账号密码
- 首次进入要下载约 3.2 GB 资源
- 实例**必须由人在多开管理器里启动**，从 SSH 命令行拉起会自己退出

### 3.2 ADB

```powershell
$a = (Get-Command adb.exe).Source
Get-Process adb -ErrorAction SilentlyContinue | Stop-Process -Force
& $a start-server
& $a connect 127.0.0.1:5555
& $a -s 127.0.0.1:5555 shell getprop ro.build.version.release   # 应该是 9
```

⚠️ **adb daemon 会随 SSH 会话消失。** `start-server` / `connect` 必须和
后续命令写在**同一次调用**里，否则会报 `device not found`。
`emulator-5554` 和 `127.0.0.1:5555` 是同一个实例，统一用后者。

### 3.3 装项目

```bash
git clone git@github.com:DeyunMa/lorwright.git
cd lorwright
pip install -e ".[dev]"
pytest                            # 应该 90 个全过，不需要游戏
ruff check src tests tools
```

### 3.4 重标定（必须做）

**所有坐标和模板都是按手机 2510×1156 采的，1280×720 下全部作废。**

```bash
lorwright devices
lorwright shot --grid --out logs/720p.png     # 带坐标网格，方便量
```

然后改 `config/settings.yaml` 的 `layout` 段四个矩形，重裁 `assets/buttons/action_button.png`。

| 项 | 手机（现有值） | Pie64 1280×720（待标定） |
|---|---|---|
| 动作按钮 | `[2035, 487, 138, 138]` | ? |
| 敌方水晶 | `[329, 372, 80, 80]` | ? |
| 出牌落点 | `[900, 750, 700, 200]` | ? |
| 手牌区 | `[1750, 940, 740, 210]` | ? |

**验证标定对不对**：`lorwright probe` 应该报 `ui=my_turn_idle` 且蓝色占比 > 45%。

---

## 4. 已知坑（都是踩过的）

### 4.1 「输入全无效」不一定是坐标错

手机端 LoR 曾自己卡死（卡图模糊、按钮变空白），期间所有 adb 输入看起来都没反应，
**连下拉通知栏都不动**。但 `input keyevent 3`（HOME）能正常回桌面。

判别三步：

```bash
adb shell input keyevent 3                       # HOME 能生效吗
adb shell dumpsys window | grep mCurrentFocus    # 前台切到桌面了吗
adb shell dumpsys power | grep mState            # 屏幕是 ON 吗
```

HOME 生效但游戏不响应 → **重启游戏，别怀疑坐标**。

### 4.2 截图时机

出牌后游戏有动画，**立刻截图会看到旧画面**。别因为「截图没变」就判断动作失败，
等 1–2 秒再看。

### 4.3 分辨率陷阱

`AdbDevice.size()` 用的是**截图尺寸**，不是 `wm size`。
`wm size` 永远报竖屏（1156×2510），横屏游戏截图是 2510×1156。已经修过了，别再改回去。

### 4.4 `NO_OP` 会被误判成卡死

`Watchdog` 比较 `state.summary()`。对手回合连续 3 帧 `NO_OP` 时摘要不变 →
判成卡住 → 刷快照 / 触发重开。**修法：`NO_OP` 不计入卡死计数。**

### 4.5 LoR 不是「回合制」

是**交替优先权**。大蓝按钮 = 我持有优先权（不管名义上是谁的回合）。
没有蓝按钮时**没有合法动作**，返回 `NO_OP`，不是 `None`。

返回 `None`（弃权）会让路由把请求送去 JEV，对手回合每帧白烧一次调用。

---

## 5. 建议的工作方式：截图回归

感知层最难测。建议：

1. 用 `lorwright shot` 存一批真实对局截图到 `tests/fixtures/screens/`
2. 每张图配一个 `.expected.json`（期望的 `GameState`）
3. 写 `tests/test_perception.py` 跑这批图

这样改解析逻辑时不用每次都开游戏验证。MAA 就是这么做的（他们有 test resource）。

---

## 6. 硬约束（违反会走错方向）

| 约束 | 原因 |
|---|---|
| **英雄知识不进 `decide/` 和 `models.py`** | 破坏解耦，插件化就无从谈起 |
| **加英雄 = 加 `champions/<name>/` 目录** | 不改核心层。要改就说明没抽象干净 |
| **状态不明不点击** | 兜底是 `NO_OP`。2026-11-02 因为盲点，机器人点进了设定菜单 |
| **出牌用 `input swipe`** | 手机版只认拖拽（实测：点击不发牌） |
| **模板按目标分辨率采** | 换分辨率就要重采，否则坐标全错 |
| **只学 MAA/ALAS 的设计，不抄代码** | 它们是 AGPL-3.0 / GPL-3.0，会传染，与闭源售卖冲突 |

---

## 7. 文档索引

**先读这四份**：

| 文档 | 内容 |
|---|---|
| `AGENTS.md` | 硬约束、命令、目录约定 |
| `docs/architecture.md` | 核心设计：决策链 + 监督器、为什么 LLM 不能直接点屏幕 |
| `docs/status.md` | 当前状态、真机验证结果、已知问题 |
| `docs/environment.md` | **F1 + BlueStacks 环境**：哪个实例能用、Android 11 崩溃的排查结论、ADB 的坑 |
| `docs/decision-l1-rules.md` | 决策层怎么分层、精确解边界、**加英雄的检查清单** |

**按需深入**：

| 文档 | 什么时候看 |
|---|---|
| `docs/champions/elise.md` | 改伊莉絲的规则/评分时。含牌表、星力、v1 八条规则的体检结论 |
| `docs/decision-l2-jev.md` | 要接 JEV 时。含契约、上下文格式、四阶段验证 |
| `docs/reference-prior-art.md` | 想知道 MAA/ALAS 哪些能学、哪些学不了时 |
| `docs/adr/` | 想推翻某个决策时，先看当时的理由 |

---

## 8. 不要做

- ❌ **不要先接 JEV / LLM。** 状态解析没做，候选生成是空的，接了也是空转。
- ❌ **不要先做插件化。** `champions/` 已经是插件形态了，够了。
- ❌ **不要为了「覆盖率」调规则。** 覆盖率只用来发现异常（比如 L3 突然涨到 30%
  说明感知层坏了），不是 KPI。
- ❌ **不要让 LLM 决定点哪里。** 它只做界面分类，动作由确定性逻辑执行。
- ❌ **不要用启发式替换穷举。** 战斗空间小到 6v6 只要 24ms，穷举更准。
- ❌ **不要在 `decide/` 里 import `champions/`。** 核心层不认识任何英雄。

---

## 9. 当前打开的问题（按优先级）

| 优先级 | 问题 |
|---|---|
| P0 | `_build_state` 只填 `ui_state`，策略永远只会结束回合 |
| P0 | 起手换牌界面被误判成「我方优先权」 |
| P0 | 卡牌识别没有模板（9 张） |
| P1 | `RecoveryPolicy` 没接进 engine |
| P1 | `NO_OP` 计入卡死计数，对手回合会误触发恢复 |
| P1 | 攻击手势（拖到敌方水晶）未真机验证 |
| P1 | 挑战者 / 击晕图标未解析 |
| P2 | JEV 接入（缺 key 和 4 项接口信息） |
| P2 | LLM 界面分类兜底 |
| P2 | 模板版本化（对应游戏 `live_7-10-13`） |
