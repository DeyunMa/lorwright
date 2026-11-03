# 项目状态

> 更新：2026-11-03
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

## 运行环境（2026-11-03 实测）

| 项 | 值 |
|---|---|
| 模拟器 | BlueStacks 5.22.286.1004 |
| 可用实例 | **`Pie64`（Android 9，1280×720，density 240）** |
| ADB | `127.0.0.1:5555` |
| LoR | `07.10.013`，已装、已登录，首次进入正在下载 3278 MB |

**Android 11 的实例（`Rvc64` / `Rvc64_2`）跑不了 LoR**——启动 0.6 秒后
`SIGSEGV`，崩在 ART 解释器的 invoke 路径（方法指针为空，`call [rdi+0x20]`
且 `rdi=0`）。把 ABI 限制成 `arm,arm64` 也一样，所以变量是 **Android 版本**，
不是 ABI，也不是“模拟器不支持 ARM”。

细节、证据和 ADB 的坑见 [`environment.md`](environment.md)。

## 已完成（可运行 / 可测试）

| 模块 | 说明 |
|---|---|
| `models.py` | GameState / Action / Layout / ClickPlan |
| `device/base.py` | Device 协议 + Frame |
| `device/adb.py` | ADB 截图/点击/滑动/启动应用 |
| `device/desktop.py` | mss + pynput（调试回退） |
| `perceive/locate.py` | 模板匹配 + NMS（合成图像测试通过） |
| `perceive/ui_state.py` | UI 状态检测（起手换牌优先于颜色探针） |
| `perceive/digits.py` | 字形模板读数（多原型 + 旋转搜索），读不出返回 `None` |
| `perceive/hand.py` | 手牌费用：环形掩码匹配徽章 + 倾斜字形识别 |
| `perceive/state.py` | 截图 → `GameState`（法力 / 血量 / 手牌 / UI 状态） |
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

**118 个单测，ruff 全绿。**

**已在真机验证**（BlueStacks `Pie64`，Android 9，横屏 1920×1080）：

- `adb screencap` 正常，`input tap` 正常
- LoR 启动、登录、进对局、打完整一局都正常
- `lorwright state` 读出 `my_turn_idle / mana 2/2 / hp 50/30`，手牌 6 张费用 `0,0,2,2,5,5`
- 起手换牌识别正常（`assets/buttons/mulligan.png`，1080p）
- 动作按钮文字可判：`略過` / `結算`
- 账号密码从 `.env`（`LOR_USERNAME` / `LOR_PASSWORD`）读取
- **未跑通**：出牌手势（牌抓得起来、松手不落地，见 `handoff.md` §4.6）、场面识别

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

**见 [`docs/handoff.md`](handoff.md) §2。** 2026-11-03 定的顺序：接口 → 底层最小集 → 英雄规则。

```
出牌手势（按住 → 停 → 拖 → 松手）   ← 卡在这，唯一 P0 阻塞
  ↓
END_TURN（已可用）
  ↓
伊莉絲英雄规则（有攻击 token 才出伊莉絲、先遣先打）
  ↓
场面识别 → 攻击声明 / 格挡
```

⚠️ **出牌手势没跑通之前不要写英雄规则** —— 规则产出的动作无法在真机验证，
「策略对不对」会退化成「手势有没有生效」。

## 已知风险

| 风险 | 说明 |
|---|---|
| 卡牌变体 | 闪卡/皮肤会导致模板不匹配 → 记录失败样本 |
| 手牌重叠 | 切分困难 → 可用固定卡位 |
| 游戏自身卡死 | 表现为「输入全无效」，实为进程无响应 → 见上文判别步骤 |
| 游戏更新 | UI 变化要重采模板 |
| 封号 | 自动化违反 ToS，用小号试错 |
