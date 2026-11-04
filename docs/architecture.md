# 架构说明

> 交接入口见 [`docs/handoff.md`](handoff.md)。本文只讲设计，不讲当前进度。

## 一、目标与边界

**目标**：自动完成《符文大地传说》英雄之路（Path of Champions）的周本。

**不做**：
- 不读写游戏内存、不改游戏文件、不绕过反作弊
- 不保证胜率——目标是「把局打完」
- 不做通用 GUI Agent

**为什么纯视觉**：Riot 的本地 API（`localhost:21337`）只覆盖收藏/构筑/PvP，
英雄之路没有 API。证据：`RiotGames/developer-relations#773`（2023-05 提出，至今 open）
> "There are currently no APIs for Path of Champions mode."

---

## 二、核心设计：两条正交的链

整个系统只有两个东西在跑，**它们不是同一条链**。把它们混成一条是最容易犯的错。

### A. 决策链 —— 回答「现在该做什么」

```
L1 穷举/规则  →  L2 JEV 有界选择  →  L3 LLM 有界分类  →  NO_OP
```

| 层 | 回答什么问题 | 输入 | 输出 | 延迟 |
|---|---|---|---|---|
| **L1** | 规则已知、空间小 → **穷举** | `GameState` | `Action`（枚举） | < 10ms |
| **L2** | 选项已知，但需要读懂卡牌效果 | 结构化局面 + 候选列表 | `choice ∈ options` | 100–500ms |
| **L3** | **连现在是什么局面都不确定** | 截图 + 已知界面标签 | `label ∈ labels` | 2–20s |
| **兜底** | 三层都不确定 | — | `NO_OP`（不点屏幕） | 0 |

**关键约束：每一层的输出都必须是「受约束的」。**

- L1 输出 `Action` 枚举，不是自由文本
- L2 输出 `choice`，**必须命中 `options` 之一**，否则判失败降级
- L3 输出 `label`，**必须命中已知界面标签之一**，否则判失败
- **任何一层都不允许「自由文本 → 直接执行」**

L3 不是「让 LLM 看着画面决定点哪」，而是「让 LLM 认出这是哪个界面」。
认出来之后，交给对应决策点的确定性逻辑去执行。理由见 §四。

### B. 监督器 —— 回答「是不是卡住了」

```
Watchdog（画面/状态摘要不变）  →  RecoveryPolicy（重试 → 重开对局 → 重启客户端 → 停）
```

这条链**不经过决策层**，是并行的守护进程。它做的是确定性判断，不调用任何模型。

| 判据 | 成本 | 说明 |
|---|---|---|
| 截图哈希连续 N 帧不变 | ~0 | 画面卡死 |
| `GameState.summary()` 连续 N 帧不变 | ~0 | 逻辑卡死 |
| 点击后 N 秒无任何像素变化 | ~0 | 动作没生效 |

**「卡住」不需要 LLM。** 画面不动是像素问题，不是语义问题。

---

## 三、为什么这样分层

### 3.1 能穷举的就穷举，不要用启发式

LoR 的动作空间小到可以穷举：

| 决策点 | 搜索空间 | 6v6 实测 |
|---|---|---|
| 格挡分配 | ≤ 13,327 种 | 17 ms |
| 攻击声明 | 2⁶−1 = 63 种 × 对手最优格挡 | 23 ms |
| 斩杀判定 | 取最大脸伤 | 24 ms |

tick 预算 200ms。**穷举比启发式既准又便宜。**

收益不只是准：斩杀判定变成了求解器的副产品，不会出现
「规则说能斩、求解器算出不能」的自相矛盾。

**但穷举有边界**：出牌是「手牌子集 × 顺序」的组合爆炸，穷举不了。
所以出牌走「贪心 + 评分」，评分分不清的才交给 L2。

### 3.2 每一层都要能弃权，但「答案唯一」时不能弃权

弃权（返回 `None`）会把请求送给下一层。这是分层的前提。

但**没有优先权时答案唯一，就是 `NO_OP`**——这时候弃权会让路由在对手回合
每一帧白烧一次 JEV 调用。这是 v1 的真实 bug。

判据：**如果这一层的答案不需要任何判断，它就不该弃权。**

### 3.3 覆盖率不是指标，胜率提升才是

早期定过「L1 70–80% / L2 15–25% / L3 1–5%」——那是拍脑袋的数字，已经废弃。

把可枚举的决策挪进 L1 之后，L2 占比必然下降，这是好事。
真正该看的是：**L2 命中时的胜率是否高于 L1 的默认选择**。如果一样，说明 L2 白花钱。

`Router.coverage()` 仍然记录每层命中次数，但只用来发现异常（比如 L3 突然涨到 30%，
说明感知层坏了），不是用来追指标的。

---

## 四、为什么 LLM 不能直接操作界面

这是这个项目最容易走偏的地方，单独写一节。

| 问题 | 后果 |
|---|---|
| 延迟 2–20s | 回来时画面早变了，你点的是过期坐标 |
| 自由文本输出 | 无法校验，无法回滚，无法单测 |
| 状态不明时点击 | 2026-11-02 就是这样点进了设定菜单 |

所以 L3 的定位是**视觉分类器**，不是操作员：

```
画面在变，但 ui_state == UNKNOWN
        ↓
L3：这是哪个界面？（战斗 / 起手换牌 / 奖励三选一 / 地图 / 断线重连 / 卡死）
        ↓
命中已知界面 → 交给对应决策点的确定性逻辑
仍不认识   → NO_OP + 存快照 + 停下等人
```

**「重启」也不该由 LLM 决定。** LLM 只说「这是卡死画面」，
`RecoveryPolicy` 决定重试几次、重开对局还是重启客户端。它是纯状态机，可单测。

---

## 五、数据契约

```python
GameState(ui_state, turn, mana, max_mana, hand[], my_units[], enemy_units[],
          nexus_hp, enemy_nexus_hp, has_attack_token, my_units_have_challenger)

Action(type, card_index, target, raw)   # 语义动作，不含坐标
```

**决策层只产出语义动作；执行层负责翻译成坐标。** 这样决策逻辑可以脱离屏幕单测。

---

## 六、目录

```
src/lorwright/
├── models.py              # 数据契约：GameState / Action / Layout / ClickPlan
├── config.py              # YAML 配置（champion / layout / adb / loop）
├── main.py                # CLI：devices / shot / crop / probe / run / doctor
├── doctor.py              # 环境自检
│
├── device/                # 设备抽象
│   ├── base.py            # Device 协议 + Frame
│   ├── adb.py             # adb screencap / input tap / swipe
│   └── desktop.py         # mss + pynput（调试回退）
│
├── perceive/              # 感知：只读截图，不产生动作
│   ├── locate.py          # 模板匹配 + NMS
│   ├── cards.py           # 卡牌识别（stub）
│   └── ui_state.py        # UI 状态：颜色探针优先
│
├── decide/                # 决策机制（不认识任何英雄）
│   ├── base.py            # Policy 协议
│   ├── card.py            # 卡牌通用词汇 CardKind / CardDef
│   ├── combat.py          # 战斗求解器（格挡分配 / 攻击声明 / 斩杀）
│   ├── candidates.py      # 候选动作生成
│   ├── jev.py             # L2 客户端
│   ├── jev_policy.py      # JEV / LLM 的 Policy 适配
│   ├── llm.py             # L3 客户端
│   └── router.py          # 分层路由 + 覆盖率统计
│
├── champions/             # 英雄包（一个英雄 = 一个目录）
│   ├── __init__.py        # available() / load()，动态发现
│   ├── base.py            # ChampionPack 协议
│   └── elise/
│       ├── __init__.py    # 暴露 PACK
│       ├── deck.py        # 牌表 + 效果分类 + 别名
│       └── policy.py      # 这套牌的 L1 规则与评分
│
├── act/
│   └── translate.py       # 语义动作 → 点击/拖拽序列
│
├── loop/
│   ├── engine.py          # 主循环：感知 → 决策 → 执行
│   ├── watchdog.py        # 卡住检测
│   └── recovery.py        # 分级恢复状态机（⚠ 尚未接入 engine）
│
└── util/
    ├── logger.py          # 按日期分目录
    ├── events.py          # JSONL 事件流
    └── snapshot.py        # 失败截图存档
```

**加英雄不改 `decide/`。** 见 `docs/decision-l1-rules.md` 的检查清单。

---

## 七、硬约束

| 约束 | 原因 |
|---|---|
| **坐标与模板按设计尺寸标定** | `config.screen` 定设计尺寸，`perceive/normalize.py` 归一化截图并反算动作坐标；换分辨率不用重标 |
| **出牌用 swipe，不是 tap** | 手机版只认拖拽（实测：点击不发牌） |
| **状态不明不点击** | 兜底是 `NO_OP`，不是盲点 |
| **英雄知识不进 `decide/` 和 `models.py`** | 破坏解耦，插件化就无从谈起 |
| 游戏语言一致 | 模板图按语言截取（当前是繁体中文） |
| 代理不假设对模拟器生效 | 模拟器走宿主 NAT，宿主机系统代理不会自动进 guest；需要时在 guest 内单独配 |

---

## 八、里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| M0 | 项目骨架 + 规则 + 单测 + CI | ✅ 完成 |
| M1 | 自动打完一场 PoC 战斗 | 🚧 进行中（缺状态解析） |
| M2 | 自动选奖励（三选一） | 待做 |
| M3 | 自动走地图 | 待做 |
| M4 | 跑完一个完整副本 | 待做 |

---

## 九、已知 stub

| 位置 | 缺什么 |
|---|---|
| `perceive/cards.py:recognize_hand` | 手牌切分 + 模板匹配（9 张牌） |
| `loop/engine.py:_build_state` | 法力 / 血量 / 场面解析（**P0，不修则策略永远只会结束回合**） |
| `perceive/ui_state.py` | 起手换牌「確定」按钮模板（否则开局误判成我方回合） |
| `loop/engine.py` | `RecoveryPolicy` 没接进主循环 |
