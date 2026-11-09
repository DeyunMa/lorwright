# 项目状态

> 2026-11-09：Jinx 地图头像已接入冒险循环；用户确认的下一节点可在
> 离线回放中被点击。未知头像会停止；尚未做实机连续验证，见
> [`handoff.md`](handoff.md)。

> 2026-11-09：隐秘及蛮力图标已接入单位感知，通用格挡评分考虑蛮力
> 溢出；Jinx 换牌规则已按用户确认调整。以上均仅离线验证，锐目视觉、
> 完整换牌连续过程及实战效果仍待核验，详见 [`handoff.md`](handoff.md)。

> 2026-11-09：Jinx 首局实战获胜（引擎起手/出牌 + 人工弃牌与水晶斩杀）。
> 地图导航补齐：Jinx 头像 ORB、发光路径端点找下一节点（边缘密度选圆）、
> 金色节点误报收紧；TargetingPolicy 支持弃牌提示与水晶目标；起手换牌
> 可识别并替换找组件。`logs/` 清理到 215M。详见 [`handoff.md`](handoff.md)。
> 奖励排序已接入有限的能力截图识别：三项全认识时输出推荐，尚不自动点击
> 或确认。冒险循环对地图/详情增加画面与按钮文字识别，未知画面停止；
> 以上均为离线验证，覆盖范围和后续素材见 `handoff.md`。

> 2026-11-07：Jinx 起手补上第三步——下场后手牌变成最左侧 2 张飞逝
> 「超威能死亡火箭！」+ 右侧 4 张「砰砰」，火箭必须当回合打掉。
> 修复 PoC 减费牌被误认成 Jinx、0 费法力读不出导致主循环卡死。
> 详情见 [`handoff.md`](handoff.md) 的最新 Jinx 记录。

> 2026-11-05：新增 Jinx 两步起手和两张牌的展开态模板。月度挑战 2 中
> 已识别 2 费 Jinx，但程序误以为必须在手牌看到应急装置才可继续；
> 用户指出开场时法术已打出。尚需补足前后连续证据并修正接续逻辑。
> 详情见 [`handoff.md`](handoff.md) 的最新 Jinx 记录。

> 当前补充：已建立 10 个标注截图案例，接入动作后验等待与超时停止、数字读数
> 有效性。详见 [`offline-validation.md`](offline-validation.md)。这些改动仅离线验收，
> 新版 LoR 的真实连续场景尚未验收。Pie64 已为 4C4G，但 07.11.015 在 Pie64 /
> Player 3 都启动闪退，根因未定。下面保留此前历史状态，不能作为新版兼容性保证。

> 2026-11-06 离线补充：格挡链路修复（`run` 的 `PassBlockPolicy` 接线错误、
> 伊莉絲包抢在通用格挡层前、未知攻血时不格挡），并补上伊莉絲展开态
> 手牌身份识别（真实 1080p 截图 6/6）。详见 `handoff.md` 最新一节。

> 以下环境、完成情况和待办保留 2026-11-04 的历史记录；较新的记录见本页顶部
> 和 `handoff.md`，issue 的实时状态以 GitHub 为准。
>
> **要接手开发，先读 [`docs/handoff.md`](handoff.md)。** 这份只记状态，不记行动计划。

## 里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| M0 | 骨架 + 规则 + 单测 + CI | ✅ 完成 |
| **M1** | 自动打完一场 PoC 战斗 | 🚧 进行中 |
| M2 | 自动选奖励（三选一） | 🚧 排序已实现，识别与接线待完成 |
| M3 | 自动走地图 | 🚧 已实现部分流程，待补场景与验收 |
| M4 | 跑完一个完整副本 | 待做 |

## 运行环境（2026-11-04 实测）

| 项 | 值 |
|---|---|
| 模拟器 | BlueStacks 5.22.286.1004 |
| 可用实例 | **`Pie64`（Android 9，density 240）** |
| 逻辑分辨率 | **1920×1080**（`adb shell wm size 1920x1080` 抬高；原生 1280×720 时手牌数字只有 ~10px，读不出） |
| ADB | `127.0.0.1:5555`（与 `emulator-5554` 是同一台） |
| LoR | `live_7-10-13`，账号 `mdy114514` |
| 账号密码 | `.env` 的 `LOR_USERNAME` / `LOR_PASSWORD`（不入库；f1 另用 `setx` 写了用户环境变量） |

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
| `perceive/normalize.py` | 分辨率解耦：按设计尺寸归一化后识别，动作坐标反算回设备像素 |
| `perceive/login.py` | 登录界面检测（`login_splash` / `login_form`） |
| `device/touch.py` | 输入原语：`TouchSurface.can_hold`、`EvdevSurface`（事件级手势）、`AdbInputSurface`（退化） |
| `perceive/hand.py` | 手牌徽章 / 费用识别（收起态 48px、展开态 56px 两套模板） |
| `perceive/unit_stats.py` | 单位攻击/生命数字：字体模板 + 颜色掩膜，读不出返回 -1 |
| `champions/elise/` | 伊莉絲英雄包：牌表 + 蜘蛛快攻规则 |
| `champions/elise/vision.py` | 展开态手牌身份：ORB 卡面匹配，低置信度保留空名 |
| `champions/jinx/` | 金克丝英雄包：牌表、起手策略与卡面识别 |
| `decide/combat.py` | 战斗求解器：精确枚举格挡分配与攻击声明 |
| `decide/generic.py` | 通用规则：英雄优先 / 攻击令牌 / 格挡资格与配对 |
| `decide/rewards.py` | 奖励三选一：英雄偏好 > 品质 > 费用 |
| `decide/card.py` | 卡牌通用词汇（CardKind / CardDef） |
| `champions/` | 英雄包注册表（加英雄 = 加目录，不改核心） |
| `decide/candidates.py` | 局面 → 候选动作 |
| `decide/router.py` | 分层路由 + 覆盖率统计 |
| `act/translate.py` | 语义动作 → 点击序列 |
| `loop/engine.py` | 主循环（含事件发射） |
| `loop/watchdog.py` | 卡住检测 |
| `loop/recovery.py` | 分级恢复状态机 |
| `tools/f1/` | f1 网络看门狗、游戏看门狗、Pie64 交互式启动脚本 |
| `util/logger.py` / `events.py` | 按日期分目录 + JSONL |
| `tools/analyze.py` | 复盘摘要 |
| `doctor.py` | 环境自检 |

测试结果随代码变化；以当前运行结果为准。

**已在真机验证**（BlueStacks `Pie64`，Android 9，横屏 1920×1080）：

- `adb screencap` 正常，`input tap` 正常
- LoR 启动、登录、进对局、手动打完一局都正常
- `lorwright state` 读出 `my_turn_idle / mana 2/2 / hp 50/30`，手牌 6 张费用 `0,0,2,2,5,5`（6/6 全对）
- 起手换牌识别正常（`assets/buttons/mulligan.png`，1080p）
- 动作按钮文字可判：`略過` / `略過格擋` / `結算` → `MY_TURN_IDLE` / `BLOCKING` / `COMBAT_RESOLVING`
- 账号密码从 `.env` 读取，`lorwright login` 可用
- **出牌手势**：展开态真机成功（蜘蛛上场、法力 3→2、手牌 6→5）；收起态拖不动，改「先 tap 展开再拖」（`handoff.md` §4.6）
- 手牌费用：收起态 6/6；展开态历史实测 4/6，现有 1080p fixtures 6/6（失败样本未保留）
- 场面识别还有敌方攻击行、生命遮挡和词条等待补充验证（issue #10）。

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

## 历史缺口清单（2026-11-04，部分已完成）

| 位置 | 缺什么 | Issue |
|---|---|---|
| `perceive/cards.py:recognize_hand` | 收起态手牌身份（展开态已由英雄包 vision 覆盖） | #3 |
| `loop/engine.py:_build_state` | 敌方攻击行真实帧、生命遮挡样本（单位攻血已接入） | #4 |
| `perceive/ui_state.py` | 地图/节点面板/商店/休息等对局外状态 | #2 |
| `config/settings.yaml:adventure` | 休息/商店按钮的真实坐标 | #2 |
| `loop/adventure.py` | 节点点击后仍在地图/旅行后仍在地图时已停止盲点；更细的面板类型识别仍缺 | #6 |

## 素材清单

| 素材 | 数量 | 位置 | 状态 |
|---|---|---|---|
| 按钮模板 | 3–5 | `assets/buttons/` | 🚧 有 `action_button.png`（手机版） |
| 卡牌图库 | **9**（伊莉絲牌组只有 9 种） | `champions/elise/assets/` | ✅ 0.35× 卡面模板 |
| 起手换牌「確定」 | 1 | `assets/buttons/` | ❌ 空（**P0**） |
| 挑战者 / 击晕图标 | 2 | `assets/buttons/` | ❌ 空 |

## 历史 issue 列表（非实时）

| # | 优先级 | 标题 |
|---|---|---|
| 1 | P0 | Windows 环境验证与首次 probe |
| 2 | P0 | UI 模板采集 + Layout 坐标标定 |
| 3 | P0 | 卡牌图库采集 + 手牌识别 |
| 4 | P0 | 状态解析：法力 / 血量 / 场面 |
| 5 | P1 | 端到端：自动打完一场战斗 |
| 6 | P1 | 异常恢复：分级策略 |
| 8 | P2 | JEV / LLM 接入验证（已按 ADR-0004 移除，不再做） |

## 历史行动顺序（非当前待办）

**见 [`docs/handoff.md`](handoff.md) §2。** 顺序：接口 → 底层最小集 → 英雄规则。

```
#9  出牌两帧流程进 run + 展开态费用 4/6 → 6/6（收起态已打通，见 handoff §4.6）
  ↓
#11 攻击声明 / 格挡手势（✅ 手势已通，通用格挡规则已接线）
  ↓
#10 场面识别（单位 / 攻血 / 挑战者 / 击晕）
  ↓
伊莉絲英雄规则（有攻击 token 才出伊莉絲、先遣先打）
  ↓
#5  端到端打完整一局
```

⚠️ **出牌没进端到端之前不要写英雄规则** —— 规则产出的动作无法在真机验证，
「策略对不对」会退化成「手势有没有生效」。

⚠️ **#12 前置自检** 优先级高于它标称的 P1：网络不通时登录页会假死，
诊断一次要半小时，不固化下来每次都要重来。

## 已知风险

| 风险 | 说明 |
|---|---|
| 卡牌变体 | 闪卡/皮肤会导致模板不匹配 → 记录失败样本 |
| 手牌重叠 | 切分困难 → 可用固定卡位 |
| 游戏自身卡死 | 表现为「输入全无效」，实为进程无响应。判据：连续两帧 0 差异 + `input keyevent 3`（HOME）有效 → `am force-stop` 后 `lorwright launch`。见 issue #12 |
| 登录态丢失 | **模拟器重启会清掉 LoR 登录态**，回到 Riot 登入页；`restart_app` 同样会掉。所以恢复阶梯的「重启客户端」默认禁用（`recovery.allow_client_restart=false`） |
| 网络不可达导致假死 | 登录页要拉 client config，`firestore.googleapis.com` 不通时永远停在「登入以開始遊戲」，点任何按钮都没反应（logcat: `BaconAuthenticationProvider Waiting on client config to be loaded`）。见 issue #12 |
| 游戏更新 | UI 变化要重采模板；`live_7-10-13` 之后要复核 `assets/buttons/*` |
| 封号 | 自动化违反 ToS，用小号试错 |
