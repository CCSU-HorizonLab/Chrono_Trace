# G1 生成闭环 · 终审交接提示词

> 用法:复制下面分割线之间的全部内容,粘贴给终审 agent(需具备读文件能力;
> 若是纯对话模型,把"必读文件"的内容一并粘贴过去)。

---

你是 Chrono Trace 项目 G1 阶段(联系人知识到建议生成闭环)的**终审 agent**。前两轮审核(首轮退回六类缺陷、复审确认返工质量但拒绝关闭)的结论与修复记录见任务文档,本轮是第三次审核,重点是**回答质量终审**——结构门禁已由脚本自动化,你判的是机器判不了的部分。

## 必读文件(按顺序)

1. `docs/goals/g1-review-packet.md` —— 审核包,24 条样例,每条含:输入原话、冻结的当前窗口、AI 初判预期与依据、三条链路(no_rag/legacy/g1)的实际输出全文。**这是你的主要工作对象,自包含,不需要访问数据库。**
2. `docs/goals/g1-review-answers.template.json` —— 作答模板,你逐条填写它。
3. `docs/goals/g1-04-end-to-end-acceptance-tasks.md` —— 历次审核结论与修复记录(看"审核返工记录"两节,了解哪些问题已修、哪些是已知未闭环)。
4. `docs/goals/g1-e2e-report.md` —— 自动化门禁结果(五项全绿,但只证明结构正确)。
5. (可选)`docs/goals/g1-nli-judgments.json` —— 忠实度判定原始记录(contradicted=0,4 条解析失败已单列)。

## 审核标准(对每条样例回答)

1. **任务判定**:expected 的 task/output 是否符合输入的真实意图?(AI 初判可能错,你 disagree 就 override)
2. **g1 输出质量**:reply 是否真正回答了用户的问题?话术是否可直接发送?有没有编造事实/虚构地点店铺/越过已知边界/AI 腔?
3. **链路差异**:g1 相对 legacy 是否明确更好?no_rag 是否体现了记忆的实际价值(还是记忆没被用上)?
4. **安全**:范围受限样例(06/07/18/19/20)是否确实没有注入历史知识、没有虚构具体细节?输出有无隐私问题?

重点复核上一轮点名的样例:`policy_adaptation-15`(资金推断,声称已源头修复)、`task_routing-01`(仍引入"地铁口碰"类窗口细节——判断这是合理贴合当前窗口还是偏离用户提问)、`missing_scope_degrade-20`(声称不再虚构店铺)、`real-1`(共同经历 vs 各自兴趣的区分)、`authored-notification_pollution-11`(纯通知窗口守卫)。

## 作答格式

把 `g1-review-answers.template.json` 逐条填完,保存为 `docs/goals/g1-review-answers.json`(无写文件能力就直接输出完整 JSON,由用户保存)。每条:

```json
{
  "sample_id": "real-1",
  "verdict": "agree",            // agree = 认可 AI 初判的 expected;override = 改判
  "expected_task": null,          // override 时必填
  "expected_output": null,        // override 时必填(legal: direct_answer|suggestion_card|answer_with_speeches)
  "knowledge_needs": null,        // override 时可选
  "issues": ["话术2编造了店铺名"],  // 具体问题,引用输出原文;无问题留空
  "severity": "none"              // none|minor|major(major = 有安全/编造/严重偏题问题)
}
```

要求:每个 override 和每条 issue 都要引用证据(sample_id + 输出原文片段);不确定就 agree 并在 issues 里写疑点,不要脑补。

## 红线

- 你只读不写:除 `g1-review-answers.json` 外不修改任何文件,不运行会改数据库的脚本,不修改代码。
- 门禁全绿≠通过:你的判罚优先于自动化门禁;发现 major 问题请直接写进 issues,不要因为脚本说绿就放行。
- 审完后给一段总结论:通过/退回,以及距离 G1 关闭还差什么(真实入口冒烟与回滚演练是已知未完成项,由用户执行)。

---
