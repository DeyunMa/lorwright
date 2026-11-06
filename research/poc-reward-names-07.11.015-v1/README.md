# PoC 奖励名称表 07.11.015 v1

给 lorwright 奖励识别/偏好匹配用的静态名称表：**79 个道具 + 76 个圣物 +
1291 个能力**，全部带繁中名（来自游戏本地化数据），关键项双语对照。
数据从 01-prop 已解析的 PROP 产物提取（见 tools/extract_reward_names.py，
仅标准库，可复现），不重新解析二进制。

## 来源与身份

| 项 | 值 |
|---|---|
| GamePlayData.bin | f1 下载的 07.11.015 版本，14,049,685 bytes，SHA-256 `7ded0a61…80ae27f0aa36659b8bb25a9922d`（01-prop header.json 记录） |
| 解析产物 | `../lorwright-artifacts/analysis/stages/01-prop/parsed/`（Phase01 严格校验通过，158,194 entry） |
| 能力本地化 | `../lorwright-artifacts/analysis/stages/03-adventure/powers.jsonl`（Phase03 静态图谱） |
| 类型归属 | `02-domain/type-catalog.json`：CardStickerData=道具(I码)、RelicData=圣物(R码) |

## 数据结构（data/reward-names.json）

- `items[]` / `relics[]`：code（I0148/R0153）、name_en、name_zh_tw、
  description_zh_tw、rarity_raw、data_path、name_key（本地化键）。
- `powers[]`：ability_code（P0606）、dev_name、name_zh_tw、
  description_zh_tw、rarity_raw、rgds_path。
- 锚点验证：Heavy Hands/重拳出擊（I0130，雙重攻擊）、
  Stabilize/分身術（power_summon_stabilize）均在表内。

## 已知边界

- **闇影圖騰（Shadow Totem，sticker_ephemeralcopy）不在三张表内**：它是
  Jinx 的初始圣物，定义挂在英雄数据而非奖励表；名字只在 LocalizedText
  （sticker_ephemeralcopy_name，提取方法见 docs/handoff.md 2026-11-05 块）。
  奖励节点不会遇到它；英雄偏好按名字匹配不受影响。
- `rarity_raw` 的枚举含义未与 UI 品质框颜色对齐（items 见 1/2/3/4/7/10），
  品质优先规则落地时需截图校准映射。
- 描述是**客户端文案**，不代表实现验证（Phase03 同口径）。
- 静态版本快照：线上热修可能变动，实机遇到对不上时以截图为准并更新本表。

## 用途

1. 奖励面板识别（issue #15）：OCR/模板拿到候选名后与表内繁中名精确匹配；
2. 英雄偏好匹配：champions/<name>/ Preference.names 的中英对照已验证
   与表内一致；
3. 名字→code 反查，供后续把奖励决策落到具体物品数据。
