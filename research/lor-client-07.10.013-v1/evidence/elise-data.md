# Phase 02：卡牌、英雄与成长配置

**本阶段完成静态对象与本地化的可追溯索引。主数据43,685条、345种顶层类型全部对应到APK原生反序列化方法；伊莉絲起始牌组和成长配置已形成独立参考文件。** 这不是完整游戏规则解释器，也没有取得当前玩家的等级、星级、遗物或局面。

## 命名依据与覆盖

类型命名来自 `native/metadata-index-v3.sqlite` 中 `BaconRGDSClassDeserialization.Deserialize_<类型名>_<十进制hash>` 方法，保留方法原名及原生地址，见 `type-catalog.json`。没有按对象字符串猜类型。345种顶层类型全部命中且没有命名冲突。

字段采用小写UTF-8 FNV-1a-32，与同一APK的实际字段名匹配；保留大小写别名和原始数值hash。1,477个不同字段hash中，1,459个命中；496,696次字段出现中482,817次命中，13,879次仍保持未命名，共18个hash。未发现不同拼写产生的字段hash冲突。`unresolved-fields.json` 保留未解列表。

102,327个嵌套结构包含403种非空类型，全部能命名；另有5,657个type=0的显式null结构，未伪造类型。12,964条带RGDSPath的记录全部通过“路径hash等于entry hash”的交叉核对。

索引保留137,982条LINK及其字段路径、源字节范围。2,154次非零引用在本份主数据中没有目标；这不是合法性验证通过，也没有把它们自动补为默认对象。具体玩法限制由后续地图/AI阶段解释。

## 对象分类

以下是序列化类型数量，可能同时包括旧内容、测试内容、事件变体，不能当作当前服务器可用数量：

| 类型 | 记录数 | 用途 |
|---|---:|---|
| ClientCardData | 2,990 | cardcode、基础属性、文本key、资源路径、格式/阵营引用 |
| AdventurePlayableEntity | 107 | 可玩英雄对象、起始牌组、成长/星力入口 |
| SpeAbilityDefinition_Client | 1,605 | 能力code、展示文本、图标等客户端定义 |
| AdventurePowerRank | 2,462 | 成长奖励、星力及能力包装对象 |
| CardStickerData | 299 | 卡牌道具和附加脚本引用 |
| RelicData | 154 | 遗物定义和附加脚本引用 |
| GdsDeck | 703 | 本地主数据携带的牌组；不等于全部敌方牌组 |

`domain.sqlite` 保存全部345种类型，`type-catalog.json` 可查询完整分类。

## 伊莉絲参考链

- 英雄：`36ad9250`，RGDSPath=`ReforgedCampaigns/Champions/Elise`。
- StartingDeck：`23c0563d`，9种牌每种2张，共18张。
- PowerRankConfig：`1112783e`；ProgressionTrack：`7fda3b36`。
- `elise-reference.json` 包含139个精确对象、9种起始牌和338条英/繁中文本关联；源字段hash、offset/end_offset、原生类型候选全部保留。
- 参考链包括静态成长/星力包装对象，按脚本明确的类型白名单展开、最多5轮；没有展开全产品的所有出链。存在未展开链接时仍能用hash查询数据库。

起始牌code：`01SI053`、`01NX046`、`01SI002`、`06SI037`、`06NX013`、`01SI056`、`04NX016`、`01NX023`、`01SI050`。

星力本地化与对象关联已取得，例如一星/三星“我方攻击时”影响各处蜘蛛的文本；二星起始魔力和回合结束条件；六星另有植入/恐惧机制。文本保留原始富文本和 `{CardRef:...}` 占位符，未执行游戏的文本替换器，也不能把描述当作已经核对过的完整执行代码。字段缺省值同样没有凭经验补写，例如部分单位省略Type字段，仍需构造器或原生证据确认默认值。

## 索引与验证

`domain.sqlite` 的主要表：

- `entries`：path_hash、类型、RGDSPath、DevName、code、原始JSON和命名JSON。
- `links` / `strings`：owner、字段路径、field_hash、目标/值、源字节范围。
- `localization`：英54,224对、繁中54,241对，均无重key；保留原entry和序号。

其它14种语言由Phase01完整解码保存；本阶段只将项目优先的英/繁中加入语义索引。locale中的空entry及非文本metadata仍留在Phase01原始JSONL，本表只摘取文本map。

验证覆盖：SQLite integrity、输入/脚本SHA；逐条比对43,685份原始及命名JSON；137,982条链接、207,959条字符串；两种语言所有文本；139个伊莉絲参考对象与源索引一致。先主动停在500条提交点，再用同一命令续跑到全量；完整验证通过，见 `validation.json`。

初版开发中遇到locale包含空entry和非文本字段，两个早期SQLite已另名保留。它们不是完成产物，恢复只使用 `domain.sqlite`，避免误接旧结果。

## 续接命令

```sh
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/02-domain/build_domain.py
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/02-domain/export_elise.py
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/02-domain/validate_domain.py
```

建索引按500条事务提交；输入或建索引脚本hash改变会拒绝沿用旧数据库，保留旧文件并选新输出后重建。`--verify` 只读检查已完成索引。导出/独立验证命令可以重跑，只替换本阶段生成结果；没有修改主项目。

下一步是读取Phase03地图/遭遇图及Phase05原生/AI结论。对项目而言，这份索引可以提供英雄包的离线知识来源；通用决策算法是否能够复用，仍取决于实际原生行为证据和可获取的局面输入。
