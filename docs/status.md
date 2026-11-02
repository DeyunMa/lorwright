# 项目状态

> 更新：2026-11-02
>
> **要接手开发，先读 [`docs/handoff.md`](handoff.md)。** 这份只记状态，不记行动计划。

## 里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| M0 | 骨架 + 规则 + 单测 + CI | ✅ 完成 |
| **M1** | 自动打完一场 PoC 战斗 | 🚧 进行中 |
| M2 | 自动选奖励（三选一） | 待做 |
| M3 | 自动走地图 | 待做 |
| M4 | 跑完一个完整副本 | 待做 |

## 已完成（可运行 / 可测试）

| 模块 | 说明 |
|---|---|
| `models.py` | GameState / Action / Layout / ClickPlan |
| `device/base.py` | Device 协议 + Frame |
| `device/adb.py` | ADB 截图/点击/滑动/启动应用 |
| `device/desktop.py` | mss + pynput（调试回退） |
| `perceive/locate.py` | 模板匹配 + NMS（合成图像测试通过） |
| `perceive/ui_state.py` | 5 状态检测（待模板） |
| `champions/elise/` | 伊莉絲英雄包：牌表 + 蜘蛛快攻规则 |
| `decide/combat.py` | 战斗求解器：精确枚举格挡分配与攻击声明 |
| `decide/card.py` | 卡牌通用词汇（CardKind / CardDef） |
| `champions/` | 英雄包注册表（加英雄 = 加目录，不改核心） |
| `decide/candidates.py` | 局面 → 候选动作 |
| `decide/jev.py` / `llm.py` | HTTP 客户端，未配置自动降级 |
| `decide/router.py` | 分层路由 + 覆盖率统计 |
| `act/translate.py` | 语义动作 → 点击序列 |
| `loop/engine.py` | 主循环（含事件发射） |
| `loop/watchdog.py` | 卡住检测 |
| `loop/recovery.py` | 分级恢复状态机 |
| `util/logger.py` / `events.py` | 按日期分目录 + JSONL |
| `tools/analyze.py` | 复盘摘要 |
| `doctor.py` | 环境自检 |

**90 个单测，ruff 全绿，CI 在 push 时自动跑。**

**已在真机验证**（小米 2510DRK44C，横屏 2510×1156）：

- `adb screencap` 正常
- LoR 启动、进对局正常
- 颜色探针识别 `my_turn_idle` 正常（蓝色占比 77%）
- Layout 四矩形已按真机实测填入 `config/settings.yaml`
- **拖拽出牌可行**：`input swipe` 从手牌拖到 `(1250, 850)` 实际打出了牌（场面出现单位、法力被扣）
- **未验证**：卡牌识别、战斗结算

### 一个容易误判的现象

手机端对局中 LoR 曾进入**游戏自身卡死 / 掉线重连**状态（卡图模糊、动作按钮变空白）。
期间所有 adb 输入「看起来无效」——点按钮、点齿轮、甚至下拉通知栏都没反应，
但 `input keyevent 3`（HOME）能正常回到桌面。

**结论：这不是 adb 输入通道的问题，是游戏进程无响应。**
以后遇到「输入全无效」先做这个判别：

```bash
adb shell input keyevent 3                       # HOME 能否生效
adb shell dumpsys window | grep mCurrentFocus    # 前台是否已切到桌面
adb shell dumpsys power | grep mState            # 屏幕是否 ON
```

HOME 生效但游戏不响应 → 重启游戏（`am force-stop` + `monkey -p ... 1`），别怀疑坐标。

## Stub（需要真实画面才能做）

| 位置 | 缺什么 | Issue |
|---|---|---|
| `perceive/cards.py:recognize_hand` | 手牌切分 + 模板匹配 | #3 |
| `loop/engine.py:_build_state` | 法力/血量/场面解析 | #4 |
| `perceive/ui_state.py` | 真实按钮模板 | #2 |
| `config/settings.yaml:layout` | 四个矩形坐标 | #2 |
| `loop/engine.py` | `RecoveryPolicy` 未接入主循环；`NO_OP` 会计入卡死 | #6 |

## 素材清单

| 素材 | 数量 | 位置 | 状态 |
|---|---|---|---|
| 按钮模板 | 3–5 | `assets/buttons/` | 🚧 有 `action_button.png`（手机版） |
| 卡牌图库 | **9**（伊莉絲牌组只有 9 种） | `assets/cards/` | ❌ 空 |
| 起手换牌「確定」 | 1 | `assets/buttons/` | ❌ 空（**P0**） |
| 挑战者 / 击晕图标 | 2 | `assets/buttons/` | ❌ 空 |

## 打开的 Issue

| # | 优先级 | 标题 |
|---|---|---|
| 1 | P0 | Windows 环境验证与首次 probe |
| 2 | P0 | UI 模板采集 + Layout 坐标标定 |
| 3 | P0 | 卡牌图库采集 + 手牌识别 |
| 4 | P0 | 状态解析：法力 / 血量 / 场面 |
| 5 | P1 | 端到端：自动打完一场战斗 |
| 6 | P1 | 异常恢复：分级策略 |
| 8 | P2 | JEV / LLM 接入验证 |

## 下一步

**见 [`docs/handoff.md`](handoff.md) §2。** 关键路径是：

```
起手换牌模板（半天）
  ↓
_build_state 解析：法力 / 血量 / 手牌费用   ← 卡在这
  ↓
9 张卡牌模板
  ↓
端到端打一局
```

⚠️ **状态解析没做完之前不要接 JEV / LLM** —— 候选生成依赖 state，接了也是空转。

## 已知风险

| 风险 | 说明 |
|---|---|
| 卡牌变体 | 闪卡/皮肤会导致模板不匹配 → 记录失败样本 |
| 手牌重叠 | 切分困难 → 可用固定卡位 |
| 游戏自身卡死 | 表现为「输入全无效」，实为进程无响应 → 见上文判别步骤 |
| 游戏更新 | UI 变化要重采模板 |
| 封号 | 自动化违反 ToS，用小号试错 |
