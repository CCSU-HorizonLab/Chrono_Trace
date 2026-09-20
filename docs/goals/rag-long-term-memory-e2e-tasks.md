# 联系人级长期记忆端到端任务

## 已完成并验证

- [x] 本地 `text2vec_base_chinese` 模型加载验证，原生输出维度为 768。
- [x] Bridge 模型状态接口实测返回 `embedding_model_ready=true`、`analysis_available=true`。
- [x] embedding 链路取消静默截断/补零，并在维度不匹配时安全降级。
- [x] 默认开启事实记忆读侧，保留文档检索回退。
- [x] 旧版 shadow-only 配置自动迁移为事实读侧开启，并保留后续手动关闭。
- [x] 设置页增加“事实记忆优先”开关，并持久化到后端配置。
- [x] 设置页增加 embedding 模型检测、下载入口和进度轮询。
- [x] RAG 状态接口返回事实读写配置。
- [x] RAG 状态接口事实配置字段契约测试通过。
- [x] 真实 Bridge `get_rag_status` 返回事实读侧开启、768 维配置。
- [x] 索引重建失败时前端收到失败状态和错误信息。
- [x] Bridge 索引重建失败回传契约测试通过。
- [x] 事实检索结果携带状态、置信度和证据消息，并注入回复提示词。
- [x] 事实 ID 与 evidence ID 写入 `rag_retrieval_logs`。
- [x] 后端回归测试：60 passed。
- [x] 事实写入→检索→日志→提示词注入与 Bridge 契约集成测试通过（新增后共 64 passed）。
- [x] LLM 生成入口消费事实上下文并携带 RAG 日志关联 ID（新增后共 65 passed）。
- [x] “我们玩过什么游戏”类共享经历问句识别为 memory_request。
- [x] 显式记忆问句的低分 fact 不再被普通聊天门控误拒。
- [x] 实时消息轮询缺失 `realtime_sentiment_cache` 时自动补表。
- [x] 真实联系人问句回放命中 `strategy=facts`、`gate=memory_request_match`。
- [x] 真实本地数据库副本回放：单联系人索引 ready，3131 文档/向量、1388 条事实成功生成。
- [x] 真实数据库副本事实回放命中 `strategy=facts`，写入 `retrieval_source=fact`、fact IDs 和 evidence IDs。
- [x] 三路对照回放测试通过：no-RAG 无注入、旧文档回退命中文档、事实优先命中 fact。
- [x] 前端生产构建通过（Vite，仅保留既有 chunk 体积提示）。
- [x] 前端 smoke 测试通过（3 passed）。
- [x] Python 应用源码编译检查通过。
- [x] RAG/意图/实时消息定向回归：76 passed。
- [x] 自我/联系人画像改为按 7/30/90 天时间窗采样，输出上限按实际 prompt 动态计算，不再按模型写死 4096/8192 token。
- [x] 画像 JSON mode、动态 token 契约与解析回归通过：自画像相关测试 3 passed。
- [x] 修复 redaction 缺失时事实内容被渲染为 `None`，并排除空事实候选；补充回归测试。
- [x] 对游戏、偏好、计划/承诺等明确记忆问句增加事实 kind 过滤，避免无关事实造成“假命中”。

## 发布前仍需人工验收

- [ ] 在实际桌面进程中打开设置页，确认模型状态、事实开关和索引重建按钮可用。
- [ ] 使用真实联系人消息完成一次“写入事实 → 事实检索 → 回复注入”回放，并核对 `rag_retrieval_logs`。
- [ ] 完成 no-RAG、旧文档 RAG、事实优先三路对照后冻结发布门禁。

人工验收未完成前，不将本任务标记为整条链路最终完成。
