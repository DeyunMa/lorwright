# Recognition：识别是一等公民，带排序和 ROI

> 来源：`MaaXYZ/MaaFramework`（**LGPL-3.0**）`docs/en_us/3.1-PipelineProtocol.md`（`## Algorithm Types`、
> `## Result Sorting Methods`、`### roi / box / target Differences`）、
> `source/MaaFramework/Vision/{VisionTypes.h,TemplateMatcher.cpp,FeatureMatcher.cpp,ColorMatcher.cpp,OCRer.cpp,VisionUtils.hpp}`、
> `source/MaaFramework/Task/Component/Recognizer.{h,cpp}`、`include/MaaFramework/Instance/MaaTasker.h`、
> `source/MaaFramework/Controller/ControllerAgent.{h,cpp}`。只提炼机制，不复制代码。
> 注：`docs/en_us/3.2-Recognition.md` 现已不存在，识别字段并入 `3.1-PipelineProtocol.md`。

## 它解决什么问题

把「找图」从一次性函数变成**可声明、可组合、可排序取第 N 个**的对象。要回答三件事：
同一模板命中多处时取哪个；模板因配色/透视/尺度变化失效时换什么；上层怎么知道「为什么没命中」。
三者最后收束成一条统一契约：`hit = box.has_value()`——所有算法共用 `box | None`，节点流只判有无。

## 机制

### 1. 算法族（11 种，`recognition` 字段）

| 类型 | 做什么 | 判据/关键参数 | 适用 |
|---|---|---|---|
| `DirectHit` | 不识别，直接执行 | —（默认值） | 无条件动作 |
| `TemplateMatch` | `cv::matchTemplate` 像素级找图 | `threshold` 0.7 | 默认首选，UI 元素 |
| `FeatureMatch` | SIFT/KAZE/AKAZE/BRISK/ORB + KNN `ratio` + RANSAC 单应 | `count` 4（最少内点数） | 抗透视/尺度，模板 ≥64px 且有纹理 |
| `ColorMatch` | `inRange` 数像素 | `count` 1、`connected` 连通域 | 血条、纯色块 |
| `OCR` | PaddleOCR onnx（det+rec） | `threshold` 0.3、`expected` 正则 | 任意文本，慢 |
| `NeuralNetworkClassify` | 固定 roi 分类 | `model`(ONNX) `expected` | 位置固定、只需「是不是」 |
| `NeuralNetworkDetect` | YOLOv8/v11 检测 | `threshold` 0.3 | 任意位置找物体，训练成本高 |
| `And` / `Or` | 复合（v5.3） | `all_of`/`any_of` + `box_index` | 粗到细两级校验 |
| `Custom` | 回调注册（v5.11 支持多结果） | `custom_recognition` | 跳出声明式配置 |

### 2. `TemplateMatch` 参数

- `roi` / `roi_offset`：见 §3。
- `template`：`string | list<string>`，相对 `image/`。**支持目录**（递归加载其中所有图片）= 多模板。
- `threshold`：`double | list<double>`，默认 `0.7`，与 `template` 等长；不足时回落到最后一个。
- `method`：等价 `cv::TemplateMatchModes`，默认 `5`（`TM_CCOEFF_NORMED`，文档推荐）；`10001` = 反向
  `TM_SQDIFF_NORMED`（分数越高越好，v5.3）。实现里由 `low_score_better_` 决定比较方向。
- `green_mask`：`true` 时把不想参与匹配的像素涂成 RGB(0,255,0)。文档自己说「算法鲁棒性已够，通常不需要」。
- `order_by`：`Horizontal`(默认) | `Vertical` | `Score` | `Random`。配合 `index` 取第几个。
- `count` **不属于 TemplateMatch**：它是 `FeatureMatch`/`ColorMatch` 的判据（内点数 / 像素数）。

读代码才看得到的四点（文档没写）：

1. 每个模板 × 每个 roi 各跑一遍，结果**合并进同一个候选池**再统一排序。所以多模板不是「取最高分」——
   只有 `order_by: Score` 时 `index: 0` 才是最高分；默认 `Horizontal` 下 `index: 0` 是**最靠左的那个**，
   可能来自任意一个模板。多模板 + 默认排序是个陷阱。
2. 分数低于 `0.5` 的候选不进候选池；但若一个都没有，**塞入 `closest_result`**（分数可能很低）。
   于是 `all_results` 永远非空（方便看「最像哪里」），`filtered_results` 才是过线集合，`best` 只从 filtered 取。
3. NMS 判据是 `(a & b).area() >= 0.2 * b.area()`，即**重叠面积 / 后一个（低分）框自身面积**，不是 IoU。
   大框套小框时比 IoU 更容易抑制。
4. `index` 越界 → `pythonic_index` 返回 `nullopt` → `best_result_` 空 → `hit=false`。不报错，也不回退到最后一个。

`order_by` 解决的实际问题：模板在画面里命中 N 次（同一张卡出现在手牌、弃牌堆、牌库提示），
业务要的是「第 3 张」。没有 `order_by`+`index` 就得每次自己写排序和越界判断；
有了它，「第几个」变成声明式参数，且 `Horizontal` 与视觉上的「从左到右」一致，能直接对应手牌序号。

### 3. `roi` 坐标系约定

- `roi = [x, y, w, h]`，相对**框架交给算法的那张截图**，不是设备像素。`ControllerAgent` 默认把截图缩放到
  短边 720（`image_target_short_side_ = 720`），动作坐标再按 `scale_width/scale_height` 换回设备像素。
  → 资源只需按 720p 采集一次，多分辨率自适应发生在**边界**，不在每个节点。
- 负数语义（v5.6）：负 `x/y` 从右/下边缘算；`w/h == 0` 延伸到边缘；`w/h < 0` 取绝对值并把 `(x,y)` 当右下角。
  越界不报错，而是裁剪进画面（`correct_roi`），裁到空才算无效。
- `roi` 可以是**字符串**：另一个节点的名字（PreTask），或 `[Anchor]Name`。此时用上一节点的 box 作为本次
  识别范围；上一节点有多个 `filtered` box 时逐个当 roi 再合并结果。这是「粗到细」两级识别，用来消灭硬编码坐标。
- `roi_offset`：四个分量**分别加到 x/y/w/h 上**（不是只平移）——负 w/h 能收缩区域。配合 PreTask 引用时
  最有用：借上一节点的框再往外扩 10px。
- `roi`（在哪找）/ `box`（识别结果）/ `target`（点哪，默认 = box）三者分工，`target_offset` 单独一层。

### 4. 结果结构

- API：`MaaTaskerGetRecognitionDetail(reco_id) → node_name, algorithm, hit, box, detail_json, raw, draws`。
- 内部 `RecoResult`：`reco_id / name / algorithm / box(optional) / detail(json) / draws`。
- `detail = {all: [...], filtered: [...], best: ...}`，元素随算法不同：
  `TemplateMatch`/`FeatureMatch`/`ColorMatch` = `{box, score|count}`；`OCR` = `{text, box, score}`；
  `NN*` = `{cls_index, label, box, score}`；`And`/`Or` = 子结果数组。
- `draws`：debug 模式下每个 roi/模板都画框存盘，误判可回放（`save_draw`）。

### 5. 阈值与误判

- 统一语义：`filtered` 为空 = 没找到 = `hit=false` = 节点失败走 `on_error`。不抛异常、不返回垃圾。
- 多模板不投票也不取 max，靠 `order_by`+`index` 显式表达意图。
- 默认阈值：TemplateMatch 0.7、OCR 0.3、Detect 0.3、FeatureMatch `count` 4。
- 防误命中的细节：`index` 越界即失败；PreTask 没有 best box 时下游 roi 视为**无 roi 直接失败**
  （源码注释明确写了否则下游会「拿着这些框继续识别并命中」）。

## 对我们的意义（lorwright）

1. **`order_by` 能不能解决「手牌第几张」——部分能，但不是靠 `order_by` 本身。** `perceive/hand.py`
   已经 `sorted(key=center.x)` 把 Horizontal 语义写死了。真正缺的是 MAA 那条链：
   匹配得 N 个 box → 排序 → 用 `index` 取第 N 个 → **把那个 box 当下一级的 roi**。我们把序号塞进了
   `CardInHand.index`，但没有 `index` 参数，也没复用 box。可借鉴的最小改动：给 `locate.py` 加
   `find_nth(order_by, index)`，`index` 越界返回 `None`（不是取最后一个）。
2. **多模板/多尺度能不能解决分辨率变化——不能。** MAA 的多模板是「同一物体的多种外观」，`matchTemplate`
   本身不尺度不变；分辨率变化 MAA 靠**边界统一缩放到短边 720** 解决。我们该学的是后者：ADB 截图先
   resize 到固定 720p 再识别，`layout` 只写一套。现状是 `config/settings.yaml` 写死 1920×1080，而
   AGENTS.md 说手机 2510×1156、Pie64 1280×720 —— 每换设备重标定，正是没做归一化的代价。
   （多模板对我们仍有用：`assets/digits/6.png` 与 `6-mulligan720.png` 已经是这个用法。）
3. **`roi` 约定该学三条**：roi 一律相对归一化后的截图；roi 允许指向「上一个节点的 box」（`perceive/state.py`
   可以把定位结果吐出来供下一步当 roi）；`roi_offset` 单独存，别把偏移混进 `layout`。
4. **NMS 口径可以换。** 我们用 IoU<0.3 保留；MAA 用「重叠 ≥ 0.2 × 较小框面积」抑制。徽章等大时两者等价，
   手牌收起/展开混在一屏时 MAA 的口径更稳（大框不会吞掉小框里的独立徽章）——**未验证**，需实测。
5. **`digits.py` 的旋转搜索不必改。** 它近似 FeatureMatch 的旋转不变性，但成本是 `19 角度 × 模板数` 次
   16×24 相关，仍比 SIFT 便宜。MAA 的答案是「模板自带不变性」或「不做旋转」，对我们不划算。
6. **可以直接借的：`detail = {all, filtered, best}` 三段式。** 现在 `find_all` 只返回 kept，调阈值时看不到
   「最像但没过线」的位置——`hand.py` 里「实测误报上限 0.956」这类结论全靠人工盯。加 `best`/margin 落日志后，
   阈值能由数据定，而不是靠试。

## 不适用 / 不要照搬的地方

- **不引入声明式 pipeline/JSON 配置。** 我们的动作语义（拖拽出牌）和状态机是自己的，抄参数名就够，
  抄声明式配置会把状态判定藏进数据文件，破坏 `perceive → decide → act` 的可测试性。
- **`green_mask` 不是我们环形掩膜的替代品。** MAA 是「涂绿 = 不参与」，我们要的是「只保留环」= 反向掩膜；
  直接给 `matchTemplate` 传 mask 更直白，多一步涂绿只会多一份素材维护成本。
- **负数 roi 坐标（v5.6）收益有限。** 我们的 `layout` 都是手工量的正数；引入前先确认没有第二处坐标来源。
- **0.5 预过滤 + 保底 `closest_result` 别照抄。** 它让 `all_results` 混入垃圾候选；日志里若不标分数，
  会误以为「识别到了」。
- **`NeuralNetwork*` 对当前牌组是过度设计。** 18 张牌、固定字体，模板够用；只有卡面识别
  （`perceive/cards.py` 的 TODO）可能真需要 Detect，因为卡面有 3D 倾斜和光效——**未验证**。
- **`And`/`Or` 复合识别暂时不需要。** UI 状态机已经是显式的（`perceive/ui_state.py`），复合识别会把
  「这是不是结算界面」这类判断藏进配置，与「UNKNOWN 绝不点击」的兜底原则冲突。
- **LGPL-3.0**：只借鉴机制与字段名，不复制代码；若将来要链接其库，注意动态链接与开源义务。

## 参考位置

- 字段定义与语义：`docs/en_us/3.1-PipelineProtocol.md` → `## Algorithm Types`、`## Result Sorting Methods`、
  `### roi / box / target Differences`、`### Version Changes`（v5.1 `Expected` 排序 / v5.3 `And`·`Or`·`10001` /
  v5.6 负坐标 / v5.11 `Custom` 多结果）。
- 参数结构体：`source/MaaFramework/Vision/VisionTypes.h`（`TemplateMatcherParam` 等，默认值都在这里）。
- 排序/索引/NMS/roi 归一：`source/MaaFramework/Vision/VisionUtils.hpp`
  （`sort_by_*`、`pythonic_index`、`NMS`、`normalize_rect`、`correct_roi`）。
- 各算法实现：`source/MaaFramework/Vision/{TemplateMatcher,FeatureMatcher,ColorMatcher,OCRer}.cpp`。
- 结果装配与 PreTask roi 解析：`source/MaaFramework/Task/Component/Recognizer.cpp`
  （`build_result`、`gen_detail`、`get_rois`、`get_rois_from_pretask`）。
- 截图归一化与坐标反算：`source/MaaFramework/Controller/ControllerAgent.cpp`（`init_scale_info`、
  `image_target_short_side_`、`scale_width/scale_height`）。
- 查询接口：`include/MaaFramework/Instance/MaaTasker.h`（`MaaTaskerGetRecognitionDetail`）。
