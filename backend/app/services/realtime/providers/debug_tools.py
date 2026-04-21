"""Debug helpers for inspecting WeChat UI Automation structures."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .detector import detect_running_wechat
from .native_uia import NativeUIARealtimeProvider
from ....config import LOG_DIR_PATH


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _rect_to_dict(rect) -> dict[str, int]:
    if rect is None:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}
    return {
        "left": int(getattr(rect, "left", 0) or 0),
        "top": int(getattr(rect, "top", 0) or 0),
        "right": int(getattr(rect, "right", 0) or 0),
        "bottom": int(getattr(rect, "bottom", 0) or 0),
    }


def serialize_control_tree(root, max_depth: int = 4, max_nodes: int = 300) -> dict:
    """Serialize a UIA control tree into a JSON-safe structure."""
    counter = {"count": 0}

    def walk(node, depth: int):
        if counter["count"] >= max_nodes:
            return None
        counter["count"] += 1
        payload = {
            "depth": depth,
            "name": _safe_call(lambda: node.window_text(), ""),
            "control_type": _safe_call(lambda: node.element_info.control_type, ""),
            "class_name": _safe_call(lambda: node.class_name(), ""),
            "automation_id": _safe_call(lambda: node.element_info.automation_id, ""),
            "runtime_id": _safe_call(lambda: list(node.element_info.runtime_id), []),
            "rectangle": _rect_to_dict(_safe_call(lambda: node.rectangle())),
            "visible": bool(_safe_call(lambda: node.is_visible(), False)),
            "children": [],
        }
        if depth >= max_depth:
            return payload
        for child in _safe_call(lambda: node.children(), []) or []:
            child_payload = walk(child, depth + 1)
            if child_payload is not None:
                payload["children"].append(child_payload)
            if counter["count"] >= max_nodes:
                break
        return payload

    return walk(root, 0) or {}


def collect_visible_item_diagnostics(provider) -> list[dict]:
    """Collect raw diagnostics for visible chat list items."""
    diagnostics = []
    try:
        items = provider._iter_chat_items()
    except Exception:
        return diagnostics

    current_label = ""
    for visible_index, item in enumerate(items):
        try:
            class_name = str(item.class_name() or "")
            raw_text = str(item.window_text() or "")
            normalized_text = raw_text.strip()
            runtime_id = list(getattr(item.element_info, "runtime_id", []) or [])
            rect = _rect_to_dict(_safe_call(lambda: item.rectangle()))
            is_system = provider._looks_like_system_item(item, normalized_text, class_name)
            sender_attr = "system" if is_system else provider._resolve_sender_attr(item)
            message_type = "system" if is_system else provider._resolve_message_type(class_name, normalized_text)
            if is_system and normalized_text:
                current_label = normalized_text
            diagnostics.append(
                {
                    "visible_index": visible_index,
                    "runtime_id": runtime_id,
                    "class_name": class_name,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                    "rectangle": rect,
                    "is_system": is_system,
                    "sender_attr": sender_attr,
                    "message_type": message_type,
                    "timestamp_label": current_label if not is_system else normalized_text,
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    "visible_index": visible_index,
                    "error": str(exc),
                }
            )
    return diagnostics


def dump_wechat_uia_snapshot(
    talker_display_name: str = "",
    max_depth: int = 4,
    max_nodes: int = 300,
) -> dict:
    """Capture a best-effort snapshot of the current WeChat UIA state."""
    result = {
        "captured_at": int(time.time()),
        "wechat_version": "",
        "listener_profile": "",
        "hwnd": 0,
        "exe_path": "",
        "target_display_name": talker_display_name,
        "messages": [],
        "item_diagnostics": [],
        "chat_list_rect": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "tree": {},
        "errors": [],
    }
    provider = None

    try:
        version_info = detect_running_wechat()
    except Exception as exc:
        result["errors"].append(f"detect_failed: {exc}")
    else:
        result["wechat_version"] = version_info.version
        result["listener_profile"] = version_info.listener_profile
        result["hwnd"] = int(version_info.hwnd or 0)
        result["exe_path"] = version_info.exe_path
        provider = NativeUIARealtimeProvider(
            listener_profile=version_info.listener_profile or "debug",
            wechat_version=version_info.version,
            hwnd=version_info.hwnd,
        )

    if provider is not None:
        try:
            provider.initialize()
            provider.activate_main_window()
        except Exception as exc:
            result["errors"].append(f"initialize_failed: {exc}")
        else:
            if talker_display_name:
                try:
                    provider.open_chat(talker_display_name)
                except Exception as exc:
                    result["errors"].append(f"open_chat_failed: {exc}")
            try:
                provider._chat_list = provider._chat_list or provider._find_chat_list()
                result["chat_list_rect"] = _rect_to_dict(
                    _safe_call(lambda: provider._chat_list.rectangle()) if provider._chat_list else None
                )
            except Exception as exc:
                result["errors"].append(f"chat_list_detect_failed: {exc}")
            try:
                result["messages"] = [
                    {
                        "runtime_id": msg.runtime_id,
                        "sender_attr": msg.sender_attr,
                        "content": msg.content,
                        "message_type": msg.message_type,
                        "timestamp_label": msg.timestamp_label,
                        "timestamp": msg.timestamp,
                        "message_hash": msg.message_hash,
                        "is_system": msg.is_system,
                        "visible_index": msg.visible_index,
                        "metadata": msg.metadata,
                    }
                    for msg in provider.list_visible_messages()
                ]
            except Exception as exc:
                result["errors"].append(f"list_messages_failed: {exc}")
            result["item_diagnostics"] = collect_visible_item_diagnostics(provider)
            if provider._main_window is not None:
                result["tree"] = serialize_control_tree(
                    provider._main_window,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                )
        finally:
            provider.close()

    logs_dir = Path(LOG_DIR_PATH)
    logs_dir.mkdir(parents=True, exist_ok=True)
    dump_path = logs_dir / f"wechat_uia_dump_{int(time.time())}.json"
    with open(dump_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    result["path"] = str(dump_path)
    return result
