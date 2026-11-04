# LoR 07.10.013：给开发 agent 的可用资料包 v1

**先用本目录继续开发，不需要等待完整AI逆向。** 这里有经过来源核验的英雄知识、9张卡面、18个关键词图标、34个关键词的AI估值参考及已核验规则组件。没有完整人机决策算法，也没有自动接入业务代码。

先运行（仅Python标准库，无需游戏、ADB、REA或Ghidra）：

```sh
python research/lor-client-07.10.013-v1/verify.py
```

## 优先使用

| 文件 | 用途 | 实际边界 |
|---|---|---|
| `data/elise-starter.json` | 9种18张起始牌；费用/攻血/类型/双语名/效果/关联牌 | 固定Data Dragon 7_10_0基础值，不含局内buff、等级道具或装备 |
| `images/cards/` | 9张繁中680×1024卡面；供身份识别/特征研究 | 原图不能直接当透视遮挡后的手牌模板；需要截图回归 |
| `images/keywords/` | 18个原包透明图标，含Scout、Challenger、Stunned | 模板候选；需按设计尺寸/ROI/缩放验证。已有单帧Scout/Challenger正例，Stunned曾在同帧误报，不能沿用统一阈值 |
| `data/elise-progression-source.json` | 139个英雄/成长/星力及起始牌对象、338条英/繁中关联文本 | 原始hash/字段/offset保留；当前玩家等级、星级和遗物未知 |
| `data/keyword-ai-weights.json` | 34种关键词，24个显式倍率、2个显式加值 | 明确的AI启发式参考；组合公式与实际调用未恢复，缺省保持null，不直接替换穷举求解器 |
| `data/native-rule-components.json` | 先遣攻击判定、不能格挡状态、威吓门槛 | 已验证的规则组件，不是完整动作合法性或完整战斗模拟器 |
| `evidence/` | 机制、输入和网络边界说明 | 用于理解和复核，不是运行时输入源 |
| `provenance/`、`manifest.json` | 原素材出处、版本、SHA、导出对象与包指纹 | 可离线检查本包身份；源码大包留在项目同级artifacts目录 |

## 交给当前开发 agent 的顺序

1. 继续项目当前P0：把截图识别结果填入GameState。用9卡数据/卡面补身份、用关键词图标补Scout/Challenger/Stunned；先建立真实截图正负例，保留UNKNOWN→NO_OP。
2. 伊莉絲专属知识继续放`champions/elise/`。核对`01NX023`群蛛之主和`01SI056`發狂疾行蛛：召唤时影响当时已有的其他蜘蛛，不能统一解释成“先出buff牌，后来蜘蛛受益”。具体顺序仍需考虑法力、星力、格子和优先权。
3. 原生规则组件可作为通用战斗测试的依据。6v6穷举仍沿用项目现有设计；不要只因发现了启发式系数就改成纯打分。
4. 关键词倍率可作为以后校准的参考值。它们不是完整官方评分器；还缺基础局面价值、叠加方式、搜索和动作选择逻辑。

这批只新增独立research目录；没有改变现有代码、配置、资源入口、依赖或分支。接入时按仓库AGENTS.md及当前源码验证，别把静态基础值当成局内实测状态。当前主项目另一个agent的修改保留原样。

## 已知的算法边界

客户端输入函数消费已有ValidActions列表；阻挡吸附按屏幕几何距离工作。已追通WebSocket接收→消息分发→ValidActionsMessage→动作列表的静态代码链，说明至少有一条合法动作列表由网络消息提供的路径。这不是PoC公开API，也没有授权/实现去接这个协议。

部分目标/脚本钩子在本包直接返回true或ret，不能当完整规则引擎。完整“局面→候选→评分/搜索→最佳动作”算法尚未恢复；本包不包含现成挂机或自动最优决策模块。AI在本地还是远端仍有未解边界。

## 文件格式

`elise-starter.json.cards`是易读的基础牌表；`keyword-ai-weights.json.keywords`是小型记录数组，倍率/加值缺失值为null；`elise-progression-source.json`较大，只有需要查具体星力/成长链时再读。`reference.schema.json`约束新生成的小型规则/系数文件。`verify.py`检查所有交付文件SHA、PNG尺寸和关键记录数。

版本范围：APK07.10.013、下载资源branch7-10-release；官方卡牌静态参考固定7_10_0。禁止静默混入latest数据。完整AI研究继续保存在项目同级`lorwright-artifacts/analysis/stages/05-native-ai/round2/`，本资料包可以独立复制到Windows使用。
