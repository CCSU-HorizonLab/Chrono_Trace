-- 实时 AI 建议表
-- 存储由触发条件检测后引擎生成的建议记录

CREATE TABLE IF NOT EXISTS realtime_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_wxid TEXT NOT NULL,                 -- 归属微信账号 wxid

    -- 关联批次
    batch_id TEXT NOT NULL,                    -- 监听批次 ID

    -- 触发信息
    trigger_type TEXT NOT NULL,                -- 触发类型: negative_streak / emotion_shift / perfunctory / silence / positive_window / topic_cooling
    intent TEXT NOT NULL,                      -- 发展走向: intimate / maintain / distance
    severity TEXT DEFAULT 'medium',            -- 严重度: high / medium / low

    -- 建议内容
    summary TEXT NOT NULL,                     -- 建议摘要
    speeches TEXT NOT NULL,                    -- 具体话术 JSON array
    confidence REAL DEFAULT 1.0,               -- 引擎置信度

    -- 状态
    status TEXT DEFAULT 'pending',             -- pending / read / dismissed
    engine_type TEXT DEFAULT 'llm',            -- 生成引擎类型

    -- 上下文（可选）
    trigger_context TEXT,                      -- 触发上下文 JSON

    -- 时间戳
    created_at INTEGER NOT NULL,               -- 创建时间
    read_at INTEGER,                           -- 已读时间
    dismissed_at INTEGER,                      -- 关闭时间
    reply TEXT,                               -- 纯对话回复
    thought_process TEXT                      -- AI 思考过程
);

CREATE INDEX IF NOT EXISTS idx_realtime_suggestions_account_batch ON realtime_suggestions(account_wxid, batch_id, status);
CREATE INDEX IF NOT EXISTS idx_realtime_suggestions_account_created ON realtime_suggestions(account_wxid, created_at DESC);
