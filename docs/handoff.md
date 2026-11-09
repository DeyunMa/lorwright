# 交接文档（给 F1 上继续开发的 agent）

> 这份是**入口**。先读完这份，再按 §7 的索引深入。

---

## 当前接手入口：先离线完善基础场景

> **阅读顺序**：本节按日期记录较新的进展；后面 §1–§2、§4 的旧进度和
> §9 的旧 issue 列表是历史记录，不作为当前待办。以本节、`status.md`
> 和 GitHub Issues 的实时状态为准。
>
### 2026-11-09：战斗中未知牌按费用尝试

- 用户确认：战斗中展开手牌后，牌名未识别但费用可读时按费用走基础
  规则。通用层在英雄策略、已知单位和英雄优先规则之后，尝试费用最低
  且可支付的未知牌；无法确定牌类型，也不能保证动作一定成功。
- Jinx 下场后若火箭还未打完、大手牌中又没有识别到可打的火箭，英雄
  策略等待，避免通用费用兜底抢在火箭前出牌。起手换牌的未知牌等待
  规则不受影响。仍需实机验证识别、拖牌、选目标及动作结果。
- `1080p_jinx_map.png` 的单独头像识别为 (735,285)，将其手动传入
  路径函数得到候选 (982,334)。实际冒险循环仍把该地图误判为打开面板，
  不选点并保存快照；头像识别也未接入导航，不能声称当前流程会点该节点。
  另一张 `1080p_map.png` 的路径回退会因 `MapNode` 当作元组而抛
  `TypeError`；头像识别在 `1080p_zoommax.png` 命中左下状态栏头像，
  不能在不排除该误定位的情况下直接接入地图导航。

### 2026-11-09：蛮力格挡与 Jinx 换牌

- 用户确认：蛮力攻击被格挡时，超过格挡者生命的伤害作用于主堡。
  通用 `BlockingPolicy` 的穷举评分和贪心回退现在都考虑已识别的蛮力
  溢出；继续遵循既有「白死且无法换掉攻击者就不挡」规则。攻血不全
  时无法计算溢出，贪心仍按已有的未知数值规则处理。
- 按用户指出的图标，从 `1080p_block_phase.png` 离线识别出六名带蛮力
  攻击者；另一张同场景截图当前定位到四名，四名均识别出蛮力；普通
  单位截图未检出。以上并不能证明跨场景、缩放、遮挡或实时识别能力。
  这张格挡图的生命值读不全，溢出数值用构造状态测试，未做实机验证。
- 用户确认 Jinx 换牌：有 Jinx 则保留一张、只替换多余 Jinx，其余牌
  都留；没有 Jinx 则四张全换；任何牌未识别或四张未齐时不操作。
  用户说明开局会抽一张英雄牌，可能是 Jinx 或辅助英雄，目标是开局
  手里有一到两张 Jinx；抽牌具体时点尚未核实。
- 现有 `mulligan-4cards.png` 识别到四张非 Jinx，离线决策是全部
  替换；有 Jinx、重复 Jinx 和未知牌仅用构造状态测试，尚缺对应实战
  截图与替换选中、确认后的连续画面。当前发送替换点击后仍未验证
  选中结果，不能声称换牌全流程实机完成。

### 2026-11-09：隐秘与锐目离线截图回归

- 用户确认：隐秘只能被隐秘或锐目单位格挡；锐目不赋予攻击隐秘。蛮力
  （Overwhelm）使超过格挡者生命的伤害作用于主堡。
- `1080p_block_phase.png` 中六个敌方攻击者都有斜线眼隐秘图标、我方
  三个单位没有隐秘或锐目。旧解析器漏掉六个攻击者，点击略过并非因为
  已识别隐秘。现在扩大攻击行范围，以斜线眼辅助找粉色数值框：离线
  识别 6 个隐秘攻击者，通用格挡规则不分配普通格挡者。
- `1080p_units_combat.png` 是独立的待命位正例，找回一个此前漏掉的
  隐秘单位；`1080p_units_idle.png` 的紫色发光单位不是隐秘，不能只按
  边框颜色判定。当前是两张正例截图的固定尺寸模板验证，不代表其他
  缩放、动画或遮挡下均可识别；未识别到图标也不能证明一定没有隐秘。
- 锐目的合法格挡规则有测试，但尚无真实锐目画面验证视觉识别；
  `BlockElusive` 的原始图标资源可作参考。该节之后蛮力已接入通用
  `BlockingPolicy`，具体覆盖与限制见上方最新记录。

### 2026-11-09：冒险画面安全边界与能力推荐（离线）

- 战斗 UI 检测器不认识地图，因此地图帧会得到战斗意义上的 `UNKNOWN`。
  `AdventureLoop` 现在另行识别地图返回键和缩放控件，或战斗详情标题；
  无法识别的画面保存快照并停止。旅行/战斗按钮还须匹配文字，只有
  识别到「遭遇戰已完成」的面板才尝试点空白关闭，且重试前重新识别。
  这些是现有截图的离线回归，尚未在 f1 复验；其他语言、遮挡和新界面
  可能被保守拒绝，不能把模板匹配视为所有未知画面的完备证明。
- `1080p_ability_select.png` 的三个能力名称与品质可由截图模板识别，
  已接 `pick_reward` 和当前英雄包能力偏好。任一候选或品质未知就弃权。
  目前只记录推荐并保存快照：没有选择后/确认后的连续实机画面，
  尚不能验证选中与确认，也未覆盖其他能力名称、道具、法术或支援英雄界面。
- 用户确认：圣物是英雄开局携带的装备；战斗中获得的道具是通用道具，
  不分英雄专属和单位专属。`闇影圖騰`可用于符合条件的英雄牌或单位牌。
  `闇影圖騰`（I0012）与 `重拳出擊`（I0130）
  是道具，已从对应英雄包的圣物偏好移至道具偏好；偏好不表示开局已拥有。
- 法力读数连续丢失 5 帧不再直接猜为 0：仅在同一优先权内此前新鲜读到
  0、且此后未发生操作或状态切换时沿用；否则保持 `NO_OP`。下文 11-07
  记载的无条件按 0 处理已被这一约束取代。
- 下方首局记录引用的 `logs/2026-11-09/events.jsonl` 在当前工作区不存在；
  首局过程暂以此前交接记录为依据，日志内容尚未在此工作区复核。

### 2026-11-09：Jinx 首局实战 + 地图导航修复 + 起手换牌

**首局实战**（每月挑战挑戰4 · 神射海盗，敌方水晶 16 血）：引擎完成
mulligan 確定、手牌展开、两张单位牌下场；`汙水坑疏濬機器人` 触发
「棄置1張牌」时 `TargetingPolicy` 只会选单位/取消导致超时停机（已修），
人工接管弃牌 + 火箭指向水晶斩杀获胜。全程事件在
`logs/2026-11-09/events.jsonl`（81 行）。

**地图导航**（协作模式逐屏审计校准）：
- `champions/jinx/vision.py: recognize_hero()`：Jinx 头像 ORB 模板
  （`assets/hero_portrait.png`，110×110，nfeatures=8000），地图帧返回
  头像中心，修复「英雄节点找不到只能回退画面中心」。
- `perceive/mapnav.py: next_node_by_path()`：`detect_nodes` 的圆环判据
  在部分地图会漏检，改取最大发光路径、选离英雄最远的端点，端点附近
  低阈值 Hough 找圆，按 **Canny 边缘密度 × 半径** 选整圆（节点
  0.22–0.27 vs 背景 0.11，阈值 0.18）。
- `perceive/mapnav.py: detect_ability_nodes()` 收紧：要求「金环 + 深色
  中心」（中心 1/3 金色占比 <0.3），尺寸限 30–90px；同色地形/装饰
  都是实心金块，此前一张图误报 10 个、现在只剩真节点。
- 已知缺口：`panel_open` 用蓝色像素总量判断，部分地图态会被误判成
  面板打开（`next_node` 因此返回 None）；本轮实测直接调
  `next_node_by_path()` 绕过，待收紧。

**TargetingPolicy**（`decide/generic.py`）：手牌展开 = 弃牌提示，点第一张
手牌；手牌收起时先敌方单位 → 我方单位 → 敌方水晶（法术可直接点
水晶斩杀）。`act/translate.py` 支持 `raw={"hand"|"nexus"}`。

**起手换牌**：`vision.recognize_mulligan()` 按 4 个「替換」按钮坐标
（438/756/1068/1386, ~820）识别卡面；`JinxOpeningPolicy` 保留
`應急裝置`/`吉茵珂絲`，其余发 `MULLIGAN_REPLACE`（多点点击，outcome
直接按已发送成功，下一 tick 確定）。起手没有这两张时会主动换牌找组件。

**仓库清理**：`logs/` 散图裁剪到 11-08/09 会话（569M→215M），保留
`f1-material-20261106/` 素材目录；删除其重复 zip（116M）、
`docs/handoff-windows.md`（已废弃、git 可找回）、无引用的
`champions/jinx/assets/legacy/` 旧模板（旧路径 git 可找回）。

### 2026-11-07 补充：Jinx 下场后的飞逝火箭

用户确认 Jinx 下场会把所有手牌替换成最左侧 2 张飞逝牌
「超威能死亡火箭！」（简中：超究极死神飞弹）和右侧 4 张「砰砰」。
两张火箭是飞逝牌，回合结束还在手牌就会自动弃掉；所以起手第三步是
**当回合打掉两张火箭**，不能先结束回合。

- `champions/jinx/policy.py`：`step 2` 优先打火箭（最多 2 张），再打砰砰；
  名字认不出时只对 ≤2 张手牌按最左兜底，中局大手牌不猜。
- `champions/jinx/vision.py`：费用过滤改为 `definition.cost >= card.cost`，
  修复 PoC 减费砰砰（2→1）被误认成 Jinx 的问题；新增 `01PZ040T1` 火箭模板。
- `loop/engine.py`：0 费时法力数字整段读不出来；连续 5 帧读不出后按 0 费
  处理，允许结束回合，避免整局卡死。
- CLI：`--jinx-summoned` 用于中局恢复（Jinx 已下场，直接从打飞逝牌开始）。

### 2026-11-07：Jinx 完整牌表 + 9 张手牌识别 + 通用下单位层

**Jinx 牌表**：`champions/jinx/deck.py` 现在是完整 9 种 ×2 = 18 张：
`01PZ040 吉茵珂絲(4/4/3)`、`99PZ130 砰砰(2 法术)`、`01PZ054 爆破幫菜鳥(2/1/3)`、
`01PZ009 懸浮飛板初學者(3/2/3)`、`99PZ104 火箭滑板(2/3/3)`、
`01PZ019 勤奮的學徒(2/2/1)`、`01PZ045 佐恩小乞丐(1/2/1)`、
`01PZ038 汙水坑疏濬機器人(3/4/3)`、`01PZ028 應急裝置(1 法术)`。
数据源：`lorwright-artifacts/research/champion-progression/data/champions.jsonl`
（Jinx 行，已对 07.11.015 ClientCardData 交叉核验）。

**手牌识别**：`champions/jinx/vision.py` 改为 9 张卡面 ORB 匹配 + 费用过滤：
- 卡面模板在 `champions/jinx/assets/<code>.png`（01PZ* 来自 Data Dragon，
  99PZ* 从 AssetBundle 提取）；
- 费用只排除「显示费用高于基础费用」的候选；PoC 道具可给任意牌减费
  （实测砰砰 2→1，Jinx 4→2）；
- 真实 8 张手牌截图 `live-8cards.png` 命名 7/8（未知的是牌组外的 5 费牌）。

**通用层**（`decide/generic.py` + `main._battle_layers`）：
- `expand_hand`：我方回合手牌收起时先展开；
- `play_unit`：场面 <6 时按费用从低到高打已知单位，跳过法术/未知牌；
- `targeting`：TARGETING 时先点敌方单位，再点我方，最后取消；
- `combat_confirm`：COMBAT_RESOLVING 点确认；
- `blocking`：沿用通用格挡。

**CLI**：`run` / `adventure` 新增 `--champion`（覆盖配置英雄包）和
`--spell-already-played`（Jinx 恢复中局跳过起手法术）。

**f1 回放验证**：`--champion jinx --replay` 喂真实 8 张手牌帧，路由为
`jinx_opening → expand_hand → play_unit → hero_first → targeting → attack_when_token → combat_confirm → blocking`，
动作是 `play_card`，拖拽起点落在應急裝置。

**对局素材**：`logs/f1-material-20261106/`（48 张，47 张可读 1920×1080；
1 张连续截图损坏），含手动出牌/选目标/卡牌详情/地图/战斗接管截图。

### 2026-11-06：单位攻血识别 + f1 最外层看门狗（f1 已恢复）

**单位攻血（#10 的数值部分）**：

- `perceive/unit_stats.py`：橙色攻击徽章里的白/绿数字 + 红色生命徽章里的
  白数字；用游戏资源 `BeaufortforLOL-Bold` 预渲染的 0–9 模板分类
  （`assets/digits_unit/`，140 张小图）。
- `perceive/units.py:to_units(..., image=...)` 现在会填 `attack/health`；
  `StateParser` 传入当前帧。读不出或置信度 <0.80 仍保留 `-1`。
- `perceive/digits.py` 的模板加载先裁到笔画外框，否则带黑边的字体模板
  缩到 16×24 后相似度会掉到噪声。
- 真实截图回归：`1080p_units_idle.png` 我方攻击 `[4,6]`、敌方 `[8,2]`；
  `1080p_units_combat.png` 我方 `[1,7,7,1,1,1]`、敌方 `[12,5,3,3,12]`。
  生命被红色高光遮住时返回 `-1`，不猜。
- `plan_blocks` 在攻/血任一为 `-1` 时退回贪心，避免把 `-1` 代进阵亡价值公式。
- `loop/adventure.py`：节点点击后仍能看到地图节点、或旅行后仍在地图时，
  存快照并停止，不再盲点旅行/休息/商店；新增真实面板 fixture 回归。

**f1 运维（已部署）**：

- `F1NetWatchdog` 仍是网络专用；TUN 试开改为“稳定 30 分钟后试开 60 秒，
  HTTP+DNS 正常就保留，失败立即关回并等 60 分钟”。
- 新增 `F1GameWatchdog`（每 5 分钟，SYSTEM）：网络看门狗失败/退避时跳过；
  检查 `HD-Player`、ADB、LoR `pidof`；缺模拟器 2 次 → 运行 `F1StartPie64`；
  缺 LoR 1–2 次 → `lorwright launch`；第 3 次 → force-stop + launch + login；
  ADB 连续 6 次失败才重启模拟器。
- `F1StartPie64` 是 Administrator + Interactive 任务，已在模拟器运行时验证
  只记日志、不重启。脚本已收进 `tools/f1/`。
- **配置错误已修**：`config/settings.yaml` 的 `adb.serial` 从 5556 改为 5555；
  f1 上实际监听 5555（`emulator-5554` 是同一实例）。
- 当前 f1：TUN 已由用户手动打开，网络 3/3；LoR PID 4583 前台；`lorwright state`
  仍为 `unknown`（主页/加载页不是战斗状态）。

### 2026-11-06：格挡链路修复 + 伊莉絲手牌身份识别（离线，未动 f1）

**格挡链路（三个会让规则静默失效的接线点）**：

1. `lorwright run` 曾 import `PassBlockPolicy`（不存在）→ 启动即
   `ImportError`。`run` / `adventure` 现在共用 `main._battle_layers()`，
   两条路径都装配 `BlockingPolicy`。
2. 伊莉絲包在 `BLOCKING` 返回 `NO_OP`，抢在通用格挡层前面；现在改为
   弃权 `None`，由 `BlockingPolicy` 接管。
3. 感知层单位攻击/生命恒为 `-1` 时，`plan_blocks` 的贪心退路原来会
   `continue` 掉所有攻击者 → 整轮不格挡。现在未知数值按「能挡就挡」
   配对，至少不会因为读数缺失直接放行。
4. `act/translate.py` 的 BLOCK 原来按下标查 `enemy_units`，而
   `BlockingPolicy` 现在按下标查 `enemy_attackers`；两者不一致会把格挡
   拖到待命单位上。翻译层已改为 `enemy_attackers or enemy_units`，
   和决策层同源。

**规则补齐**（`decide/generic.py` 与 `decide/combat.py` 同步）：

| 规则 | 判定 | 证据 |
|---|---|---|
| Fearsome | blocker 攻击 `< 3` 才失败（攻击 3 可挡） | 原生 `GetFearsomeBlockingValue`=3 |
| Elusive | blocker 需有 `Elusive` 或 `BlockElusive` | 原生 `NoStealthBlock(41)` |
| Brash | blocker 生命 `< 3` 才失败（生命 3 可挡） | 官方关键词文本 `globals-en_us.json` |
| Reckless / Immobile | 不能格挡 | 原生 `StatePreventsBlock` |

回归：`tests/test_generic_rules.py`、`tests/test_combat.py`、
`tests/test_battle_layers.py`。其中 `test_battle_layers.py` 同时锁住
「run/adventure 必须装 BlockingPolicy」和「英雄包在 BLOCKING 必须弃权」。

**伊莉絲手牌身份（#3 的展开态部分）**：

- `champions/elise/vision.py` 用 ORB 匹配 9 张卡面模板，模板在
  `champions/elise/assets/`（Data Dragon 680×1024 缩到 0.35，共 1.1MB）。
- 真实截图 `tests/fixtures/screens/1080p_hand_expanded.png` 6/6 命中：
  小蜘蛛(1)、尖嘯蜘蛛(4)、蜘蛛哨兵(3)、發狂疾行蛛(3)、伊莉絲(2)、
  闇影島泰爾石(0)。
- 回放验证：`lorwright run --replay` 喂这张图，命中 `elise_spider_aggro`，
  动作是 `play_card`（拖拽起点落在 2 费伊莉絲），说明名字已进入评分链。
- 低置信度（匹配数 <20 或第一名领先 <10）保留空名，不猜；收起态扇形
  仍只有费用，身份识别只覆盖展开态。

**仍未解决（需要 f1 实机帧）**：

- `GameState.enemy_attackers` 已接 `layout.enemy_combat` 区域（合成图测试）；
  真实 BLOCKING 帧还没标定，识别不到时 `BlockingPolicy` 回退到 `enemy_units`。
- 单位攻击/生命已由 `unit_stats.py` 接入；敌方攻击行真实帧和生命遮挡样本
  仍未验证，这是 #10 剩下的部分。
- mapnav 已切到 1080p-only（英雄=画面中心，点击不再 ×2）；已换 2 张实机
  1080p 帧，剩余场景的 20 帧回归仍待补采。

### 2026-11-06：地图识别基准与 mapnav v2（离线迭代，未动 f1）

**语义链（本轮用 20 张实机截图 + 连续帧移动链确认）**：
- 英雄头像所在节点 = 当前节点（glow 指标跟随头像）；
- **节点中心的青绿徽章 = 已完成**。颜色 BGR≈(149,147,118)，
  判别式 `g>135 & r<135 & g-r>=20 & b-g<=15`——b-g<=15 是关键：
  徽章 B/G 平衡（+3），节点环蓝主导（+42），漏掉会误判；
  徽章在离开节点后保留，事件完成即出现；
- 亮白蓝发光线 = 当前可走，**节点事件完成后才点亮**（m3-g6 商店
  事件未完成时全图无可走线，shopD 完成后 (240,373) 才亮）；
- 金色菱形 = 能力/辅助节点的**类型图标**，不是位置标记
  （此前误当过位置标记）。

**mapnav v2 改动**（960×540 历史空间；现已迁移到 1080p）：
1. has_checkmark 换青绿判据（旧纯绿判据 0 命中，导致已完成节点
   不被排除、回走旧线）；
2. _reachable_nodes 采样 dist/12→dist/8、窗口 ±10→±12、阈值
   0.6→0.38（实测真可走线 0.41-0.93、锁定/背景 0.06-0.32）；
3. next_node 面板门控：blue_glow ≥2500px（面板态实测 ≥3354，
   地图态 ≤1832）直接返回 None，面板打开时不导航；
4. 英雄指标丢失时用金色菱形关联 fallback（re2-map2 缩放态实测找回）。

**历史离线基准**：旧 tests/fixtures/mapnav/ 20 张 960×540 图（1.6MB），14 张地图态
断言 hero+next 精确坐标、6 张门控态断言不导航不崩溃、对勾用移动链
断言。此前 16 张只有 6 张完全识别成功，现在 14 张地图态全部命中。

**素材问题结论（用户问）**：截图全部是程序产物（f1 上 adb screencap，
与运行时同一管线）。旧地图图是 960×540；2026-11-06 起 mapnav 直接用
1920×1080 原帧，旧图已归档到 `tests/fixtures/mapnav_960_legacy/`。

### 2026-11-06：奖励决策模块落地（decide/rewards.py）

- **决策链路（用户确认）**：英雄包偏好 > 品质优先 > 费用优先。
  pick_reward(candidates, preferences)：偏好按 Preference.names
  精确匹配（中英对照、大小写不敏感）；未命中按 QUALITY_RANK 降序、
  费用升序、未知品质垫底。返回 RewardPick(candidate, reason)。
- 节点类型决定用哪张偏好表（圣物/道具/法术/能力各自调用）。
- 6 条单测；UI 自动化等遇到奖励节点再建。

**下次 f1 实机采集清单（1080p PNG 原帧，一次采完）**：
1. 结算屏各变体：战斗胜利横幅、每月挑战胜利/结果页、失败画面
   （960x540 jpg 变体差异大且跨屏不通用，必须用原帧裁模板）。
2. 奖励节点面板：道具节点、法术节点、能力节点、支援英雄选择、
   商店购买面板（给 rewards.py 接识别层用）。
3. 休息节点（加号）面板 —— 目前完全没素材。
4. **地图帧 1080p PNG ×20**：与现有 960x540 fixtures 同批同场景重采
   （对应 tests/test_mapnav.py 的 CASES + GATED_CASES），供 mapnav
   迁移到统一 1080p 设计空间用。

**任务：mapnav 统一 1080p 设计空间（2026-11-06 已执行代码迁移）**

背景：AdventureLoop 目前把 1080p 帧缩到 960x540 喂 mapnav、点击 ×2
还原——第二套坐标空间已造成过『忘 ×2 点空处』的坑（卡点记录 1）。
地图分析尺寸不是性能需要（mapnav 低频运行），是历史包袱。

执行状态：
1. ✅ 在真 1080p 帧上重新标定 detect_nodes（半径 36–84、param2=40）、
   发光采样（dist/16、窗口 ±24）与面板阈值（blue ≥5000）；
2. ✅ 删除 `_find_next` 缩半与 ×2，`next_node` 直接吃 1080p，英雄=画面中心；
3. 🚧 fixtures 已换 2 张实机 1080p 帧（`1080p_map.png` / `1080p_panel.png`），
   旧 960 图归档到 `mapnav_960_legacy/`；剩余 18 个场景待补采；
4. 🚧 当前 1080p 基准 + pytest 全绿；完整 20 帧回归待补采后收尾。

### 2026-11-06：research 逆向资料包接入

**资料包**：research/lor-client-07.10.013-v1/（43 文件，verify.py 全过）。
来源：lorwright-artifacts/analysis/stages/05-native-ai/round2/（完整
AI 算法未恢复，Round2 结论见其 findings.md——合法动作列表存在
WebSocket 静态链路，但不是 PoC API，禁止接入，ADR-0002 继续成立）。

**已接入（本次）**：
- **格挡资格规则**（decide/generic.py）：恐惧门槛=3（原生
  GetFearsomeBlockingValue 恒返 3，data/native-rule-components.json）、
  击晕/Immobile/Reclless 不能格挡（StatePreventsBlock）。穷举候选按
  攻击者预过滤，贪心同规则；攻击力未识别（-1）按能挡就挡。
  +6 条测试（273 全绿）。
- **牌表交叉核验**：elise-starter.json（Data Dragon 7_10_0）
  9 种 18 张与 champions/elise/deck.py 逐张比对，费用/攻血全一致。

**已入库待用（不要现在接）**：
- images/cards/ 9 张繁中 680×1024 卡面 → 手牌身份识别素材
  （不能直接当透视遮挡后的手牌模板，需截图回归）；
- images/keywords/ 18 个透明关键词图标 → 场面识别素材（issue #10；
  Stunned 同帧曾误报，不能用统一阈值）；
- data/keyword-ai-weights.json 34 关键词 AI 倍率 → 未来评分校准
  参考，**不要**替换穷举求解器；
- data/elise-progression-source.json 139 个成长/星力对象+338 条双语
  文本 → 星级/成长链研究用。

### 2026-11-06：数据集按 verify-not-infer 标准重查完毕

- **牌表审计**（tools/audit_deck_cards.py → data/deck-audit.json）：
  Elise 9 张 + Jinx 2 张名字/cost 对 07.11.015 ClientCardData 全一致。
  **Jinx PoC 卡码 = 01PZ040**（4/4/3），经典 04SI006 当前数据不存在——
  引用卡码必须用 01PZ040（jinx/__init__.py 已注）。
- **奖励名称表修正**：闇影圖騰是道具 I0012（不是 Jinx 初始圣物——
  用户纠错）；loc 键大小写不统一（_Name/_name），匹配必须不敏感；
  范围按路径统计实锤；无显示名变体进 excluded；全集校验内置提取器。
  最终 178 道具 + 153 圣物 + 1291 能力（15 缺名全是 FoePowers 敌方
  能力，已加 foe_power 标记，玩家侧 841 缺名 = 0）。
- **REA 项目交接文档**：`../lorwright-artifacts/analysis/
  INTEGRATION-STATUS-lorwright-2026-11-06.md`——已消费产物、验证
  标准、深挖建议排序（PoC 卡名本地化源 > 图标提取 > 品质映射 >
  adventure 未解），给后续分析对话的入口。
- 反面教训已入 memory（feedback_verify-not-infer）：推断污染系统，
  锚点抽样不能代替全集校验。

### 2026-11-05：Jinx 起手与月度挑战 2

**2026-11-05 晚：本轮新增（已测 238 项全绿）**：

- **JEV/LLM 层移除**（用户决策）：纯脚本路线（MAA 式）。删了 decide/jev*.py、
  llm.py、test_jev_fallback.py 及 config/doctor 相关字段；Router 分层保留。
- **BlockingPolicy 通用格挡**（decide/generic.py）：能挡就挡；穷举全部指派
  （6v6 约 3700 种，超限退贪心）取最小总损失 = 脸伤×2（未挡攻击者）
  + 阵亡单位价值 + 残留威胁；白死（挡了死但杀不死）配对直接禁止。
  攻击者 = BLOCKING 时 enemy_combat 区域内的敌方单位（settings 新增
  layout.enemy_combat）；识别不出（-1）退化为能挡就挡。声明后下一 tick 确认。
  outcome 的格挡验证与攻击同向（格挡位在敌方半场，单位向上移动）。
- **AdventureLoop（loop/adventure.py + lorwright adventure 命令）**：
  地图上点带蓝色指向标的下一节点（mapnav，跳过绿色对勾已完成节点，
  分叉随机）→ 节点面板 → travel → 分类处理：战斗交引擎 / 商店离开 /
  休息点第一个选项（待实机校准坐标）→ 回地图。坐标在 settings.adventure。
- 顶层「打月本/打周本」= lorwright adventure（后续按冒险类型分化）。

**2026-11-05 深夜：英雄奖励偏好规则（已落数据，237 全绿，含 3 条新测试）**：

- **默认规则（用户确认）**：奖励选择未命中英雄偏好时，按「品质优先，
  其次费用」排序；英雄包里的偏好永远压过默认规则。
- **节点类型**：圣物 = 英雄开局自带的装备；道具节点 = 给卡组已有卡牌
  选道具；法术节点 = 新选一个法术；能力节点 = 菱形节点（选星力）。
  道具/法术节点的 UI 自动化等遇到节点再做，先落偏好数据。
- **Jinx**：遗物「闇影圖騰」(Shadow Totem) 高优先；能力「分身術」
  (Stabilize) 高优先。
- **Elise**：遗物「重拳出擊」(Heavy Hands) 最优先（雙重攻擊；
  已有双攻/閃靈/不可移动的卡不吃）。
- **数据位置**：`champions/base.py` 的 `Preference`（names=中英对照,
  note=理由）+ `ChampionPack` 协议的 relic/item/spell/power_preferences
  四个属性；偏好常量在各英雄包 `__init__.py`。
- **名字来源（官方本地化数据，以后查译名照这个方法）**：
  `../lorwright-artifacts/game/downloaded/PatcherData/PatchableFiles/
  GamePlayData/LocalizedText_<locale>.bin`，格式 = 键名 + 2 字节小端
  长度 + UTF-8 值，直接顺序拼接。遗物/能力名字在 `sticker_*` /
  `power_*` 键下（如 sticker_ephemeralcopy=闇影圖騰、
  power_summon_stabilize=分身術、sticker_I0130=重拳出擊）。
- **素材情况**：遗物/道具/能力节点的真实截图已有
  （diagnostics/2026-11-05-pie64-restart/ 的 hero-item-open.jpg、
  power-node.jpg、take-item-confirmed.jpg、monthly2-spell-pick.jpg 等），
  做识别时直接从截图裁模板，不用解析 AssetBundles。

**2026-11-05 卡点记录（后续不要再犯）**：

1. **坐标空间**：mapnav 在 960x540 预览图上算出的节点坐标，直接拿去
   f1-control --tap（真实 1920x1080）导致点到空处、静默无响应，浪费半小时。
   规则：感知坐标必须 x2 或直接在原图上算，点击前先确认坐标空间。
2. **f1 网络反复断线**：Riot 掉线弹 服務錯誤 17000/18000，对局被踢回主页，
   节点交互静默失败（面板空白、点节点无反应）。恢复路径：
   主页 → 英雄之路横幅 → 每月挑战 → 挑战3 → 继续冒险。
   主页直接点右侧「英雄之路」横幅即可进世界地图（每周宝库上方）。
3. **地图语义（用户确认）**：金菱形标记 = 英雄当前节点；白棋子圆圈 = 下一个
   节点（棋子=遭遇战；绿色箭头是方向指示，不是节点）；发光白蓝实线 = 可走；
   暗红虚线 = 锁定。商店节点：点节点 → 旅行 → 购买/离开。
   **节点推进机制（用户确认，2026-11-05）**：节点内操作完成后英雄
   **不会自动离开**，必须点击下一个节点触发移动，当前节点才算结束。
   导航循环必须显式分两步：完成节点事件 → 点击下一节点移动；
   不能假设操作完成后地图自动前进。
4. **每月挑战英雄次数**：每位英雄每月 3 次，Jinx 剩 1 次（截至 2026-11-05）。
5. **顶层目标（用户确认）**：最终封装「打月本」「打周本」等单命令入口；
   现在的 mapnav/节点事件/战斗引擎都是它的基础能力。

**对局外导航（新增 perceive/mapnav.py，已用真实截图回归）**：

- 节点检测：HoughCircles 圈出地图节点（过滤左菜单/顶栏/右详情栏），三张
  实拍截图稳定检出英雄节点、节点圆、商店/Boss 节点。
- 英雄节点：环下缘（中心 +8..+45px）有蓝色指向标（B-R>80）的节点，
  三张截图都唯一命中。
- 可走路径：发光白线阈值 min(B,G)>200 & R>170；走廊采样 60% 命中判可达。
  暗红虚线（锁定路径）被正确排除。分叉多条时随机选（用户规则）。
- 月本 3 地图实测结论：英雄 →「甜蜜家園」休息节点（提示“遭遇战已完成”）
  → 商店/战斗；右上 Boss（爐）当前锁定（“有东西阻挡了去路”）。
- 待做：把 mapnav 接进 AdventureLoop（点节点 → 处理商店/休息/选卡事件 →
  进战斗交引擎 → 回地图循环）；f1 恢复后同步验证。

**月度挑战 2 已用 Jinx 胜利通关（S 评价，13:47，Jinx 为主力）。**

- 起手两步组合在实战中完整走通：先打 1 费「應急裝置」召出 3/3 蜘蛛，
  Jinx 随即减费至 2 并下场（下场即升级，8+ 攻），之后每回合结算对手 2-6 点灼烧。
- 本局因 f1 断线曾弹「服務錯誤 18000」并被踢回主界面；重新进入
  英雄之路 → 世界地图 → 每月挑戰 → 挑戰2 →「繼續冒險」可恢复同一局。程序需要实现这个恢复路径。
- **新通用原则：有英雄优先出英雄**（用户确认）。例外由英雄包维护；
  Jinx 包的例外是起手两步组合（先應急裝置给 Jinx 减费）。
- 攻击令牌按回合轮换：攻击过的下一回合没有令牌，不能当作有令牌处理。
  格挡权衡：Jinx 这类 1 血英雄不换死挡。
- 实战确认应急装置开局自动补入手牌（换牌没抽到也能首回合打出）。

- 用户指定起手顺序：先打 1 费「應急裝置」召蟹，再打减到 2 费的 Jinx；
  英雄优先级高于默认规则。已新增 Jinx 英雄包及两张牌的展开态识别。
- 用户补充：「應急裝置」有装备保证其开局可用，这个组合每局一次；
  用户指出月度挑战 2 的画面已是应急装置打出后的状态。程序识别了两张
  2 费 Jinx，却因手牌没看到该法术而错误等待。缺少开局连续帧，
  日志不能独立确定它何时被打出或弃置；不能将手牌里没有等同于未抽到。
  此后手动空过，最近一次确认画面中 Jinx 为 4 费、我方血量 34；
  连接恢复后的截图仍显示 Jinx 4 费、我方 34 血。
- Jinx 策略可由调用方在有可靠证据或人工确认时用
  `JinxOpeningPolicy(spell_already_played=True)` 接续第二步，换牌时重置；
  普通 CLI 尚未提供此接续参数。不能仅凭 2 费或手牌缺牌推断第一步完成。
- 开场动画期间首次展开手牌未成功，程序等待后超时停止；已增加稳定帧
  等待。展开手牌会遮挡场上单位，起手策略现在保存收起态的场面基数，
  再检查新单位；场面或牌无法确认时停止，不按费用猜牌。
- 两张历史实战截图通过模板和费用识别；模板只覆盖少量截图，尚需更广泛验证。
  本机代码为最新；f1 的独立试验目录不一定含最后的修订。


### 2026-11-05 最新闪退诊断（优先于下文历史采集状态）

- 匹配构建的 boot.art 切片已读取；远端 oatdump 确认现场反射 Method 对象为
  `java.security.MessageDigest.getInstance(String)`，DEX 索引8769，静态入口非零。
  **对象身份已确认，故障调用者与根因尚未确认，LoR 尚未修复。**
- 同一 Pie64 的独立 DEX 探针直接/反射调用 SHA-256 均成功，结果正确。
- 一次 speed 编译模式对照仅启动一次 LoR（PID6367），仍 SIGSEGV/PC0；APK SHA前后一致。
- 最初 compile --reset 被系统拒绝，随后显式 compile -m speed-profile -f 成功；
  此前远端读回确认 filter=speed-profile、reason=unknown。恢复的是编译模式，非字节级缓存。
- 连接恢复后，最新 compile-control.json 与完整 message-digest-oatdump.txt 已取回并通过SHA校验。
  当前只读查询再次确认 Android9、同一boot_id、filter=speed-profile；LoR当前无运行PID。
  本次未编译、未启动游戏。完整OAT输出没有补出JIT调用者，根因结论不变。
- 下一缺口是将 JIT 返回地址候选绑定到实际调用指令及应用调用者；现有 tombstone 未记录
  所需机器码/方法映射。不能根据 Method 对象身份修补 MessageDigest 或归因 cf53/Houdini。

诊断目录：`../lorwright-artifacts/analysis/diagnostics/2026-11-05-pie64-restart/`。
下文“映像采集未成功、未执行编译变更”属于此前阶段，已由以上进展覆盖。

本轮已新增截图标注案例、动作后验等待/超时停止、读数新鲜度标记。
实现与验收方法见 [`offline-validation.md`](offline-validation.md)，
截图格式见 [`tests/fixtures/cases/README.md`](../tests/fixtures/cases/README.md)。
主循环现在不会在等待结果时重复输入；缺少本帧数字时不会用旧值继续普通决策。

用户要求：先在外层通过截图/回放迭代，再解决模拟器，进 LoR 后定点验收，
最后完善英雄逻辑。本轮未调整英雄评分；只修复展开手牌被记作出牌失败的状态记录。

环境新事实：Pie64 已改为 4C4G；LoR 更新为 07.11.015 后，Pie64 与新 Player 3
均启动闪退。原因尚未确定，不能将旧版 Android 对照结论用于新版。
2026-11-05 已从 f1 的 Engine/requirements.json 取到 LoR 规则 l63d8gsp：
Pie64 / Nougat64 且 BlueStacks>=5.9.100 时推荐 **Nougat32**，链接与原弹窗文章一致；
translations.json 中文文字也已核实。规则无 LoR 版本条件，grmEvaluation=0 含义未定，
未恢复实际弹窗触发日志；不要把缓存推荐当成新版必能运行的保证。现有导出包是 ARM64 分包，
当前游戏是否有32位发行尚未确认。实际 BlueStacks 为5.22.286.1004，已满足该版本条件。
本次 Pie64 单次启动仍在约331ms后 SIGSEGV/PC0；未定位故障模块。
升级静态比较：两版 minSdk24/targetSdk36/compileSdk36 相同，Unity/Firebase等14个同名原生库SHA一致；
Firebase/LoRActivity/UnityPlayerActivity初始化方法结构与小型原生库有变化，但尚未定位责任函数。
证据见 `../lorwright-artifacts/analysis/diagnostics/2026-11-05-upgrade-diff/README.md`；不能据此归因反作弊或配置。
已读取Player3 / Android11历史SYSTEM_TOMBSTONE：栈顶返回地址对应libart文件偏移0x170bdd，
其前为`call [rdi+0x20]`，记录rdi/rip为0；BuildId和记录的局部代码字节已核对。
支持ART间接调用到0的调用点推断，但未确定Java方法或根因；不能套用于Pie64。
记录DEX片段在新版两DEX均未匹配；Pie64对应DropBox为contents lost，本轮未重新启动游戏。
后续已完成Pie64独立重启：Windows进程9584→12112，新boot_id为
`ff86618f-8437-4f11-ab9c-e4a1f995b3af`，4C4G、Android9、ADB5555、07.11.015确认。
单次启动LoR仍闪退（PID4207，设备时间2026-11-05 14:20:03），但普通ADB bugreport成功取得完整
`tombstone_10`，无需root。主线程展开仍仅PC0；栈顶值0x44ff26a6落在JIT代码缓存，
不能套用Android11的ART解释器调用点。libcf53已映射，未见Unity具名模块；具体调用者尚未定位。
证据与后续分析见 `../lorwright-artifacts/analysis/diagnostics/2026-11-05-pie64-restart/`。
用于交互桌面启动的无触发器临时任务已删除，Player3进程21196未重启；未改编译模式、未清游戏数据。
进一步离线解析见同目录`pie64-managed-object-layout.md`：记录中的相邻对象支持
`getInstance(String)`签名候选，Method对象候选字段为declaringClass=0x70a265a8、
artMethod=0x70b70568、dexMethodIndex=0x2241。尚未确认它是故障调用目标。
下一步用同构建静态boot.art交叉验证；保留`collect-boot-image.py`，只读取系统映像，
不启动游戏、不读实时进程内存。设备支持oatdump与package compile speed/--reset，
但本轮未执行任何编译变更。最后f1显示Tailscale在线但ping/SSH实际不可达，映像采集未成功。
不要继续盲建实例，也不要将单图回归通过称作新版实机验证。

下面是此前历史记录，其中“手牌恒为空”、测试数和环境兼容结论已有过期内容；
当前 StateParser 已解析费用与单位攻血，仍缺卡牌身份和词条。

## 0.0 历史状态（2026-11-04 深夜）

**已完成**：一局战斗可以自主打完（mulligan → 出牌 → 攻击 → 格挡 → 结算 → 战后流程），
单场能赢；但整次冒险仍会失败（生命值耗尽）。当前主线是**跑通一整个关卡**。

**今天的提交**（都在 main，已同步到 f1）：

| commit | 内容 |
|---|---|
| `ef6c8fe` | 「召喚此牌時」型 buff 要**后出**（群蛛之主/發狂疾行蛛），旧排序是反的 |
| `7825528` | 伊莉絲评分 +2 → **+10**（她是牌组核心，旧评分排到第四，实战整局不打） |
| `5e4f55b` | `enemy_board` 覆盖攻击行（否则格挡阶段看不到正在攻击的单位） |
| `3607866` | 攻击行方块尺寸 68×59 + 距离抑制改欧氏距离（否则漏掉正下方单位） |
| `22004d4` | 攻击改成**全员压上**，不再让 `best_attack` 只挑一两个 |
| `cdb7829` | `TARGETING` 改成**点单位完成选择**（cancel 在这个状态下点空白无效，会死循环） |

**明天第一件事（等用户确认后做）**：提高 BlueStacks `Pie64` 的资源分配。

```
C:\ProgramData\BlueStacks_nxt\bluestacks.conf   （备份：bluestacks.conf.bak-lorwright）
  bst.instance.Pie64.cpus="2"    → "4"
  bst.instance.Pie64.ram="2048"  → "4096"
```

宿主机是 Ryzen 5 7640HS / 6C12T / 19.8 GB，给 4C4G 不影响宿主。改完要**重启实例**。
`fb_width/fb_height` 是 1280×720（真实渲染），逻辑分辨率靠 `adb shell wm size 1920x1080`
抬上去——画面因此偏糊。**先只加 CPU/内存**，确认不卡再考虑抬渲染分辨率。

**明天第二件事**：把星力接进策略。`research/lor-client-07.10.013-v1/` 里有伊莉絲
1★/2★/3★/6★ 的繁中原文（用户是 6 星，四条全生效）：

| 星 | 效果 |
|---|---|
| 1★ 蜘蛛女王 | **我方攻擊時**，賦予**各處**的友軍 +1\|+0 |
| 2★ 蛛網纏身 | **起始魔力 +1**；回合結束：若本回合有友軍陣亡，召喚 1 個小蜘蛛 |
| 3★ 蜘蛛女王II | 我方攻擊時，賦予各處友軍 +1\|+0 **及英雄的增益特性** |
| 6★ 不息夢魘 | 牌局開始植入 3 張；蜘蛛陣亡時在敵方牌組植入複製牌；**打出蜘蛛時恐懼 1** |

**这四条推翻了现在的评分模型**：1★+3★ 意味着「攻击 = 永久全体 buff」，
攻击的价值远不止脸伤；2★ 的「阵亡召唤小蜘蛛」意味着**送死不亏**，
所以「1/1 打 5/5 不打」这类旧规则更站不住。6★ 说明每张蜘蛛牌本身就在削弱对面。

**还欠用户一件事**：用户口述伊莉絲的操作规范（2026-11-04 说「等下口述」但被打断）。
**在他口述之前不要凭自己推断去改策略层。**

**素材现状**：`research/lor-client-07.10.013-v1/` 是另一个 agent 的逆向交付包
（9 张卡面 PNG、18 个关键词图标、34 种关键词 AI 倍率、原生规则组件），
`python research/lor-client-07.10.013-v1/verify.py` 可离线校验。
完整 `PatchableFiles`（3.5 GB）在 `lorwright-artifacts/game/downloaded/`。

**注意**：录屏脚本 `C:\Users\Administrator\loop.ps1`（f1）会连续截图到
`lor-capture`；停它用 `stoponly.ps1`（**只停进程**）。别用 `reset.ps1`——
那个会 `Remove-Item -Force` 把已录的帧全删掉（2026-11-04 删过一次 167 张）。

---

## 0. 30 秒速览

**这是什么**：用视觉自动化打《符文大地传说》英雄之路（PoC）周本的工具。
纯截图 → 决策 → adb 输入，不碰游戏内存、不接游戏 API（PoC 没有 API）。

**目标牌组**：伊莉絲（Elise）蜘蛛快攻，18 张（9 种 × 2）。牌表已核实。

**现在卡在哪**：单位攻血已接入；仍缺敌方攻击行真实帧、生命遮挡样本、
出牌两帧端到端和奖励面板识别。

**核心设计一句话**：能穷举的穷举（战斗），穷举不了的按分数排（出牌），
状态不明就 `NO_OP`；任何一层都不允许「自由文本 → 直接点屏幕」。

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
| **攻击 / 格挡手势** | ✅ 真机验证：拖单位到分隔线上方声明攻击；拖到敌方单位上声明格挡（见 §4.8） |
| **场上单位定位** | ✅ `perceive/units.py` 攻击力徽章 + 挖空数字的掩膜；我方 3/3、敌方 5/5，跨区互匹 0 误报 |
| **攻击令牌检测** | ✅ `perceive/attack_token.py` 橙色箭头连通域，有令牌 8446px vs 无 30px |
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
| 单位攻击力 / 生命值读数 | 位置有了但数值还是 -1，战斗求解器走「全体压上」简化分支（原因见 §4.10） | #10 |
| 先遣（Scout）词条识别 | 卡面词条图标没做，认不出带先遣的单位 | #10 |
| 卡牌身份识别 | 手牌只有费用没有身份，同费牌分不出（9 种牌只知道 9 个费用） | #3 |
| 挑战者 / 击晕图标 | 求解器拿到的 `challenger`/`stunned` 永远是 False | #10 |
| 前置自检（网络 / 登录假死 / App 冻死） | 卡住一次要人工诊断半小时 | #12 |
| JEV / LLM 兜底未接 | L2 / L3 层空转 | #8 |

---

## 2. 你要做的第一件事

**不要先碰 JEV、不要先碰 LLM、不要先做插件化。** 顺序（2026-11-04 按 issue 重排）：

```
#9 出牌手势（✅）→ #11 攻击/格挡（✅）→ #10 单位数值/词条 → 英雄规则 → #5 端到端
```

理由：英雄规则是纯逻辑、离线可测，但它产出的 `PlayCard(index)` 现在**还没在真机验证成功**。
先写规则，任何「策略对不对」的结论都会退化成「手势有没有生效」。

### 第 1 步：接口（动作集合）

`models.ActionType` 就够用，但要明确**每个动作由哪个原语执行**，且原语必须真机验证过。

| 动作 | 执行原语 | 真机状态 |
|---|---|---|
| `PLAY_CARD` | tap 手牌展开 → 下一帧徽章中心拖到我方行 | ✅ 展开态真机成功（#9 待端到端） |
| `END_TURN` / `PASS` | 点 `layout.end_turn` | ✅ |
| `ATTACK` | 单位拖到攻击行（分隔线上方）+ 下一帧点「確認」 | ✅ 真机验证 |
| `BLOCK` | 单位拖到敌方攻击单位上 + 下一帧点「確認」 | ✅ 真机验证 |
| `CONFIRM` | 点 `layout.end_turn`（同一个按钮） | ✅ |
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

返回 `None`（弃权）会让路由继续遍历后续通用策略。

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

#### 当时还剩什么（2026-11-04 历史记录）

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

### 4.8 攻击 / 格挡手势（2026-11-04 真机打通）

**攻击**：把单位拖到**分隔线上方**（落点约 `(960,500)`）→ 单位吸附到攻击行
（y≈710）→ 按钮从「略過」变「**確認**」→ 点确认发动。

- 拖到**敌方水晶**（原来的 `enemy_nexus` 落点）**无效**，会弹回原位。
- 声明后敌方水晶上方出现红色 `-N` 伤害预览，可以据此判断有没有生效。
- **没有攻击令牌时同样的拖拽也会弹回**——这是「现在能不能攻击」的唯一可靠信号，
  不要靠「有单位就试」。令牌的视觉特征是动作按钮左侧的橙色箭头（§4.9）。

**格挡**：对手攻击时按钮变「略過格擋」，把单位拖到**敌方攻击单位上**→ 单位吸附到
它正下方 → 水晶旁的伤害预览数字实时下降（实测 32→27）→ 点「確認」结算。

**拖拽和确认必须分两帧**：拖完单位按钮才变「確認」，同一帧里既算不出新按钮位置，
也没法确认拖拽有没有生效。策略层用**单位 y 坐标**判断「已声明」：平躺约 930，
声明后约 710，阈值 800（见 `policy.ATTACK_ROW_MAX_Y`）。不用按钮文字，是因为
「確認」目前没有模板，状态机会退化成颜色判断。

**两个没解开的**：

- 有的单位**拒绝格挡**（实测场上 5|5 拖到 5|3 上无反应，同回合 7|7 拖到 5|6 正常）。
  可能是击晕或「无法格挡」词条，需要卡面状态图标才能分辨。
- **先遣（Scout）词条**认不出来。卡面右下角的词条图标还没采模板。

**其他交互**（用户告知，未验证）：闇影島泰爾石这类「三选一」牌，点**左侧空白区域**
可以回退。

### 4.10 攻击力数字有白、绿两色

单位攻击力徽章里的数字**被 buff 过就变绿**（和 0 费卡的绿字同一个机制），
所以读数要同时认白字和绿字：

- 切字形用「白或绿」掩膜，别用 Otsu —— 徽章的金色边框会被 Otsu 一起切出来。
  判据沿用 `hand.py`：白 = `min(R,G,B) ≥ 170`，绿 = `G ≥ 180 且 R,B ≤ 120`。
- 现有的白色字形模板对绿色数字不够好：实测 1/5 能读，**7 读不出、8 会读成 3**。
  要读数值得单独采绿色字形（`tools/build_digits.py` 加一批）。
- 数字高 26–27px，比手牌费用（约 20px）大一号，归一化到 `GLYPH_SIZE` 后能对上。

### 4.9 攻击令牌 = 按钮左侧的橙色箭头

动作按钮左边会出现一个带火焰的橙色箭头。实测最大橙色连通域面积：

| 状态 | 面积 |
|---|---|
| 我方有攻击令牌 | 8446 px |
| 攻击已声明、等确认 | 3603 px |
| 我方回合无令牌 | 30 px |
| 对手施法中 | 5 px |

阈值取 1000（`attack_token.ATTACK_TOKEN_MIN_BLOB`）。注意**对手攻击时按钮旁也会
有箭头**，所以只在 `MY_TURN_IDLE` 下用它区分「能攻击」和「只能出牌」。

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
| `docs/decision-l1-rules.md` | 历史规则设计与加英雄检查清单；当前实现以代码和 ADR-0004 为准 |

**按需深入**：

| 文档 | 什么时候看 |
|---|---|
| `docs/champions/elise.md` | 改伊莉絲的规则/评分时。含牌表、星力、v1 八条规则的体检结论 |
| `docs/decision-l2-jev.md` | 已废弃的 JEV 历史设计，见 ADR-0004 |
| `docs/reference-prior-art.md` | 想知道 MAA/ALAS 哪些能学、哪些学不了时 |
| `docs/adr/` | 想推翻某个决策时，先看当时的理由 |

---

## 8. 不要做

- ❌ **不要接 JEV / LLM。** 当前决策采用 ADR-0004 的纯脚本路线。
- ❌ **不要先做插件化。** `champions/` 已经是插件形态了，够了。
- ❌ **不要为了「覆盖率」调规则。** 覆盖率用于发现异常，不是 KPI。
- ❌ **不要用启发式替换穷举。** 战斗空间小到 6v6 只要 24ms，穷举更准。
- ❌ **不要在 `decide/` 里 import `champions/`。** 核心层不认识任何英雄。

---

## 9. 历史 issue 列表（截至 2026-11-04）

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
