# Pipeline：用配置描述任务，而不是写代码

> 来源：MaaXYZ/MaaFramework（**LGPL-3.0**）。协议 `docs/en_us/3.1-PipelineProtocol.md`；资源目录与开发档位
> `docs/en_us/1.1-QuickStarted.md`；`{name}` 归属哪层 `docs/en_us/3.3-ProjectInterfaceV2.md`。实现：
> `Resource/PipelineTypes.h`（`PipelineData` 字段与默认值）、`Task/PipelineTask.cpp`（状态机）、
> `Resource/PipelineResMgr.cpp`（加载）。只提炼机制，不复制代码。

## 它解决什么问题

手游自动化里绝大多数步骤是「屏幕上出现 A → 点 A → 等下一屏」。这类流程没有决策，只有识别 + 点击 + 顺序。
写代码是重复劳动；写成数据则可复用、可视编辑、换分辨率只重采模板。MaaFramework 把一个「识别 → 动作 →
后继」三元组叫**节点**，整条流程就是节点图，用 JSON 写。QuickStarted 分三档：纯 JSON 低代码 /
JSON + Custom 扩展（推荐）/ 全代码。

## 机制

### 1. 节点结构

pipeline 是 `{节点名: 节点定义}` 的平表（不是嵌套树）；根键以 `$` 开头被跳过，`.` 开头的文件/目录不读
（`PipelineResMgr::load_all_json`）。字段与默认值来自 `PipelineTypes.h` 的 `struct PipelineData`：

| 字段 | 默认 | 语义 |
|---|---|---|
| `recognition` | `DirectHit` | 识别算法；`DirectHit` = 不识别，直接执行动作 |
| `action` | `DoNothing` | 动作类型 |
| `next` / `on_error` | 空 | 后继候选表 / 失败后继候选表（string、NodeAttr 或混排数组） |
| `rate_limit` | 1000ms | 每轮识别最小间隔，不足则 sleep 补足 |
| `timeout` | 20000ms，`-1`=无限 | **限的是「本节点 `next` 列表的扫描」**，即父节点的等待时长 |
| `pre_delay` / `post_delay` | 200 / 200ms | 识别→动作、动作→下一轮识别之间的固定延时 |
| `pre_wait_freezes` / `post_wait_freezes` | 0 | 等画面稳定（连续 N ms 无显著变化）才继续 |
| `repeat` / `repeat_delay` / `repeat_wait_freezes` | 1 / 0 / 0 | 同一动作重复 N 次，中间插延时或等稳定 |
| `max_hit` | UINT_MAX | 成功识别次数上限，超过后在别人的 `next` 里被跳过 |
| `enabled` / `inverse` | true / false | 跳过该节点 / 反转识别结果（反转命中时自带点击被禁用） |
| `anchor` | 空 | 设置锚点名（数组；v5.7 起可对象形式指定目标节点或清除） |
| `focus` / `attach` | null / {} | 回调通知模板 / 不参与执行的自定义数据（与默认值 dict merge） |
| `is_sub` / `interrupt` | — | **v5.1 废弃**，改用 `[JumpBack]`（官方有 `tools/migrate_pipeline_v5.py`） |

Pipeline **v2**（v4.4.0 起）把这两个字段收进二级字典 `{"type":…, "param":{…}}`，其余不变，v1/v2 兼容。

`timeout` 归属父节点这点常被误用，文档与源码一致：`run_next(next, pretask)` 里 `check_timeout_and_sleep`
读的是 `pretask.reco_timeout`。入口节点例外——它把自己当自己的父节点（`next = {{.name = entry_}}`）。

### 2. 分支与失败恢复

**唯一的分支机制**：`next` 里按顺序逐个试识别，第一个命中的赢，后面的不再试
（`PipelineTask::recognize_list` 就是顺序 `for`）。没有 goto、没有 while、没有变量。
`PipelineTask::run` 的四种转移：

- 命中 + 动作成功 → 进入**命中节点**的 `next`
- 命中 + 动作失败 → 进入**命中节点**的 `on_error`，置 `error_handling = true`
- `next` 全 miss 且超时 → 进入**当前节点**的 `on_error`
- 处于 `error_handling` 时 `next` 再 miss → 清空退出（日志 `error handling loop detected`，防错误链死循环）

终止：`next` 空（`jumpback_stack` 非空则先 pop 回父节点），或外部 `post_stop` / `StopTask`。
**`[JumpBack]`** 是唯一的回边，用于临时弹窗（断线提示、权限框）：带此属性的节点命中后先跑完它那条链，
再回父节点从 `next` **开头**重扫。源码即 `jumpback_stack`：命中时 push 父节点名，`next` 空且
**不在**错误路径时 pop（v5.9 修正：错误处理路径不 jump back）。两种写法等价可混排：
`"next": ["B", {"name":"C","jump_back":true}, "[JumpBack]D"]`。

**任务串怎么被驱动**：`tasker.post_task(entry, pipeline_override)` 投递入口节点名；`AsyncRunner` 内部
只有一条 `std::thread` + 一个队列，所以多个 task **串行**执行。一个 task 从入口按上述状态机走，直到 `next` 空。

### 3. 识别与动作怎么解耦

两者是**正交字段**，任意组合：同一个 `TemplateMatch` 可配 `Click`、配 `Swipe`，也可配 `DoNothing`
当纯探针。`Click.target` 默认 `true` = 用本次识别的 `box`，这就是「识别完自动点它」。

坐标语义三分，是协议里最值得抄的设计：

| 概念 | 含义 | 可取值 |
|---|---|---|
| `roi` (+`roi_offset`) | **在哪找** | `[x,y,w,h]` / 字符串=另一节点名 / `[Anchor]X`；v5.6 起支持负坐标 |
| `box` | **找到哪**（识别输出） | 框架产出，不手填 |
| `target` (+`target_offset`) | **点哪 / 拖到哪** | `true` / 节点名 / `[x,y]` / `[x,y,w,h]` |

`roi` / `target` 写节点名 = 用该节点上次的识别结果（源码 `TargetType::PreTask`）；引用不存在的
节点或锚点视为识别（动作）失败。这就是 core 层「`Node.Name` 引用」的实际形式。

`anchor` 是弱化的具名指针：节点写 `"anchor": "X"`，下游写 `[Anchor]X`，运行时解析到**最后一次设置 X
的节点**；从未设置或已清除则跳过该候选。复合识别 `And` / `Or`（v5.3）的 `all_of` / `any_of` 元素可内联，
也可直接写节点名复用识别参数（v5.7）；`sub_name` 让前面的子识别结果当后面的 `roi`。

### 4. 参数模板 / 变量

**core 没有 `{...}` 替换。** 证据：`3.1-PipelineProtocol.md` 全文无变量章节；`PipelineData` 无相关字段；
`PipelineResMgr` 只做「读 JSON → 与默认值合并 → 存 map」，不做字符串替换。

`{name}` 属于 **ProjectInterface 层**：`3.3` 的 `option.inputs[].pipeline_override` / `hotkeys` 用
`{name}`、`{name}.primary`、`{name}.modifier1` 占位，由 **Client 在生成 `pipeline_override` 时**替换
（按 `pipeline_type` 做 string/int/bool 转换），再交给 core。

core 层面真正的参数化只有三条路：`default_pipeline.json` 继承（节点内 > 算法/动作默认 > `Default` >
内置；`attach` 是 dict merge）、运行时 `MaaResourceOverridePipeline` / `override_next` / `override_image`、
以及 `roi` / `target` / `all_of` 里的节点名与 `[Anchor]` 引用。

## 对我们的意义（lorwright）

我们的循环是 `Engine.run()`：screencap → `_build_state()` → `router.decide()` → `translate()` →
tap/drag，200ms 一 tick。流程全是代码，坐标在 `config/settings.yaml` 的 `layout` 段，是 1920×1080
手工标定的绝对像素。按 pipeline 的眼光重看三块流程：

| 流程 | 合适度 | 理由 |
|---|---|---|
| PoC 地图推进 / 菜单导航 | **较高** | 形状就是「看到按钮就点，点完等下一屏」，没有决策。节点图比 `ui_state.py` 的 if-else 链清楚 |
| 起手换牌 | **部分** | 骨架（mulligan 按钮 → 选牌 → 点確定）是 pipeline 形状；「换哪几张」是策略，在 `champions/elise/policy.py` |
| 对局内出牌 / 战斗 | **低** | 动作是 `PlayCard(index)` 语义动作，坐标由 `act/translate.py` 按扇形手牌反推；`target` 没有「第 N 张牌」 |

两条有实际价值的结论：

1. **分辨率解耦是真赢。** pipeline 模板是 720p 归一化、`roi` 是相对框，换分辨率只重采模板；我们是绝对
   像素标定（`settings.yaml` 明写「换分辨率就要重标定」）。导航层若搬到「模板 + 相对 roi」，换设备不必重标。
2. **该借的是形状，不是运行时。** MaaFramework 是 C++，绑定自己的 Controller/Tasker/Agent 模型，引进来等于
   重写 `device/` 和 `loop/`。更划算的是在现有 `device` + `perceive` 之上写 ~50 行的「节点表 + 顺序试 next
   + on_error 一跳」执行器，只服务导航；出牌仍走 `decide/router`。与 AGENTS.md 分层一致：导航是机制，出牌是英雄知识。

顺带一个值得抄的小设计：`need_screencap`——`next` 里全是 `DirectHit` 时这一轮**不截图**。我们每 tick
无条件 `screencap()`，导航里纯等待的 tick 可直接省掉。

## 不适用 / 不要照搬的地方

1. **没有状态机，只有优先级表。** 分支是「next 里谁先命中」，而我们的 `UIState`（`MULLIGAN` /
   `MY_TURN_IDLE` / `ENEMY_TURN` / `COMBAT_RESOLVING`）是互斥状态。用 next 优先级模拟会得到一张隐式、
   难读的优先级表，加一个状态就得重排。
2. **没有「一次截图产出一个结构化状态」的原语。** pipeline 每轮只在 roi 里找一样东西；我们要的是「一次
   截图 → 6 张手牌 + 双方单位 + 血量」。只能塞一个 `Custom` 识别，等于把整个 `perceive/` 关进回调，反而
   更难测（违反「决策层不碰坐标、可离线单测」）。
3. **没有算术。** `expected` 支持正则，但法力够不够、斩杀线、格挡分配，一个都写不了。
4. **失败恢复只有一跳。** `on_error` 是「去跑另一条链」，没有「重试 N 次」也没有「升级处理」。
   我们的 `RecoveryPolicy` 是分级状态机（重试 → 回主菜单 → 重启客户端），映射不上去。
5. **别在 pipeline JSON 里做参数化。** core 没有 `{...}`，那是 PI 层 Client 的职责；core 只有 default 继承 + 运行时 override。
6. **`repeat` 不是循环。** 它是「同一动作重复 N 次」，不是「循环直到条件成立」。真循环只能靠
   `[JumpBack]` 或 `max_hit` 逼近。
7. **坐标系别混。** 我们是 1920×1080 实测像素，pipeline 是 720p 归一化 + 官方裁图工具，混用会静默错位。

未验证：`MaaResourceOverridePipeline` 的覆盖是「整字段替换」还是「按字段 merge」。加载路径是逐节点重新
parse（拿旧数据当默认值），但运行时入口 `ResourceMgr::override_pipeline` 的实现未读到，**不下结论**。

## 参考位置

| 位置 | 内容 |
|---|---|
| `3.1-PipelineProtocol.md` §Basic Format / §Execution Logic / §Node Flow | 节点结构、四步执行逻辑、生命周期 flowchart |
| 同上 §Property Fields / §Node Attributes | 全部字段语义、`[JumpBack]` / `[Anchor]` 两种写法 |
| 同上 §Algorithm Types / §Action Types / §Default Properties | 10 种识别 + 21 种动作、`Custom` 的注册名、`default_pipeline.json` 四级优先级 |
| `1.1-QuickStarted.md` §Development Approach / §File Structure | 三档开发方式、`pipeline/ image/ model/ocr/` 目录约定 |
| `3.3-ProjectInterfaceV2.md` §option.inputs / `pipeline_override` | `{name}` 替换、`pipeline_type` 转换 |
| `Resource/PipelineTypes.h` `struct PipelineData` | 字段与默认值的**权威**出处（含 `kNodeAttr_JumpBack`、`kNodePrefix_Ignore`） |
| `Task/PipelineTask.cpp` `run` / `run_next` / `recognize_list` | 状态机、`jumpback_stack`、`error_handling`、`pretask.reco_timeout` |
| `Resource/PipelineResMgr.cpp` | 加载/合并逻辑，证明 core 无变量替换 |
| `Tasker/Tasker.cpp` + `Base/AsyncRunner.hpp` | `post_task` 投递、单工作线程串行执行 |
