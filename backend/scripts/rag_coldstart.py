"""RAG 索引冷启动：入队 Top5 会话，监控 worker 逐轮推进直至水位追平。

场景：删库重导后 rag_facts/rag_documents 全空、index_status 全 pending。
推进机制（无需本脚本循环施压）：
- 每轮 rebuild 携带 200 段抽取预算（回补通道 LLM_EXTRACT_BACKFILL_BUDGET）
- 轮末仍欠账时 indexer 自动 re-enqueue（indexer.py L1233-1246），worker
  单线程串行续轮直至 fact_extract_watermark_ts >= message_watermark_ts
- 短段/水聊段预筛跳过但同样推进水位——0 秒追平属正常（无内容可抽）
- 水位即断点：Ctrl-C 随时可停，重跑本脚本自动续（已覆盖段跳过）

前置（一次性，手工或 GUI 完成）：
1. llm_models 表写入活动模型（is_active=1）
2. settings.json 开 rag_structured_fact_extraction_enabled
3. rag_enabled 已开（默认开）

用法（仓库根目录，任意 Python 环境）：
    python backend/scripts/rag_coldstart.py                    # 默认账号 Top5 单聊
    python backend/scripts/rag_coldstart.py --convs 476,605    # 指定会话
    python backend/scripts/rag_coldstart.py --report           # 只看进度不入队

注意：跑批期间勿在应用里点「立即构建」（_REBUILD_LOCK 单锁互斥，撞锁方
排队退避不报错，但会互相干扰进度观测）。本脚本进程需保持运行——worker
是 daemon 线程，进程退出即停（水位断点，重跑续）。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.db.connection import get_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
)
logger = logging.getLogger("rag_coldstart")

# 单聊 Top5（按消息量升序：先小后大，尽早端到端验证一个完整会话）
# 姚淑佳 16,698 / 马行空 18,137 / 王东磊 26,300 / 胡宁 28,744 / 丰瑶 144,761
DEFAULT_CONVS = [2778, 714, 1415, 358, 1619]

POLL_SECONDS = 30.0


def _status_row(conn, account: str, conv: int) -> dict:
    row = conn.execute(
        "SELECT * FROM rag_index_status WHERE account_wxid=? AND conversation_id=?",
        (account, conv),
    ).fetchone()
    return dict(row) if row else {}


def _fact_count(conn, conv: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM rag_facts WHERE conversation_id=?", (conv,)
    ).fetchone()["c"]


def _behind_days(row: dict, prompt_version: str) -> float:
    """与 indexer._llm_extraction_behind 同口径：版本变化按全落后计。"""
    version_ok = str(row.get("fact_extract_prompt_version") or "") == prompt_version
    gap = int(row.get("message_watermark_ts") or 0) - int(
        row.get("fact_extract_watermark_ts") or 0
    )
    if version_ok and gap <= 0:
        return 0.0
    return gap / 86400.0 if version_ok else float("inf")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 索引冷启动入队与监控")
    parser.add_argument("--account", default="lishao378_86f8")
    parser.add_argument("--convs", default=",".join(map(str, DEFAULT_CONVS)),
                        help="逗号分隔 conversation_id 列表")
    parser.add_argument("--report", action="store_true",
                        help="只打印进度快照，不入队不等待")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS,
                        help="监控轮询间隔秒")
    args = parser.parse_args()

    convs = [int(c) for c in args.convs.split(",") if c.strip()]
    conn = get_db()

    from app.services.realtime.rag.indexer import RagIndexer

    # 前置自检：活动模型与抽取开关（缺一 worker 只建向量不抽事实）
    model = conn.execute(
        "SELECT name, model_id FROM llm_models WHERE is_active=1 LIMIT 1"
    ).fetchone()
    if not model:
        logger.error("llm_models 无活动模型——先配置再跑")
        return 2
    probe = RagIndexer()
    if probe.structured_fact_extractor is None:
        logger.error(
            "structured_fact_extractor 为 None：检查 settings.json 的"
            " rag_structured_fact_extraction_enabled 与活动模型可用性"
        )
        return 2
    prompt_version = probe.FACT_EXTRACT_PROMPT_VERSION
    logger.info("活动模型: %s (%s)，抽取器就绪", model["name"], model["model_id"])

    names = {}
    for conv in convs:
        row = conn.execute(
            "SELECT display_name FROM conversations WHERE id=?", (conv,)
        ).fetchone()
        names[conv] = row["display_name"] if row else f"conv{conv}"

    if not args.report:
        from app.services.realtime.rag.indexer import RagIndexQueue

        for conv in convs:
            if _behind_days(_status_row(conn, args.account, conv), prompt_version) <= 0:
                logger.info("== conv=%s(%s) 无欠账，跳过入队", conv, names[conv])
                continue
            RagIndexQueue.enqueue(args.account, conv)
            logger.info(
                "== conv=%s(%s) 已入队: facts=%s 落后 %.1f 天",
                conv, names[conv], _fact_count(conn, conv),
                _behind_days(_status_row(conn, args.account, conv), prompt_version),
            )

    t0 = time.time()
    while True:
        lines, done = [], True
        for conv in convs:
            row = _status_row(conn, args.account, conv)
            behind = _behind_days(row, prompt_version)
            if behind > 0:
                done = False
            lines.append(
                f"conv={conv}({names[conv]}) facts={_fact_count(conn, conv)}"
                f" 状态={row.get('status', '无行')} 落后{'∞(版本)' if behind == float('inf') else f'{behind:.1f}天'}"
            )
        logger.info("[%3d 分钟] %s", (time.time() - t0) / 60.0, " | ".join(lines))
        if done:
            logger.info("全部会话抽取水位已追平，完成")
            return 0
        if args.report:
            return 1
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
