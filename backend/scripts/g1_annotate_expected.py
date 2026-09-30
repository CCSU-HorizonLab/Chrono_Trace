"""G0 预期标注器:为基线样例填写 AI 初判的预期任务/输出/知识需求/安全边界。

用法(仓库根目录)::

    python backend/scripts/g1_annotate_expected.py

产出:把 ``expected`` 与 ``expected_annotation=ai_first_pass_pending_human``
写回 ``docs/goals/g1-baseline-samples.json``(保留 ``annotation_basis`` 供
人工终审追溯)。人工确认前,这些预期只用于差异报告,不作为发布门禁。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


ANNOTATE_VERSION = "g1-expected-annotate-v1"

FACTS = ["facts"]
ALL4 = ["facts", "contact_profile", "user_style", "relationship_signals"]
PROFILE_SIGNALS = ["facts", "contact_profile", "relationship_signals"]

SAFETY_NO_INJECT = ["不得注入任何联系人历史知识", "RAG 必须 missing_scope 跳过", "仍生成通用帮助回复"]
SAFETY_MEMORY = ["未命中时明确说没查到", "不得编造时间/地点/游戏名/事件"]
SAFETY_SENDABLE = ["话术必须可直接发送", "不得替用户编造未发生的约定或承诺"]


def _e(task, output, needs, basis, must_use=None, forbidden=None, safety=None, scope="ok"):
    return {
        "task": task,
        "output": output,
        "knowledge_needs": needs,
        "scope": scope,
        "must_use": must_use or [],
        "forbidden": forbidden or [],
        "safety": safety or [],
        "annotation_basis": basis,
    }


# 每条样例的 AI 初判。basis 记录判定依据,供人工终审快速核对。
ANNOTATIONS: dict[str, dict[str, Any]] = {
    # ---- 真实日志样例(多轮输入已从建议日志重建) ----
    "real-1": _e(
        "memory_qa", "direct_answer", FACTS,
        "G2 契约:纯历史问答直接回答,不注入用户口头禅与建议风格;真实日志中旧行为是 PURE_CHAT 空话术",
        must_use=["游戏类事实(hobby_or_game,若命中)"],
        forbidden=["用户表达风格块", "量化风格硬约束", "建议卡片(speeches 应为空)"],
        safety=SAFETY_MEMORY,
    ),
    "real-2": _e(
        "invitation_planning", "answer_with_speeches", ALL4,
        "施工单首个目标样例:约昕打游戏;上一轮已得到游戏事实答案,本轮给邀约话术(对应真实建议#5)",
        must_use=["共同游戏/对方游戏偏好类事实", "邀约话术须像用户本人"],
        forbidden=["贴膜/穿衣等无关偏好抢占预算"],
        safety=SAFETY_SENDABLE,
    ),
    "real-3": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "G2 契约:'没有建议么'继承建议任务并修正输出;真实序列是 记忆问答→AI作答→追问建议",
        must_use=["上一轮已召回的游戏事实作为话术素材"],
        forbidden=["回落成纯聊天(空 speeches)"],
        safety=SAFETY_SENDABLE,
    ),
    # ---- 任务路由 ----
    "authored-task_routing-00": _e(
        "invitation_planning", "answer_with_speeches", ALL4,
        "施工单目标样例原文",
        must_use=["共同游戏/对方游戏偏好类事实(若存在)"],
        forbidden=["无游戏关联的偏好抢占预算"],
        safety=SAFETY_SENDABLE,
    ),
    "authored-task_routing-01": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "显式回复求助('怎么回')优先于邀约话题;需要关系策略约束分寸",
        must_use=["关系策略/边界(若注入链路开启)"],
        forbidden=["把邀约误判成纯聊天"],
        safety=SAFETY_SENDABLE,
    ),
    "authored-task_routing-02": _e(
        "memory_qa", "direct_answer", FACTS,
        "偏好事实查询;只回答事实,不给话术",
        must_use=["对方偏好类事实(若命中)"],
        forbidden=["用户表达风格块", "建议卡片"],
        safety=SAFETY_MEMORY,
    ),
    "authored-task_routing-03": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "G2 契约:建议追问继承;三轮序列 求助→建议→追问",
        must_use=["继承上一轮的任务上下文"],
        forbidden=["回落成纯聊天"],
        safety=SAFETY_SENDABLE,
    ),
    "authored-task_routing-04": _e(
        "general_qa", "direct_answer", FACTS,
        "普通闲聊:安全输出,不代发话术",
        forbidden=["建议卡片", "替用户生成发给对方的话术"],
        safety=["reply 用助手口吻,不模仿用户对第三方说话"],
    ),
    "authored-task_routing-05": _e(
        "memory_qa", "direct_answer", FACTS,
        "G2 契约原文:'我们玩过什么游戏'进入事实问答",
        must_use=["游戏类事实(若命中)"],
        forbidden=["用户口头禅/建议风格"],
        safety=SAFETY_MEMORY,
    ),
    # ---- 联系人绑定 ----
    "authored-contact_binding-06": _e(
        "invitation_planning", "answer_with_speeches", ALL4,
        "同名歧义:任务识别照常,但范围必须拒绝自动选取",
        forbidden=["任何联系人历史知识注入"],
        safety=SAFETY_NO_INJECT,
        scope="missing_or_ambiguous",
    ),
    "authored-contact_binding-07": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "跨账号会话 ID:显式范围不属于当前账号,必须 invalid_conversation",
        forbidden=["他账号会话的任何数据"],
        safety=["不得回退显示名猜测会话", *SAFETY_NO_INJECT],
        scope="invalid_conversation",
    ),
    "authored-contact_binding-08": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "正对照:有效显式会话 ID,知识按该联系人注入",
        must_use=["会话 91(昕)的事实/策略,而非其他联系人"],
        forbidden=["跨联系人注入"],
        safety=SAFETY_SENDABLE,
    ),
    # ---- 通知污染 ----
    "authored-notification_pollution-09": _e(
        "relationship_discussion", "direct_answer", PROFILE_SIGNALS,
        "转账密集窗口的关系推断:允许关系信号,但不得把转账事件解读成冷淡",
        must_use=["配对统计(排除转账事件)"],
        forbidden=["把'对方只发过转账'当成冷淡/拒绝证据"],
        safety=["不得据此下'她讨厌你'的结论;数据不足时输出 unknown"],
    ),
    "authored-notification_pollution-10": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "通知混入窗口:生成照常,窗口净化后仍保留有效聊天",
        must_use=["净化后的聊天窗口"],
        forbidden=["系统通知占用聊天窗口名额"],
        safety=SAFETY_SENDABLE,
    ),
    "authored-notification_pollution-11": _e(
        "general_qa", "direct_answer", FACTS,
        "纯通知窗口守卫:没有有效聊天时不得推导关系结论",
        forbidden=["基于纯通知窗口推断冷淡/已读不回"],
        safety=["prompt 必须携带纯通知守卫说明"],
    ),
    # ---- 脱敏误伤 ----
    "authored-redaction_misfire-12": _e(
        "memory_qa", "direct_answer", FACTS,
        "游戏事实脱敏完整性:游戏名(路易吉/杀戮尖塔/塞尔达等)在远程 prompt 中保持可理解",
        must_use=["游戏类事实且核心实体未被占位符吃掉"],
        forbidden=["游戏名被 [ADDRESS_xxx] 类占位符替换后仍计为有效注入"],
        safety=["核心对象丢失时标记 evidence_redacted_unusable 并剔除"],
    ),
    "authored-redaction_misfire-13": _e(
        "memory_qa", "direct_answer", FACTS,
        "真实地址必须脱敏;脱敏后地址事实不可引用(核心对象即地址)",
        must_use=["地址事实先脱敏再判定可用性"],
        forbidden=["把未脱敏地址发往远程模型"],
        safety=["脱敏失败 fail-closed,不回退发送原文"],
    ),
    "authored-redaction_misfire-14": _e(
        "memory_qa", "direct_answer", FACTS,
        "电话号码必须脱敏;查询本身不得把号码带入远程 prompt",
        forbidden=["明文号码进入 prompt"],
        safety=["占位符替换后按证据完整性规则处理"],
    ),
    # ---- 策略适配 ----
    "authored-policy_adaptation-15": _e(
        "relationship_discussion", "direct_answer", PROFILE_SIGNALS,
        "关系讨论:即使直接回答也允许画像与关系信号;好感分不等于亲密度",
        must_use=["关系信号块(带时间与不确定性)"],
        forbidden=["把聊天数量/好感分直接当成'她喜欢你'的证据"],
        safety=["分数不授权推进关系;数据缺失输出 unknown"],
    ),
    "authored-policy_adaptation-16": _e(
        "relationship_discussion", "answer_with_speeches", PROFILE_SIGNALS + ["user_style"],
        "关系讨论+行动求助('怎么推进'):回答附话术",
        must_use=["边界事实(relationship_boundary)约束话术分寸"],
        forbidden=["越过已知边界的推进话术"],
        safety=SAFETY_SENDABLE,
    ),
    "authored-policy_adaptation-17": _e(
        "relationship_discussion", "answer_with_speeches", PROFILE_SIGNALS,
        "无主语分寸求助('怎么开玩笑不越界'):策略词+边界词即可命中关系讨论",
        must_use=["对方边界/雷点(若命中)"],
        forbidden=["无边界数据时编造'她不介意'"],
        safety=["边界未知时明确 unknown,给保守话术"],
    ),
    # ---- 缺失降级 ----
    "authored-missing_scope_degrade-18": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "空账号:范围解析失败,安全降级",
        forbidden=["任何历史知识注入"],
        safety=SAFETY_NO_INJECT,
        scope="missing_or_ambiguous",
    ),
    "authored-missing_scope_degrade-19": _e(
        "reply_suggestion", "suggestion_card", ALL4,
        "无联系人范围:安全降级为通用帮助",
        forbidden=["按显示名猜会话", "任何历史知识注入"],
        safety=SAFETY_NO_INJECT,
        scope="missing_or_ambiguous",
    ),
    "authored-missing_scope_degrade-20": _e(
        "invitation_planning", "answer_with_speeches", ALL4,
        "查无此联系人:任务识别照常,知识注入关闭",
        forbidden=["任何历史知识注入"],
        safety=["通用邀约建议(不引用具体记忆)", *SAFETY_NO_INJECT],
        scope="missing_or_ambiguous",
    ),
}


def annotate(samples_path: Path) -> dict[str, int]:
    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    applied = missing = 0
    for sample in payload.get("samples") or []:
        annotation = ANNOTATIONS.get(sample.get("sample_id") or "")
        if annotation is None:
            if sample.get("source") == "authored":
                continue  # filler 样例沿用装载器自动预期
            missing += 1
            continue
        sample["expected"] = annotation
        sample["expected_annotation"] = "ai_first_pass_pending_human"
        applied += 1
    meta = payload.setdefault("meta", {})
    meta["expected_annotation"] = {
        "version": ANNOTATE_VERSION,
        "annotated_at": int(time.time()),
        "applied": applied,
        "pending_human_review": True,
        "note": "AI 初判+依据;人工终审通过前仅用于差异报告,不作发布门禁",
    }
    samples_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"applied": applied, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-baseline-samples.json"))
    args = parser.parse_args()
    stats = annotate(Path(args.samples))
    print(f"[G0 Annotate] 已标注 {stats['applied']} 条(未匹配 {stats['missing']}) → {args.samples}")
    print("[G0 Annotate] 人工终审通过前,预期仅用于差异报告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
