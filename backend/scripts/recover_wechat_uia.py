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
    output_path = logs_dir / f"wechat_uia_recovery_{int(time.time())}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run_recovery(
    recover: bool,
    wechat_exe: str,
    narrator_path: str,
    wait_after_kill: float,
    wait_after_narrator: float,
    wait_after_launch: float,
    probe_interval: float,
    max_probes: int,
    stop_narrator_after_check: bool,
) -> dict:
    sys.stdout.reconfigure(encoding="utf-8")

    from backend.app.services.realtime.providers.recovery import recover_shell_only_wechat_uia

    payload = recover_shell_only_wechat_uia(
        recover=recover,
        wechat_exe=wechat_exe,
        narrator_path=narrator_path,
        wait_after_kill=wait_after_kill,
        wait_after_narrator=wait_after_narrator,
        wait_after_launch=wait_after_launch,
        probe_interval=probe_interval,
        max_probes=max_probes,
        stop_narrator_after_check=stop_narrator_after_check,
    )

    payload["output_path"] = str(_write_result(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe and optionally recover WeChat UIA accessibility by relaunching WeChat with Narrator."
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="If shell-only UIA is detected, close WeChat, launch Narrator, relaunch WeChat, and re-probe.",
    )
    parser.add_argument("--wechat-exe", default="", help="Optional explicit WeChat executable path.")
    parser.add_argument("--narrator-path", default="", help="Optional explicit Narrator executable path.")
    parser.add_argument("--wait-after-kill", type=float, default=1.0, help="Seconds to wait after terminating WeChat.")
    parser.add_argument("--wait-after-narrator", type=float, default=1.5, help="Seconds to wait after launching Narrator.")
    parser.add_argument("--wait-after-launch", type=float, default=6.0, help="Seconds to wait after relaunching WeChat.")
    parser.add_argument("--probe-interval", type=float, default=2.0, help="Seconds between post-recovery probes.")
    parser.add_argument("--max-probes", type=int, default=6, help="Maximum number of post-recovery probes.")
    parser.add_argument(
        "--stop-narrator-after-check",
        action="store_true",
        help="Terminate Narrator after the final accessibility probe.",
    )
    args = parser.parse_args()

    result = run_recovery(
        recover=args.recover,
        wechat_exe=args.wechat_exe,
        narrator_path=args.narrator_path,
        wait_after_kill=args.wait_after_kill,
        wait_after_narrator=args.wait_after_narrator,
        wait_after_launch=args.wait_after_launch,
        probe_interval=args.probe_interval,
        max_probes=args.max_probes,
        stop_narrator_after_check=args.stop_narrator_after_check,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
