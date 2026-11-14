# Mirage 对 lorwright 的适用性评估

日期：2026-11-09。范围：当前代码与官方公开资料核对；未安装或运行模型，未修改识别链路。

## 当前实现

- `pyproject.toml` 的主视觉依赖为 `opencv-python`、`numpy`；`rapidocr-onnxruntime` 只列为可选依赖，在当前 `src/` 中未找到调用。
- `perceive/state.py` 将截图解析为 `GameState`；数字由 `perceive/digits.py` 的字形模板识别，手牌由徽章模板定位。
- `champions/jinx/vision.py` 使用 OpenCV ORB 特征匹配识别已知卡面与地图头像；`perceive/reward_screen.py` 用已采集的名称、品质模板识别有限的能力选项。
- `docs/handoff.md` 和 `docs/offline-validation.md` 记录了遮挡、未知画面、读数缺失和连续操作验收的限制，不能把已有离线正例等同于实机全覆盖。

## 官方资料确认的事实

| 事项 | 已确认内容 | 来源 |
|---|---|---|
| 模型定位 | 图像描述、物体框、分割、OCR、关系及结构化字段提取 | [发布说明](https://cactuscompute.com/blog/mirage) |
| 规模 | 51.3M 参数，发布的混合量化方案以 2 bit 为主，权重文件约 21.6 MB；不是运行时内存占用承诺 | [发布说明](https://cactuscompute.com/blog/mirage) |
| 许可证 | 模型卡声明 Apache-2.0 | [模型卡](https://huggingface.co/Cactus-Compute/mirage/blob/main/README.md) |
| Python 与 Windows | `cactus.Mirage().describe(...)`；官方列出 Windows x64/ARM64 Python runtime wheels，首次使用下载引擎和权重 | [runtime 文档](https://huggingface.co/Cactus-Compute/cactus/blob/main/README.md)、[Python API](https://cactuscompute.com/blog/needle-python-docs) |
| 输入输出 | 支持图片路径、编码图片、Pillow 或 RGB uint8 数组；框使用相对图像的 0–1000 坐标 | [发布说明](https://cactuscompute.com/blog/mirage)、[Python 实现](https://github.com/cactus-compute/cactus/blob/main/cactus/agent/mirage.py) |
| 描述语言 | 官方列出 en/de/fr/es/it/nl/pl，未列中文；这不能单独证明 OCR 字符表不含中文 | [模型卡](https://huggingface.co/Cactus-Compute/mirage/blob/main/README.md)、[发布说明](https://cactuscompute.com/blog/mirage) |
| 分辨率 | 主编码画布为 512；文本先在画布上检测，再从原始 RGB 裁切并缩放到高 48 像素，以宽 320 的滑窗读取。不能断言 OCR 只读取缩到 512 的图 | [配置](https://huggingface.co/Cactus-Compute/mirage/blob/main/config.json)、[OCR 说明](https://cactuscompute.com/blog/ocr-decoding) |
| 官方速度 | Galaxy S26 上 NPU 74 ms、CPU 107 ms；不能外推为 F1 Windows 的截图识别延迟 | [发布说明](https://cactuscompute.com/blog/mirage) |

## 判断与建议（尚未经过模型实测）

有小范围试验价值，当前证据不足以支持整体替换 OpenCV。

- 保留数字读数、已知卡面 ORB、词条图标与确定按钮的现有路径。Mirage 尚无本项目上的正确率、漏检率或错误接受率证据。
- 优先离线评估地图、战斗详情、奖励、结果页等界面分类和候选区域定位。模型的自然照片演示不能证明其熟悉 LoR UI；结构化字段或枚举输出也不证明字段真实。
- 繁体中文名称和说明的 OCR 是待验证项；若核心目标是读这些文本，可将支持中文的专用 OCR 与 Mirage、现有模板一起做相同截图对照。
- 模型仅提供感知候选，继续由纯脚本策略决定动作；UNKNOWN 和读数缺失仍遵循现有停止或 NO_OP 规则。
- 初步对照使用已有人工标注截图，覆盖正例、未知画面、遮挡、动画、零值、小数字及牌组外卡牌；分别统计字段正确率、错误接受与弃权、框偏差、冷启动/预热耗时及内存，再考虑接线。

尚未核实：中文 OCR 字符覆盖、LoR 截图泛化、F1 实际延迟与内存、是否优于现有识别，以及游戏界面所需的训练或微调成本。

## 补充：MAA 路线与 F1 的运行压力

- MAA 应用本身的[任务协议](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/master/docs/zh-cn/protocol/task-schema.md)明确支持 `MatchTemplate`（默认）、`OcrDetect`、`FeatureMatch`，并列出 OpenCV 模板匹配方法及 SIFT/ORB 等特征检测器。[官方 README](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/master/README.md)列出 OpenCV、PaddleOCR、FastDeploy 和 ONNX Runtime。不能把 MaaFramework 的全部算法清单等同于 MAA 应用的实际使用。
- 按 `docs/environment.md` 记录，F1 为 R5-7640HS（6C/12T）、24 GB RAM。就模型规模看，单实例、低频使用 Mirage 的硬件压力预计不大；这是工程判断，并非 F1 实测。模拟器并行运行时的实际资源余量未知。
- 当前 `config/settings.yaml` 设置 `tick_ms: 200`、`max_frame_age_s: 2.0`。`loop/engine.py` 顺序截图、识别再检查帧龄；200 ms 是循环目标，超出会降低频率，截图与识别后帧龄大于 2 s 则跳过动作。因此更关键的是整条链路的延迟，而非权重是否放得进内存。
- 建议先复用同一个 Mirage 实例，仅在奖励、地图或结果页等状态变化时调用；避免每个循环对多张卡分别做完整模型推理。若要替换每轮主识别，需在模拟器运行时测预热后的整体耗时、CPU、进程内存及帧龄，再决定。
