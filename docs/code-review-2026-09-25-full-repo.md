# Chrono Trace 全库代码审查报告

- **日期**：2026-09-25
- **范围**：backend/app 全部（6 个分区）+ frontend/src + backend/scripts + packaging + 根目录构建脚本
- **方法**：8 个并行审查代理逐文件精读并交叉核实调用方；叠加 Linux 可执行的机械检查（compileall、ruff F/E9、前端 build+冒烟、轻量 pytest 子集）
- **结论**：去重后 **49 条发现**（高危 7 / 中危 22 / 低危 20）。脱敏红线、SQL 注入、API Key 泄漏、HTTP 连接泄漏、database-is-locked 根治结论等专项核查全部通过。
- **状态**：本文档为审查记录；修复按文末优先级顺序推进，修复项在提交说明中引用本文编号。

## 编号约定

- A*：分析服务（analysis/）
- B*：桥接层与入口（webview/bridge.py、config、app 入口）
- R*：实时监听核心（monitor_service、message_buffer、providers 等）
- G*：RAG 记忆子系统（rag_*、feedback_*）
- L*：LLM 建议链路（llm_engine、privacy_redactor、profiler、悬浮窗）
- F*：前端（frontend/src）
- S*：脚本与打包（backend/scripts、packaging、tools）
- W*：微信导入与 DB 层（wechat/、db/）

---

## 高危（7 条）

### W1 实时与导入共用 local_id 唯一键，跨 ID 空间撞车
- 位置：`backend/app/services/wechat/ingest_service.py:717-739`；`backend/app/services/realtime/monitor_service.py:2623-2626、3027-3031`；`backend/app/db/schema.sql:72-74`
- 机制：唯一索引 `idx_messages_conv_local_unique ON messages(conversation_id, local_id) WHERE local_id IS NOT NULL` 是导入去重唯一依据；实时侧却把 UIA 监听器 `runtime_id`（甚至非纯数字 → NULL）写入同一列。增量导入后同一物理消息双份入库（统计/预处理/RAG 翻倍）；数值撞车时 `INSERT OR IGNORE` 静默丢真消息，且启动期 `_run_compat_migrations`（connection.py:255-266）按 `(conversation_id, local_id)` 去重会保留实时行删除导入行，损失固化。
- 置信度：确认

### R1 监听中 UIA 失败后无限自旋
- 位置：`backend/app/services/realtime/monitor_service.py:1927-1928、1948-1952`
- 机制：监听就绪后微信关闭/重启 → `GetAllMessage()` 抛 `UINotAccessibleError`，非 GDI 异常被 raise 到外层，外层仅打印+sleep(1) 继续；`is_monitoring` 恒 True、`_chat_error` 从不设置。每秒一次全量 UIA 枚举+traceback 刷屏，前端永远显示「监听中」，UIA 恢复流程只挂在 `_try_chat_with` 切聊天路径（1643-1650）上，监听阶段完全缺失。
- 置信度：确认

### R2 run_backfill 与 start_monitoring 并发，finally 清空新会话状态
- 位置：`backend/app/services/realtime/monitor_service.py:2938-2943、2994-2998`
- 机制：`run_backfill` 入口只检查一次 `is_monitoring`，回溯可跑数十秒；期间 `start_monitoring` 启动新会话后，回溯线程因 `self.wx` 被置 None 抛 AttributeError 进入 finally：清掉新会话的 `current_display_name/current_talker`、销毁新 wx。新轮询线程拿空候选进入「等待恢复」死循环（1799），`is_monitoring` 卡 True，监听永久失效。
- 置信度：确认

### A1 喜好兼容度查询 sessions 表不存在的列
- 位置：`backend/app/services/analysis/preference_compatibility_service.py:217-222`（对照 `schema.sql:248-261`）
- 机制：`SELECT id, start_unit_id, end_unit_id FROM sessions` —— 表实际列为 `start_time/end_time`；`OperationalError` 被外层 `except Exception`（248-250）吞掉返回空。已用内存 SQLite 实测复现。后果：配置喜好关键词后 `topic_mention_score` 恒 0、`matched_keywords` 恒空，225 行「没有会话表」兜底永远不可达。
- 置信度：确认（审查代理实测 + 主会话独立复核 schema）

### A2 重跑预处理从不清理 sessions 表，行数按分析次数累积
- 位置：`backend/app/services/analysis/preprocessing_orchestrator.py:140-153`；`preprocessing_service.py:1690-1703`
- 机制：`clear_cached_pairs` 只删 interaction_pairs/speech_units；`save_sessions` 为 `INSERT OR REPLACE`（表无 (conversation_id,start_time) 唯一约束，等价追加）。bridge.py:4423 每次好感度分析强制 `effective_force_reanalyze=True` → sessions 行数成倍累积 → `attitude_tendency_service.calculate_positive_word_frequency`（76-89 行，JOIN 命中 k 份重复行，正面计数放大 k 倍）、nickname 频率、活跃日历全部虚高。feature_extraction 路径有 `DELETE FROM sessions`，affinity 路径没有。
- 置信度：确认

### F1 分析页切换联系人竞态：旧结果覆盖新状态
- 位置：`frontend/src/views/Analytics.vue:919-931（onConversationChange）、1360-1372（轮询回调）、956-966`
- 机制：onConversationChange 并发发起多个异步加载无请求序号；好感度轮询完成时直接写 `analysisResult` 且用当前（可能已切换的）`selectedConversationId` 取分数。A 的分析结论/画像可显示在 B 名下。
- 置信度：确认（主会话独立复核）

### F2 轮询 interval 卸载不清理 + 异常被吞，可永久轮询
- 位置：`frontend/src/views/Analytics.vue:1314、1351、1386（catch 吞错）、1611-1615（onUnmounted 无 timer 清理）`
- 机制：分析进行中离开页面 → 500ms bridge 轮询继续、闭包泄漏；后端任务状态卡 running 或 bridge 持续抛错时轮询永不停止。`waitForModelDownload`（1084）的 1s interval 同样未清理。
- 置信度：确认

---

## 中危（22 条）

### 数据/导入链路

- **W2 解密明文临时库在构造异常时永久残留**：`wechat/db/v4/message.py:79-84`、`contact.py:50-53`——`tempfile.mktemp` 后解密抛异常则构造未完成，`close()` 不可达，前 N-1 个分片全量明文聊天记录留在 %TEMP%；`ingest_service.py:582-584` 的构造在 try/finally 之外；全仓库无陈旧临时文件清扫。确认。
- **W3 单页解密失败把密文页写进「已解密」库，逐会话吞错，导入仍报成功**：`db_decryptor_v2.py:226-233`（密文页原样 write）、`ingest_service.py:647-652`（per-会话 except continue）、`v4/message.py:161-163`（只吞 OperationalError，DatabaseError 上抛被上层吞）。微信在线并发写库产生撕裂页时相关会话整段静默缺失。确认。
- **R4 迁移/回溯按「内容+同一分钟」判重，同分钟相同短消息漏采**：`monitor_service.py:2298-2317`（消费点 2614、3023）。实时缓冲靠 runtime_id 哈希可分，落历史表后五元组判重把「嗯/好/哈哈哈」连发的第二条静默跳过。确认。
- **R3 主循环前 UIA/DB 调用无保护，线程死亡后 is_monitoring 卡 True**：`monitor_service.py:1874、1701`（同族 1843、2746、1605）。`_seed_visible_message_baseline` 等在 while 之前抛异常直接冲出线程。确认。

### RAG 记忆

- **G1 退役事实经「文档孪生」复活**：`rag_indexer.py:641-699`（semantic_facts 直接生成 fact_memory 文档，不查 rag_facts 状态/墓碑）+ `rag_retriever.py:103-123`（事实路径无命中落入文档路径）。被 supersede/被用户标记「不准确」的记忆在重建后以 enabled=1 文档重生——刚修复的复活 bug 在文档通道的残留。确认。
- **G2 跨 index_version 旧文档永不清理**：`rag_store.py:781-790`（delete 只删当前 RAG_INDEX_VERSION）、`758-770/808-819`（读取不过滤版本）。v1→v2→v3 升级库新旧两套文档+向量永久残留、重复注入、计数虚高。确认。
- **G3 一次融合多路 UPDATE 时 supersedes_fact_id 被覆盖，演变链断链**：`rag_store.py:1195-1204`、`rag_indexer.py:971-973`。新事实单链指针只留最后一个旧事实，其余 superseded 无后继指向。确认（读侧不受影响，纯审计缺陷）。
- **G4 纠错触发的偏好槽刷新不带 embedding，聚好的槽被拆散**：`rag_relationship_policy.py:319-327` 未传 embedding_service → `rag_contact_preference.py:89-125` 降级为每事实一槽。与 touched_fact_id 守卫注释声明的防分裂意图相悖，且产生版本 churn。确认。

### LLM / 隐私

- **L1 流式超时重试重发已下发 delta**：`llm_engine.py:1629-1634`（重试）与 `1690、1693`（delta emit）。长流式读超时 → 已 emit 的部分入队 → 重试从头再流 → 前端按 seq 追加出现重复文本。确认。
- **L2 「最近对话/用户需求」块绕过脱敏器原文直发远端**：`llm_engine.py:1037-1040、1079`。同一条消息走 hot_context/事实抽取路径会被逐条 redact，走这两个 prompt 块（每条 90 字符×20 条 + 320 字符）始终原文。与 README「远程模型发送前默认脱敏」宣称不符的覆盖缺口。疑似（产品取舍待定）。
- **L3（=B5）建议流/下载/密钥会话三个任务字典只增不删**：`bridge.py:65-70、910-925、604-610、3941`。长驻进程内存无界增长。确认。

### 桥接 / 设置

- **B1（=W4）settings 并发读改写无锁 + 非原子写入**：`bridge.py:84-89、1392-1462、541-547`；`account_settings.py:285-291（write_text 非原子）、265-273（损坏 JSON 静默当空）`。并发丢更新；半写文件下次启动被当空 dict，此后任意一次保存把微信账号/密钥/基线永久清空。确认。
- **B2 模型下载无后端互斥**：`bridge.py:3940、3955-4039、198-222`；`model_manager.py:31、156-162、175-223`。`_download_lock` 是实例级而 Bridge 每次新建实例（跨实例无效）；双入口并发对固定 temp/backup 目录互删；task_id 按秒生成撞号。确认。
- **B3 affinity task_id 靠 sleep(0.1)+扫描+本地猜测**：`bridge.py:4426、4441-4456、4496-4503`。猜错 ID 时 `get_affinity_progress` 永远 pending，前端轮询永不 resolve 且无法被 cancel 解救。疑似（触发依赖时序）。

### 分析

- **A3 特征提取睡眠时段用 UTC 判定**：`feature_extraction_service.py:322-323、500-501`（`datetime.fromtimestamp(ts, tz=timezone.utc)`）。东八区实际扣除白天 8:00-15:00 的回复、深夜反而不扣；与 `SessionManager._check_crosses_sleep_time`（本地时区）口径不一致。确认。
- **A4 词云/统计截断最早 1 万条而时间序列全量**：`analysis_service.py:145-147`（未传 limit）→ `preprocessing_service.py:204-205`（`ORDER BY timestamp ASC LIMIT 10000`）；对照 `:201-220`（timeseries 无 LIMIT）。同页口径不一致且无提示。确认。
- **A5 话题延续性忽略 preference_session_ids**：`preference_compatibility_service.py:301-330`。SQL 只按 conversation_id 过滤，喜好维度 60% 权重的子分与关键词配置无关。确认。

### 前端

- **F3 秒级时间戳进 new Date → 1970**：`FloatingPanel.vue:1737、1743`。后端 `created_at` 为 Unix 秒，`new Date(秒)` 当毫秒解析；AI 气泡 ts 缩小 1000 倍、排序错乱到顶部。确认（主会话独立复核）。
- **F4 DimensionRadar removeEventListener 传新匿名函数**：`DimensionRadar.vue:187-199`。移除无效，每次重挂泄漏一份监听+对已 dispose 实例 resize。确认（主会话独立复核）。
- **F5 FloatingPanel 顶层匿名 resize 监听无移除**：`FloatingPanel.vue:496-497、1224-1229`。反复进出悬浮模式累积监听，闭包持有整个组件作用域。确认。
- **F6 toISOString() 取 UTC 日期**：`Analytics.vue:797-798`、`DateRangeFilter.vue:32-37`、`ConversationTimeline.vue:214`。东八区 0:00-8:00 期间默认日期终点少一天、凌晨会话归前一天。确认。

### 脚本 / 打包

- **S1 export_for_labeling 无条件覆写已标注 CSV**：`backend/scripts/export_for_labeling.py:30、202`。再运行一次即清空全部人工标签（'w' 模式重写），无存在性检查/备份/确认。确认。
- **S2 打包 wheel 相对路径按 CWD 解析**：`requirements-packaging.txt:10` + `setup_packaging_env.ps1:80` + `build_release.ps1:222-228`。非仓库根运行（右键 PowerShell/powershell -File）pip 解析 `packaging/vendor/...` 失败，构建中止。pip 行为已实测。确认。

---

## 低危（20 条）

- **A6** 活跃天数 UTC 与本地两种分桶并存：`preprocessing_service.py:589`（`DATE(timestamp,'unixepoch')`）vs `emotional_resonance_service.py:995/1026`（localtime）。确认。
- **A7** 信任倾诉加分 `(比例)×20×100` 量纲放大，0.75% 倾诉率即达 15 分封顶；注释「上限30」与 `TRUST_BONUS_MAX=15` 矛盾：`attitude_tendency_service.py:180-184`。疑似。
- **A8** 好感度/预处理缓存键不含配置与算法指纹，改配置读到脏结果（主流程因强制重算受限）：`affinity_analysis_service.py:664、677-705`；`affinity_config.py:69-101`；`preprocessing_orchestrator.py:74-75、270-287`。确认。
- **B4** `get_latest_thread`/`load_thread_context` 在 Bridge 类内重复定义（771/783 与 4598/4613），后者静默覆盖，两份返回契约不一致（`data` vs `context`、`ok:False` vs `ok:True,thread:null`）；前端 `r.data || r.context` 双兼容。确认（主会话独立复核）。
- **R5** `_resolve_time_label` 两处边界：跨零点 "HH:MM" 解析成未来 ~24h（`monitor_service.py:2141-2146`）；星期标签等于今天时 `(x-x)%7=0` 少算 7 天（`:2201`）。确认。
- **R6** `configure_device_mode` 无锁置 None 与推理线程竞争，单条消息情感误判为中性：`realtime_sentiment_service.py:101-105 vs 295-298`。确认（窗口小）。
- **R7** `open_chat` 会话条目点击失败不走搜索回退，直接抛错靠上层重试：`native_uia.py:552-559`。疑似。
- **G5** 事实向量回填判定用「全表向量数（含退役）」对比「活跃事实数」，活跃缺向量时回填被跳过：`rag_indexer.py:196-205`；`rag_store.py:747-755`。确认。
- **G6** marker_fallback 质量门 context 恒空（`RagSegment` 无 `render_excerpt`，方法在 RagSegmenter 上）：`rag_semantic_memory.py:319-325`。确认。
- **G7** 反馈候选裸 INSERT 撞 UNIQUE(account,conversation,kind,content) 被整体吞掉，部分成功状态无日志：`feedback_attribution.py:416-440`；`rag_store.py:120`。确认。
- **G8** LLM 抽取的 status 字段原样写入（ALLOWED_STATUS 放行 superseded/uncertain），可将 active 事实无后继静默退役：`rag_indexer.py:955`、`rag_fact_extractor.py:84-86`、`rag_store.py:983-991`。疑似。
- **L4** 流事件环形裁剪（保留 400）不通知消费方，慢轮询时游标跨度静默丢失、流式文本缺段：`bridge.py:907-908、976-981`。确认。
- **L5** PrivacyRedactor 原始偏移多模式替换，重叠匹配（地址吞电话）产出损坏占位符（无原文泄漏）：`privacy_redactor.py:62-84`。确认。
- **L6** 悬浮窗跟踪线程函数顶层 `import win32gui`，失败即静默死亡且 enter_floating_mode 已返回成功：`floating_window_service.py:577-580`。确认。
- **F7** GPU 安装轮询 installTimer 未在卸载时清理：`Settings.vue:627、644、659 vs 1277-1281`。确认。
- **F8** bridge.ts 声明 `get_dashboard_stats` 后端不存在；affinity.ts 实际调用的十余个方法未声明（build 不做类型检查被掩盖）：`bridge.ts:68`；`affinity.ts:26-198`。确认。
- **S3** cleanup_realtime_backfill 默认直接 DELETE 无确认/备份（与同目录 backfill_* 的默认 dry-run 模式相反）：`backend/scripts/cleanup_realtime_backfill.py:44-56`。确认。
- **S4** setup_packaging_env 的 PyInstaller 健康检查 try/catch 捕不到原生命令非零退出，损坏 venv 误报就绪：`setup_packaging_env.ps1:71-76`。确认。
- **S5** train_sentiment_model 非原子覆写运行时模型目录，中断后损坏且加载失败静默降级纯规则：`backend/scripts/train_sentiment_model.py:39、311-312`。确认。
- **M1**（机械检查）ruff 残余 129 条清理级（F541×84、F401×31、F841×10、F811×4）；抽查 F811/F841 均无行为影响（如 `monitor_service.py:1707/1714` 的 `msg`/`resolved_timestamp`、`rag_retriever.py:307` 的 `fact_tokens` 均为遗留死变量）。

---

## 专项核查通过项

- **脱敏红线**：`rag_fact_llm._require_redactor` 构造失败抛异常阻断整段；`rag_context_builder` 主链路失败降级 strong_mask（纯本地）再失败 blocked；关系策略/偏好槽失败丢文本留枚举。全部 fail-closed。
- **SQL 注入**：全参数化；表名为 `Msg_`+md5 hexdigest、列名来自微信库 PRAGMA、LIMIT 有 int 把关。
- **API Key 泄漏**：key 仅入 Authorization 头，URL 与日志不含。
- **HTTP 连接泄漏**：urlopen 均在 with 内。
- **database is locked**：主库统一 autocommit + WAL + busy_timeout，无新遗留持锁路径。
- **RAG 门控预算**：`_minimize_items` 1600/560 字符与 8 条上限核算正确；事实层 supersede 复活路径确认已修好。
- **密钥校验**：捕获路径有 `^[0-9a-fA-F]{64}$`，日志不输出密钥内容。

## 机械检查结果（Linux）

- `python3 -m compileall`（backend/app、backend/scripts、入口、tools）：**0 语法错误**
- `ruff check --select F,E9`：无 F821/E9；残余均为清理级（见 M1）
- 前端 `npm install + npm run build`：**通过**（8.4s，仅 chunk>500kB 提示）；`test:smoke`：**3/3 通过**
- 轻量 pytest 子集（preprocessing/keyword_libraries/attitude_preprocessing/interaction_pairs/sql_write_arity/db_connection_migration）：**88 通过 / 1 失败**。失败项 `test_session_split_with_midnight_cross` 已排除系统时区因素（本机 CST），疑与缺 sentence 模型时相似度回退 0.0 的路径相关，需 Windows 复跑定性。
- 未执行（Linux 不可行，按约定跳过）：全量 pytest（torch/sentence-transformers/modelscope/wx_key wheel 不可装）、运行时/桌面行为验证。

## 修复优先级

1. **数据完整性**：W1（local_id 撞车）、W3（密文页静默丢失）、W2（明文临时文件泄漏）、A2（sessions 累积）
2. **监听死状态**：R1（UIA 自旋）、R2（finally 清态竞态）
3. **分析页前端**：F1（竞态守卫）、F2（轮询清理）＋顺手 F7
4. **偏好维度**：A1（列名）、A5（session_ids 失效）
5. **RAG**：G1（文档通道复活）、G2（index_version 清理）
6. 其余中低危按批次跟进
