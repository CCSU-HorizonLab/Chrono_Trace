-- Migration 001: Create feature extraction tables
-- Date: 2025-01-05
-- Description: Add tables for session analysis, response time calculation, initiative rate, and word count statistics

-- ========================================
-- 1. 会话表
-- ========================================
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
-- 2. 响应时间表
-- ========================================
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
-- 3. 主动性统计表（聚合结果）
-- ========================================
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
-- 4. 字数统计表（聚合结果）
-- ========================================
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
