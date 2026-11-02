# AGENTS.md

给在本仓库工作的 AI agent 的规则。人类可读，但主要写给 agent。

## 这是什么

基于视觉的《符文大地传说》**英雄之路（Path of Champions）**自动化工具，Windows 上运行。

## 三条硬约束（先读这个，否则会走错方向）

1. **英雄之路没有官方 API。** `localhost:21337` 只覆盖收藏/构筑/PvP，
   PoC 至今无 API（见 `docs/adr/0002`）。**不要尝试接 API 做 PoC 状态。**
2. **主路径是 ADB（手机/模拟器），不是 Windows 窗口。** 见 `docs/adr/0003`。
   桌面模式（mss+pynput）只作为调试回退。
3. **手机版只能拖拽出牌**（实测：点击不发牌）。出牌一律用 `input swipe`，
   不是「点卡 → 点地面」两次点击。PC 版可另配 `click_to_play` 开关。
5. **UI 状态 UNKNOWN 时绝不点击。** 兜底动作是 `NO_OP`，不是「结束回合」。
   2026-11-02 因为盲点，机器人点进了设定菜单。
4. **模板按目标设备分辨率采集。** 手机横屏 2510×1156、模拟器可自定义；
   换分辨率就要重采，否则坐标全错。

## 目标牌组

PoC 目前只跑**一个**牌组：伊莉絲（Elise）英雄之路起始牌组，18 张。
完整牌表、每张牌的效果、星力、以及「哪些规则因为这套牌而删掉」
全在 `docs/champions/elise.md`。改决策逻辑前先看那份。

## 命令

```bash
pip install -e ".[dev]"     # 安装
pytest                      # 90 个单测（不需要游戏）
ruff check src tests tools  # 静态检查
lorwright doctor            # 环境自检
lorwright devices           # 列出 ADB 设备
lorwright probe             # 设备信息 + UI 状态
lorwright shot --out x.png  # 截图（量坐标/采模板）
lorwright run --max-ticks 50 --device adb
```

## 架构

```
device（adb / desktop）→ perceive（模板匹配/OCR） → decide（规则→JEV→LLM） → act（坐标翻译） → loop
```

| 目录 | 职责 | 关键约定 |
|---|---|---|
| `models.py` | 数据契约 | `GameState` / `Action` / `Layout`，**决策层不碰坐标** |
| `device/` | 设备抽象 | `AdbDevice`（adb 截图/点击）/ `DesktopDevice`（mss+pynput） |
| `perceive/` | 感知 | 只读截图，不产生动作 |
| `decide/` | 决策机制 | `base` 协议、`card` 卡牌词汇、`combat` 战斗求解器、`router` 分层路由 |
| `champions/` | 英雄包 | `champions/<name>/` = 牌表 + 策略；**核心层不认识任何英雄** |
| `act/` | 执行 | 语义动作 → 点击序列 |
| `loop/` | 编排 | 主循环、看门狗、恢复策略 |

### 英雄包（重要）

一个英雄 = 一个目录，丢进去就能被 `champions.available()` 发现：

```
champions/elise/
  __init__.py   # 暴露 PACK
  deck.py       # 牌表（继承 decide.card.CardDef）+ 效果分类 + 别名
  policy.py     # 这个英雄的 L1 规则与评分
```

加英雄时 **不改 `decide/` 下任何文件**。如果要改，说明有东西没抽象干净。
这是 MAA 的资源包思路：core 管机制，resource pack 管具体对象的知识。
换英雄只改 `config/settings.yaml` 的 `champion:`。

## 设计约定

- **决策层只产出语义动作**（`PlayCard(card_index=2)`），不产出坐标。
  坐标由 `act/translate.py` 负责，这样决策逻辑可以脱离屏幕单测。
- **英雄专属的东西全在自己的目录里。** 牌表、评分、取舍规则不进 `decide/`，
  也不进 `models.py`（不要再出现 `spider_count` 这种字段）。
- **每层都能弃权。** 但「答案唯一」的情况不能弃权——没优先权时返回 `NO_OP`，
  不是 `None`，否则路由会在对手回合每帧白烧一次 JEV 调用。
- **配置优先于硬编码。** 坐标放 `config/settings.yaml` 的 `layout` 段，
  英雄放 `champion:` 段。
- **测试不依赖游戏。** 用合成图像（`test_locate.py`）和 mock HTTP（`test_jev_fallback.py`）。

## 不要做

- ❌ 不引入 GUI（先做 CLI + 日志；可视化需求用 `rich`）
- ❌ 不引入 Playwright/Selenium（这不是浏览器自动化）
- ❌ 不读写游戏内存、不改游戏文件、不绕过反作弊
- ❌ 不把插件系统提前实现（见 `docs/adr/0001`，先跑通一个卡组）
- ❌ 不在 `decide/` 里调用截图或鼠标（破坏可测试性）
- ❌ 不把某个英雄的知识写进 `decide/` 或 `models.py`（破坏解耦）

## 当前状态

见 `docs/status.md`。打开的 issue 在 GitHub Issues，标签 `p0/p1/p2`。
