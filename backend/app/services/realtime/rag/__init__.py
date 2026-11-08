"""联系人长期记忆（RAG v4）子系统。

按联系人维护可追溯的长期记忆：事实抽取（fact_llm/fact_quality）、存储与演变链
（store）、分段与嵌入（segmenter/embedding）、索引（indexer）、召回与门控
（retriever/relevance_gate）、上下文分槽注入（context_builder）、关系与偏好策略
（relationship_policy/contact_preference）、语义记忆（semantic_memory）。
配置见 config.py（fact_kind_hints.json / fact_quality_patterns.json 随包分发）。
"""
