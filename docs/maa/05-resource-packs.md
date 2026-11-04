# Resource pack：模板与流程是数据，不是代码

> 来源：MaaXYZ/MaaFramework（`docs/en_us/1.1-QuickStarted.md`、`3.1-PipelineProtocol.md`、`3.3-ProjectInterfaceV2.md`、
> `2.2-IntegratedInterfaceOverview.md`、`sample/resource/`、`source/MaaFramework/Resource/PipelineResMgr.cpp`），
> 许可证 **LGPL-3.0**（`LICENSE.md`）；MaaAssistantArknights（`resource/`、`docs/zh-cn/develop/overseas-client-adaptation.md`、
> `src/MaaCore/Config/TaskData.cpp`、`src/MaaWpfGui/Main/AsstProxy.cs`），许可证 **AGPL-3.0**。只提炼机制，不复制代码。

## 它解决什么问题

游戏 UI 是外部契约：会改版、会分服、会换分辨率。MAA 系列的做法是把「认哪块、用哪张图、阈值多少、命中后去哪」
全部从代码里搬进数据，于是**改 UI 只改数据**，代码不动。由此得到三个能力：一份逻辑服务多个客户端 /
分辨率 / 语言（靠**叠加覆盖**而不是 fork 副本）；资源可独立于程序更新（MAA 的资源更新链路「只增不删、只覆盖」）；
判断一条知识该进资源还是进代码有了明确判据（见 §4）。

## 机制

### 1. 目录结构（Bundle）

```tree
my_resource/
├── pipeline/            # 节点图，递归读取目录下所有 .json
├── image/               # 模板图，template 字段按相对路径引用（支持子目录、整目录递归）
├── model/ocr/           # ONNX：det.onnx + rec.onnx + keys.txt（另有 classify/ detect/）
└── default_pipeline.json  # 与 pipeline/ 同级，默认参数
```

| 位置 | 职责 | 关键约定 |
|---|---|---|
| `pipeline/` | 节点（Node）与节点链 | 一个 JSON = 若干节点；同目录多文件合并 |
| `image/` | 模板图 / 特征图 | 路径**相对 `image/`**，不带前缀 |
| `model/` | OCR / 分类 / 检测模型 | 按算法分子目录，文件名固定 |
| `default_pipeline.json` | 默认参数 | 优先级：节点显式 > 算法/动作类型默认 > `Default` > 框架内置 |

**Bundle** = 一个上述结构；**Resource** = 按顺序加载的多个 Bundle。

### 2. 多客户端：叠加而不是复制

**加载顺序决定覆盖关系**（MAA `AsstProxy.LoadResource`，代码实测）：

```
resource/                       # 国服基线
cache/resource/                 # OTA 下来的资源（后加载 → 覆盖基线）
global/<client>/resource/       # 非官服/B服才加：YoStarEN / JP / KR / txwy
cache/global/<client>/resource/
platform_diff/PC/resource/      # 仅 PC 窗口连接模式
```

**覆盖粒度因对象而异**（这是整套机制的关键）：

| 对象 | 粒度 | 依据 |
|---|---|---|
| `image/` 同相对路径 | 后者整文件胜；目录按相对路径合并 | MaaFW 文档明确 |
| `default_pipeline.json` | dict merge，同名字段后者胜 | MaaFW 文档明确 |
| pipeline 节点 | 同名节点**整节点替换**（`insert_or_assign`） | `PipelineResMgr.cpp` |
| MAA 任务字段 | 同名任务**逐字段覆盖**，未写的字段继承 | `TaskData.cpp::lazy_parse` |

MAA 的逐字段覆盖让「外服包」可以小到极致：`task.json` 里只写 `text`（换成外服文字）、必要时写 `roi`
（文字长度差太多才改）、换图就丢一张同名 png。其余全部回落到国服。这就是「叠加」的全部含义。

配套的继承原语：`baseTask: "ClickChapter"` 从另一任务继承、只写差异字段（`ClickChapter1` 只写 `text`）；
`baseTask: "#none"` 显式**断开**继承；`A@B` 前缀派生（复用 B 的 `next`/`sub` 并整体加前缀，一个模板跑遍多上下文）；
`#self` / `#next` / `#back` 是不占节点名的流程符号。

多语言分两层，别混：**识别文本**（`text` 字段）在资源里，跟着客户端/语言包走；**UI 文案**在
`interface.json` 的 `languages` + `$key`，与识别资源无关。

分辨率靠**归一化**而不是复制模板：模板统一裁自「缩放到 720p 的无损原图」，控制器用 `display_short_side` /
`display_long_side` / `display_raw` 把截图缩到同一坐标空间，识别坐标再换算回原始帧。

### 3. 版本升级（UI 改版）时的最小改动

代价从低到高，优先选前面的：

1. **加模板候选**：`template` 支持数组，`threshold` 支持等长数组一一对应。MAA 的
   `SwitchTheme@ToggleSettingsMenu` 同时挂 `xxx.png` 和 `xxx-v2.png` —— 新旧 UI 各命中一张，不写版本分支。
2. **调 `threshold`**：MaaFW 默认 0.7、method=5（TM_CCOEFF_NORMED，对光照/色差不敏感）；但降阈值换召回会带来假阳性，不是通用解法。
3. **改 `roi`**：只在识别内容尺寸明显变化时才需要（外服适配文档明确「通常不需要改」）。
4. **整节点替换**：放进一个后加载的 bundle，同名节点覆盖。

**版本标记只做包级，不做逐模板级**（重要事实修正）：MAA 没给单张 png 打版本号。它有的是
`resource/version.json`（活动/卡池时间 + `last_updated`，判断资源是否过期）、PI 的 `version` 与
`resource.hash`（`MaaResourceGetHash` 校验，不匹配只警告不阻断）、CI 生成的 `filelist.txt` 完整性清单。逐模板打版本的成本远高于收益，他们没做。

**兼容层三件套**：`resource/tasks/hotfix/ocr_replace.json` 只放数据体（OCR 纠错表），由主任务转发引用，
改错字不必动 `tasks.json`；cache 资源层后加载覆盖，热修模板图不要求用户换客户端；
`MaaResourceOverridePipeline` / `OverrideImage` / `OverrideNext` 运行时改单节点或单图，不落盘。

### 4. 资源与代码的边界

| 进资源 | 必须写代码 |
|---|---|
| 模板图、`roi`、`threshold` | 图像算法本身（匹配/OCR/特征） |
| 识别文本、节点顺序、默认参数 | 状态机、战斗求解、评分 |
| 模型文件 | 动作语义（拖拽手势、点击序列） |
| 客户端/分辨率/语言差异 | 异常恢复、看门狗、跨节点计算 |

判据一句话：**这条知识换一个客户端 / 分辨率 / 语言还成立吗？** 成立 → 代码；不成立 → 资源。MaaFW 还留了
第三条路：`Custom Recognition` / `Custom Action` 走 Agent 子进程，把「必须写代码但只属于某个项目」的部分隔离出核心。

## 对我们的意义（lorwright）

现状对照：模板在 `assets/buttons/*.png`（`UIStateDetector` 按 `png.stem` 建 dict，缺图静默跳过）、字形在
`assets/digits/*.png`（多原型取最高分，`stem.split("-")[0]` 是数字，`-hand1080` / `-hp720` 是临时分辨率标记）、
徽章路径硬编码 `assets/ui/badge.png`、坐标在 `config/settings.yaml` 的 `layout`（按 Pie64 1920×1080 实测）、
阈值是全局 `match_threshold: 0.85`、游戏版本 `live_7-10-13`。

**结论：值得引入「资源包 + 覆盖」，但要最小版本——只做两层和包级版本，不做 JSON DSL。**

1. **两层目录 + 覆盖**：`assets/base/`（与版本无关：徽章、几何结构）+ `assets/<game_version>/`
   （版本敏感：按钮文字、字形、layout），加载时 base 打底、版本层覆盖同名文件。升级时只新增一个目录
   + 改 `config` 一行 `game_version`，代码不动。我们的加载器已是「按 stem 建 dict / 按前缀取数字」，
   加一层覆盖只是换个遍历顺序，改动极小。
2. **包级版本标记，不是逐模板**：`assets/<ver>/pack.json` 写
   `{"game_version": "live_7-10-13", "resolution": [1920,1080], "captured_at": "..."}`，
   启动时和 `config` 比对，不一致打 WARN（不 fail）。`docs/reference-prior-art.md` §4 说「MAA 的模板图带版本号」
   ——不准确，MAA 只在包级做版本；我们照包级做，成本一天，收益是「模板过期」从静默失败变成一行日志。
3. **模板多候选优先于版本分支**：`mulligan`、`victory` 这类「按钮文字会变」的改成
   `mulligan: [mulligan.png, mulligan-v2.png]`，命中任一即算。比按版本切目录便宜，也是 MaaFW `template: [...]` 的原样做法。
   `digits` 已是「多原型取最高分」，机制上已支持，只差把 `-hand1080` 的语义从文件名移进 pack.json。
4. **分辨率归一化，这是真正的坑**：我们踩的「换分辨率要全部重标定」不是模板问题，是**坐标**问题。
   MaaFW 的解法是截图先缩到固定短边再识别、坐标在 `ControllerAgent` 换算回原始帧。对应到我们：
   `perceive` 入口把帧 resize 到固定短边（1080），`layout` 只维护这一套，原始分辨率只用于手势换算。
   ⚠️ 未验证：手牌费用数字在 720p 下只有 ~10px（当初抬到 1080 的原因），归一化目标必须选
   「最小可读」那一档，或允许 `digits` 单独吃原始帧。这条要实测再定。
5. **不建议照搬**：完整 pipeline JSON DSL 和那套资源加载框架。MAA 的节点图价值在于
   「让非程序员零代码改流程」，我们没这个需求，把 JEV/combat 求解拆进 JSON 只会让逻辑散成两处。

## 不适用 / 不要照搬的地方

- **JSON DSL / 惰性求值语义**：决策层是 Python（规则 → JEV → 路由），JSON 化会破坏可测试性与类型检查；
  「已加载节点不受后续 default 影响」是为了增量热加载，我们一次进程内加载全部资源，不需要这层复杂度。
- **靠降阈值兼容改版**：`UNKNOWN` 时绝不点击是硬约束，假阳性的代价高于漏识别。先加模板候选。
- **四层客户端叠加**：MAA 是「客户端 × 缓存 × 平台」的组合拳；我们只有手机版 LoR 一个客户端，两层
  （base + 版本）就够，多出来的层只会让「到底加载了哪张图」难以回答。
- **未验证**：MaaFramework 的 LGPL-3.0 具体义务（若将来搬运其 schema 或资源需先确认）；`display_short_side`
  归一化对亚像素小字形的影响（见上文第 4 条）。

## 参考位置

| 内容 | 位置 |
|---|---|
| Bundle 目录结构与职责 | MaaFramework `docs/en_us/1.1-QuickStarted.md` §File Structure Specification |
| 覆盖规则 / 默认参数 / 720p 归一化 | `docs/en_us/3.1-PipelineProtocol.md` §Default Properties、§Multiple Bundle Loading Behavior、§TemplateMatch |
| 资源分层 / `resource.hash` / 控制器分辨率选项 | `docs/en_us/3.3-ProjectInterfaceV2.md` §resource、§controller（`display_short_side` 等） |
| 运行时覆盖 API | `docs/en_us/2.2-IntegratedInterfaceOverview.md` §MaaResourceOverridePipeline / OverrideImage |
| 示例资源包 | MaaFramework `sample/resource/`（`default_pipeline.json` + `pipeline/` + `image/`） |
| 多客户端叠加流程 / 加载顺序 | MAA `docs/zh-cn/develop/overseas-client-adaptation.md`；`src/MaaWpfGui/Main/AsstProxy.cs` → `LoadResource()` |
| 字段级覆盖 / `baseTask` / 节点级覆盖 | MAA `src/MaaCore/Config/TaskData.cpp`（`lazy_parse`）；MaaFW `source/MaaFramework/Resource/PipelineResMgr.cpp`（`insert_or_assign`） |
| 目录清单 | MAA `resource/`（`tasks/` `template/` `global/<client>/` `platform_diff/` `version.json`） |
| 数据热修层 | MAA `resource/tasks/hotfix/ocr_replace.json` |
