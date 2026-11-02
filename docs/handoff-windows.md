# Windows 上手步骤

## 1. 拉代码

```powershell
git clone https://github.com/DeyunMa/lorwright.git
cd lorwright
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## 2. 环境验证

```powershell
lorwright probe
```

**预期**：打印分辨率、UI 状态、模板数量。
**此时模板数为 0 是正常的**——下一步采集。

## 3. 游戏设置（必须）

| 设置 | 值 |
|---|---|
| 分辨率 | 1920×1080 **全屏** |
| 显示缩放 | Windows 设置里改 **100%** |
| 出牌方式 | **点击出牌**（不是拖拽） |
| 画质 | 中以上 |

## 4. 采集素材

### 4.1 按钮模板（3–5 张）

```powershell
lorwright capture --out logs/probe.png
```

用截图工具从 `logs/probe.png` 裁出：

| 文件 | 内容 |
|---|---|
| `assets/buttons/end_turn.png` | 「结束回合」按钮 |
| `assets/buttons/victory.png` | 胜利界面特征（如"胜利"字样） |
| `assets/buttons/defeat.png` | 失败界面特征 |

### 4.2 卡牌图库（20–30 张）

```powershell
python tools/collect_cards.py
```

从手牌裁出卡面，存为 `assets/cards/<card_id>.png`。

## 5. 填坐标

编辑 `config/settings.yaml` 或代码里的 `Layout`：

| 字段 | 含义 |
|---|---|
| `end_turn` | 结束回合按钮矩形 |
| `enemy_nexus` | 敌方水晶位置 |
| `play_area` | 出牌落点（棋盘中央） |
| `hand_region` | 手牌区域 |

## 6. 跑

```powershell
lorwright run --max-ticks 50
```

**先跑 50 个循环观察**，确认：
- UI 状态能识别
- 能点击结束回合
- 不会乱点

## 7. 需要补的代码

| 文件 | 任务 |
|---|---|
| `perceive/cards.py` | 手牌切分 + 匹配 |
| `loop/engine.py:_build_state` | 解析法力/血量/场面 |
| `champions/elise/policy.py` | 按伊莉絲卡组补规则 |

## 8. 日志位置

```
logs/2026-11-02/
├── run_*.log       # 文本日志
└── events.jsonl    # 结构化事件（供 LLM 复盘）
logs/snapshots/     # 出错截图
```
