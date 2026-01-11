-- Chrono Trace 数据库表结构设计
-- 参考 EchoTrace 设计，适配 Chrono Trace 的长期分析 + 短期实时建议场景

-- ========================================
-- 1. 会话（对话）表
-- ========================================
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,          -- 微信username（唯一标识）
    display_name TEXT NOT NULL,              -- 显示名称（备注名 > 昵称 > username）
    remark TEXT,                             -- 备注名
    nickname TEXT,                           -- 昵称
    avatar_path TEXT,                        -- 头像路径（可选，预留扩展）
    conversation_type TEXT DEFAULT 'private', -- 会话类型: private, group
    platform TEXT DEFAULT 'wechat',          -- 平台：wechat（预留扩展）
    created_at INTEGER NOT NULL,             -- 首次聊天时间戳（秒）
    updated_at INTEGER NOT NULL,             -- 最后一条消息时间戳（秒）
    message_count INTEGER DEFAULT 0,         -- 消息总数
    is_deleted INTEGER DEFAULT 0             -- 是否已删除（软删除）
);

CREATE INDEX IF NOT EXISTS idx_conversations_username ON conversations(username);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);


-- ========================================
-- 2. 联系人表
-- ========================================
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,           -- 微信username
    nickname TEXT,                           -- 昵称
    remark TEXT,                             -- 备注名
    alias TEXT,                              -- 微信号
    phone TEXT,                              -- 电话（部分用户可见）
    contact_type TEXT DEFAULT 'friend',      -- 类型: friend, stranger, official, chatroom_member
    avatar_path TEXT,                        -- 头像路径
    is_friend INTEGER DEFAULT 1,             -- 是否为好友
    is_deleted INTEGER DEFAULT 0,            -- 是否已删除
    created_at INTEGER,                      -- 添加时间
    updated_at INTEGER                       -- 更新时间
);

CREATE INDEX IF NOT EXISTS idx_contacts_username ON contacts(username);


-- ========================================
-- 3. 消息表
-- ========================================
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,        -- 关联会话ID
    local_id INTEGER,                        -- 微信本地消息ID
    talker TEXT NOT NULL,                    -- 对方username（群聊时为群ID）
    sender TEXT,                             -- 发送者username（群聊消息时有效）
    is_sender INTEGER NOT NULL,              -- 是否为本人发送（1=发送，0=接收）
    message_type INTEGER NOT NULL,           -- 消息类型（1=文本，3=图片，34=语音，43=视频等）
    content TEXT,                            -- 消息内容（文本消息）
    media_path TEXT,                         -- 媒体文件路径（图片/语音/视频，预留）
    timestamp INTEGER NOT NULL,              -- 消息时间戳（秒）
    source TEXT DEFAULT 'long',              -- 数据来源: long（长期导入）, realtime（实时监听）
    emotion REAL,                            -- 情绪分值（可选，AI分析后填充）
    created_at INTEGER NOT NULL,             -- 导入时间
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type);


-- ========================================
-- 4. 分段分析结果表
-- ========================================
-- 用于存储按时间段（周/月）聚合的分析结果
CREATE TABLE IF NOT EXISTS analysis_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,        -- 关联会话ID
    from_ts INTEGER NOT NULL,                -- 时间段起始（秒）
    to_ts INTEGER NOT NULL,                  -- 时间段结束（秒）
    summary TEXT,                            -- 总结摘要
    metrics_json TEXT,                       -- 统计指标JSON: {total, sent, received, emotion_avg, keywords:[], ...}
    created_at INTEGER NOT NULL,             -- 分析生成时间
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analysis_conversation ON analysis_segments(conversation_id);
CREATE INDEX IF NOT EXISTS idx_analysis_time_range ON analysis_segments(from_ts, to_ts);


-- ========================================
-- 5. 建议记录表
-- ========================================
-- 存储LLM生成的话术建议
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,        -- 关联会话ID
    intent TEXT NOT NULL,                    -- 意图: intimate(亲密), maintain(维持), distance(疏远)
    summary TEXT,                            -- 建议摘要
    speech_json TEXT,                        -- 话术列表JSON: ["话术1", "话术2", ...]
    source TEXT DEFAULT 'manual',            -- 来源: manual（手动触发）, realtime（实时生成）
    context_json TEXT,                       -- 上下文信息JSON（最近N条消息等）
    created_at INTEGER NOT NULL,             -- 生成时间
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_suggestions_conversation ON suggestions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_source ON suggestions(source);
CREATE INDEX IF NOT EXISTS idx_suggestions_created_at ON suggestions(created_at DESC);


-- ========================================
-- 6. 配置表
-- ========================================
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,                -- 配置键
    value TEXT,                              -- 配置值
    updated_at INTEGER NOT NULL              -- 更新时间
);

-- 默认配置
INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES 
    ('llm_model', 'local', strftime('%s', 'now')),
    ('realtime_interval_minutes', '30', strftime('%s', 'now')),
    ('analysis_range_days', '7', strftime('%s', 'now')),
    ('wechat_db_key', '', strftime('%s', 'now'));


-- ========================================
-- 7. 运行时事件表（可选）
-- ========================================
-- 用于记录实时监听、错误、心跳等事件
CREATE TABLE IF NOT EXISTS runtime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,                -- 事件类型: heartbeat, error, realtime_message, import等
    payload_json TEXT,                       -- 事件数据JSON
    created_at INTEGER NOT NULL              -- 事件发生时间
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_type ON runtime_events(event_type);
CREATE INDEX IF NOT EXISTS idx_runtime_events_created_at ON runtime_events(created_at DESC);


-- ========================================
-- 8. 导入记录表
-- ========================================
-- 记录每次导入操作的元数据
CREATE TABLE IF NOT EXISTS import_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_type TEXT NOT NULL,               -- 导入类型: wechat_full, wechat_incremental
    total_messages INTEGER DEFAULT 0,        -- 导入消息数
    total_conversations INTEGER DEFAULT 0,   -- 导入会话数
    status TEXT DEFAULT 'pending',           -- 状态: pending, success, failed
    error_message TEXT,                      -- 错误信息（如果失败）
    started_at INTEGER NOT NULL,             -- 开始时间
    completed_at INTEGER,                    -- 完成时间
    metadata_json TEXT                       -- 其他元数据JSON
);

CREATE INDEX IF NOT EXISTS idx_import_records_status ON import_records(status);
CREATE INDEX IF NOT EXISTS idx_import_records_started_at ON import_records(started_at DESC);


-- ========================================
-- 9. 实时消息暂存表
-- ========================================
-- 用于临时存储实时监听到的消息,会话结束后可处理迁移
CREATE TABLE IF NOT EXISTS realtime_message_buffer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 监听对象信息
    talker_username TEXT NOT NULL,          -- 对话对象username
    talker_display_name TEXT NOT NULL,      -- 对话对象显示名称
    
    -- 消息内容
    message_hash TEXT,                      -- 消息哈希值(wxauto4提供,用于去重)
    runtime_id TEXT,                        -- wxauto4消息运行时ID
    sender_attr TEXT NOT NULL,              -- 发送者属性: self(本人), friend(对方), system(系统)
    content TEXT,                           -- 消息内容
    message_type TEXT,                      -- 消息类型(text/image/voice等)
    
    -- 时间信息
    timestamp INTEGER NOT NULL,             -- 消息时间戳(秒)
    captured_at INTEGER NOT NULL,           -- 抓取时间(秒)
    
    -- 状态管理
    is_processed INTEGER DEFAULT 0,         -- 是否已处理(0=未处理, 1=已处理)
    batch_id TEXT,                          -- 批次ID(同一次监听的消息共享,用于批量处理)
    
    created_at INTEGER NOT NULL             -- 记录创建时间
);

CREATE INDEX IF NOT EXISTS idx_realtime_buffer_talker ON realtime_message_buffer(talker_username);
CREATE INDEX IF NOT EXISTS idx_realtime_buffer_batch ON realtime_message_buffer(batch_id);
CREATE INDEX IF NOT EXISTS idx_realtime_buffer_processed ON realtime_message_buffer(is_processed);
CREATE INDEX IF NOT EXISTS idx_realtime_buffer_timestamp ON realtime_message_buffer(timestamp);
CREATE INDEX IF NOT EXISTS idx_realtime_buffer_hash ON realtime_message_buffer(message_hash);


-- ========================================
-- 10. 消息预处理缓存表
-- ========================================
-- 存储清洗后的消息内容和统计信息，避免重复处理
CREATE TABLE IF NOT EXISTS message_preprocessed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,         -- 关联 messages.id
    conversation_id INTEGER NOT NULL,           -- 关联 conversations.id (冗余字段，便于查询)
    
    -- 清洗后的内容
    cleaned_content TEXT,                       -- 清洗后的文本内容
    
    -- 统计信息
    char_count INTEGER DEFAULT 0,               -- 字符数（不含空格）
    word_count INTEGER DEFAULT 0,               -- 词数（jieba分词）
    is_valid INTEGER DEFAULT 0,                 -- 是否为有效消息（1=有效，0=无效）
    
    -- 元数据标记
    has_xml INTEGER DEFAULT 0,                  -- 是否包含XML系统消息
    has_media INTEGER DEFAULT 0,                -- 是否包含媒体标签
    
    -- 时间戳
    created_at INTEGER NOT NULL,                -- 预处理时间
    
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_preprocessed_message ON message_preprocessed(message_id);
CREATE INDEX IF NOT EXISTS idx_preprocessed_conversation ON message_preprocessed(conversation_id);
CREATE INDEX IF NOT EXISTS idx_preprocessed_valid ON message_preprocessed(is_valid);


-- ========================================
-- 11. 特征提取：会话表
-- ========================================
-- 存储切分后的对话会话，记录每个会话的起止时间、消息数和发起者
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    start_time INTEGER NOT NULL,          -- 会话开始时间戳（秒）
    end_time INTEGER NOT NULL,            -- 会话结束时间戳（秒）
    message_count INTEGER NOT NULL,       -- 会话中的消息总数
    initiator TEXT NOT NULL,              -- 会话发起者: 'user' 或 'other'
    source TEXT DEFAULT 'long',           -- 数据来源: long=长期导入, realtime=实时监听
    created_at INTEGER NOT NULL,          -- 分析完成时间戳（秒）
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CHECK (initiator IN ('user', 'other')),
    CHECK (end_time >= start_time),
    CHECK (message_count >= 1)
);

CREATE INDEX IF NOT EXISTS idx_sessions_conversation ON sessions(conversation_id, start_time DESC);


-- ========================================
-- 12. 特征提取：响应时间表
-- ========================================
-- 存储每对发送-回复消息的响应时间，标记异常值
CREATE TABLE IF NOT EXISTS response_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    sent_message_id INTEGER NOT NULL,     -- 发送的消息ID
    reply_message_id INTEGER NOT NULL,    -- 回复的消息ID
    response_time_seconds REAL,           -- 响应时间（秒），NULL表示异常值
    is_abnormal INTEGER DEFAULT 0,        -- 是否异常值：0=正常, 1=异常
    abnormal_reason TEXT,                 -- 异常原因：'negative', 'too_long', 'single_message'
    source TEXT DEFAULT 'long',           -- 数据来源
    created_at INTEGER NOT NULL,          -- 记录创建时间戳（秒）
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (sent_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (reply_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CHECK (is_abnormal IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_response_times_conversation ON response_times(conversation_id, response_time_seconds);
CREATE INDEX IF NOT EXISTS idx_response_times_abnormal ON response_times(is_abnormal);


-- ========================================
-- 13. 特征提取：主动性统计表（聚合结果）
-- ========================================
-- 存储每个对话的主动性聚合统计（主动率、会话数分布）
CREATE TABLE IF NOT EXISTS initiative_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL UNIQUE,  -- 每个会话一条记录
    total_sessions INTEGER NOT NULL,          -- 总会话数
    user_initiated_sessions INTEGER NOT NULL, -- 用户主动发起的会话数
    other_initiated_sessions INTEGER NOT NULL,-- 对方主动发起的会话数
    initiative_rate REAL NOT NULL,            -- 对方主动率（0-1）
    last_updated INTEGER NOT NULL,            -- 最后更新时间戳（秒）
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CHECK (total_sessions = user_initiated_sessions + other_initiated_sessions),
    CHECK (initiative_rate >= 0.0 AND initiative_rate <= 1.0),
    CHECK (total_sessions > 0)
);


-- ========================================
-- 14. 特征提取：字数统计表（聚合结果）
-- ========================================
-- 存储字数统计，支持整体统计和按会话统计
CREATE TABLE IF NOT EXISTS word_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    session_id INTEGER,                       -- NULL表示整体统计
    user_char_count INTEGER NOT NULL,         -- 用户字数
    other_char_count INTEGER NOT NULL,        -- 对方字数
    char_ratio REAL NOT NULL,                 -- 字数比（对方/用户）
    last_updated INTEGER NOT NULL,            -- 最后更新时间戳（秒）
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    CHECK (user_char_count >= 0),
    CHECK (other_char_count >= 0),
    CHECK (char_ratio >= 0)
);

CREATE INDEX IF NOT EXISTS idx_word_counts_conversation ON word_counts(conversation_id);
CREATE INDEX IF NOT EXISTS idx_word_counts_session ON word_counts(session_id);


-- ========================================
-- 15. 好感度分析：情感缓存表
-- ========================================
-- 缓存情感分析结果,避免重复计算
CREATE TABLE IF NOT EXISTS sentiment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,          -- 关联 messages.id
    polarity INTEGER NOT NULL,                   -- -1 (负面), 0 (中性), 1 (正面)
    intensity REAL NOT NULL,                     -- -1.0 到 1.0
    embedding_vector BLOB,                       -- 384维向量 (序列化为字节)
    created_at INTEGER NOT NULL,                 -- 缓存时间戳
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CHECK (polarity IN (-1, 0, 1)),
    CHECK (intensity >= -1.0 AND intensity <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_cache_message ON sentiment_cache(message_id);


-- ========================================
-- 16. 好感度分析：发言单元表
-- ========================================
-- 存储合并后的发言单元 (连续5分钟内同一发送者的消息)
CREATE TABLE IF NOT EXISTS speech_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    message_ids TEXT NOT NULL,                   -- 逗号分隔的消息ID列表 (如 "123,124,125")
    sender TEXT NOT NULL,                        -- 'user' 或 'other'
    first_message_timestamp INTEGER NOT NULL,    -- 发言单元第一条消息时间戳
    last_message_timestamp INTEGER NOT NULL,     -- 发言单元最后一条消息时间戳
    message_count INTEGER NOT NULL,              -- 发言单元包含的消息数
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CHECK (sender IN ('user', 'other')),
    CHECK (message_count >= 1),
    CHECK (first_message_timestamp <= last_message_timestamp)
);

CREATE INDEX IF NOT EXISTS idx_speech_units_conversation ON speech_units(conversation_id, first_message_timestamp);


-- ========================================
-- 17. 好感度分析：交互对表
-- ========================================
-- 存储构建的交互对 (speech_unit_A → speech_unit_B)
CREATE TABLE IF NOT EXISTS interaction_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    from_speech_unit_id INTEGER NOT NULL,        -- 发起方发言单元ID
    to_speech_unit_id INTEGER NOT NULL,          -- 响应方发言单元ID
    time_gap INTEGER NOT NULL,                   -- 两个发言单元之间的时间间隔 (秒)
    semantic_similarity REAL,                    -- 余弦相似度 (可选,稍后计算)
    from_polarity INTEGER NOT NULL,              -- 发起方情感极性 (-1, 0, 1)
    to_polarity INTEGER NOT NULL,                -- 响应方情感极性 (-1, 0, 1)
    from_intensity REAL NOT NULL,                -- 发起方情感强度 (-1.0 到 1.0)
    to_intensity REAL NOT NULL,                  -- 响应方情感强度 (-1.0 到 1.0)
    is_negative_initiation INTEGER DEFAULT 0,    -- 是否为负面情绪发起 (1=是)
    is_empathetic_response INTEGER DEFAULT 0,    -- 是否为共情响应 (1=是)
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (from_speech_unit_id) REFERENCES speech_units(id) ON DELETE CASCADE,
    FOREIGN KEY (to_speech_unit_id) REFERENCES speech_units(id) ON DELETE CASCADE,
    CHECK (time_gap >= 0),
    CHECK (from_polarity IN (-1, 0, 1)),
    CHECK (to_polarity IN (-1, 0, 1)),
    CHECK (from_intensity >= -1.0 AND from_intensity <= 1.0),
    CHECK (to_intensity >= -1.0 AND to_intensity <= 1.0),
    CHECK (is_negative_initiation IN (0, 1)),
    CHECK (is_empathetic_response IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_conversation ON interaction_pairs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_from_unit ON interaction_pairs(from_speech_unit_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_to_unit ON interaction_pairs(to_speech_unit_id);


-- ========================================
-- 18. 好感度分析：配置表
-- ========================================
-- 存储每个对话的配置 (权重、阈值、关键词)
CREATE TABLE IF NOT EXISTS affinity_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL UNIQUE,
    config_version INTEGER DEFAULT 1,
    -- 维度权重 (必须总和为1.0)
    weight_emotional_resonance REAL DEFAULT 0.30,
    weight_chat_positivity REAL DEFAULT 0.30,
    weight_attitude_tendency REAL DEFAULT 0.20,
    weight_preference_compatibility REAL DEFAULT 0.20,
    -- 阈值配置
    reply_timeliness_threshold INTEGER DEFAULT 3600,            -- 回复及时阈值 (秒, 默认1小时)
    topic_continuity_time_window INTEGER DEFAULT 604800,        -- 话题延续时间窗口 (秒, 默认7天)
    similarity_threshold_initiation REAL DEFAULT 0.40,          -- 相似度阈值 (用于判定新话题)
    sliding_window_size INTEGER DEFAULT 5,                      -- 滑动窗口大小
    -- 关键词自定义 (JSON格式)
    custom_keywords_json TEXT,                                 -- 自定义关键词覆盖
    preference_keywords_json TEXT,                             -- 用户提供的喜好关键词
    -- 元数据
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CHECK (reply_timeliness_threshold > 0),
    CHECK (topic_continuity_time_window >= 86400),
    CHECK (similarity_threshold_initiation >= 0.0 AND similarity_threshold_initiation <= 1.0),
    CHECK (sliding_window_size >= 3)
);

CREATE INDEX IF NOT EXISTS idx_affinity_config_conversation ON affinity_config(conversation_id);


-- ========================================
-- 19. 好感度分析：关键词库表
-- ========================================
-- 存储全局关键词库 (默认集合 + 用户扩展)
CREATE TABLE IF NOT EXISTS keyword_libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,                     -- 'positive', 'negative', 'empathy', 'soothing', 'privacy', 'holiday'
    keyword TEXT NOT NULL,
    is_custom INTEGER DEFAULT 0,                -- 1=用户添加, 0=默认关键词
    created_at INTEGER NOT NULL,
    UNIQUE(category, keyword)
);

CREATE INDEX IF NOT EXISTS idx_keyword_libraries_category ON keyword_libraries(category);

-- 填充默认关键词 (is_custom=0, 不可删除)
INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES
-- Positive (正面词) - 10个
('positive', '哈哈', 0, strftime('%s', 'now')),
('positive', '谢谢', 0, strftime('%s', 'now')),
('positive', '开心', 0, strftime('%s', 'now')),
('positive', '高兴', 0, strftime('%s', 'now')),
('positive', '棒', 0, strftime('%s', 'now')),
('positive', '赞', 0, strftime('%s', 'now')),
('positive', '喜欢', 0, strftime('%s', 'now')),
('positive', '爱', 0, strftime('%s', 'now')),
('positive', '幸福', 0, strftime('%s', 'now')),
('positive', '满足', 0, strftime('%s', 'now')),

-- Negative (负面词) - 10个
('negative', '讨厌', 0, strftime('%s', 'now')),
('negative', '烦', 0, strftime('%s', 'now')),
('negative', '生气', 0, strftime('%s', 'now')),
('negative', '难过', 0, strftime('%s', 'now')),
('negative', '伤心', 0, strftime('%s', 'now')),
('negative', '痛苦', 0, strftime('%s', 'now')),
('negative', '失望', 0, strftime('%s', 'now')),
('negative', '厌恶', 0, strftime('%s', 'now')),
('negative', '恨', 0, strftime('%s', 'now')),
('negative', '郁闷', 0, strftime('%s', 'now')),

-- Empathy (共情词) - 10个
('empathy', '理解', 0, strftime('%s', 'now')),
('empathy', '心疼', 0, strftime('%s', 'now')),
('empathy', '懂你', 0, strftime('%s', 'now')),
('empathy', '不容易', 0, strftime('%s', 'now')),
('empathy', '辛苦', 0, strftime('%s', 'now')),
('empathy', '委屈', 0, strftime('%s', 'now')),
('empathy', '抱歉', 0, strftime('%s', 'now')),
('empathy', '同情', 0, strftime('%s', 'now')),
('empathy', '担心', 0, strftime('%s', 'now')),
('empathy', '安慰', 0, strftime('%s', 'now')),

-- Soothing (安抚词) - 10个
('soothing', '没事', 0, strftime('%s', 'now')),
('soothing', '别担心', 0, strftime('%s', 'now')),
('soothing', '会好的', 0, strftime('%s', 'now')),
('soothing', '支持你', 0, strftime('%s', 'now')),
('soothing', '陪着你', 0, strftime('%s', 'now')),
('soothing', '相信你', 0, strftime('%s', 'now')),
('soothing', '加油', 0, strftime('%s', 'now')),
('soothing', '放心', 0, strftime('%s', 'now')),
('soothing', '有我在', 0, strftime('%s', 'now')),
('soothing', '慢慢来', 0, strftime('%s', 'now')),

-- Privacy (隐私词) - 10个
('privacy', '秘密', 0, strftime('%s', 'now')),
('privacy', '私密', 0, strftime('%s', 'now')),
('privacy', '隐私', 0, strftime('%s', 'now')),
('privacy', '只告诉你', 0, strftime('%s', 'now')),
('privacy', '别告诉别人', 0, strftime('%s', 'now')),
('privacy', '保密', 0, strftime('%s', 'now')),
('privacy', '悄悄说', 0, strftime('%s', 'now')),
('privacy', '只有你知道', 0, strftime('%s', 'now')),
('privacy', '不告诉别人', 0, strftime('%s', 'now')),
('privacy', '偷偷说', 0, strftime('%s', 'now')),

-- Holiday (节日词) - 10个
('holiday', '新年快乐', 0, strftime('%s', 'now')),
('holiday', '春节快乐', 0, strftime('%s', 'now')),
('holiday', '圣诞快乐', 0, strftime('%s', 'now')),
('holiday', '生日快乐', 0, strftime('%s', 'now')),
('holiday', '节日快乐', 0, strftime('%s', 'now')),
('holiday', '国庆快乐', 0, strftime('%s', 'now')),
('holiday', '中秋快乐', 0, strftime('%s', 'now')),
('holiday', '五一快乐', 0, strftime('%s', 'now')),
('holiday', '元旦快乐', 0, strftime('%s', 'now')),
('holiday', '情人节快乐', 0, strftime('%s', 'now'));


-- ========================================
-- 20. 好感度分析：评分结果表
-- ========================================
-- 存储计算的维度评分和总体好感度评分
CREATE TABLE IF NOT EXISTS affinity_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    analysis_version INTEGER DEFAULT 1,         -- 分析版本号 (重新分析时递增)
    -- 总体评分
    overall_score REAL NOT NULL,                -- 0.0 到 100.0
    -- 各维度评分
    emotional_resonance_score REAL NOT NULL,    -- 情感共振率评分
    chat_positivity_score REAL NOT NULL,        -- 聊天积极度评分
    attitude_tendency_score REAL NOT NULL,      -- 态度倾向评分
    preference_compatibility_score REAL NOT NULL, -- 喜好兼容度评分
    -- 子维度详细分数 (JSON格式)
    sub_scores_json TEXT,                       -- 各维度子分数详细分解
    -- 元数据
    message_count INTEGER NOT NULL,             -- 消息总数
    interaction_pair_count INTEGER NOT NULL,    -- 交互对总数
    config_snapshot TEXT,                       -- 配置快照 (用于检测配置变化)
    analysis_duration_ms INTEGER,               -- 分析耗时 (毫秒)
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CHECK (overall_score >= 0.0 AND overall_score <= 100.0),
    CHECK (emotional_resonance_score >= 0.0 AND emotional_resonance_score <= 100.0),
    CHECK (chat_positivity_score >= 0.0 AND chat_positivity_score <= 100.0),
    CHECK (attitude_tendency_score >= 0.0 AND attitude_tendency_score <= 100.0),
    CHECK (preference_compatibility_score >= 0.0 AND preference_compatibility_score <= 100.0),
    CHECK (message_count >= 0),
    CHECK (interaction_pair_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_affinity_scores_conversation ON affinity_scores(conversation_id, created_at DESC);

