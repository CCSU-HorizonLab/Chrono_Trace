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
    output_path = logs_dir / f"realtime_listener_validation_{int(time.time())}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run_validation(
    chat_name: str,
    poll_interval: float,
    max_polls: int,
    message_limit: int,
) -> dict:
    sys.stdout.reconfigure(encoding="utf-8")

    from backend.app.services.realtime.message_query import get_messages_with_sentiment
    from backend.app.services.realtime.monitor_service import RealtimeMonitorService

    monitor = RealtimeMonitorService()
    payload = {
        "captured_at": int(time.time()),
        "chat_name": chat_name,
        "provider": "db_watch",
        "start": {},
        "statuses": [],
        "messages": [],
        "stop": {},
        "errors": [],
    }

    try:
        payload["start"] = monitor.start_monitoring(
            talker_username="",
            talker_display_name=chat_name,
            resume_mode="skip",
        )

        for _ in range(max_polls):
            time.sleep(poll_interval)
            status = monitor.get_status()
            payload["statuses"].append(status)
            batch_id = status.get("batch_id")
            if batch_id:
                payload["messages"] = get_messages_with_sentiment(batch_id, message_limit)
            if status.get("chat_ready") and payload["messages"]:
                break
    except Exception as exc:
        payload["errors"].append(str(exc))
    finally:
        try:
            payload["stop"] = monitor.stop_monitoring()
        except Exception as exc:
            payload["errors"].append(f"stop_failed: {exc}")

    payload["output_path"] = str(_write_result(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a smoke test for the db_watch realtime listener.")
    parser.add_argument("--chat", required=True, help="Chat display name to validate against")
    parser.add_argument("--poll-interval", type=float, default=3.0, help="Seconds between status polls")
    parser.add_argument("--max-polls", type=int, default=5, help="Maximum number of status polls")
    parser.add_argument("--message-limit", type=int, default=20, help="How many messages to load at the end")
    args = parser.parse_args()

    result = run_validation(
        chat_name=args.chat,
        poll_interval=args.poll_interval,
        max_polls=args.max_polls,
        message_limit=args.message_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
