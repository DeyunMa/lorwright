# PoC 奖励名称表 07.11.015 v1

给 lorwright 奖励识别/偏好匹配用的静态名称表：**178 个道具 + 153 个圣物 +
1291 个能力**，全部带繁中名且 code 唯一，关键项双语对照。数据从 01-prop
已解析的 PROP 产物提取（tools/extract_reward_names.py，仅标准库，可复现），
不重新解析二进制。

## 来源与身份

| 项 | 值 |
|---|---|
| GamePlayData.bin | f1 下载的 07.11.015 版本，14,049,685 bytes，SHA-256 `7ded0a61…80ae27f0aa36659b8bb25a9922d`（01-prop header.json 记录） |
| 解析产物 | `../lorwright-artifacts/analysis/stages/01-prop/parsed/`（Phase01 严格校验通过，158,194 entry） |
| 能力本地化 | `../lorwright-artifacts/analysis/stages/03-adventure/powers.jsonl`（Phase03 静态图谱） |
| 类型归属 | `02-domain/type-catalog.json`：CardStickerData、RelicData 的 native 类型关联 |

## 收录规则（全部有路径统计证据，2026-11-06）

- **items** = CardStickerData 且数据路径以 `ReforgedCampaigns/Items/` 开头；
- **relics** = RelicData 且路径以 `Loot/CardMetaProgression/Relics` 开头；
- 排除（有统计依据）：`Mods/Power_4/Stickers`（power 贴图变体）、
  `Mods/Power_XP1`、XP1 活动贴纸、`CardProfiles`/`Illustrations` 美术条目；
- 收录体要求 name_key 能在 LocalizedText 解析出繁中名且 code 唯一；
  不满足的 25 道具 + 1 圣物在 `excluded_no_display_name[]` 留档
  （Equipment 双形态子贴纸如 Sheen/TitansAxe 的部件、8A_ITEMS 事件贴纸、
  活力关键词贴纸——显示名来自父条目或其它源，不是独立奖励选项）。

## 数据结构（data/reward-names.json）

- `items[]` / `relics[]`：code（I0012/R0153）、name_en、name_zh_tw、
  description_zh_tw、rarity_raw、data_path、icon_path（图标资源路径，
  以后从 AssetBundles 裁模板用）、name_key。
- `powers[]`：ability_code（P0606）、dev_name、name_zh_tw、
  description_zh_tw、rarity_raw、rgds_path。
- 锚点：Heavy Hands/重拳出擊 = **I0130（道具）**；
  Shadow Totem/闇影圖騰 = **I0012（道具）**；Stabilize/分身術 =
  power_summon_stabilize。

## 审计（2026-11-06，verify-not-infer 标准）

- 全集校验内置：缺繁中名/缺 code/重复 code != 0 时提取器直接拒绝交付；
- 牌表交叉审计（tools/audit_deck_cards.py，产出 data/deck-audit.json）：
  Elise 9 张 + Jinx 2 张的名字与 cost 对 07.11.015 ClientCardData 全部一致；
- **Jinx PoC 卡码 = 01PZ040**（4/4/3）；经典 04SI006 在当前数据中不存在；
- powers 缺繁中名的 15 条全部是 `ReforgedCampaigns/FoePowers/`（敌方
  能力，不进奖励选择，已加 foe_power 标记）；玩家侧 841 条缺名 = 0；
- 修正记录：闇影圖騰最初被误标为「Jinx 初始圣物」——实际是道具 I0012
  （ReforgedCampaigns/Items/ShadowTotem）；被漏原因是 loc 键大小写
  （_Name vs _name），已改大小写不敏感并用路径统计定范围。

## 已知边界

- `rarity_raw` 枚举含义未与 UI 品质框颜色对齐，品质优先规则落地时
  需截图校准映射；
- 描述是**客户端文案**，不代表实现验证（Phase03 同口径）；
- 静态版本快照：线上热修可能变动，实机遇到对不上时以截图为准并更新。

## 用途

1. 奖励面板识别（issue #15）：OCR/模板拿到候选名后与表内繁中名精确匹配；
2. 英雄偏好匹配：champions/<name>/ Preference.names 中英对照已验证一致；
3. 名字→code 反查，供后续把奖励决策落到具体物品数据；
4. icon_path 供后续从 AssetBundles 提取奖励图标模板。
