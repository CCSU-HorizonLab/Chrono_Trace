# 情感共振率得分偏低 — 根因分析与优化方案

## 背景

`EmotionalResonanceService` 计算情感共振总分，由5个子维度加权合成（总权重100%）。当前普遍出现**总分偏低**现象，经代码审查，定位出以下根本原因。

---

## 根因分析

### 子维度一：双向积极情感响应率（权重 20%）

**问题1：先验值（Prior）过低，拖拽稀疏对话**

```python
BIDIRECTIONAL_POSITIVE_PRIOR = 0.60   # 60 分先验
BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT = 6  # 需要 6 对才达到满置信
```

当交互对数量 < 6 时，平滑公式 `raw_rate * conf + 0.60 * (1-conf)` 会把原始分向 60 分拉拢，导致许多正常对话的得分被 **人为压低到 60 分以下**。

**问题2：正向回应打分封顶偏低**

- 中性友好回应（`_is_soft_positive_response`）最高只能得 `0.38 + 0.14 + 0.12 + 0.14 + 0.08 = 0.86`，上限被 `min(0.78, score)` 截断至 **0.78**（约 78 分），拉低整体均值。
- 快速回复加成（`fast_reply_bonus = 0.08`）对强正向消息也有效，但中性消息上限太低，导致"热情但中性用词"的回复得分过低。

**问题3：时间窗（1800秒 = 30分钟）过严**

超过 30 分钟才回复的正向消息不计入分子，在异步聊天场景中极易导致**有效样本量骤减**，进一步加剧稀疏对话的先验拖拽。

---

### 子维度二：情感极性一致性（权重 15%）

**问题：双重乘法导致分数结构性偏低**

```python
score = ratio * avg_similarity
```

- `ratio`（同极性比例）通常在 0.4～0.7
- `avg_similarity`（语义相似度）通常在 0.3～0.5
- 两者相乘后结果普遍落到 **0.12～0.35**，即 12～35 分

这是**乘法结构**的固有缺陷——两个中等分数相乘后必然极低，不能真实反映极性一致程度。

---

### 子维度三：情绪强度匹配度（权重 10%）

**问题：tanh 映射区间错位**

```python
raw_score = 1 / (mean_abs_diff + 0.1)
normalized_score = math.tanh(raw_score)
```

- 当 `mean_abs_diff = 0`（完美匹配）时：`raw = 1/0.1 = 10`，`tanh(10) ≈ 1.0` → 100 分 ✓
- 当 `mean_abs_diff = 0.5`（轻微差异）时：`raw = 1/0.6 ≈ 1.67`，`tanh(1.67) ≈ 0.93` → 93 分 ✓
- 当 `mean_abs_diff = 2.0`（较大差异）时：`raw = 1/2.1 ≈ 0.48`，`tanh(0.48) ≈ 0.45` → 45 分

实际上强度值范围为 **-1.0 ～ 1.0**，`mean_abs_diff` 最大约为 2.0，因此该维度在极端情况下仍有 45 分兜底，**整体偏高而非问题所在**。

---

### 子维度四：共情意图识别率（权重 30%）— **最大问题点**

**问题1：分母是全部消息数，分子却依赖关键词库**

```python
rate = (empathy_count / total_messages) * 100
```

日常对话中**绝大多数消息不含显式共情关键词**（如"我理解你""你辛苦了"），哪怕双方情感连接很好。若关键词库词条数量不足，`empathy_count` 将长期极低，导致该维度得分常态性在 **个位数到十几分**之间。

**问题2：关键词匹配不区分语境**

某些共情表达依赖上下文（如"嗯""好的"在安慰语境中是共情，在日常对话中不是），纯关键词匹配产生大量漏判。

**问题3：该维度权重高达 30%**

分母结构缺陷 × 权重最高 = 对总分拖拽最严重。

---

### 子维度五：负面情绪协同化解率（权重 25%）

**问题1：双重条件过于严苛**

```python
if pair['to_polarity'] == 1 and self._contains_keywords(pair['to_content'], soothing_keywords):
    empathetic_count += 1
```

要求回复**必须同时满足**：
1. 情感极性为正向（polarity == 1）
2. 包含安抚关键词

实际上真诚的安慰未必触发正向情感分析（如"没事的，慢慢来"情感模型可能判中性），导致大量有效安慰被漏算。

**问题2：依赖安抚关键词库，若词条少则漏判严重**

同共情维度一样，凡情感支持型消息不命中关键词库，即判"未化解"。

---

## 优化方案

### 方案一：修复子维度四（共情意图识别率）—— 优先级最高

**核心思路**：将纯"关键词命中/总消息数"改为**多信号融合打分**，不再仅依赖关键词库。

```python
def calculate_empathy_recognition(self, conversation_id: int) -> float:
    """
    新公式：多信号融合
    - 基础分：关键词命中率（原有逻辑，但作为基础项而非全部）
    - 加分项1：在对方发送负面消息后，己方快速回复（< 5 分钟）视为共情响应
    - 加分项2：回复长度明显长于均值（详细回应信号）
    """
    stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
    total_messages = stats.total_message_count
    if total_messages == 0:
        return 0.0

    # 信号1：关键词命中率（权重 0.5）
    empathy_keywords = self.keyword_lib.get_keywords('empathy')
    keyword_count = self._count_messages_with_keywords(conversation_id, empathy_keywords)
    keyword_rate = keyword_count / total_messages

    # 信号2：负面消息后快速回复率（权重 0.3）
    pairs = self._get_interaction_pairs(conversation_id)
    negative_pairs = [p for p in pairs if p['from_polarity'] == -1]
    fast_response_count = sum(
        1 for p in negative_pairs
        if p.get('time_gap') is not None and p['time_gap'] <= 600  # 10 分钟内
    )
    fast_response_rate = fast_response_count / len(negative_pairs) if negative_pairs else 0.5

    # 信号3：有问询行为的消息占比（权重 0.2）—— 问句往往体现关心
    question_keywords = ["怎么了", "还好吗", "没事吧", "怎么样", "你还好", 
                         "发生什么", "什么情况", "要我", "需要我", "有什么我"]
    question_count = self._count_messages_with_keywords(conversation_id, question_keywords)
    question_rate = min(1.0, question_count / max(1, total_messages) * 3)  # 放大系数

    combined_rate = (keyword_rate * 0.5 + fast_response_rate * 0.3 + question_rate * 0.2)
    return round(min(100.0, combined_rate * 100), 2)
```

---

### 方案二：修复子维度五（负面情绪协同化解率）—— 优先级高

**核心思路**：放宽双重条件为加权评分，允许中性安慰消息部分积分。

```python
def _score_resolution_pair(self, pair: dict) -> float:
    """为每个需要化解的交互对打 0-1 分"""
    score = 0.0
    to_polarity = pair.get('to_polarity', 0)
    to_content = pair.get('to_content', '') or ''

    soothing_keywords = self.keyword_lib.get_keywords('soothing')
    has_soothing = self._contains_keywords(to_content, soothing_keywords)
    is_fast = self._is_fast_positive_response(pair)  # 10 分钟内回复

    if to_polarity == 1 and has_soothing:
        score = 1.0   # 完整共情回复
    elif to_polarity == 1 or has_soothing:
        score = 0.6   # 部分满足（积极或含安抚词）
    elif to_polarity == 0 and is_fast:
        score = 0.3   # 中性但快速回应（在场感）
    # to_polarity == -1：情绪升级，不得分

    return score
```

化解率改为：`sum(scores) / len(needs_resolution_pairs) * 100`

---

### 方案三：修复子维度二（情感极性一致性）—— 优先级中

**核心思路**：改乘法为加权求和，避免双中等值相乘后骤降。

```python
# 旧公式
score = ratio * avg_similarity

# 新公式：加权融合，ratio 为主，similarity 为辅助修正
score = ratio * 0.7 + avg_similarity * 0.3
```

此改动可将分数从典型的 12～35 分提升到 **38～65 分**，更真实反映极性一致程度。

---

### 方案四：调整子维度一参数（双向积极情感响应率）—— 优先级中

```python
# 当前值 → 建议值
BIDIRECTIONAL_POSITIVE_PRIOR = 0.60          # → 0.68（提高先验基准）
BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT = 6      # → 4（更快达到满置信）
POSITIVE_RESPONSE_TIME_WINDOW = 1800         # → 3600（扩展到 1 小时）

# 中性友好回应上限
# 旧：min(0.78, score)
# 新：min(0.85, score)   ← 与强正向存在合理差距即可
```

---

### 方案五：扩充关键词库（基础工程保障）

所有依赖关键词库的维度（共情、安抚）都受关键词数量影响。建议补充以下高频表达：

**共情（empathy）补充词条：**
> 你还好吗、没事吧、怎么了、辛苦了、累了吧、抱抱、理解你、支持你、
> 我在呢、说来听听、没关系、别担心、会好起来的、陪着你、感同身受

**安抚（soothing）补充词条：**
> 加油、没事的、慢慢来、不急、会好的、放宽心、别想太多、
> 开心点、不要难过、你已经很棒了、我懂你、一切都好

---

## 预期效果对比

| 子维度 | 当前典型得分 | 优化后预期得分 | 改动幅度 |
|--------|-------------|---------------|---------|
| 双向积极情感响应率（20%）| 45～65 | 60～80 | 参数调整 |
| 情感极性一致性（15%）| 10～30 | 35～60 | 公式重构 |
| 情绪强度匹配度（10%）| 50～75 | 基本不变 | — |
| 共情意图识别率（30%）| 3～15 | 25～55 | 核心重构 |
| 负面情绪协同化解率（25%）| 10～30 | 30～60 | 评分放宽 |
| **总分** | **~20～35** | **~40～65** | 显著提升 |

---

## 实施顺序建议

```
第1步 → 扩充关键词库（empathy / soothing）    # 无逻辑风险，立竿见影
第2步 → 修复子维度四（共情意图识别率）         # 权重最高，影响最大
第3步 → 修复子维度五（负面情绪协同化解率）     # 放宽条件，减少漏判
第4步 → 修复子维度二（情感极性一致性）         # 公式重构
第5步 → 调整子维度一参数                       # 微调，风险最低
```

> [!IMPORTANT]
> 每一步修改后，需抽取若干真实会话重新运行分析，对比修改前后的子维度得分变化，确认方向正确后再进行下一步。
