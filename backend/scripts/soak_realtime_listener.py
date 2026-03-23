import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _logs_dir() -> Path:
    return PROJECT_ROOT / "backend" / "data" / "logs"


def _write_result(payload: dict) -> Path:
    logs_dir = _logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = logs_dir / f"realtime_listener_soak_{int(time.time())}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def analyze_batch_messages(messages: list[dict]) -> dict:
    """Summarize batch contents for duplicate and type stability checks."""
    sender_counts = Counter()
    type_counts = Counter()
    hash_counts = Counter()
    runtime_counts = Counter()
    semantic_counts = Counter()

    for item in messages:
        sender = str(item.get("sender_attr") or "")
        msg_type = str(item.get("message_type") or "")
        content = str(item.get("content") or "")
        timestamp = int(item.get("timestamp") or 0)
        runtime_id = str(item.get("runtime_id") or "")
        message_hash = str(item.get("message_hash") or "")

        sender_counts[sender] += 1
        type_counts[msg_type] += 1
        if message_hash:
            hash_counts[message_hash] += 1
        if runtime_id:
            runtime_counts[runtime_id] += 1
        semantic_counts[f"{sender}|{msg_type}|{content}|{timestamp}"] += 1

    duplicate_hashes = {key: count for key, count in hash_counts.items() if count > 1}
    duplicate_runtime_ids = {key: count for key, count in runtime_counts.items() if count > 1}
    duplicate_semantics = {key: count for key, count in semantic_counts.items() if count > 1}

    return {
        "total_messages": len(messages),
        "sender_counts": dict(sender_counts),
        "type_counts": dict(type_counts),
        "duplicate_hashes": duplicate_hashes,
        "duplicate_runtime_ids": duplicate_runtime_ids,
        "duplicate_semantics": duplicate_semantics,
    }


def summarize_cycle(cycle: dict, requested_backend: str) -> dict:
    """Evaluate whether a soak cycle stayed healthy enough for replacement use."""
    statuses = cycle.get("statuses") or []
    batch_analysis = cycle.get("batch_analysis") or {}
    errors = list(cycle.get("errors") or [])
    provider_values = [str(status.get("provider") or "") for status in statuses]
    providers_seen = [value for value in provider_values if value]
    unique_providers = sorted(set(providers_seen))
    requested = str(requested_backend or "").strip().lower()
    ready_samples = [status for status in statuses if status.get("chat_ready")]
    chat_errors = [
        str(status.get("chat_error") or "")
        for status in statuses
        if status.get("chat_error")
    ]
    provider_mismatch = bool(
        requested == "native_uia"
        and providers_seen
        and any(value != "native_uia" for value in providers_seen)
    )
    polling_drops = sum(1 for status in statuses if not status.get("polling_alive", False))

    return {
        "ok": (
            bool(ready_samples)
            and not provider_mismatch
            and not errors
            and not batch_analysis.get("duplicate_hashes")
            and not batch_analysis.get("duplicate_runtime_ids")
            and polling_drops == 0
            and not chat_errors
        ),
        "providers_seen": unique_providers,
        "provider_mismatch": provider_mismatch,
        "chat_ready_reached": bool(ready_samples),
        "chat_error_samples": chat_errors[:10],
        "polling_drop_count": polling_drops,
        "duplicate_hash_count": len(batch_analysis.get("duplicate_hashes") or {}),
        "duplicate_runtime_id_count": len(batch_analysis.get("duplicate_runtime_ids") or {}),
        "duplicate_semantic_count": len(batch_analysis.get("duplicate_semantics") or {}),
        "status_samples": len(statuses),
        "final_message_count": int(batch_analysis.get("total_messages") or 0),
    }


def run_soak(
    chat_name: str,
    backend: str,
    cycles: int,
    duration_seconds: float,
    poll_interval: float,
) -> dict:
    sys.stdout.reconfigure(encoding="utf-8")

    from backend.app.services.realtime.message_buffer import MessageBuffer
    from backend.app.services.realtime.monitor_service import RealtimeMonitorService

    monitor = RealtimeMonitorService()
    buffer = MessageBuffer()
    original_backend = monitor.get_suggestion_config().get("listener_backend", "auto")
    payload = {
        "captured_at": int(time.time()),
        "chat_name": chat_name,
        "requested_backend": backend,
        "original_backend": original_backend,
        "cycles": [],
        "errors": [],
    }

    try:
        monitor.set_suggestion_config({"listener_backend": backend})
        for cycle_index in range(1, int(cycles) + 1):
            cycle = {
                "cycle_index": cycle_index,
                "start": {},
                "statuses": [],
                "message_snapshots": [],
                "batch_analysis": {},
                "stop": {},
                "errors": [],
            }
            batch_id = ""
            cycle_started_at = time.time()
            try:
                cycle["start"] = monitor.start_monitoring(
                    talker_username="",
                    talker_display_name=chat_name,
                    resume_mode="skip",
                )
                batch_id = str(cycle["start"].get("batch_id") or "")
                poll_deadline = cycle_started_at + max(1.0, float(duration_seconds))
                while time.time() < poll_deadline:
                    time.sleep(max(0.2, float(poll_interval)))
                    status = monitor.get_status()
                    cycle["statuses"].append(status)
                    if batch_id:
                        batch_messages = buffer.get_batch_messages(batch_id)
                    else:
                        batch_messages = []
                    snapshot = analyze_batch_messages(batch_messages)
                    snapshot["captured_at"] = int(time.time())
                    cycle["message_snapshots"].append(snapshot)
                if batch_id:
                    cycle["batch_analysis"] = analyze_batch_messages(buffer.get_batch_messages(batch_id))
            except Exception as exc:
                cycle["errors"].append(str(exc))
            finally:
                try:
                    cycle["stop"] = monitor.stop_monitoring()
                except Exception as exc:
                    cycle["errors"].append(f"stop_failed: {exc}")
                if batch_id and not cycle["batch_analysis"]:
                    cycle["batch_analysis"] = analyze_batch_messages(buffer.get_batch_messages(batch_id))
                cycle["summary"] = summarize_cycle(cycle, requested_backend=backend)
                cycle["duration_seconds"] = round(time.time() - cycle_started_at, 2)
                payload["cycles"].append(cycle)
    except Exception as exc:
        payload["errors"].append(str(exc))
    finally:
        try:
            monitor.set_suggestion_config({"listener_backend": original_backend})
        except Exception as exc:
            payload["errors"].append(f"restore_backend_failed: {exc}")

    payload["summary"] = {
        "cycle_count": len(payload["cycles"]),
        "ok_cycles": sum(1 for cycle in payload["cycles"] if (cycle.get("summary") or {}).get("ok")),
        "failed_cycles": sum(1 for cycle in payload["cycles"] if not (cycle.get("summary") or {}).get("ok")),
        "errors": payload["errors"],
    }
    payload["output_path"] = str(_write_result(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a long-running soak validation for the realtime listener.")
    parser.add_argument("--chat", required=True, help="Chat display name to validate against")
    parser.add_argument("--backend", default="native_uia", help="Listener backend to validate")
    parser.add_argument("--cycles", type=int, default=2, help="How many start/stop cycles to execute")
    parser.add_argument("--duration-seconds", type=float, default=20.0, help="How long each cycle should run")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between status polls")
    args = parser.parse_args()

    result = run_soak(
        chat_name=args.chat,
        backend=args.backend,
        cycles=args.cycles,
        duration_seconds=args.duration_seconds,
        poll_interval=args.poll_interval,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] and result["summary"]["failed_cycles"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
