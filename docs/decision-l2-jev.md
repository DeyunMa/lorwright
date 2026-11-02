# L2 JEV 层：有界选择

**定位**：规则弃权时，从**有限候选集**里挑一个。
**不是**自由生成——JEV 只能在给定选项里选，输出受约束。

代码：`src/lorwright/decide/jev.py`、`decide/jev_policy.py`

---

## 一、为什么用 JEV 而不是直接上 LLM

| 维度 | JEV | LLM |
|---|---|---|
| 延迟 | 100–500ms | 2–20s |
| 输出 | 受约束（必须选一个候选） | 自由文本，需要解析 |
| 成本 | 低 | 高 |
| 失败模式 | 返回 None → 降级 | 幻觉、格式错、超时 |

**回合制对局里 500ms 完全可接受，20s 会让对局节奏崩掉。**

---

## 二、接口契约

### 请求

```json
POST {base_url}/decide
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "kind": "choice",
  "context": "局面描述（见第三节）",
  "options": ["打出 尖啸蜘蛛（2 费）", "打出 群蛛之主（5 费）", "结束回合"]
}
```

### 响应

```json
{ "choice": "打出 尖啸蜘蛛（2 费）" }
```

### 约束

| 项 | 规则 |
|---|---|
| `choice` 必须 ∈ `options` | 否则视为失败，降级 |
| 超时 | 2s（可配） |
| 失败 | 返回 `None`，路由跳到下一层 |

**布尔决策**（`kind: "noul"`）返回 `{"value": true|false}`，暂未使用。

---

## 三、上下文格式

`state.summary()` 目前只给一行。**JEV 需要更完整的结构化上下文**，
建议扩展成：

```
回合 3 | 我方 50 血 | 敌方 30 血 | 法力 2/3（法术槽 0）
我方场面：无
敌方场面：5/7 化学庞克撕裂乐手
手牌（6 张）：
  - 尖啸蜘蛛 2 费 2/2（召唤时+2/+0）
  - 伊莉丝 2 费 2/3（挑战者）
  - 倾巢而出 6 费 法术
  - 群蛛之主 5 费 6/6
  - 尖啸蜘蛛 2 费 2/2
  - 蛛网 3 费 法术
可出：尖啸蜘蛛、伊莉丝、尖啸蜘蛛
```

**关键**：上下文里要包含**卡牌效果文本**，否则 JEV 不知道「召唤时+2/+0」意味着什么。

---

## 四、候选生成

`decide/candidates.py::generate(state)`：

| 候选 | 条件 |
|---|---|
| `PLAY_CARD` | 每张 `cost <= mana` 的牌 |
| `ATTACK nexus` | 有 `can_attack` 单位 |
| `END_TURN` | 永远有 |

**候选数 ≤ 1 时不调 JEV**（没得选，直接返回）。

---

## 五、降级链路

```
L1 规则  ──弃权──▶  L2 JEV  ──失败──▶  L3 LLM  ──失败──▶  NO_OP
                         │                                    │
                    超时/非法选项                        不动，等下一 tick
```

**每一层都可弃权，任何一层失败都不阻塞主循环。**

---

## 六、配置

`config/settings.yaml`：

```yaml
jev_base_url: ""      # 例：https://your-jev-endpoint/v1
jev_api_key: ""       # 你后续提供
```

**留空 = 不启用，路由直接跳过 L2。**

---

## 七、验证步骤

| 阶段 | 做法 | 通过标准 |
|---|---|---|
| 1. Mock | `MockJev(answer="...")` | 路由正确选中，30 个单测全绿 |
| 2. 连通 | 真实 endpoint + 1 条固定 context | 返回合法 `choice` |
| 3. 覆盖率 | 跑 20 局，统计各层命中 | L2 命中 15–25% |
| 4. 合法性 | 记录所有非法选项 | 非法率 < 5% |

**现在停在阶段 1**——`MockJev` 已可用，真实 endpoint 等你配 key。

---

## 八、需要你提供的信息

配 key 时请一并给出：

| # | 信息 | 用途 |
|---|---|---|
| 1 | **endpoint URL** | `jev_base_url` |
| 2 | **请求格式**（是否就是上面的 `/decide` + `kind/context/options`） | 若不是，我改 `JevClient` |
| 3 | **模型/引擎名**（如果有） | 请求参数 |
| 4 | **超时与限流** | 决定 `timeout` 和重试策略 |

**如果 JEV 是 OpenAI 兼容接口**（`/v1/chat/completions`），
那 `LlmClient` 已经能直接调，只是 prompt 不同——告诉我一声即可复用。
