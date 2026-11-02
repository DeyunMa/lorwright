# 项目状态

> 更新：2026-11-02

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
| `decide/rules.py` | 蜘蛛快攻规则（斩杀/出牌/结束/弃权） |
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

**30 个单测，ruff 全绿，CI 在 push 时自动跑。**

**已在真机验证**（小米 2510DRK44C，横屏 2510×1156）：

- `adb screencap` 正常
- LoR 启动、进对局正常
- 颜色探针识别 `my_turn_idle` 正常（蓝色占比 77%）
- Layout 四矩形已按真机实测填入 `config/settings.yaml`
- **未验证**：拖拽出牌（`input swipe`）、卡牌识别、战斗结算

## Stub（需要真实画面才能做）

| 位置 | 缺什么 | Issue |
|---|---|---|
| `perceive/cards.py:recognize_hand` | 手牌切分 + 模板匹配 | #3 |
| `loop/engine.py:_build_state` | 法力/血量/场面解析 | #4 |
| `perceive/ui_state.py` | 真实按钮模板 | #2 |
| `config/settings.yaml:layout` | 四个矩形坐标 | #2 |
| `loop/engine.py` 恢复动作 | 真正执行重开/重启 | #6 |

## 素材清单

| 素材 | 数量 | 位置 | 状态 |
|---|---|---|---|
| 按钮模板 | 3–5 | `assets/buttons/` | ❌ 空 |
| 卡牌图库 | 20–30 | `assets/cards/` | ❌ 空 |

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

## 下一步（按依赖顺序）

```
#1 环境验证（人）
  ├→ #2 按钮模板 + 坐标（人，3 张图）
  └→ #3 卡牌图库（人，20+ 张图）
        ↓
      #4 状态解析（agent，对着截图写）
        ↓
      #5 端到端（agent + 人一起验证）
        ↓
      #6 恢复动作（agent，对着 UI 写）
```

## 已知风险

| 风险 | 说明 |
|---|---|
| 卡牌变体 | 闪卡/皮肤会导致模板不匹配 → 记录失败样本 |
| 手牌重叠 | 切分困难 → 可用固定卡位 |
| 游戏更新 | UI 变化要重采模板 |
| 封号 | 自动化违反 ToS，用小号试错 |
