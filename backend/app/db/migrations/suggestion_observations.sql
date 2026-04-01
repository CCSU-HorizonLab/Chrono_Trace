-- 建议观察事件表
-- 用于记录建议展示、查看、关闭、采纳、改写、忽略等行为结果

CREATE TABLE IF NOT EXISTS suggestion_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suggestion_id INTEGER NOT NULL,
    batch_id TEXT,
    display_name TEXT,
    trigger_type TEXT,
    event_type TEXT NOT NULL,
    similarity REAL,
    selected_speech TEXT,
    actual_message TEXT,
    actual_message_type TEXT,
    metadata_json TEXT,
    created_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestion_observations_singleton
ON suggestion_observations(suggestion_id, event_type);

CREATE INDEX IF NOT EXISTS idx_suggestion_observations_event_created
ON suggestion_observations(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_suggestion_observations_display
ON suggestion_observations(display_name, created_at DESC);
