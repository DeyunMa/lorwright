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
| ADB 设备发现 / 截图 / 点击 / 文本输入 / 启动 | ✅ 真机验证 |
| 分辨率解耦（`perceive/normalize.py`） | ✅ 按设计尺寸归一化后识别，动作坐标反算回设备像素 |
| 法力 / 双方水晶血量读数 | ✅ 字形模板，真机核对（注意右侧上排是对手、下排是我方） |
| 手牌费用识别（收起态扇形） | ✅ 环形掩码 + 主轴扶正 + ±8° 搜索，1080p 实战 6/6 |
| 起手换牌识别 | ✅ `assets/buttons/mulligan.png`（1080p）+ `UIState.MULLIGAN` 优先于颜色探针 |
| 动作按钮文字识别 | ✅ `action_pass` / `action_block` / `action_commit` → `MY_TURN_IDLE` / `BLOCKING` / `COMBAT_RESOLVING`，区分度 1.00 vs ≤0.50 |
| 帧时效校验 | ✅ `loop.max_frame_age_s=2s`，超龄退 `no_op` |
| 登录检测 + 登录流程 | ✅ `perceive/login.py` + `lorwright login`（账号从 `.env`） |
| 输入原语（down/move/up + 能力声明） | ✅ `device/touch.py`，真机事件级手势 |
| **出牌手势（展开态）** | ✅ 真机一次成功：蜘蛛上场、法力 3→2、手牌 6→5（收起态拖不动，见 §4.6） |
| 手牌展开 / 收起判定 | ✅ 两套徽章模板（48px / 56px）互不匹配 |
| 战斗求解器（格挡分配 / 攻击声明 / 斩杀） | ✅ 6v6 穷举 17–24ms，18 个单测（但输入还是空的，见下） |
| 伊莉絲牌表 + 评分 + buff 优先排序 | ✅ 16 个单测 |
| 分层路由 + 覆盖率统计 | ✅ 单测 |
| 恢复状态机 `RecoveryPolicy` | ✅ 已接进 `Engine`，L3 默认禁用（见 §4.7） |
| 143 个单测 / ruff 全绿 | ✅ |

### 不能跑（缺东西）

| 缺什么 | 后果 | 对应 issue |
|---|---|---|
| 出牌还没进端到端 | 展开态手势已成功，但两帧流程没在 `lorwright run` 里验证过（见 §4.6） | **#9（P0）** |
| 展开态费用识别 4/6 | `_tilt` 主轴角已修（1/6→4/6），还差 2 张 | #9 |
| 攻击声明 / 格挡手势 | 只靠出牌 + 结束回合打不完一局 | #11 |
| 场面识别（我方/敌方单位） | `my_units` / `enemy_units` 恒空，战斗求解器等于空转 | #10 |
| 卡牌身份识别 | 手牌只有费用没有身份，同费牌分不出（9 种牌只知道 9 个费用） | #3 |
| 挑战者 / 击晕图标 | 求解器拿到的 `challenger`/`stunned` 永远是 False | #10 |
| 前置自检（网络 / 登录假死 / App 冻死） | 卡住一次要人工诊断半小时 | #12 |
| JEV / LLM 兜底未接 | L2 / L3 层空转 | #8 |

---

## 2. 你要做的第一件事

**不要先碰 JEV、不要先碰 LLM、不要先做插件化。** 顺序（2026-11-04 按 issue 重排）：

```
#9 出牌手势（✅ 已完成）  →  #11 攻击/格挡手势  →  #10 场面识别  →  英雄规则  →  #5 端到端
```

理由：英雄规则是纯逻辑、离线可测，但它产出的 `PlayCard(index)` 现在**还没在真机验证成功**。
先写规则，任何「策略对不对」的结论都会退化成「手势有没有生效」。

### 第 1 步：接口（动作集合）

`models.ActionType` 就够用，但要明确**每个动作由哪个原语执行**，且原语必须真机验证过。

| 动作 | 执行原语 | 真机状态 |
|---|---|---|
| `PLAY_CARD` | tap 手牌展开 → 下一帧徽章中心拖到我方行 | ✅ 展开态真机成功（#9 待端到端） |
| `END_TURN` / `PASS` | 点 `layout.end_turn` | ✅ |
| `ATTACK` | 单位拖到攻击行 + 点 `結算` | ❌ 未验证（#11） |
| `NO_OP` | 无 | ✅ |

### 第 2 步：底层最小集

1. ~~**出牌手势**（#9）~~ —— ✅ 2026-11-04 真机跑通，见 §4.6
2. `END_TURN` —— 已可用
3. `ReadHand()` —— 费用已完成，身份见 #3

**场面识别（#10）排在出牌之后**：第一轮循环不需要，而且它依赖出牌能验证「场面变化确实发生了」。

### 第 3 步：英雄规则（伊莉絲）

等 #9 通过之后再写。规则清单见 `docs/champions/elise.md`，已确认的两条：

1. **有攻击 token 才出伊莉絲**（她带「狂風之力」给先遣，但回合结束会洗回牌组）
2. **先遣单位先打第一波**

---

## 3. F1 上的环境准备

> **环境细节全在 [`environment.md`](environment.md)。** 下面只写要点。

### 3.1 模拟器：BlueStacks 5 的 `Pie64`（Android 9）

**只有 `Pie64` 能跑 LoR。** 已实测：Android 11 的实例（`Rvc64` / `Rvc64_2`，
包括 ABI 选 `ARM` 的那个）启动 LoR 都会在 0.6 秒内 `SIGSEGV`；
Android 9 的 `Pie64` 正常。**换 ABI 不解决问题，变量是 Android 版本。**

- 原生 1280×720，**实际用 `adb shell wm size 1920x1080` 抬到 1080p**（720p 下数字读不出）
- 登录：`lorwright login`（账号密码在 `.env`），或手动登一次
- 首次进入要下载约 3.2 GB 资源
- 实例**必须由人在多开管理器里启动**，从 SSH 命令行拉起会自己退出
- **重启实例会清掉登录态**，且游戏可能冻死在启动页（判据见 §4.1）

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
pytest                            # 应该 143 个全过，不需要游戏
ruff check src tests tools
```

### 3.4 标定（已完成，换设备才需要重做）

2026-11-03 已在 1920×1080 上完成全量标定，结果写在 `config/settings.yaml`。
**现在不需要重新标定**——`perceive/normalize.py` 会先把截图归一化到设计尺寸
（`config.screen`），所以实际分辨率变了也只是缩放系数变化，坐标和模板不用重做。

真要重标（换设备、换游戏 UI 版本）：

```bash
lorwright devices
lorwright shot --grid --out logs/1080p.png     # 带坐标网格，方便量
```

然后改 `config/settings.yaml` 的 `layout` 段，并用工具重采模板：

| 模板 | 工具 |
|---|---|
| 手牌徽章 | `lorwright crop --rect x,y,w,h --name badge` |
| 动作按钮文字 | `python tools/build_action_texts.py` |
| 字形（血量 / 法力 / 手牌） | `python tools/build_digits.py` / `build_hand_digits.py` |

**验证**：`lorwright state` 应该报 `ui=my_turn_idle` 且 mana / hp 与画面一致。

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

HOME 生效但游戏不响应 → **重启游戏，别怀疑坐标**：

```bash
adb shell am force-stop com.riotgames.legendsofruneterra
lorwright launch
```

#### 2026-11-04 补：还有第二种「输入全无效」

停在「登入以開始遊戲」，点任何按钮都没反应，但画面**完全静止**（连续两帧 0 差异）。
这不是冻死，是**网络不可达**——登录页要拉 client config：

```
[BaconAuthenticationProvider] Waiting on client config to be loaded
Firestore: connect failed to firestore.googleapis.com:443 … ECONNREFUSED
```

`firestore.googleapis.com` 不通（而 Riot 自己的域名通）时就会这样。检查：

```bash
adb shell "dumpsys window | grep mCurrentFocus"          # 前台是不是 LoR
adb logcat -d -t 300 | grep -i "client config|firestore"
```

先修网络（代理 / TUN），再谈自动化。固化这条检查见 issue #12。

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

### 4.6 出牌手势：收起态拖不动，展开态可行（2026-11-04 打通）

#### 结论

**收起态手牌拖不动，展开态可以。** 真机实测：展开态一次成功——蜘蛛上场、法力 3→2、手牌 6→5。

原因是收起态卡片**斜叠**，每张只露出左边缘；`DRAG_OFFSET` 偏移后落点经常在卡片外，
所以怎么调时长、步数、`hold` 都没用（`sendevent` 和 `input swipe` 全试过）。

#### 现在的流程（两帧）

```
帧 N  ：PLAY_CARD → 先 tap 手牌区域（展开手牌）
帧 N+1：PLAY_CARD → 在展开态算拖拽起点并拖拽
```

必须拆两帧：展开后卡片位置全变，同一帧里算不出拖拽起点。

#### 展开 / 收起怎么判

两套徽章模板互不匹配，正好当状态位用，不需要额外探测：

| 状态 | 模板 | 尺寸 | `DRAG_OFFSET` |
|---|---|---|---|
| 收起 | `assets/ui/badge.png` | 48×48 | `(15, 45)` |
| 展开 | `assets/ui/badge_expanded.png` | 56×56 | `(64, 10)`（平铺不重叠） |

`GameState.hand_expanded` / `Layout.hand_expanded`（配置区 `[200,700,1600,380]`）。
实测：6 张命中 6 个（≥0.977），5 张命中 5 个。

#### 早期踩过的两个真因（都已修，别再回头）

| 真因 | 现象 | 修法 |
|---|---|---|
| 状态判错：格挡阶段被当成我方回合 | 每帧出牌、每帧失败，看着像「拖拽没反应」 | `UIState.BLOCKING` + 按钮文字模板（区分度 1.00 vs ≤0.50） |
| 手势太慢：86 个 `sendevent`（每次 ~40ms）= 4.7s | LoR 判成**长按预览**：卡片放大居中但不跟手，松手回手牌 | 6 步、hold 120ms、drag 600ms；事件数 ≤30 |

#### 排除过的方向（别重复试）

| 试过的 | 结果 |
|---|---|
| `input swipe` 各种时长（700/900/1500/2000/2500ms） | 只能抓起牌（长按预览），落不了地 |
| 8 个落点（y 650–1050 × x 600/960/1200） | 全部回手 —— 落点不是主因 |
| `input draganddrop` | 被当成滑动取消 |
| `input motionevent` | **Android 9 没有这个命令** |
| 收起态下调 hold / 步数 / 两套输入通道 | 全部无效（卡片斜叠，落点在卡外） |

#### 还剩什么

- **展开态费用识别 4/6**：`_tilt` 主轴角符号已修（1/6 → 4/6），还差 2 张。
  根因是 `atan2` 以 180° 为周期，同一方向可能算出 -87° 或 +93°，`rotate_glyph` 会朝反方向转。
- **两帧流程还没进 `lorwright run` 端到端验证**（issue #9）。

### 4.7 别用重启客户端做恢复（已修）

`restart_app` 会清掉登录态，重启后回到 Riot 登入页，等于把「卡住」升级成「要人工登录」。
原来的恢复阶梯里 `RESTART_BATTLE` 因为缺「投降 / 离开对局」模板，直接升级成重启客户端，
所以第 2 级和第 3 级做的是同一件事，而且做的是错的那件 —— 一旦触发，之后每帧都卡在登录页。

现在：`recovery.allow_client_restart` 默认 `false`，`Engine._recover()` 走到
`RESTART_BATTLE` / `RESTART_CLIENT` 时只记日志并**停下主循环**，不盲点。
等自动登录做完再把开关打开。

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
| **出牌用手势拖拽** | 手机版只认拖拽（实测：点击不发牌）。手势细节见 §4.6 |
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

## 9. 当前打开的问题

**以 GitHub Issues 为准**（标签 `p0` / `p1` / `p2`）。截至 2026-11-04：

| Issue | 优先级 | 标题 |
|---|---|---|
| #9 | P0 | 出牌手势：真机验证与参数标定（展开态已打通，剩两帧端到端 + 展开态费用 6/6） |
| #4 | P0 | 状态解析：法力 / 血量（已完成，可关） |
| #2 | P0 | UI 模板采集 + Layout 坐标标定（缺 victory / defeat） |
| #3 | P0 | 卡牌图库采集 + 手牌识别（费用已完成，剩身份） |
| #5 | P1 | 端到端：自动打完一场战斗 |
| #6 | P1 | 异常恢复：分级策略（L2 缺投降模板、L3 默认禁用） |
| #10 | P1 | 场面识别：单位 / 攻血 / 挑战者 / 击晕 |
| #11 | P1 | 攻击声明与格挡手势验证 |
| #12 | P1 | 前置自检：网络 / 登录假死 / App 冻死 |
| #8 | P2 | JEV / LLM 接入验证与降级链路 |
