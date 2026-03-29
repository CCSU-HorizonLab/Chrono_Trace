"""Native UI Automation provider for supported WeChat desktop versions."""

from __future__ import annotations

import logging
import re
import time

from .base import ProviderInitError, RealtimeProvider, UINotAccessibleError
from .models import (
    RealtimeMessage,
    build_message_hash,
    normalize_text,
    runtime_id_to_string,
)

logger = logging.getLogger(__name__)

TIME_LABEL_RE = re.compile(
    r"^("
    r"\d{1,2}:\d{2}"
    r"|昨天\s+\d{1,2}:\d{2}"
    r"|前天\s+\d{1,2}:\d{2}"
    r"|\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}"
    r"|星期[一二三四五六日天]\s+\d{1,2}:\d{2}"
    r"|周[一二三四五六日天]\s+\d{1,2}:\d{2}"
    r")$"
)
EMOJI_ONLY_RE = re.compile(r"^[\W_]{1,8}$")
SYSTEM_TEXT_PREFIXES = (
    "以下是新消息",
    "以下为新消息",
    "你撤回了一条消息",
    "对方撤回了一条消息",
)
CHAT_MESSAGE_AUTOMATION_ID = "chat_message_list"
SESSION_LIST_AUTOMATION_ID = "session_list"
CHAT_ITEM_CLASS_NAMES = {
    "mmui::ChatBubbleItemView",
    "mmui::ChatTextItemView",
    "mmui::ChatItemView",
}
SHELL_ONLY_CLASS_NAMES = {
    "Qt51514QWindowIcon",
    "MMUIRenderSubWindowHW",
}


def _classify_bubble_midpoint(active_mid: float, width: int) -> str:
    """Classify a bubble by its detected active midpoint inside a row screenshot."""
    if width <= 0:
        return ""
    if active_mid <= width * 0.38:
        return "friend"
    if active_mid >= width * 0.62:
        return "self"
    return ""


def _build_active_segments(
    column_activity: list[int],
    active_threshold: int,
    gap_tolerance: int,
) -> list[tuple[int, int]]:
    """Build merged active column spans from per-column activity counts."""
    active_indices = [index for index, count in enumerate(column_activity) if count >= active_threshold]
    if not active_indices:
        return []

    segments: list[tuple[int, int]] = []
    start = active_indices[0]
    end = start
    for index in active_indices[1:]:
        if index - end <= max(1, gap_tolerance):
            end = index
            continue
        segments.append((start, end))
        start = index
        end = index
    segments.append((start, end))
    return segments


def _resolve_primary_active_midpoint(
    column_activity: list[int],
    width: int,
    active_threshold: int,
) -> float | None:
    """Pick the dominant activity span and return its weighted midpoint."""
    if width <= 0 or not column_activity:
        return None

    gap_tolerance = max(6, int(width * 0.03))
    segments = _build_active_segments(column_activity, active_threshold, gap_tolerance)
    if not segments:
        return None

    best_segment = None
    best_score = -1
    for start, end in segments:
        segment_counts = column_activity[start : end + 1]
        score = sum(segment_counts)
        if score > best_score:
            best_score = score
            best_segment = (start, end)
    if best_segment is None:
        return None

    start, end = best_segment
    weighted_total = 0
    weight_sum = 0
    for index in range(start, end + 1):
        weight = int(column_activity[index] or 0)
        if weight <= 0:
            continue
        weighted_total += index * weight
        weight_sum += weight
    if weight_sum <= 0:
        return (start + end) / 2
    return weighted_total / weight_sum


class NativeUIARealtimeProvider(RealtimeProvider):
    """Best-effort realtime provider using pywinauto UI Automation."""

    backend_name = "native_uia"

    def __init__(self, listener_profile: str, wechat_version: str = "", hwnd: int = 0):
        super().__init__()
        self.listener_profile = listener_profile
        self.wechat_version = wechat_version
        self._hwnd = int(hwnd or 0)
        self._main_window = None
        self._chat_list = None
        self._chat_rect = None

    def _import_backend(self):
        try:
            from pywinauto import Application
            from pywinauto.keyboard import send_keys
        except Exception as exc:
            raise ProviderInitError(f"pywinauto unavailable: {exc}") from exc
        return Application, send_keys

    def initialize(self) -> None:
        Application, _ = self._import_backend()
        if not self._hwnd:
            from .detector import detect_running_wechat

            info = detect_running_wechat()
            self._hwnd = int(info.hwnd or 0)
            self.wechat_version = self.wechat_version or info.version
            self.listener_profile = self.listener_profile or info.listener_profile
        if not self._hwnd:
            raise UINotAccessibleError("ui_not_accessible: WeChat main window not found")

        try:
            app = Application(backend="uia").connect(handle=self._hwnd)
            self._main_window = app.window(handle=self._hwnd)
            self._main_window.wait("exists enabled visible ready", timeout=5)
        except Exception as exc:
            raise UINotAccessibleError(
                f"ui_not_accessible: unable to bind main window ({exc})"
            ) from exc
        self._ensure_accessible_tree()

    def activate_main_window(self) -> bool:
        if self._main_window is None:
            self.initialize()
        try:
            self._main_window.restore()
        except Exception:
            pass
        try:
            self._main_window.set_focus()
        except Exception as exc:
            logger.debug("Failed to focus WeChat window: %s", exc)
        return True

    def _visible_descendants(self, control_type: str | None = None):
        if self._main_window is None:
            self.initialize()
        kwargs = {}
        if control_type:
            kwargs["control_type"] = control_type
        try:
            descendants = self._main_window.descendants(**kwargs)
        except Exception:
            return []
        result = []
        for item in descendants:
            try:
                if item.is_visible():
                    result.append(item)
            except Exception:
                continue
        return result

    def _ensure_accessible_tree(self, attempts: int = 3, delay: float = 0.2) -> None:
        """Fail fast when UIA only exposes the outer Qt shell panes."""
        if self._main_window is None:
            raise UINotAccessibleError("ui_not_accessible: WeChat main window not initialized")

        last_visible_descendants = []
        for attempt in range(max(1, int(attempts or 1))):
            try:
                descendants = list(self._main_window.descendants())
            except Exception as exc:
                raise UINotAccessibleError(
                    f"ui_not_accessible: unable to enumerate WeChat descendants ({exc})"
                ) from exc

            visible_descendants = []
            meaningful_visible_descendants = []
            for item in descendants:
                try:
                    if not item.is_visible():
                        continue
                    class_name = str(item.class_name() or "")
                    control_type = str(getattr(item.element_info, "control_type", "") or "")
                    automation_id = str(getattr(item.element_info, "automation_id", "") or "")
                except Exception:
                    continue
                visible_descendants.append((class_name, control_type, automation_id))
                if automation_id or class_name not in SHELL_ONLY_CLASS_NAMES or control_type != "Pane":
                    meaningful_visible_descendants.append((class_name, control_type, automation_id))

            last_visible_descendants = visible_descendants
            if meaningful_visible_descendants:
                return

            if attempt + 1 < max(1, int(attempts or 1)) and delay > 0:
                time.sleep(delay)

        raise UINotAccessibleError(
            "ui_not_accessible: WeChat UIA tree unavailable; only shell panes are visible. "
            f"visible_descendants={last_visible_descendants[:6]}. "
            "Try reopening WeChat; if it still fails, enable Narrator once before login and then relaunch WeChat."
        )

    def _find_chat_list(self):
        candidates = []
        for control in self._visible_descendants("List"):
            try:
                items = control.children(control_type="ListItem")
            except Exception:
                continue
            if not items:
                continue

            score = 0
            automation_id = str(getattr(control.element_info, "automation_id", "") or "")
            control_name = normalize_text(control.window_text())
            texts = []
            class_names = []
            for item in items[:8]:
                try:
                    class_names.append(item.class_name() or "")
                    texts.append(item.window_text() or "")
                except Exception:
                    continue

            joined_class = " ".join(class_names)
            joined_text = " ".join(texts)
            if automation_id == CHAT_MESSAGE_AUTOMATION_ID:
                score += 100
            if automation_id == SESSION_LIST_AUTOMATION_ID:
                score -= 30
            if control_name == "消息":
                score += 20
            if control_name == "会话":
                score -= 10
            if "Chat" in joined_class or "mmui::Chat" in joined_class:
                score += 5
            if any(TIME_LABEL_RE.match(normalize_text(text)) for text in texts if text):
                score += 3
            if "消息" in joined_text or "图片" in joined_text or "文件" in joined_text:
                score += 1
            try:
                rect = control.rectangle()
                score += max(0, int((rect.right - rect.left) / 200))
            except Exception:
                pass
            candidates.append((score, control))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _find_session_list(self):
        candidates = []
        for control in self._visible_descendants("List"):
            try:
                items = list(control.children(control_type="ListItem"))
            except Exception:
                continue
            if not items:
                continue

            score = 0
            automation_id = str(getattr(control.element_info, "automation_id", "") or "")
            control_name = normalize_text(control.window_text())
            class_names = []
            for item in items[:8]:
                try:
                    class_names.append(str(item.class_name() or ""))
                except Exception:
                    continue

            if automation_id == SESSION_LIST_AUTOMATION_ID:
                score += 100
            if control_name == "会话":
                score += 30
            if all(name == "mmui::ChatSessionCell" for name in class_names if name):
                score += 20
            try:
                rect = control.rectangle()
                score += max(0, int((rect.right - rect.left) / 150))
            except Exception:
                pass
            candidates.append((score, control))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _iter_session_items(self):
        session_list = self._find_session_list()
        if session_list is None:
            return []
        items = []
        try:
            raw_items = list(session_list.children(control_type="ListItem"))
        except Exception:
            raw_items = []
        for item in raw_items:
            try:
                class_name = str(item.class_name() or "")
                automation_id = str(getattr(item.element_info, "automation_id", "") or "")
                if class_name == "mmui::ChatSessionCell" or automation_id.startswith("session_item_"):
                    items.append(item)
            except Exception:
                continue
        items.sort(key=lambda node: (node.rectangle().top, node.rectangle().left))
        return items

    def _iter_direct_chat_items(self):
        items = []
        for item in self._visible_descendants("ListItem"):
            try:
                class_name = str(item.class_name() or "")
                automation_id = str(getattr(item.element_info, "automation_id", "") or "")
                if automation_id == SESSION_LIST_AUTOMATION_ID or class_name == "mmui::ChatSessionCell":
                    continue
                if automation_id and CHAT_MESSAGE_AUTOMATION_ID in automation_id:
                    items.append(item)
                    continue
                if class_name in CHAT_ITEM_CLASS_NAMES:
                    items.append(item)
            except Exception:
                continue
        items.sort(key=lambda node: (node.rectangle().top, node.rectangle().left))
        return items

    def _refresh_chat_rect(self, items=None):
        if items:
            try:
                left = min(item.rectangle().left for item in items)
                top = min(item.rectangle().top for item in items)
                right = max(item.rectangle().right for item in items)
                bottom = max(item.rectangle().bottom for item in items)
                self._chat_rect = (left, top, right, bottom)
                return
            except Exception:
                pass
        if self._chat_list is not None:
            try:
                rect = self._chat_list.rectangle()
                self._chat_rect = (rect.left, rect.top, rect.right, rect.bottom)
                return
            except Exception:
                pass
        self._chat_rect = None

    def _find_session_entry(self, display_name: str):
        normalized_target = normalize_text(display_name)
        for item in self._iter_session_items():
            try:
                text = normalize_text(item.window_text())
            except Exception:
                continue
            if not text or text == normalized_target:
                if text == normalized_target:
                    return item
                continue
            if normalized_target in text:
                return item
        return None

    def _find_search_edit(self):
        edit_controls = self._visible_descendants("Edit")
        if not edit_controls:
            return None

        session_list = self._find_session_list()
        session_rect = None
        try:
            session_rect = session_list.rectangle() if session_list is not None else None
        except Exception:
            session_rect = None

        candidates = []
        for control in edit_controls:
            try:
                automation_id = str(getattr(control.element_info, "automation_id", "") or "")
                class_name = str(control.class_name() or "")
                rect = control.rectangle()
            except Exception:
                continue
            if automation_id == "chat_input_field":
                continue

            score = 0
            if rect.top < 400:
                score += 30
            if session_rect is not None:
                if rect.left >= session_rect.left - 40 and rect.right <= session_rect.right + 40:
                    score += 40
                if rect.bottom <= session_rect.top + 10:
                    score += 20
            if "Validator" in class_name:
                score += 10
            candidates.append((score, control))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], -item[1].rectangle().top), reverse=True)
        return candidates[0][1]

    def _is_target_chat_active(self, display_name: str) -> bool:
        normalized_target = normalize_text(display_name)
        if not normalized_target or self._main_window is None:
            return False
        try:
            main_rect = self._main_window.rectangle()
            header_bottom = main_rect.top + max(120, int((main_rect.bottom - main_rect.top) * 0.18))
        except Exception:
            return False

        has_visible_chat_items = bool(self._iter_direct_chat_items())
        if not has_visible_chat_items:
            return False

        for control in self._visible_descendants("Text"):
            try:
                text = normalize_text(control.window_text())
                if text != normalized_target:
                    continue
                rect = control.rectangle()
            except Exception:
                continue
            if rect.top <= header_bottom and rect.left >= main_rect.left + 250:
                return True
        return False

    def _visible_header_texts(self) -> list[str]:
        if self._main_window is None:
            return []
        try:
            main_rect = self._main_window.rectangle()
            header_bottom = main_rect.top + max(120, int((main_rect.bottom - main_rect.top) * 0.18))
        except Exception:
            return []

        header_texts: list[str] = []
        for control in self._visible_descendants("Text"):
            try:
                text = normalize_text(control.window_text())
                rect = control.rectangle()
            except Exception:
                continue
            if not text:
                continue
            if rect.top <= header_bottom and rect.left >= main_rect.left + 250:
                if text not in header_texts:
                    header_texts.append(text)
        return header_texts

    def _focus_search_and_open(self, display_name: str) -> bool:
        _, send_keys = self._import_backend()
        self.activate_main_window()
        send_keys("^f", pause=0.05)
        time.sleep(0.2)
        edit = self._find_search_edit()
        if edit is None:
            return False
        try:
            edit.set_edit_text(display_name)
        except Exception:
            try:
                edit.click_input()
                send_keys("^a{BACKSPACE}", pause=0.02)
                send_keys(display_name, with_spaces=True, pause=0.02)
            except Exception:
                return False
        time.sleep(0.3)
        send_keys("{ENTER}", pause=0.03)
        return True

    def open_chat(self, display_name: str, expected_display_name: str | None = None) -> bool:
        if self._main_window is None:
            self.initialize()
        self._ensure_accessible_tree(attempts=1, delay=0.0)
        expected_name = (expected_display_name or display_name or "").strip()
        search_name = (display_name or "").strip()
        self.current_display_name = expected_name or search_name
        self.activate_main_window()
        if expected_name and self._is_target_chat_active(expected_name):
            self._chat_list = self._find_chat_list()
            self._refresh_chat_rect(self._iter_direct_chat_items())
            return True

        target = self._find_session_entry(search_name)
        if target is not None:
            try:
                target.click_input()
            except Exception as exc:
                logger.debug("Direct session click failed: %s", exc)
        elif not self._focus_search_and_open(search_name):
            raise ProviderInitError(f"Unable to locate chat '{search_name}'")

        last_error = ""
        for _ in range(10):
            time.sleep(0.25)
            self._chat_list = self._find_chat_list()
            direct_items = self._iter_direct_chat_items()
            self._refresh_chat_rect(direct_items)
            if expected_name and self._is_target_chat_active(expected_name):
                return True
            if self._chat_list is not None:
                try:
                    items = list(self._chat_list.children(control_type="ListItem"))
                except Exception as exc:
                    last_error = str(exc)
                else:
                    if items and not all(item.class_name() == "mmui::ChatSessionCell" for item in items) and expected_name:
                        self._refresh_chat_rect(items)
                        if self._is_target_chat_active(expected_name):
                            return True
        header_texts = self._visible_header_texts()
        raise ProviderInitError(
            f"Unable to confirm target chat '{expected_name or search_name}' after search '{search_name}'"
            + (f"; visible_headers={header_texts[:6]}" if header_texts else "")
            + (f"; chat_list_error={last_error}" if last_error else "")
        )

    def _iter_chat_items(self):
        direct_items = self._iter_direct_chat_items()
        if direct_items:
            self._refresh_chat_rect(direct_items)
            return direct_items
        if self._chat_list is None:
            self._chat_list = self._find_chat_list()
        if self._chat_list is None:
            self._ensure_accessible_tree(attempts=1, delay=0.0)
            raise UINotAccessibleError("ui_not_accessible: chat list not found")
        try:
            items = list(self._chat_list.children(control_type="ListItem"))
        except Exception as exc:
            raise UINotAccessibleError(
                f"ui_not_accessible: unable to read chat items ({exc})"
            ) from exc
        if items and all(item.class_name() == "mmui::ChatSessionCell" for item in items):
            raise UINotAccessibleError("ui_not_accessible: selected session list instead of chat list")
        self._refresh_chat_rect(items)
        return items

    def _looks_like_system_item(self, item, text: str, class_name: str) -> bool:
        del item
        if TIME_LABEL_RE.match(text):
            return True
        if "Time" in class_name or "System" in class_name:
            return True
        if any(text.startswith(prefix) for prefix in SYSTEM_TEXT_PREFIXES):
            return True
        return False

    def _resolve_sender_attr(self, item) -> str:
        if self._chat_rect is None:
            self._refresh_chat_rect()
        if self._chat_rect is None:
            return ""
        try:
            center_x = (self._chat_rect[0] + self._chat_rect[2]) / 2
        except Exception:
            return ""

        child_rects = []
        item_rect = None
        try:
            descendants = item.descendants()
        except Exception:
            descendants = []
        for child in descendants:
            try:
                if not child.is_visible():
                    continue
                rect = child.rectangle()
                child_rects.append((rect.left, rect.right))
            except Exception:
                continue
        try:
            rect = item.rectangle()
            item_rect = (rect.left, rect.right)
        except Exception:
            item_rect = None
        if not child_rects and item_rect is not None:
            child_rects.append(item_rect)
        if not child_rects:
            return self._resolve_sender_attr_from_screenshot(item)

        left_edge = min(pair[0] for pair in child_rects)
        right_edge = max(pair[1] for pair in child_rects)
        if item_rect is not None and (right_edge - left_edge) >= (item_rect[1] - item_rect[0]) * 0.9:
            return self._resolve_sender_attr_from_screenshot(item)
        if right_edge - center_x > 80 and right_edge > center_x:
            return "self"
        if center_x - left_edge > 80 and left_edge < center_x:
            return "friend"
        return self._resolve_sender_attr_from_screenshot(item)

    def _resolve_sender_attr_from_screenshot(self, item) -> str:
        try:
            from PIL import ImageGrab
        except Exception as exc:
            logger.debug("Pillow/ImageGrab unavailable for sender detection: %s", exc)
            return ""
        try:
            rect = item.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return ""
        width = max(0, bbox[2] - bbox[0])
        height = max(0, bbox[3] - bbox[1])
        if width <= 8 or height <= 8:
            return ""
        try:
            image = ImageGrab.grab(bbox=bbox).convert("RGB")
        except Exception as exc:
            logger.debug("Screenshot-based sender detection failed: %s", exc)
            return ""

        background_samples = [
            image.getpixel((min(5, width - 1), min(height // 2, height - 1))),
            image.getpixel((width // 2, min(2, height - 1))),
            image.getpixel((max(0, width - 5), min(height // 2, height - 1))),
        ]
        background = tuple(
            sum(sample[channel] for sample in background_samples) // len(background_samples)
            for channel in range(3)
        )
        threshold = 50
        min_active_pixels = max(4, height // 10)
        column_activity = [0] * width
        for x in range(width):
            active_pixels = 0
            for y in range(height):
                pixel = image.getpixel((x, y))
                if (
                    abs(pixel[0] - background[0])
                    + abs(pixel[1] - background[1])
                    + abs(pixel[2] - background[2])
                ) > threshold:
                    active_pixels += 1
            column_activity[x] = active_pixels

        active_mid = _resolve_primary_active_midpoint(
            column_activity,
            width,
            min_active_pixels,
        )
        if active_mid is None:
            return ""
        return _classify_bubble_midpoint(active_mid, width)

    def _resolve_message_type(self, class_name: str, text: str) -> str:
        lowered = text.lower()
        if text == "图片" or "image" in lowered:
            return "image"
        if "视频" in text or "video" in lowered:
            return "video"
        if "语音" in text or "voice" in lowered:
            return "voice"
        if text.startswith("[链接]") or text.startswith("链接"):
            return "link"
        if "文件" in text or "file" in lowered:
            return "file"
        if "emoji" in lowered or class_name.endswith("EmojiItemView"):
            return "emoji"
        if EMOJI_ONLY_RE.match(text) and len(text) <= 8:
            return "emoji"
        if "ReferItemView" in class_name and text:
            return "image"
        return "text"

    def list_visible_messages(self) -> list[RealtimeMessage]:
        items = self._iter_chat_items()
        current_label = ""
        messages: list[RealtimeMessage] = []
        occurrence_map: dict[str, int] = {}
        for visible_index, item in enumerate(items):
            try:
                class_name = str(item.class_name() or "")
                text = normalize_text(item.window_text())
            except Exception:
                continue

            runtime_id = runtime_id_to_string(getattr(item.element_info, "runtime_id", ""))
            if self._looks_like_system_item(item, text, class_name):
                current_label = text or current_label
                messages.append(
                    RealtimeMessage(
                        runtime_id=runtime_id,
                        sender_attr="system",
                        content=text,
                        message_type="system",
                        timestamp_label=text,
                        timestamp=0,
                        message_hash="",
                        is_system=True,
                        visible_index=visible_index,
                    )
                )
                continue

            sender_attr = self._resolve_sender_attr(item)
            if not sender_attr:
                logger.debug("Skipping ambiguous chat item at index %s", visible_index)
                continue

            message_type = self._resolve_message_type(class_name, text)
            occurrence_key = "|".join(
                [
                    sender_attr,
                    message_type,
                    text,
                    current_label,
                    runtime_id or str(visible_index),
                ]
            )
            occurrence_map[occurrence_key] = occurrence_map.get(occurrence_key, 0) + 1
            occurrence = occurrence_map[occurrence_key]
            message_hash = build_message_hash(
                self.listener_profile,
                sender_attr,
                message_type,
                text,
                0,
                runtime_id or f"{visible_index}:{occurrence}",
            )
            messages.append(
                RealtimeMessage(
                    runtime_id=runtime_id,
                    sender_attr=sender_attr,
                    content=text,
                    message_type=message_type,
                    timestamp_label=current_label,
                    timestamp=0,
                    message_hash=message_hash,
                    is_system=False,
                    visible_index=visible_index,
                    metadata={"class_name": class_name, "occurrence": occurrence},
                )
            )
        return messages

    def scroll_up(self, wheel_times: int = 3) -> bool:
        if self._chat_list is None:
            self._chat_list = self._find_chat_list()
        if self._chat_list is None:
            return False
        step_count = max(1, int(wheel_times or 1))
        try:
            self._chat_list.scroll("up", "line", count=step_count, retry_interval=0.05)
            time.sleep(max(0.12, step_count * 0.05))
            return True
        except Exception as exc:
            logger.debug("native_uia line scroll up failed, fallback to wheel: %s", exc)
        try:
            self._chat_list.wheel_mouse_input(wheel_dist=step_count)
            time.sleep(max(0.12, step_count * 0.05))
            return True
        except Exception as exc:
            logger.debug("native_uia wheel scroll up failed, fallback to page: %s", exc)
        try:
            self._chat_list.type_keys("{PGUP}", pause=0.05)
            time.sleep(max(0.18, step_count * 0.08))
            return True
        except Exception as exc:
            logger.debug("native_uia page scroll up failed: %s", exc)
            return False

    def scroll_down(self, wheel_times: int = 3) -> bool:
        if self._chat_list is None:
            self._chat_list = self._find_chat_list()
        if self._chat_list is None:
            return False
        step_count = max(1, int(wheel_times or 1))
        try:
            self._chat_list.scroll("down", "line", count=step_count, retry_interval=0.05)
            time.sleep(max(0.12, step_count * 0.05))
            return True
        except Exception as exc:
            logger.debug("native_uia line scroll down failed, fallback to wheel: %s", exc)
        try:
            self._chat_list.wheel_mouse_input(wheel_dist=-step_count)
            time.sleep(max(0.12, step_count * 0.05))
            return True
        except Exception as exc:
            logger.debug("native_uia wheel scroll down failed, fallback to page: %s", exc)
        try:
            self._chat_list.type_keys("{PGDN}", pause=0.05)
            time.sleep(max(0.18, step_count * 0.08))
            return True
        except Exception as exc:
            logger.debug("native_uia page scroll down failed: %s", exc)
            return False

    def get_hwnd(self) -> int:
        return int(self._hwnd or 0)

    def close(self) -> None:
        self._chat_list = None
        self._main_window = None
