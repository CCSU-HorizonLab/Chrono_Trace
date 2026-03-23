import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _logs_dir() -> Path:
    return PROJECT_ROOT / "backend" / "data" / "logs"


def _write_result(payload: dict) -> Path:
    logs_dir = _logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = logs_dir / f"realtime_cross_chat_regression_{int(time.time())}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _collect_batch_snapshot(batch_id: str) -> dict:
    from backend.app.db.connection import get_db
    from backend.app.services.realtime.message_buffer import MessageBuffer

    buffer = MessageBuffer()
    conn = get_db()
    messages = buffer.get_batch_messages(batch_id) if batch_id else []
    suggestion_rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM realtime_suggestions
        WHERE batch_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (batch_id,),
    ).fetchall() if batch_id else []

    return {
        "buffer_count": len(messages),
        "sender_counts": {
            key: sum(1 for item in messages if item.get("sender_attr") == key)
            for key in ("friend", "self", "system")
        },
        "suggestion_status_counts": {
            str(row["status"]): int(row["count"])
            for row in suggestion_rows
        },
        "sample_messages": [
            {
                "sender_attr": item.get("sender_attr"),
                "content": item.get("content"),
                "message_type": item.get("message_type"),
                "timestamp": item.get("timestamp"),
            }
            for item in messages[:8]
        ],
    }


def _run_single_session(monitor, chat_name: str, duration_seconds: float, poll_interval: float) -> dict:
    session = {
        "chat_name": chat_name,
        "start": {},
        "statuses": [],
        "batch_snapshot": {},
        "stop": {},
        "errors": [],
    }
    batch_id = ""
    started_at = time.time()

    try:
        session["start"] = monitor.start_monitoring(
            talker_username="",
            talker_display_name=chat_name,
            resume_mode="skip",
        )
        batch_id = str(session["start"].get("batch_id") or "")
        deadline = started_at + max(1.0, float(duration_seconds))
        while time.time() < deadline:
            time.sleep(max(0.3, float(poll_interval)))
            status = monitor.get_status()
            session["statuses"].append(status)
        if batch_id:
            session["batch_snapshot"] = _collect_batch_snapshot(batch_id)
    except Exception as exc:
        session["errors"].append(str(exc))
    finally:
        try:
            session["stop"] = monitor.stop_monitoring()
        except Exception as exc:
            session["errors"].append(f"stop_failed: {exc}")
        if batch_id and not session["batch_snapshot"]:
            session["batch_snapshot"] = _collect_batch_snapshot(batch_id)

    ready = any(status.get("chat_ready") for status in session["statuses"])
    providers_seen = sorted(
        {
            str(status.get("provider") or "")
            for status in session["statuses"]
            if status.get("provider")
        }
    )
    session["summary"] = {
        "chat_ready_reached": ready,
        "providers_seen": providers_seen,
        "buffer_count": int(session["batch_snapshot"].get("buffer_count") or 0),
        "suggestion_status_counts": session["batch_snapshot"].get("suggestion_status_counts") or {},
    }
    return session


def run_regression(
    first_chat: str,
    second_chat: str,
    backend: str,
    duration_seconds: float,
    poll_interval: float,
) -> dict:
    sys.stdout.reconfigure(encoding="utf-8")

    from backend.app.db.connection import get_db
    from backend.app.services.realtime.monitor_service import RealtimeMonitorService

    monitor = RealtimeMonitorService()
    original_backend = monitor.get_suggestion_config().get("listener_backend", "auto")
    conn = get_db()
    before_rule_counts = {
        first_chat: conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='contact_rules'"
        ).fetchone()[0]
    }
    payload = {
        "captured_at": int(time.time()),
        "requested_backend": backend,
        "original_backend": original_backend,
        "first_chat": first_chat,
        "second_chat": second_chat,
        "sessions": [],
        "errors": [],
    }

    try:
        monitor.set_suggestion_config({
            "listener_backend": backend,
            "trigger_mode": "semi_auto",
        })
        payload["sessions"].append(
            _run_single_session(monitor, first_chat, duration_seconds, poll_interval)
        )
        time.sleep(1.0)
        payload["sessions"].append(
            _run_single_session(monitor, second_chat, duration_seconds, poll_interval)
        )
    except Exception as exc:
        payload["errors"].append(str(exc))
    finally:
        try:
            monitor.set_suggestion_config({"listener_backend": original_backend})
        except Exception as exc:
            payload["errors"].append(f"restore_backend_failed: {exc}")

    payload["summary"] = {
        "session_count": len(payload["sessions"]),
        "all_ready": all((item.get("summary") or {}).get("chat_ready_reached") for item in payload["sessions"]),
        "all_native_uia": all(
            "native_uia" in ((item.get("summary") or {}).get("providers_seen") or [])
            for item in payload["sessions"]
        ),
        "all_zero_buffer": all(
            int((item.get("summary") or {}).get("buffer_count") or 0) == 0
            for item in payload["sessions"]
        ),
        "all_zero_suggestions": all(
            not ((item.get("summary") or {}).get("suggestion_status_counts") or {})
            for item in payload["sessions"]
        ),
        "errors": payload["errors"],
    }
    payload["output_path"] = str(_write_result(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Regression check for cross-chat realtime listener switching.")
    parser.add_argument("--first-chat", required=True, help="First chat display name")
    parser.add_argument("--second-chat", required=True, help="Second chat display name")
    parser.add_argument("--backend", default="native_uia", help="Listener backend to validate")
    parser.add_argument("--duration-seconds", type=float, default=6.0, help="How long to observe each chat")
    parser.add_argument("--poll-interval", type=float, default=1.5, help="Seconds between status polls")
    args = parser.parse_args()

    result = run_regression(
        first_chat=args.first_chat,
        second_chat=args.second_chat,
        backend=args.backend,
        duration_seconds=args.duration_seconds,
        poll_interval=args.poll_interval,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] and result["summary"]["all_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
