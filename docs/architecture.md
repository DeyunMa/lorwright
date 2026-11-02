# 架构说明

## 一、目标与边界

**目标**：自动完成《符文大地传说》英雄之路（Path of Champions）的周本。

**不做**：
- 不读写游戏内存、不改游戏文件、不绕过反作弊
- 不保证胜率——目标是「把局打完」
- 不做通用 GUI Agent

## 二、为什么是纯视觉

Riot 的本地 API（`localhost:21337`）只覆盖**收藏、构筑器、PvP 对局**，
英雄之路没有 API。

证据：`RiotGames/developer-relations#773`（2023-05 提出，至今 open）
> "There are currently no APIs for Path of Champions mode."

**结论**：感知层只能走截图 → 模板匹配 / OCR。

## 三、四层架构

```
感知 → 决策 → 执行 → 异常
```

| 层 | 模块 | 职责 |
|---|---|---|
| 设备 | `device/` | 截图 + 输入（ADB / 桌面），上层不关心设备类型 |
| 感知 | `perceive/` | 颜色探针 + 模板匹配、卡牌识别、UI 状态 |
| 决策 | `decide/` | 规则 / JEV / LLM 分层路由 |
| 执行 | `act/` | 语义动作 → 点击坐标 |
| 异常 | `loop/` | 主循环、看门狗、截图存档 |

## 四、分层决策

**按成本递增，逐级升级；每层都能弃权（返回 None）。**

| 层 | 延迟 | 预期覆盖 | 典型场景 |
|---|---|---|---|
| L1 规则 | < 1ms | 70–80% | 斩杀、出最便宜的牌、结束回合 |
| L2 JEV | 100–500ms | 15–25% | 从候选动作里挑一个 |
| L3 LLM | 1–3s | 1–5% | 复杂交换、对手卡组判断 |

`Router` 记录每层命中次数，运行结束打印覆盖率——用来判断规则是否够用。

## 五、数据契约

```python
GameState(ui_state, turn, mana, max_mana, hand[], my_units[], enemy_units[],
          nexus_hp, enemy_nexus_hp)

Action(type, card_index, target)   # 语义动作，不含坐标
```

**决策层只产出语义动作；执行层负责翻译成坐标。** 这样决策逻辑可以脱离屏幕单测。

## 六、目录

```
src/lorwright/
├── models.py           # GameState / Action / UIState / Rect
├── device/
│   ├── base.py         # Device 协议 + Frame
│   ├── adb.py          # adb exec-out screencap / input tap
│   └── desktop.py      # mss + pynput（调试用）
├── config.py           # YAML 配置
├── main.py             # CLI: probe / capture / run
├── perceive/
│   ├── capture.py      # mss 截屏
│   ├── locate.py       # 模板匹配 + NMS
│   ├── cards.py        # 卡牌识别（图库）
│   └── ui_state.py     # 5 状态检测
├── decide/
│   ├── base.py         # Policy 协议
│   ├── candidates.py   # 候选动作生成
│   ├── rules.py        # L1 蜘蛛快攻
│   ├── jev.py          # L2 客户端
│   ├── llm.py          # L3 客户端
│   ├── jev_policy.py   # JEV/LLM 的 Policy 适配
│   └── router.py       # 分层路由
├── act/
│   ├── mouse.py        # 点击 / 拖拽
│   └── translate.py    # 语义动作 → 点击序列
└── loop/
    ├── engine.py       # 主循环
    └── watchdog.py     # 卡住检测
```

## 七、硬约束

| 约束 | 原因 |
|---|---|
| **模板分辨率 = 目标设备分辨率** | 手机横屏 2510×1156 / 模拟器自定义，换了就重采 |
| **出牌用 swipe，不是 tap** | 手机版只认拖拽 |
| **状态不明不点击** | 兜底是 `NO_OP`，不是盲点 |
| 游戏语言一致 | 模板图按语言截取 |
| 加速器用 TUN 模式 | 模拟器不认 Windows 系统代理 |

## 八、里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| M0 | 项目骨架 + 规则单测 | ✅ 完成 |
| M1 | 自动打完一场战斗 | 🚧 进行中 |
| M2 | 自动选奖励（三选一） | 待做 |
| M3 | 自动走地图 | 待做 |
| M4 | 跑完一个完整副本 | 待做 |

## 九、已知 stub

| 位置 | 缺什么 |
|---|---|
| `perceive/cards.py:recognize_hand` | 手牌区域切分 + 模板匹配 |
| `loop/engine.py:_build_state` | 法力 / 血量 / 场面解析 |
| `perceive/ui_state.py` | 需要真实按钮模板 |
