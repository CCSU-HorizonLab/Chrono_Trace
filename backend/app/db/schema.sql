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
