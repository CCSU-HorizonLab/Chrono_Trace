# G1-02 知识装配(G4 脱敏证据 + G5 按任务选择)

- **上游文档**:`docs/goals/g1-generation-goal.md` 第三节 G4/G5、第四节知识优先级
- **状态**:代码落地（单测通过；真实回放待 G0/G7）
- **改造点**:`privacy_redactor.py`、`rag/context_builder.py`(重排/偏好排序/证据完整性)、`llm_engine._build_prompt`(关系信号块、unknown 语义)

## G4 脱敏后证据可用

- [x] 地址规则误伤修复:"路易吉鬼屋"等含"路/街"字符的游戏/作品译名不再命中地址模式(受保护片段表 + 裸路名需要门牌数字或地址介词上下文)。
- [x] 增加游戏名、地名、真实地址、电话号码的脱敏正反例单测(`test_privacy_redactor_games.py`)。
- [x] 脱敏后核心对象完整性检查:`evidence_core_intact`(CJK bigram 保留率阈值 + 短内容特判)。
- [x] 核心对象丢失的事实记录 `evidence_redacted_unusable`,从注入清单剔除并写入排除原因,不得计为有效注入。
- [x] 远程脱敏失败继续 fail-closed(strong_mask → blocked),不回退发送原文——回归测试锁定。

## G5 按任务选择知识

- [x] `_rerank_candidates_for_task` 感知 task:invitation_planning 提升共同经历/游戏类事实,relation 讨论提升关系信号类;general_qa 压低风格样本。
- [x] `contact_preferences` 注入按任务排序:邀约场景游戏类偏好优先,贴膜/穿衣等无关偏好不抢预算(上限 6 条不变)。
- [x] 好感分析以带时间与不确定性的【关系信号】块注入:分析时间、覆盖窗口、数据量、置信度、趋势、可支持建议、不能推出的结论;缺失输出 unknown。
- [x] 画像 `interests` 仅作兴趣线索,不升级为"共同经历"(prompt 使用规则措辞)。
- [x] 缺数据一律输出 unknown:昵称习惯、情感风格等不再生成"没有昵称习惯"式伪结论。
- [x] 选择顺序保持固定:当前目标 → 相关事实 → 直接边界 → 相关偏好 → 关系背景 → 表达风格(`_build_prompt` 块顺序对齐)。

## 验收

- 隐私规则不回退;游戏名、项目名在远程 prompt 中保持可理解。
- 同一联系人在游戏邀约、冲突降温、项目协作、普通闲聊中选择不同知识集合。
