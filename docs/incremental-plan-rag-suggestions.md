# Chrono Trace 增量计划书：面向聊天对象的共同记忆 RAG 建议系统

## 1. 背景

Chrono Trace 当前已经具备微信历史数据导入、本地分析、实时监听、LLM 建议、联系人画像、用户画像、建议观察与反馈规则提取等能力。实时建议链路目前主要依赖最近对话、情绪触发、画像摘要、量化风格约束和少量历史记忆来构造 prompt。

后续增量的核心方向是：将建议生成升级为“按聊天对象隔离的共同记忆 RAG 系统”。每一个聊天对象都对应一套独立的关系记忆、聊天方式、表达边界和建议策略。模型生成建议时，应优先服务当前聊天和关系推进，而不是单纯模仿用户语气。

核心原则：

> 一个聊天对象 = 一套共同记忆 + 一套沟通方式 + 一种关系状态 + 一套建议策略。

## 2. 产品定位

### 2.1 主要目标

- 生成建议首先服务“当前聊天怎么回更合适”，关系策略优先。
- 用户表达风格用于约束话术，而不是替代策略判断。
- 共同记忆围绕具体聊天对象隔离，不做无差别全局混用。
- 让模型能理解“我和这个人是怎么聊的”，而不是只知道“我平时怎么说话”。
- 默认本地索引和本地 embedding，远程 embedding 作为用户自行配置的可选能力，默认关闭。
- 第一版直接做完整 RAG 闭环，避免后续推翻架构。

### 2.2 非目标

- 不把 RAG 做成自动翻旧账系统。
- 不让模型主动引用敏感记忆。
- 不追求“完全复刻用户本人”，避免生成对关系不利但风格相似的话。
- 不默认把所有联系人语料混在一起训练全局人格。

## 3. 决策结论

### 3.1 知识库边界

RAG 空间以 `account_wxid + conversation_id` 为主键隔离。

每个聊天对象独立维护：

- `shared_memories`：双方共同经历、共同话题、重要历史事实。
- `relationship_profile`：关系状态、亲密度、主动模式、边界感、当前阶段。
- `self_style_examples`：用户在这个聊天对象面前的表达习惯。
- `contact_preferences`：对方偏好、雷点、常见情绪模式、沟通禁忌。
- `feedback_examples`：AI 建议与用户实际发送内容的对照样本。

全局用户风格可以作为低权重兜底，但不能覆盖联系人级关系策略。

### 3.2 建议生成目标

第一优先级：服务当前聊天和关系策略。

第二优先级：符合这个聊天对象下的既有沟通方式。

第三优先级：贴近用户本人表达风格。

这意味着：

- 话术不能只因为“像用户”就被采纳。
- 如果用户平时冷淡，但当前关系策略需要轻量安抚，模型可以给出克制但有效的安抚。
- 如果历史共同记忆与当前话题无关，不应强行引用。

### 3.3 Embedding 策略

- 默认使用本地 embedding。
- 第一版默认复用项目现有本地模型：`tingting0514/text2vec-base-chinese`。
- 第一版默认向量维度：384 维，与当前 `sentiment_cache.embedding_vector`、`SentimentService` 和现有测试假设保持一致。
- 默认不调用远程 embedding。
- 远程 embedding 作为高级配置项，由用户自行填 API、模型、base URL 和开关。
- 远程 embedding 开启前需要明确提示：被索引文本可能发送到用户配置的第三方接口。
- 远程 LLM 建议生成也只发送压缩后的最小必要上下文。

不建议第一版切换到新 embedding 模型。RAG 第一版的重点是打通闭环和验证检索质量，复用现有模型可以减少下载、打包、GPU/CPU 兼容、历史向量迁移和测试改造成本。

后续可以做成可插拔：

- 默认本地：`tingting0514/text2vec-base-chinese`。
- 自定义本地：用户指定 sentence-transformers 兼容模型目录。
- 自定义远程：用户配置 OpenAI-compatible embedding API。
- 模型切换后按 `embedding_model + embedding_dim` 分批重建索引，不混用旧向量。

### 3.4 记忆使用规则

推荐采用“分级注入”：

| 记忆类型          | 是否默认注入   | 用途                           | 限制                               |
| ----------------- | -------------- | ------------------------------ | ---------------------------------- |
| 关系状态记忆      | 是             | 判断聊天策略、主动程度、边界感 | 只注入摘要，不注入长原文           |
| 沟通模式记忆      | 是             | 判断这个对象下怎么说更自然     | 只约束表达，不决定话题             |
| 共同经历/具体事实 | 语义唤醒后注入 | 当前话题提到相关内容时补充背景 | 不主动翻旧账                       |
| 对方偏好/雷点     | 高置信时注入   | 避免踩雷，调整措辞             | 需要来源和置信度                   |
| 敏感记忆          | 默认不注入     | 隐私、争吵、金钱、家庭、疾病等 | 用户显式允许或当前话题强相关才可用 |
| 反馈改写样本      | 是             | 学习用户如何修正 AI 建议       | 权重高，但不照搬                   |

### 3.5 脱敏策略

本地数据没有经过脱敏是隐私风险，但过度脱敏会直接损害 RAG 效果。共同记忆依赖具体指代、称呼、地点、事件和时间线，如果全部替换成空泛占位，模型会无法判断关系语境。

推荐策略不是“全量脱敏后再检索”，而是：

- 本地原始消息继续保留在本地数据库，不默认上传。
- 本地 RAG 索引尽量只存最小必要文本和摘要，不复制无关长原文。
- 本地检索可以使用较完整语义，保证召回效果。
- 发送给远程 LLM 或远程 embedding 前，必须执行脱敏和上下文压缩。
- 脱敏使用稳定占位符，而不是直接删除信息。
- RAG 远程上下文脱敏默认开启；用户可在高级设置中关闭，但必须明确提示远程模型会收到未脱敏或弱脱敏的 RAG 上下文。

示例：

```text
原文：她说周五在五道口那家店见，顺便聊她妈妈住院的事。
脱敏：对方说周五在 [地点1] 见，顺便聊 [家庭健康事件1]。
```

这样既保留“见面安排 + 家庭健康敏感事件”的关系语义，又避免把具体地点和敏感细节发给远程模型。

关闭远程 RAG 脱敏的含义：

- 本地 RAG 检索和本地 LLM 可继续使用本地内容。
- 远程 LLM 可以接收 RAG `retrieval_context`、共同记忆、历史样本和反馈样本。
- 系统仍应尽量执行最小化上下文和敏感记忆过滤，不发送无关长原文。
- 关闭脱敏属于高级风险选项，需要用户显式确认，并在设置页清楚标注隐私影响。
- 远程 embedding 默认仍关闭；如果用户同时开启远程 embedding 且关闭脱敏，需要再次确认。

## 4. 当前基础

项目已有的可复用基础：

- `messages`、`message_preprocessed`：历史语料和清洗结果。
- `sentiment_cache.embedding_vector`：已有向量能力参考，但建议 RAG 使用独立表。
- `self_profiles` / `contact_profiles`：已有用户画像和联系人画像缓存。
- `realtime_suggestions`：实时建议记录。
- `suggestion_observations`：展示、查看、采纳、改写、实际发送内容等反馈事件。
- `feedback_rule_extractor.py`：已有反馈偏好提取基础。
- `historical_context.py` / `style_constraints.py`：已有历史上下文和风格约束入口。
- `llm_engine.py`：统一 LLM 建议入口，可接入 retrieval context。

## 5. 总体架构

完整 RAG 闭环：

```text
历史消息 / 实时消息 / 建议反馈
  -> 清洗与切块
  -> 隐私识别与脱敏视图生成
  -> 联系人级 RAG 文档库
  -> 本地 embedding 索引
  -> 当前聊天 query 构造
  -> 检索与重排
  -> 记忆分级过滤
  -> retrieval_context 压缩
  -> LLM 关系策略判断 + 话术生成
  -> 用户反馈观察
  -> 反馈样本和偏好规则回写
```

建议生成时的权重顺序：

```text
最近对话 > 当前触发原因 > 关系状态记忆 > 被唤醒共同记忆 > 联系人级表达习惯 > 全局用户风格
```

### 5.1 脱敏层推荐位置

脱敏不建议放在微信导入入口直接改写 `messages.content`。原因：

- 原始聊天记录是用户本地资产，历史分析、时间线、搜索、调试都可能需要原文。
- 过早脱敏会损害本地分析和本地 RAG 召回效果。
- 不同使用场景需要不同脱敏强度，导入时一刀切会很难回退。

推荐新增一个统一的隐私处理层，位置在“消息清洗之后、AI/RAG 派生上下文之前”：

```text
messages / realtime_message_buffer 原文
  -> message_preprocessed 清洗文本
  -> privacy_redactor 识别敏感实体
  -> redacted view / redacted_content
  -> RAG 远程上下文、远程 embedding、画像 prompt、建议 prompt
```

也就是说：

- 本地库保留原文。
- 新增脱敏视图和敏感标记。
- 所有可能出本机的 LLM/embedding 请求统一走脱敏视图。
- 本地分析和本地 embedding 可以按用户隐私模式决定使用原文或脱敏文本。

## 6. 数据层设计

### 6.1 RAG 文档表

```sql
CREATE TABLE IF NOT EXISTS rag_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,
    conversation_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    sender_role TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    metadata_json TEXT,
    source_message_ids TEXT,
    source_ts INTEGER,
    sensitivity_level TEXT DEFAULT 'normal',
    confidence REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_docs_scope
ON rag_documents(account_wxid, conversation_id, doc_type);

CREATE INDEX IF NOT EXISTS idx_rag_docs_source_ts
ON rag_documents(account_wxid, conversation_id, source_ts DESC);
```

### 6.2 RAG 向量表

```sql
CREATE TABLE IF NOT EXISTS rag_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL UNIQUE,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_vector BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
);
```

第一版约定：

- `embedding_provider = local`
- `embedding_model = tingting0514/text2vec-base-chinese`
- `embedding_dim = 384`

如果以后切换模型，不直接覆盖旧向量，而是通过 `embedding_model` 和 `embedding_dim` 区分索引版本，并触发联系人级或全量重建。

### 6.3 检索日志表

```sql
CREATE TABLE IF NOT EXISTS rag_retrieval_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,
    conversation_id INTEGER NOT NULL,
    batch_id TEXT,
    suggestion_id INTEGER,
    trigger_type TEXT,
    intent TEXT,
    query_text TEXT,
    retrieved_document_ids TEXT,
    retrieval_scores_json TEXT,
    injected_context_json TEXT,
    created_at INTEGER NOT NULL
);
```

### 6.4 Embedding 配置

可以复用现有 `settings` 或新增配置键：

- `rag_enabled`: `0/1`
- `rag_embedding_provider`: `local/custom`
- `rag_embedding_model`: 本地模型名或远程模型名
- `rag_embedding_base_url`: 远程 embedding 地址
- `rag_embedding_api_key`: 远程 embedding key
- `rag_allow_remote_embedding`: `0/1`
- `rag_cross_contact_style_enabled`: `0/1`
- `rag_privacy_mode`: `balanced/strict/raw_local`
- `rag_remote_context_redaction`: `0/1`，默认开启；关闭时远程 LLM 可接收未脱敏 RAG 上下文
- `rag_embedding_dim`: 默认 `384`

默认值：

- `rag_enabled = 0`
- `rag_embedding_provider = local`
- `rag_embedding_model = tingting0514/text2vec-base-chinese`
- `rag_embedding_dim = 384`
- `rag_allow_remote_embedding = 0`
- `rag_cross_contact_style_enabled = 0`
- `rag_privacy_mode = balanced`
- `rag_remote_context_redaction = 1`

配置语义：

- `rag_remote_context_redaction = 1`：远程 LLM 可以接收脱敏后的 RAG 上下文。
- `rag_remote_context_redaction = 0`：远程 LLM 可以接收未脱敏或弱脱敏的 RAG 上下文；必须由用户显式开启并显示风险提示。
- 本地 LLM 和本地 embedding 是否使用原文，由 `rag_privacy_mode` 决定，不受远程脱敏开关直接影响。

### 6.5 脱敏与最小化字段

`rag_documents` 中建议区分原始来源、可检索内容和可远程发送内容：

```sql
-- 可作为后续迁移方向，不一定第一版全部落地
ALTER TABLE rag_documents ADD COLUMN redacted_content TEXT;
ALTER TABLE rag_documents ADD COLUMN entity_map_json TEXT;
ALTER TABLE rag_documents ADD COLUMN pii_flags_json TEXT;
```

字段含义：

- `content`：本地检索使用的最小必要文本，仅本机存储。
- `redacted_content`：可发送给远程 LLM/embedding 的脱敏文本。
- `entity_map_json`：会话内稳定占位符映射，例如 `[地点1]`、`[联系人亲属1]`。
- `pii_flags_json`：标记手机号、身份证、银行卡、地址、健康、金钱等敏感类型。

如果用户选择严格模式，可以只生成和保存 `redacted_content` 的 embedding；如果选择平衡模式，本地 embedding 使用 `content`，远程上下文使用 `redacted_content`。

### 6.6 通用隐私实体缓存

脱敏不应只服务 RAG，也应服务后续画像、实时建议、会话总结、反馈规则提取等所有 LLM 调用。建议新增通用表：

```sql
CREATE TABLE IF NOT EXISTS privacy_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,
    conversation_id INTEGER,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    raw_value_hash TEXT NOT NULL,
    placeholder TEXT NOT NULL,
    sensitivity_level TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    confidence REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_redaction_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,
    conversation_id INTEGER,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    redaction_mode TEXT NOT NULL,
    redacted_text TEXT NOT NULL,
    entity_map_json TEXT,
    pii_flags_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(source_table, source_id, redaction_mode)
);
```

用途：

- `privacy_entities` 记录识别到的敏感实体，但不直接保存明文实体值，只保存 hash 和占位符。
- `privacy_redaction_cache` 缓存不同模式下的脱敏文本，避免每次拼 prompt 重复扫描。
- RAG 的 `redacted_content` 可以从该缓存生成，不需要每个模块各自实现脱敏。

## 7. 文档类型

| doc_type               | 内容                           | 来源                        | 主要用途           |
| ---------------------- | ------------------------------ | --------------------------- | ------------------ |
| `relationship_state` | 当前关系阶段、主动模式、边界感 | 历史分析、画像、统计        | 策略判断           |
| `shared_memory`      | 双方共同经历、反复出现的话题   | 历史对话抽取                | 语义唤醒后补充背景 |
| `dialogue_turn`      | 一组连续往返对话片段           | 历史消息切块                | 找相似聊天场景     |
| `self_style_example` | 用户在该对象面前的典型说法     | 本人消息                    | 约束表达风格       |
| `contact_preference` | 对方偏好、雷点、沟通禁忌       | 对方消息、画像              | 避免策略错误       |
| `feedback_example`   | AI 建议与用户实际改写对照      | `suggestion_observations` | 学习修正偏好       |

## 8. 服务层设计

建议新增模块：

- `rag_store.py`：RAG 文档、向量、日志读写。
- `rag_indexer.py`：从历史消息、实时消息、反馈事件构建文档。
- `rag_memory_extractor.py`：抽取共同记忆、关系状态、偏好和雷点。
- `privacy_redactor.py`：通用隐私识别和脱敏服务，供 RAG、画像、实时建议、会话总结、反馈规则共用。
- `rag_retriever.py`：向量召回、关键词召回、过滤、重排。
- `rag_context_builder.py`：将检索结果压缩为 prompt 片段。
- `rag_evaluator.py`：统计采纳率、改写率、忽略率、无关记忆率。

接入点：

- `monitor_service.py`：实时建议前构造当前聊天 query。
- `llm_engine.py`：在 `_build_prompt()` 前接收 `context["retrieval_context"]`。
- `llm_engine.py` / `self_profiler.py` / `contact_profiler.py` / `session_thread_service.py` / `feedback_rule_extractor.py`：所有远程 LLM prompt 发送前统一调用脱敏服务。
- `suggestion_observer.py`：用户反馈后写入 `feedback_example`。
- `feedback_attributor.py`：对建议后的用户行为做归因，避免把下一条铺垫消息误判为采纳或改写。
- 设置页：RAG 开关、索引状态、重建索引、清空索引、远程 embedding 配置。

## 9. 检索与注入策略

### 9.1 Query 构造

query 应由以下内容组合：

- 最近 3-8 条对话，越新权重越高。
- 对方最新消息。
- 当前触发类型，如 `emotion_shift`、`topic_cooling`。
- 用户目标 intent，如 `intimate`、`maintain`、`distance`。
- 手动输入需求。
- 当前联系人和账号约束。

### 9.2 召回策略

第一版建议同时支持：

- 向量召回：找语义相似的共同记忆和对话片段。
- 关键词召回：找明确名字、地点、事件、物品、时间等。
- 结构化召回：默认取最新高置信 `relationship_state` 和沟通模式。

### 9.3 重排策略

重排因子：

- 同账号、同联系人强优先。
- `relationship_state` 和高置信 `contact_preference` 稳定注入。
- 与最近对话语义相似的 `shared_memory` 优先。
- 最近发生且多次出现的共同话题优先。
- 用户采纳或改写过的 `feedback_example` 优先。
- 敏感记忆默认降权或过滤。
- 过旧、低置信、无来源的记忆降权。

### 9.4 Prompt 注入格式

建议新增段落：

```text
【当前关系策略参考】
- 关系状态：...
- 沟通模式：...
- 注意边界：...

【被当前对话唤醒的共同记忆】
- 2026-xx-xx，双方曾聊过 ...（仅当前话题相关时使用）

【这个聊天对象下的表达习惯】
- 我常用的表达：...
- 我通常不会：...

【用户反馈偏好】
- AI 曾建议“...”，我实际改成“...”
```

提示词约束：

- 最近对话优先于所有 RAG 记忆。
- 关系策略优先于表面模仿。
- 共同记忆只在当前话题相关时使用。
- 敏感记忆不能主动提起。
- 不得直接复述大段历史原文。

### 9.5 脱敏对注入的影响

注入 prompt 时按模型位置选择内容：

- 本地 LLM：可使用 `content`，但仍要控制长度和敏感记忆规则。
- 远程 LLM：默认只使用 `redacted_content`。
- 远程 LLM 且 `rag_remote_context_redaction = 0`：允许使用 `content` 或弱脱敏摘要注入 RAG，但必须经过用户显式确认、上下文最小化和日志标记。
- 远程 embedding：默认关闭；开启后只发送 `redacted_content`。

脱敏不应删除所有实体，而应保留稳定结构：

| 信息类型            | 本地检索            | 远程注入                           | 说明           |
| ------------------- | ------------------- | ---------------------------------- | -------------- |
| 昵称/称呼           | 保留                | 可保留低敏称呼                     | 影响聊天风格   |
| 联系人真实姓名      | 保留                | 替换为 `[对方]` 或 `[联系人1]` | 避免身份泄露   |
| 地点                | 保留                | 替换为 `[地点1]`                 | 保留事件结构   |
| 具体日期            | 保留                | 可泛化为 `[近期]`、`[上周]`    | 保留时间远近   |
| 手机/身份证/银行卡  | 不进入 RAG 或强遮罩 | 强遮罩                             | 不应参与建议   |
| 健康/家庭/金钱/争吵 | 标记敏感            | 默认不注入，必要时摘要化           | 防止误用       |
| 共同经历            | 保留摘要            | 脱敏摘要                           | RAG 的核心价值 |

## 10. 反馈归因升级

当前反馈机制如果直接拿“建议后的下一条用户消息”作为实际发送结果，会误判很多真实场景：

- 用户先发一句铺垫，再发真正回复。
- 用户连续发多条短句，合起来才是完整回复。
- 用户先问 AI 继续改写，并没有发给对方。
- 用户转移话题或临时处理别的消息，下一条并不是对本次建议的反馈。
- 对方先插话，导致用户后续回复语境变化。

因此反馈学习不能只看下一条消息，而应该做“归因窗口”。

### 10.1 归因窗口

建议每条 `realtime_suggestions` 进入一个待归因状态：

- 时间窗口：建议生成后 3-10 分钟内的用户消息。
- 会话窗口：同一个 `account_wxid + conversation_id/batch_id`。
- 轮次窗口：直到对方下一轮明显改变话题，或用户连续发送结束。
- 操作窗口：如果用户点击复制、采纳、改写、关闭，应作为强信号。

归因时不要只取第一条用户消息，而是收集候选消息序列。

```text
建议生成
  -> 等待用户行为
  -> 收集候选用户消息序列
  -> 判断是否铺垫/采纳/改写/无关/未使用
  -> 写入 feedback_example 或负反馈
```

### 10.2 多消息聚合

用户真实回复经常是多条连发。应先按时间和发送者聚合：

- 连续本人消息，间隔小于 30-90 秒，合并为一个候选回复。
- 纯表情、语气词、图片占位可以作为辅助信号，但不单独作为最终回复。
- 如果第一条很短且像铺垫，例如“等下”“我想想”“这样吧”“其实”，继续等待下一条。
- 如果用户连续发了 2-5 条短句，应整体与 AI 建议做相似度和意图比较。

### 10.3 反馈分类

归因结果建议分为：

| 类型                            | 含义                         | 是否写入正向样本       |
| ------------------------------- | ---------------------------- | ---------------------- |
| `accepted`                    | 用户直接复制或高度相似发送   | 是                     |
| `rewritten`                   | 用户保留策略但改了措辞       | 是，权重高             |
| `preface_then_reply`          | 用户先铺垫，再发送有效回复   | 是，记录完整序列       |
| `strategy_used_style_changed` | 策略采纳，表达风格明显调整   | 是，重点学习风格差异   |
| `style_used_strategy_changed` | 语气接近建议，但策略变了     | 部分写入，降低策略权重 |
| `ignored`                     | 用户查看后无相关发送         | 否，作为降权信号       |
| `unrelated`                   | 后续消息与建议无关           | 否，不污染样本         |
| `interrupted`                 | 对方插话或场景变化，无法归因 | 否，标记为不可判定     |

### 10.4 判断信号

反馈归因应结合多种信号：

- 文本相似度：用户消息与建议话术是否相似。
- 语义相似度：是否表达了相同意图。
- 策略一致性：是否仍是安抚、转移话题、解释、邀约、降温等同一策略。
- 风格差异：长度、标点、称呼、emoji、语气词是否被用户改写。
- 时间距离：越靠近建议生成，权重越高。
- 用户操作：复制、点击、改写、关闭、重新生成等前端事件。
- 对方插话：如果对方在中间发了新消息，需要重新判断语境。

### 10.5 数据层补充

可以新增归因表，避免直接覆盖原始观察事件：

```sql
CREATE TABLE IF NOT EXISTS suggestion_feedback_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,
    conversation_id INTEGER,
    suggestion_id INTEGER NOT NULL,
    batch_id TEXT,
    attribution_type TEXT NOT NULL,
    candidate_messages_json TEXT,
    final_reply_text TEXT,
    similarity REAL,
    semantic_score REAL,
    strategy_match REAL,
    style_delta_json TEXT,
    confidence REAL DEFAULT 0.0,
    reason TEXT,
    created_at INTEGER NOT NULL
);
```

`suggestion_observations` 继续记录原始事件，`suggestion_feedback_attributions` 负责把原始事件解释成可学习样本。

### 10.6 RAG 使用规则

只有高置信反馈才进入 `feedback_example`：

- `accepted`、`rewritten`、`preface_then_reply` 可作为正向样本。
- `ignored` 只作为建议类型降权，不作为文本样本。
- `unrelated` 和 `interrupted` 不进入 RAG。
- 低置信归因保留日志，但不参与后续建议生成。

## 11. 索引构建与重建策略

第一版采用“联系人级懒加载索引”，不在用户首次开启 RAG 时全量扫描所有联系人。

### 11.1 索引触发

触发索引的时机：

- 用户在某个联系人上首次启用 RAG。
- 某个联系人首次触发实时建议，但该联系人索引不存在。
- 用户在设置页手动点击“重建索引”。
- embedding 模型、向量维度、隐私模式变化，导致已有索引需要重建。

首次触发时只索引当前 `account_wxid + conversation_id`，其他联系人保持未索引状态。

### 11.2 增量更新

导入新消息或实时监听入库后，不同步更新向量索引。第一版使用后台队列：

```text
messages / realtime_message_buffer 入库
  -> 记录 dirty conversation
  -> 后台队列按联系人聚合任务
  -> 批量生成文档和 embedding
  -> 更新索引状态
```

要求：

- 导入和实时监听不等待 embedding 完成。
- 同一联系人短时间内多条消息合并为一个索引任务。
- 后台任务失败不影响原建议链路。
- 索引完成前，建议生成可以使用已有旧索引或无 RAG 降级。

### 11.3 索引状态

建议为每个联系人维护索引状态：

| 状态 | 含义 |
| --- | --- |
| `pending` | 已进入队列，尚未开始 |
| `indexing` | 正在构建或增量更新 |
| `ready` | 当前配置下可用 |
| `stale` | 配置变化或新消息较多，需要重建 |
| `failed` | 最近一次构建失败 |

状态可存入独立表，例如 `rag_index_status`，也可以第一版先放在设置或元数据表中，但必须能按 `account_wxid + conversation_id` 查询。

### 11.4 重建策略

以下变化必须标记索引为 `stale`：

- `rag_embedding_model` 变化。
- `rag_embedding_dim` 变化。
- `rag_privacy_mode` 变化。
- 本地 embedding 模型目录迁移或模型文件变化。
- 用户清空、禁用或重新生成某联系人的记忆。

重建策略：

- 默认按联系人重建，不自动全量重建。
- 用户可以在设置页触发全量重建。
- 新索引成功前，旧索引仍可读，但检索日志需要标记 `index_status = stale`。
- 新索引失败时保留旧索引，状态标记为 `failed` 并记录错误。

## 12. 性能与降级策略

RAG 是实时建议增强层，不是硬依赖。第一版必须保证 RAG 异常时原建议链路可继续工作。

### 12.1 性能预算

单次建议生成中，RAG 检索与上下文构造额外耗时默认控制在 800ms 内。

建议预算拆分：

- 索引状态读取：50ms 内。
- 候选召回：300ms 内。
- 重排与过滤：200ms 内。
- 脱敏与上下文压缩：250ms 内。

超过 800ms 时立即降级：

- 不等待未完成的召回或重排。
- 使用已完成的高置信候选。
- 如果没有可用候选，则走无 RAG 原链路。
- 在 `rag_retrieval_logs` 记录 `timeout = true` 和实际耗时。

### 12.2 模块失败降级

| 失败点 | 降级行为 |
| --- | --- |
| 索引不存在 | 触发后台懒加载，本次走无 RAG 或结构化画像 |
| 索引状态 `indexing` | 使用旧索引；无旧索引则无 RAG |
| 索引状态 `failed` | 跳过 RAG，提示设置页可重试 |
| 本地 embedding 模型缺失 | 回退关键词/结构化关系状态检索，并提示下载模型 |
| 远程 embedding 失败 | 跳过远程索引更新，不阻塞建议 |
| 检索结果为空 | 走原建议链路 |
| RAG 上下文压缩失败 | 丢弃 RAG 上下文，保留最近对话 |

### 12.3 脱敏异常降级

正常路径：

- 远程 LLM/embedding 使用 `redacted_content` 或 `privacy_redaction_cache`。
- 已标记为 `sensitive` 的记忆默认不进入远程上下文。
- 如果用户关闭 `rag_remote_context_redaction`，远程 LLM 可使用未脱敏或弱脱敏 RAG 上下文；日志必须记录 `redaction_disabled = true`。

如果脱敏服务异常，但仍需要远程生成，允许发送“强规则遮罩后的压缩 RAG”，边界如下：

- 只能发送已压缩摘要，不发送长原文。
- 必须经过现场强规则遮罩。
- 不包含已标记为 `sensitive` 的记忆。
- 不包含手机号、证件号、银行卡、详细地址、API key、密钥等强敏字段。
- 检索日志必须记录 `redaction_fallback = true`。

如果现场强规则遮罩也失败，则阻断远程请求，回退本地模型、模板建议或无 RAG 建议。

现场强规则遮罩只是兜底，不替代 `privacy_redactor.py` 和脱敏缓存。

## 13. 记忆生命周期

共同记忆不应永久等权使用，也不应简单按固定天数删除。第一版采用软降权。

### 13.1 软降权规则

记忆保留但降低检索和注入权重：

- 时间越久，权重越低。
- 长期未命中，权重降低。
- 命中后用户没有采纳相关建议，权重降低。
- 与新记忆冲突，旧记忆降权。
- 被用户手动禁用，权重归零且不再进入候选。

### 13.2 冲突处理

当新记忆与旧记忆冲突：

- 新记忆优先。
- 旧记忆标记为 `superseded`。
- `superseded` 记忆不主动注入，只保留审计和历史追溯。
- 冲突无法判断时，两条都保留，但降低注入置信度，并要求当前对话强相关才可使用。

### 13.3 敏感与删除

- 敏感记忆默认不主动注入，只在当前话题强相关时进入候选。
- 用户删除或禁用的记忆必须永久排除，除非用户显式重新生成索引。
- 清空某联系人 RAG 数据时，删除该联系人的文档、向量、记忆状态和反馈样本索引，不删除原始聊天记录。

## 14. 效果评估方法

第一版以固定人工样例集为主要评估方式，不依赖 LLM 自动评分作为验收依据。

### 14.1 样例集

建立匿名/脱敏样例集，覆盖：

- 冷场续聊。
- 轻量安抚。
- 邀约。
- 解释和道歉。
- 争执降温。
- 共同记忆被当前话题唤醒。
- 敏感记忆不应注入。
- 用户先铺垫再正式回复。

### 14.2 对比方式

每次 RAG、prompt、脱敏或反馈归因改动后，对同一批样例生成两组输出：

- 无 RAG 原链路。
- 开启 RAG 链路。

人工评估维度：

- 关系策略是否合适。
- 是否误用或强行引用记忆。
- 是否符合这个聊天对象下的关系方式。
- 是否比无 RAG 更贴合上下文。
- 是否泄露或主动提起敏感信息。
- 是否保持用户表达风格但不过度模仿。

### 14.3 通过标准

第一版目标：

- RAG 输出在关系策略上不劣于无 RAG。
- 无强敏泄露。
- 无明显身份混淆。
- 共同记忆只在相关样例中被使用。
- 反馈归因样例中不把铺垫误判为最终改写。

## 15. 第一版实施范围

第一版直接做完整闭环，但控制每个模块复杂度。

必须包含：

- 联系人级 RAG 文档表和向量表。
- 本地 embedding 索引。
- 默认 embedding 模型固定为 `tingting0514/text2vec-base-chinese`，先不引入新模型。
- 远程 embedding 可配置但默认关闭。
- 历史消息切块为 `dialogue_turn`。
- 抽取基础 `relationship_state`。
- 抽取基础 `shared_memory`。
- 生成建议前检索、重排、注入。
- 建议反馈先经过归因窗口，再回写为 `feedback_example`。
- 增加基础脱敏：远程 LLM/embedding 前执行敏感信息替换。
- RAG 远程上下文脱敏默认开启；关闭时远程 LLM 可接收未脱敏 RAG，但必须显式确认和记录。
- 增加联系人级懒加载索引、后台增量队列和索引状态。
- 增加 800ms RAG 超时降级。
- 增加记忆软降权和冲突标记。
- 增加固定人工样例集。
- 检索日志落库。
- RAG 总开关。

可以延后：

- 复杂前端记忆编辑器。
- 多模型重排。
- 大规模自动评测面板。
- 跨联系人全局风格融合。
- 高级敏感信息分类器。

## 16. 实施阶段

### Phase 1：完整链路骨架

目标：打通索引、检索、注入、生成、反馈回写。

任务：

- 新增 RAG 表和配置项。
- 实现本地 embedding 生成和向量存储。
- 增加联系人级索引状态：`pending / indexing / ready / stale / failed`。
- 增加后台增量索引队列，不阻塞导入和监听。
- 从 `messages` 构建 `dialogue_turn`、`self_style_example`。
- 从 `suggestion_observations` 构建 `feedback_example`。
- 增加基础反馈归因：不再默认取下一条消息，而是聚合短时间内的本人消息序列。
- 增加基础 `privacy_redactor.py`：手机号、身份证、银行卡、详细地址、API key 等强敏信息默认遮罩。
- 增加 RAG 800ms 超时降级。
- 增加基础人工样例集。
- 接入 `LLMSuggestionEngine` prompt。
- 写入 `rag_retrieval_logs`。

验收：

- 开启 RAG 后，同一联系人建议能检索到该联系人的历史关系片段。
- 关闭 RAG 后完全回到原链路。
- 每次建议可以追溯使用了哪些文档。
- 用户先铺垫再回复时，不把第一条铺垫误写成改写样本。
- 远程 LLM 上下文不包含明显强敏信息。
- 关闭 RAG 远程上下文脱敏后，远程 LLM 可接收 RAG 检索记忆，但检索日志必须标记 `redaction_disabled = true`。
- 索引不存在、索引失败、RAG 超时都不会阻断建议生成。

### Phase 2：共同记忆与关系状态

目标：让系统理解“我和这个人是什么关系、经历过什么”。

任务：

- 从历史对话抽取 `relationship_state`。
- 从高频话题和明确事实抽取 `shared_memory`。
- 为记忆增加主体、客体、时间、置信度、敏感级别。
- 建立记忆唤醒规则。
- 增加记忆软降权。
- 增加冲突记忆 `superseded` 标记。

验收：

- 关系状态可以默认影响策略。
- 共同经历必须由当前话题唤醒后才进入 prompt。
- 不出现明显身份混淆。
- 旧记忆和冲突记忆不会压过新的高置信记忆。

### Phase 3：重排与安全过滤

目标：减少无关记忆、敏感记忆和噪音片段。

任务：

- 增加混合召回和重排分。
- 过滤系统消息、无效短句、纯表情、红包转账等。
- 增加敏感词和敏感类型识别。
- 增加稳定占位符脱敏，减少脱敏后语义损失。
- 增加脱敏异常时的现场强规则遮罩降级。
- 对低置信、过旧、不相关记忆降权。

验收：

- 检索结果中无关片段明显减少。
- 敏感记忆默认不进入 prompt。
- 脱敏后的远程上下文仍保留足够关系语义。
- 生成延迟仍在可接受范围。
- 脱敏服务异常时不会直接发送未处理原文。

### Phase 4：反馈学习

目标：让用户实际行为持续修正建议系统。

任务：

- 将采纳、改写、忽略映射到 RAG 样本权重。
- 从“AI 建议 -> 用户实际发送”中提取表达偏好。
- 引入 `suggestion_feedback_attributions`，区分采纳、改写、铺垫后回复、无关、被打断。
- 同联系人相似场景优先召回历史反馈样本。
- 对忽略率高的触发类型降权。

验收：

- 多次改写后，后续建议更接近用户实际会发的内容。
- 用户忽略较多的建议类型减少出现。
- 反馈样本能在检索日志中看到贡献。
- 低置信和无关反馈不会污染 RAG 样本。

### Phase 5：前端控制与可解释

目标：让用户能控制 RAG 数据和理解建议依据。

任务：

- 设置页展示 RAG 状态、索引数量、更新时间、占用空间。
- 支持重建索引、清空索引、暂停索引。
- 支持联系人级启用/禁用 RAG。
- 建议卡片展示简短依据：关系状态、共同记忆、表达习惯、反馈偏好。
- 远程 embedding 开启时展示隐私提示。

验收：

- 用户能一键关闭 RAG。
- 用户能清除某个联系人的 RAG 数据。
- 建议依据可理解，但不泄露长篇历史内容。

## 17. 质量指标

| 指标           | 说明                                               | 目标     |
| -------------- | -------------------------------------------------- | -------- |
| 采纳率         | 用户直接使用建议的比例                             | 上升     |
| 改写距离       | 用户实际发送与建议的差异                           | 下降     |
| 忽略率         | 展示后关闭或无操作比例                             | 下降     |
| 关系策略命中率 | 用户认为建议适合当前关系的比例                     | 上升     |
| 无关记忆率     | 注入或引用了不相关记忆的比例                       | 接近 0   |
| 敏感误用率     | 主动提起敏感记忆的比例                             | 0        |
| 生成耗时       | 触发到建议可见时间                                 | 可接受   |
| 远程上下文大小 | 发送给 LLM 的上下文长度                            | 最小化   |
| 反馈误归因率   | 把铺垫、无关消息误判为采纳或改写的比例             | 持续下降 |
| 反馈不可判定率 | 因插话、场景变化导致无法归因的比例                 | 可解释   |
| 脱敏语义保留率 | 脱敏后仍能判断关系、事件和策略的比例               | 保持可用 |
| 强敏泄露率     | 远程上下文包含手机号、证件、银行卡等强敏信息的比例 | 0        |
| RAG 超时率     | RAG 检索与上下文构造超过 800ms 的比例              | 持续下降 |
| 索引失败率     | 联系人级索引任务进入 `failed` 的比例               | 可追踪   |
| stale 索引比例 | 使用过期索引参与建议的比例                         | 可控下降 |
| 记忆冲突命中率 | 检索命中 `superseded` 或冲突记忆的比例             | 低       |
| 脱敏降级触发率 | 触发现场强规则遮罩兜底的比例                       | 低       |
| 样例集通过率   | 固定人工样例集中通过验收的比例                     | 上升     |

## 18. 风险与对策

| 风险                    | 表现                               | 对策                                          |
| ----------------------- | ---------------------------------- | --------------------------------------------- |
| 过度翻旧账              | 当前没提到却引用历史共同经历       | 共同记忆必须语义唤醒                          |
| 策略被风格覆盖          | 话像用户但不利于当前关系           | 关系策略优先于表达模仿                        |
| 身份混淆                | 把对方经历说成用户经历             | 记忆结构化记录主体和客体                      |
| 敏感信息误用            | 主动提及隐私、争吵、金钱等         | 敏感记忆默认不注入                            |
| 远程 embedding 隐私风险 | 用户语料发到第三方                 | 默认关闭，用户显式配置和确认                  |
| 过度脱敏                | RAG 找得到片段但模型看不懂关系语境 | 稳定占位符、分级脱敏、本地检索与远程注入分离  |
| 脱敏不足                | 远程上下文暴露个人信息             | 远程前强制脱敏、强敏字段不入 prompt、日志审计 |
| 关闭脱敏带来隐私风险    | 用户关闭脱敏后远程收到原始 RAG     | 默认开启脱敏，关闭需显式确认、最小化上下文并记录日志 |
| 检索噪音                | 找到无关短句或旧片段               | 混合召回、重排、阈值过滤                      |
| 反馈误归因              | 用户铺垫或转移话题被当成采纳       | 归因窗口、多消息聚合、低置信不入库            |
| 实时变慢                | 检索增加延迟                       | 预构建索引、限制召回数量、异步更新            |
| RAG 超时                | 检索或压缩拖慢实时建议             | 800ms 预算，到点降级                          |
| 索引失败                | 某联系人无法生成向量索引           | 状态标记 failed，保留旧索引或无 RAG 降级      |
| 旧记忆污染              | 过期事实影响当前策略               | 软降权、冲突标记、当前话题强相关才注入        |
| 脱敏异常降级过宽        | 兜底路径发送过多历史内容           | 只发压缩摘要，现场强遮罩，过滤 sensitive 记忆 |
| 数据膨胀                | 向量库占用过大                     | 只索引有效文本，支持联系人级清理              |

## 19. 推荐落地顺序

优先做：

1. RAG 表结构和本地 embedding。
2. 联系人级懒加载索引状态和后台增量队列。
3. 联系人级 `dialogue_turn` 与 `self_style_example` 索引。
4. `relationship_state` 的基础抽取。
5. `LLMSuggestionEngine` 注入 `retrieval_context`。
6. 800ms 超时降级和检索日志。
7. 基础反馈归因窗口。
8. 基础远程上下文脱敏和强遮罩兜底。
9. `suggestion_observations` 经归因后回写 `feedback_example`。
10. RAG 开关和基础人工样例集。
11. 设置页明确“关闭 RAG 脱敏会把未脱敏 RAG 上下文发送给远程模型”。

随后做：

1. `shared_memory` 抽取和唤醒规则。
2. 记忆软降权、冲突标记和敏感记忆过滤。
3. 通用脱敏缓存覆盖画像、会话总结、反馈规则等所有 LLM prompt。
4. 混合召回和重排。
5. 前端状态展示、联系人级控制和索引重建入口。

## 20. 第一版验收标准

第一版完成时，应满足：

- RAG 可以按联系人隔离启用。
- 本地 embedding 可用，远程 embedding 默认关闭。
- 远程上下文默认使用脱敏版本，强敏信息不会进入远程请求。
- RAG 远程上下文脱敏默认开启；关闭后远程 LLM 可以接收未脱敏 RAG 上下文，但必须由用户显式开启并记录日志。
- 联系人索引采用懒加载，导入和监听不会等待 embedding。
- 索引状态可查询，失败和 stale 状态不会阻断建议生成。
- 单次建议中 RAG 额外耗时超过 800ms 时自动降级。
- 生成建议时能注入当前联系人的关系状态、相似对话片段、表达习惯和反馈样本。
- 共同记忆不会无条件进入 prompt。
- 旧记忆会软降权，冲突旧记忆会标记为 `superseded`。
- 建议结果仍以当前最近对话为主，不被历史记忆带偏。
- 用户反馈能经过归因后进入后续检索闭环。
- 用户先铺垫再回复、对方中途插话、用户转移话题时，不会被粗暴当成采纳或改写。
- 脱敏异常时只能发送经过现场强规则遮罩的压缩摘要；遮罩失败则阻断远程请求。
- 固定人工样例集可用于对比无 RAG 和有 RAG 输出。
- 任意一次建议都能在日志中追溯检索来源。
