"""融合负样本注入的回放评测：边界带场景集验证 DENY 判定质量。

两级漏斗第二级（0.70~0.85 边界带把否认事实注入融合 prompt）的行为
评测：同一批边界场景跑注入后的真实 LLM 决策，对照期望动作。基线无需
LLM 调用——无注入时该路径本就回落 ADD（decide_fusion 任何校验失败
都按 ADD 落库），评测焦点是注入后的误杀/漏杀。

场景覆盖设计时点名的两类风险：
- 漏杀：概念泛化重述（对虾过敏 → 不能吃海鲜）本地相似度不过硬线
- 误杀：与否认同题但方向相反的演进（脱敏治疗）、与用户纠正一致的
  新事实（reason 说其实是蟹过敏）都不得 DENY

用法（需已配置激活的 LLM 模型）：
    python backend/scripts/replay_fusion_deny.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.rag.fact_extractor import StructuredFactExtractor
from app.services.realtime.rag.indexer import RagIndexer

DENIED_ID = 9001

# 边界带场景集：expected 是注入后的期望动作（DENY=丢弃 / ADD=正常落库）
SCENARIOS = [
    {
        "name": "泛化重述（漏杀风险）",
        "new_fact": "对方不能吃海鲜，聚餐要避开",
        "denied": {"fact_id": DENIED_ID, "content": "对方对虾过敏", "deny_reason": None},
        "expected": "DENY",
    },
    {
        "name": "同义改写（本地硬线对照）",
        "new_fact": "对方吃虾会过敏",
        "denied": {"fact_id": DENIED_ID, "content": "对方对虾过敏", "deny_reason": None},
        "expected": "DENY",
    },
    {
        "name": "与用户纠正一致（不得误杀）",
        "new_fact": "对方对蟹过敏，点菜要注意",
        "denied": {
            "fact_id": DENIED_ID,
            "content": "对方对虾过敏",
            "deny_reason": "记错了，是蟹过敏",
        },
        "expected": "ADD",
    },
    {
        "name": "同题反向演进（不得误杀）",
        "new_fact": "对方在做吃虾脱敏治疗，医生说现在可以少量尝试",
        "denied": {"fact_id": DENIED_ID, "content": "对方对虾过敏", "deny_reason": None},
        "expected": "ADD",
    },
    {
        "name": "无关事实（不得误杀）",
        "new_fact": "对方周末喜欢去爬山",
        "denied": {"fact_id": DENIED_ID, "content": "对方对虾过敏", "deny_reason": None},
        "expected": "ADD",
    },
]


def main() -> int:
    from app.services.realtime.rag.fact_llm import build_llm_fact_extractor

    adapter = build_llm_fact_extractor()
    if adapter is None:
        print("未找到激活的 LLM 模型配置（实时监听-建议模型），请先在设置中配置。")
        return 2

    indexer = RagIndexer.__new__(RagIndexer)
    indexer.structured_fact_extractor = StructuredFactExtractor(llm_call=adapter)

    print(f"场景数 {len(SCENARIOS)}，基线（无注入）一律 ADD 路径，只评注入后动作\n")
    rows = []
    passed = 0
    for scenario in SCENARIOS:
        fact = {
            "subject": "contact",
            "kind": "preference",
            "content": scenario["new_fact"],
            "confidence": 0.8,
            "evidence_message_ids": [],
        }
        decisions = indexer._decide_fact_fusion(fact, [], [scenario["denied"]])
        actions = sorted({item["action"] for item in decisions}) or ["ADD"]
        actual = "DENY" if "DENY" in actions else "ADD"
        ok = actual == scenario["expected"]
        passed += ok
        reason = next(
            (item["reason"] for item in decisions if item["action"] == "DENY"), ""
        )
        rows.append((scenario["name"], scenario["expected"], actual, "✓" if ok else "✗", reason))

    width = max(len(row[0]) for row in rows) + 2
    print(f"{'场景':<{width}}{'期望':<8}{'实际':<8}{'判定':<4}模型理由")
    for name, expected, actual, mark, reason in rows:
        print(f"{name:<{width}}{expected:<8}{actual:<8}{mark:<4}{reason[:60]}")
    print(f"\n通过 {passed}/{len(rows)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
