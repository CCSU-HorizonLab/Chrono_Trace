# Feature Specification: Conversation Affinity Analysis System

**Feature Branch**: `002-affinity-analysis`
**Created**: 2026-01-08
**Status**: Draft
**Input**: User description: "实现历史记录好感度分析系统,包括4个核心评分维度:情感共振率30%、聊天积极度30%、态度倾向20%、喜好维度20%。需要集成SnowNLP情感分析、sentence-transformers句向量生成、构建交互对、关键词库、支持用户自定义配置参数"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Emotional Resonance Analysis (Priority: P1)

用户想要量化与聊天对象之间的情感共鸣程度,了解双方在情绪上的同步性和相互理解程度。系统能够分析双向情感响应、极性一致性、情绪强度匹配、共情意图和负面情绪化解等5个子维度,生成综合的情感共振率评分(0-100分),帮助用户判断关系的情感质量。

**Why this priority**: 情感共振是衡量关系深度和亲密度的核心指标,直接影响用户对关系状态的理解。这是好感度分析中最有价值的维度,优先级最高。

**Independent Test**: 可以通过包含已知情感标签和交互模式的测试数据验证。给定一组带有情感极性和强度的对话,系统能够正确计算所有5个子维度指标,并输出综合评分。预期输出应包含每个子维度的分数和加权总分。

**Acceptance Scenarios**:

1. **Given** 用户导入了包含1000条消息的对话记录,系统已完成情感分析和交互对构建,**When** 系统计算情感共振率,**Then** 输出5个子维度分数(双向积极情感响应率、情感极性一致性、情绪强度匹配度、共情意图识别率、负面情绪协同化解率)和加权总分(权重分别为20%、15%、10%、30%、25%)
2. **Given** 对方在用户发送消极消息后回复了积极的安抚话语,**When** 系统计算负面情绪协同化解率,**Then** 该交互对应被识别为一次成功化解,化解率指标上升
3. **Given** 双方在连续10个交互对中都表现出相同情感极性(都积极或都消极),**When** 系统计算情感极性一致性,**Then** 同极性占比应为100%,并计算这些对的语义相似度均值
4. **Given** 用户查看情感共振率报告,**When** 系统展示结果,**Then** 显示总分(0-100分)、5个子维度的分数和百分比、以及基于分数的文字解读(如"情感共振强烈,双方情绪高度同步")

---

### User Story 2 - Chat Positivity Analysis (Priority: P1)

用户想要评估聊天对象的积极程度和投入度,了解对方的主动性、回复速度、内容质量和话题延续意愿。系统能够分析日均消息数、回复及时率、消息长度、话题延续性、主动发起率等5个方面,生成聊天积极度评分(0-100分),帮助用户判断对方对对话的重视程度。

**Why this priority**: 聊天积极度直接反映对方的投入意愿和互动热情,是评估关系活跃度的重要指标。与情感共振率同等重要,共同构成好感度分析的核心(各占30%权重)。

**Independent Test**: 可以通过包含已知时间戳和消息长度的测试数据验证。给定一组消息及其发送时间,系统能够正确计算所有5个子维度,并考虑用户设定的"规定时效"参数。预期输出应包含及时回复率、主动发起率、话题延续性得分等指标。

**Acceptance Scenarios**:

1. **Given** 用户设定规定时效为1小时,导入了包含500个交互对的对话,**When** 系统计算回复及时率,**Then** 统计在1小时内回复的交互对数,计算及时回复率(及时回复对数/总交互对数*100%)
2. **Given** 两个交互对之间相隔2小时,**When** 系统判断是否为主动发起,**Then** 计算这两个交互对的句向量余弦相似度,如果<0.4则判定为新话题的主动发起,次数+1
3. **Given** 用户设定时窗为7天,**When** 系统计算话题延续性得分,**Then** 将所有会话按7天窗口分组,计算每个窗口内会话的平均延续性得分,最终得出总体得分
4. **Given** 对方在100个交互对中主动发起了60个,**When** 系统计算主动发起率,**Then** 主动发起率应为60%,并解读为"对方更主动发起话题"
5. **Given** 系统完成所有计算,**When** 用户查看聊天积极度报告,**Then** 显示总分(0-100分)、5个子维度的分数、以及基于分数的文字解读(如"对方积极度高,回复及时且主动")

---

### User Story 3 - Attitude Tendency Analysis (Priority: P2)

用户想要了解聊天对象的语言态度和表达习惯,识别对方的情感倾向、亲密程度和互动方式。系统能够分析正负面词汇频次、表情包/语音/视频使用、专属称呼、隐私分享、节假日祝福等5个维度,生成态度倾向评分(0-100分),帮助用户判断对方的态度性质(友好、疏远、亲密等)。

**Why this priority**: 态度倾向提供了关于对方性格和关系性质的额外洞察,但相比情感共振和积极度,它对关系判断的参考价值略低,因此优先级为P2,权重20%。

**Independent Test**: 可以通过包含特定关键词和消息类型的测试数据验证。给定一组包含正面词汇("哈哈""谢谢")、表情包、专属称呼的消息,系统能够正确统计各类指标并计算综合评分。

**Acceptance Scenarios**:

1. **Given** 对话中出现100次"哈哈""谢谢""想你"等正面词汇,**When** 系统计算正面词汇频次,**Then** 统计包含正面词汇的消息数,计算正面词汇出现频次(正面词汇消息数/总消息数)
2. **Given** 对话中出现50次表情包、30次语音、20次视频通话,**When** 系统计算多媒体使用占比,**Then** 按权重0.3:0.2:0.5计算多媒体使用得分,并除以总消息数
3. **Given** 对方在消息中使用"宝贝""亲爱的"等专属称呼,**When** 系统统计专属称呼频率,**Then** 统计包含专属称呼的消息数,计算专属称呼使用频率
4. **Given** 双方在对话中分享"秘密""私密"等关键词,**When** 系统计算隐私分享比例,**Then** 统计包含隐私分享关键词的消息数,计算隐私内容分享比例
5. **Given** 系统完成态度分析,**When** 用户查看态度倾向报告,**Then** 显示总分(0-100分)、5个子维度的分数、以及态度性质解读(如"态度友好,表达亲密")

---

### User Story 4 - Preference Compatibility Analysis (Priority: P2)

用户想要了解与聊天对象的兴趣匹配度,判断双方在喜好话题上的契合程度。系统能够分析话题提及频率和喜好话题延续性,生成喜好维度评分(0-100分),帮助用户评估双方的共同兴趣和话题契合度。

**Why this priority**: 喜好维度提供了关于兴趣匹配度的有价值信息,但依赖用户提供喜好关键词,且对关系判断的影响相对间接,因此优先级为P2,权重20%。

**Independent Test**: 可以通过用户提供喜好关键词列表(如"篮球""电影")和包含这些关键词的测试数据验证。给定一组提及喜好的会话,系统能够正确统计提及频率和计算话题延续性得分。

**Acceptance Scenarios**:

1. **Given** 用户提供喜好关键词["篮球","电影","旅行"],对话中有100个会话,**When** 系统计算话题提及频率,**Then** 统计包含任一喜好关键词的会话次数(假设30个),计算话题提及频率(30/100=30%)
2. **Given** 有30个会话提及了喜好,**When** 系统计算喜好话题延续性得分,**Then** 对这30个会话分别计算内部延续性得分,取平均值作为喜好话题延续性得分
3. **Given** 系统完成喜好分析,**When** 用户查看喜好维度报告,**Then** 显示总分(0-100分)、话题提及频率(40%权重)、喜好话题延续性得分(60%权重)、以及兴趣匹配度解读(如"兴趣高度契合,常聊共同喜好")

---

### Edge Cases

- **交互对构建边界**: 如果连续两条消息间隔恰好为5分钟,系统应将其合并为一个发言单位
- **空会话处理**: 如果会话中只有一条消息(无法形成交互对),系统应在交互对相关计算中排除该会话
- **无交互对场景**: 如果整个对话没有形成任何交互对,系统应将基于交互对的指标设为0,并在前端显示"无数据"
- **情感分析失败**: 如果SnowNLP无法分析某条消息的情感,系统应将其标记为中性(极性=0,强度=0),并记录日志
- **句向量生成失败**: 如果sentence-transformers无法生成某条消息的句向量,系统应使用零向量,并在相似度计算中降低该条消息的权重
- **关键词库缺失**: 如果用户未提供某类关键词(如共情关键词、喜好关键词),系统应跳过相关计算,在总分中按比例重新分配权重
- **时效参数极端值**: 如果用户设定的规定时效过短(如1秒)或过长(如30天),系统应提供默认值建议(5分钟-1天),并允许用户确认
- **相似度阈值边界**: 如果语义相似度恰好等于阈值(如0.4),系统应将其判定为同一话题
- **除零错误处理**: 在计算比例时,如果分母为0(如总会话数为0),系统应返回0而不报错
- **大数据集性能**: 如果对话包含超过10万条消息,系统应采用分批处理和缓存策略,确保分析在合理时间内完成(不超过5分钟)

## Requirements *(mandatory)*

### Functional Requirements

**预处理阶段 (Preprocessing Layer)**:

*目标：一次遍历收集所有统计常量，避免后续维度重复计算，确保 O(N) 复杂度*

**Phase 0: 配置准备 (Configuration Setup)**:

- **FR-000**: System MUST allow users to provide contact labels (e.g., "colleague", "close friend") which influence session splitting thresholds
- **FR-000**: System MUST prepare keyword libraries before preprocessing: positive words, negative words, exclusive nicknames, privacy sharing keywords, holiday greetings, empathy keywords, soothing keywords, preference keywords
- **FR-000**: System MUST support user customization of keyword libraries after initialization, allowing dynamic extension without reprocessing

**Phase 1: 数据准备 (Data Preparation)**:

- **FR-001**: System MUST sort all messages by timestamp for each conversation in ascending order
- **FR-002**: System MUST analyze sentiment for each message in batches (32 messages/batch), generating three outputs: polarity (-1 for negative, 0 for neutral, 1 for positive), intensity score (from -1 to 1), and sentence embedding vector

**Phase 2: 会话划分 (Session Splitting)**:

- **FR-003**: System MUST split conversations into sessions based on semantic similarity valleys using sliding window algorithm, where similarity below threshold marks topic boundary
- **FR-004**: System MUST support user-configurable sliding window size (number of messages) and similarity threshold for session splitting
- **FR-005**: System MUST combine semantic similarity with time interval fallback: if time gap > 30 minutes, force split regardless of similarity
- **FR-006**: System MUST record session initiator as the sender of the first message in each session

**Phase 3: 交互对构建与统计收集 (Interaction Pair Construction & Statistics Collection)**:

- **FR-007**: System MUST merge consecutive messages from same person into "speech units" if time gap < 5 minutes
- **FR-008**: System MUST record message IDs contained in each speech unit for traceability
- **FR-009**: System MUST construct "interaction pairs" from one person's speech unit to the other person's next speech unit (bidirectional)
- **FR-010**: System MUST collect all statistics in a single pass through all interaction pairs and sessions (O(N) complexity)

**基础常量统计 (Basic Statistics)**:

- **FR-011**: System MUST pre-calculate message statistics: total_message_count, user_message_count, other_message_count, total_character_count, avg_message_length, long_text_message_count (>100 chars)
- **FR-012**: System MUST pre-calculate sentiment statistics: total_positive_count (polarity=1), total_negative_count (polarity=-1), total_neutral_count (polarity=0)
- **FR-013**: System MUST pre-calculate time statistics: conversation_duration_days (date difference between first and last message)
- **FR-014**: System MUST pre-calculate session statistics: total_session_count, user_initiated_session_count, other_initiated_session_count (from Phase 2 session initiators)
- **FR-015**: System MUST pre-calculate interaction pair statistics: total_pair_count, user_initiated_pair_count, other_initiated_pair_count, same_polarity_pair_count, positive_positive_pair_count, negative_initiated_by_user_count
- **FR-016**: System MUST calculate resolved_negative_pair_count by checking if response has positive polarity AND contains soothing keywords

**态度倾向统计 (Attitude Tendency Statistics)**:

- **FR-017**: System MUST count messages containing emoji in single pass through interaction pairs
- **FR-018**: System MUST count voice messages and video call messages in single pass through interaction pairs
- **FR-019**: System MUST count messages containing exclusive nicknames in single pass through interaction pairs
- **FR-020**: System MUST count messages containing privacy sharing keywords in single pass through interaction pairs
- **FR-021**: System MUST count messages containing holiday greetings and track unique holidays sent (deduplicated) in single pass
- **FR-022**: System MUST mark sessions that mention preference keywords at session level (not message level) during single pass

**Phase 4: 后处理统计 (Post-Processing)**:

- **FR-023**: System MUST analyze high-response time periods based on timestamp distribution of interaction pairs after main preprocessing completes
- **FR-024**: System MUST cache all preprocessing results to database tables: sentiment_cache, speech_units, interaction_pairs, and aggregated statistics tables
- **FR-025**: System MUST provide unified interface for four dimensions to query preprocessed statistics without re-computation

**情感共振率维度 (30%权重)**:

- **FR-026**: System MUST calculate bidirectional positive emotion response rate = (number of positive-positive interaction pairs / total positive messages) × 100%
- **FR-027**: System MUST calculate emotion polarity consistency score = (proportion of same-polarity interaction pairs) × (average semantic similarity of same-polarity pairs)
- **FR-028**: System MUST calculate emotion intensity matching degree = reciprocal of average absolute difference in intensity scores between paired messages, using formula 1/(mean_abs_diff + 0.1) and clamping to 0-1 range with tanh if needed
- **FR-029**: System MUST calculate empathy intent recognition rate = (messages containing empathy keywords / total messages) × 100%
- **FR-030**: System MUST calculate negative emotion collaborative resolution rate = (empathetic responses / negative-initiated pairs) × 100%, where empathetic response requires positive polarity AND containing soothing keywords
- **FR-031**: System MUST generate weighted composite score for emotional resonance with weights: bidirectional positive response (20%), polarity consistency (15%), intensity matching (10%), empathy recognition (30%), negative resolution (25%)

**聊天积极度维度 (30%权重)**:

- **FR-032**: System MUST calculate daily average message count = (total messages / conversation duration in days)
- **FR-033**: System MUST calculate reply timeliness rate = (interaction pairs with response time ≤ user-specified threshold / total interaction pairs) × 100%
- **FR-034**: System MUST support user-configurable reply timeliness threshold (e.g., 5 minutes, 1 hour, 1 day)
- **FR-035**: System MUST calculate average message length in characters
- **FR-036**: System MUST calculate long text ratio = (messages with >100 characters / total messages) × 100%
- **FR-037**: System MUST calculate topic continuity score based on semantic similarity, averaging scores of sessions within user-specified time window
- **FR-038**: System MUST support user-configurable time window for topic continuity (minimum 1 day)
- **FR-039**: System MUST calculate active initiation rate using session initiators from preprocessing: (other_initiated_session_count / total_session_count) × 100%
- **FR-040**: System MUST generate weighted composite score for chat positivity with weights: daily messages (10%), reply timeliness (20%), avg length (10%), long text ratio (15%), topic continuity (20%), active initiation (25%)

**态度倾向维度 (20%权重)**:

- **FR-041**: System MUST calculate positive word frequency using preprocessed statistics: (messages containing positive words / total messages) × 100%
- **FR-042**: System MUST calculate negative word frequency using preprocessed statistics: (messages containing negative words / total messages) × 100% and deduct from score (reverse scoring with -20% weight)
- **FR-043**: System MUST calculate multimedia usage ratio using preprocessed statistics: (emoji_message_count + voice_message_count + video_message_count) / total messages × 100%, with internal weights 0.3:0.2:0.5 for emoji:voice:video
- **FR-044**: System MUST calculate exclusive nickname frequency using preprocessed statistics: (nickname_message_count / total messages) × 100%
- **FR-045**: System MUST calculate privacy sharing ratio using preprocessed statistics: (privacy_message_count / total messages) × 100%
- **FR-046**: System MUST calculate holiday greeting frequency using optimized formula: (holidays_sent_count / total_holiday_count) × 100%, where holidays_sent_count is unique holidays sent (deduplicated) and total_holiday_count is total number of holidays in calendar
- **FR-047**: System MUST generate weighted composite score for attitude tendency with weights: positive words (25%), negative words (-20%), multimedia (10%), nickname (25%), privacy (20%), holiday (10%)

**喜好维度 (20%权重)**:

- **FR-048**: System MUST allow users to input custom preference keywords (e.g., hobbies, interests)
- **FR-049**: System MUST calculate topic mention frequency using preprocessed statistics: (preference_session_count / total_session_count) × 100%
- **FR-050**: System MUST calculate preference topic continuity score = average of internal continuity scores for all sessions mentioning preferences
- **FR-051**: System MUST generate weighted composite score for preference compatibility with weights: topic mention frequency (40%), preference topic continuity (60%)

**综合评分与配置**:

- **FR-052**: System MUST calculate overall affinity score = (emotional resonance × 0.3) + (chat positivity × 0.3) + (attitude tendency × 0.2) + (preference compatibility × 0.2)
- **FR-053**: System MUST allow users to customize dimension weights (default: 30%, 30%, 20%, 20%)
- **FR-054**: System MUST allow users to configure: reply timeliness threshold, topic continuity time window, similarity threshold for session splitting, sliding window size
- **FR-055**: System MUST allow users to customize keyword libraries: positive words, negative words, empathy words, soothing words, privacy keywords, holiday greetings
- **FR-056**: System MUST provide text interpretation for scores (e.g., "Strong emotional resonance, highly synchronized emotions" for scores >80)
- **FR-057**: System MUST support re-analysis when configuration or keywords change, invalidating cached preprocessing results

### Key Entities

- **Conversation**: Represents a complete chat history with one contact, contains messages ordered by timestamp
- **Message**: Individual chat message with attributes: timestamp, sender (user/other), content, sentiment polarity (-1/0/1), sentiment intensity (-1 to 1), sentence embedding vector, character count
- **Session**: Topic-based conversation segment split by semantic similarity valleys, has start time, end time, message count
- **Speech Unit**: Group of consecutive messages from same person with <5 minute gaps between them
- **Interaction Pair**: Basic analysis unit from one person's speech unit to other person's next speech unit, has sender, receiver, messages, time gap, semantic similarity
- **Sentiment Analysis Result**: Contains polarity (positive/negative/neutral), intensity score, sentence embedding vector for each message
- **Keyword Library**: User-configurable collections of words for different categories: positive, negative, empathy, soothing, privacy, holiday greetings
- **Affinity Score**: Composite score for each dimension (emotional resonance, chat positivity, attitude, preference) and overall affinity, all in 0-100 range

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can view complete affinity analysis for conversations with up to 100,000 messages within 5 minutes of processing time
- **SC-002**: Sentiment analysis achieves 85%+ accuracy on manually labeled test messages (polarity classification)
- **SC-003**: Session splitting based on semantic similarity achieves 90%+ accuracy on test conversations with manually labeled topic boundaries
- **SC-004**: Interaction pair construction correctly identifies speech units and pairs in 100% of test cases (verifiable via manual inspection)
- **SC-005**: All four dimension scores (emotional resonance, chat positivity, attitude, preference) calculate correctly with verified test data, achieving 95%+ accuracy on expected scores
- **SC-006**: Overall affinity score calculates as weighted sum of four dimensions using correct formula (30%, 30%, 20%, 20%) in 100% of test cases
- **SC-007**: Users can customize all configuration parameters (timeliness threshold, time window, similarity threshold, weights) and see results update within 30 seconds after re-analysis
- **SC-008**: Keyword libraries support user customization (add/remove words) and correctly affect analysis results (verified via controlled tests)
- **SC-009**: System handles edge cases (empty conversations, single-message sessions, zero interaction pairs) without crashes and displays appropriate "no data" messages
- **SC-010**: Analysis results can be exported or displayed in the UI within 3 seconds after processing completes
- **SC-011**: Text interpretations for scores provide meaningful insights to users, with 90%+ user satisfaction rating on interpretability
- **SC-012**: Re-analysis after configuration changes invalidates old cache and recalculates all affected metrics within 3 minutes for 50,000 messages

## Assumptions

- Preprocessing service already exists and provides cleaned message data with character counts (from feature extraction module 001)
- Message timestamps are accurate and sorted in ascending order
- "User" refers to the application user (juitar/ting), "other person" refers to the contact being analyzed
- 5-minute threshold for speech unit merging is based on industry best practices and is configurable
- 0.4 similarity threshold for initiation determination is default value based on testing and is user-configurable
- SnowNLP provides acceptable sentiment analysis accuracy for Chinese messages; if accuracy is insufficient, consider alternative models
- sentence-transformers model (e.g., paraphrase-multilingual-MiniLM-L12-v2) provides adequate semantic similarity for Chinese text
- Keyword libraries start with default values but require user customization for optimal accuracy
- Holiday greetings detection uses keyword matching; calendar-based detection is future enhancement
- Emotion intensity score from SnowNLP (0-1 range) is mapped to -1 to 1 scale by multiplying by 2 and subtracting 1
- Session splitting uses combined approach: semantic similarity valleys + time gap fallback (if gap > 30 minutes, force split regardless of similarity)
- Affinity analysis is performed on-demand (not real-time) when user requests analysis for a contact
- System runs locally on user's machine; no data is uploaded to external services except optional LLM API for suggestions

## Out of Scope

- Real-time affinity analysis during active conversation (future enhancement)
- Multimedia content analysis (images, videos, files) - only detects message type, not content
- Group chat analysis (focus on 1-to-1 conversations)
- Sentiment analysis language support beyond Chinese (SnowNLP is Chinese-focused)
- Advanced emotion detection (anger, joy, sadness, etc.) - only three-way polarity (positive/negative/neutral)
- Calendar-based holiday detection (uses keyword matching instead)
- Relationship advice generation based on affinity scores (covered by separate AI suggestion feature)
- Historical trend analysis of affinity scores over time (future enhancement)
- Comparative analysis across multiple contacts (future enhancement)
- Privacy-preserving analysis for shared/concurrent access scenarios
- Integration with external CRM or contact management systems
