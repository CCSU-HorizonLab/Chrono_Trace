"""Helpers for persisted WeChat multi-account settings."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ...config import SETTINGS_PATH


WECHAT_ACCOUNTS_KEY = "wechat_accounts"
WECHAT_ACTIVE_ACCOUNT_KEY = "wechat_active_account_wxid"
LEGACY_WECHAT_KEYS = {
    "wechat_use_custom_path",
    "wechat_data_dir",
    "wechat_user_wxid",
    "wechat_db_key",
    "wechat_import_completed",
    "wechat_last_import_at",
    "wechat_last_import_total_size",
    "wechat_last_import_files",
}


def default_settings_path() -> Path:
    return Path(SETTINGS_PATH)


def _normalize_snapshot_files(raw_files: Any) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not isinstance(raw_files, list):
        return files

    for item in raw_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        files.append({
            "path": path,
            "kind": str(item.get("kind") or "").strip(),
            "size": int(item.get("size") or 0),
        })
    return files


def normalize_wechat_account(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None

    wxid = str(raw.get("wxid") or raw.get("current_user") or "").strip()
    if not wxid:
        return None

    label = str(raw.get("label") or "").strip() or wxid
    avatar = str(raw.get("avatar") or "").strip()
    wechat_dir = str(raw.get("wechat_dir") or "").strip()
    source = str(raw.get("source") or "auto").strip() or "auto"
    db_key = str(raw.get("db_key") or "").strip()

    last_import_at_raw = raw.get("last_import_at")
    last_import_at = int(last_import_at_raw) if last_import_at_raw not in (None, "") else None

    return {
        "wxid": wxid,
        "label": label,
        "avatar": avatar,
        "wechat_dir": wechat_dir,
        "source": source,
        "db_key": db_key,
        "import_completed": bool(raw.get("import_completed")),
        "last_import_at": last_import_at,
        "last_import_total_size": int(raw.get("last_import_total_size") or 0),
        "last_import_files": _normalize_snapshot_files(raw.get("last_import_files")),
    }


def normalize_wechat_accounts(raw_accounts: Any) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    seen = set()

    if not isinstance(raw_accounts, list):
        return accounts

    for raw in raw_accounts:
        normalized = normalize_wechat_account(raw)
        if not normalized:
            continue
        wxid = normalized["wxid"]
        if wxid in seen:
            continue
        seen.add(wxid)
        accounts.append(normalized)

    return accounts


def migrate_legacy_wechat_settings(settings: dict[str, Any]) -> bool:
    changed = False

    accounts = normalize_wechat_accounts(settings.get(WECHAT_ACCOUNTS_KEY))
    if settings.get(WECHAT_ACCOUNTS_KEY) != accounts:
        settings[WECHAT_ACCOUNTS_KEY] = accounts
        changed = True

    legacy_wxid = str(settings.get("wechat_user_wxid") or "").strip()
    legacy_dir = str(settings.get("wechat_data_dir") or "").strip()
    if legacy_wxid:
        legacy_account = normalize_wechat_account({
            "wxid": legacy_wxid,
            "label": legacy_wxid,
            "avatar": "",
            "wechat_dir": legacy_dir,
            "source": "custom" if settings.get("wechat_use_custom_path") else "auto",
            "db_key": str(settings.get("wechat_db_key") or "").strip(),
            "import_completed": bool(settings.get("wechat_import_completed")),
            "last_import_at": settings.get("wechat_last_import_at"),
            "last_import_total_size": settings.get("wechat_last_import_total_size") or 0,
            "last_import_files": settings.get("wechat_last_import_files") or [],
        })
        if legacy_account and not any(item["wxid"] == legacy_account["wxid"] for item in accounts):
            accounts.append(legacy_account)
            settings[WECHAT_ACCOUNTS_KEY] = accounts
            changed = True

    active_wxid = str(settings.get(WECHAT_ACTIVE_ACCOUNT_KEY) or "").strip()
    if active_wxid and not any(item["wxid"] == active_wxid for item in accounts):
        active_wxid = ""

    if not active_wxid and accounts:
        active_wxid = accounts[0]["wxid"]

    if settings.get(WECHAT_ACTIVE_ACCOUNT_KEY) != active_wxid:
        settings[WECHAT_ACTIVE_ACCOUNT_KEY] = active_wxid
        changed = True

    return changed


def get_wechat_accounts(settings: dict[str, Any]) -> list[dict[str, Any]]:
    migrate_legacy_wechat_settings(settings)
    return [dict(item) for item in normalize_wechat_accounts(settings.get(WECHAT_ACCOUNTS_KEY))]


def get_active_wechat_account_wxid(settings: dict[str, Any]) -> str:
    migrate_legacy_wechat_settings(settings)
    return str(settings.get(WECHAT_ACTIVE_ACCOUNT_KEY) or "").strip()


def get_active_wechat_account(settings: dict[str, Any]) -> Optional[dict[str, Any]]:
    active_wxid = get_active_wechat_account_wxid(settings)
    if not active_wxid:
        return None
    return get_wechat_account(settings, active_wxid)


def get_wechat_account(settings: dict[str, Any], wxid: str) -> Optional[dict[str, Any]]:
    normalized_wxid = str(wxid or "").strip()
    if not normalized_wxid:
        return None
    for account in get_wechat_accounts(settings):
        if account["wxid"] == normalized_wxid:
            return account
    return None


def upsert_wechat_account(settings: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    migrate_legacy_wechat_settings(settings)
    normalized = normalize_wechat_account(account)
    if not normalized:
        raise ValueError("Invalid WeChat account payload")

    accounts = get_wechat_accounts(settings)
    replaced = False
    for index, existing in enumerate(accounts):
        if existing["wxid"] != normalized["wxid"]:
            continue
        merged = dict(existing)
        merged.update(normalized)
        accounts[index] = normalize_wechat_account(merged) or normalized
        replaced = True
        break

    if not replaced:
        accounts.append(normalized)

    settings[WECHAT_ACCOUNTS_KEY] = accounts
    if not get_active_wechat_account_wxid(settings):
        settings[WECHAT_ACTIVE_ACCOUNT_KEY] = normalized["wxid"]
    return normalized


def set_active_wechat_account(settings: dict[str, Any], wxid: str) -> str:
    normalized_wxid = str(wxid or "").strip()
    if normalized_wxid and not any(item["wxid"] == normalized_wxid for item in get_wechat_accounts(settings)):
        raise ValueError(f"WeChat account not found: {normalized_wxid}")
    settings[WECHAT_ACTIVE_ACCOUNT_KEY] = normalized_wxid
    return normalized_wxid


def build_custom_paths(account: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
    if not account:
        return None

    wechat_dir = str(account.get("wechat_dir") or "").strip()
    wxid = str(account.get("wxid") or "").strip()
    if not wechat_dir or not wxid:
        return None

    return {
        "wechat_dir": wechat_dir,
        "current_user": wxid,
        "account_wxid": wxid,
    }


def update_wechat_account_import_state(
    settings: dict[str, Any],
    wxid: str,
    *,
    snapshot: Optional[dict[str, Any]] = None,
    db_key: Optional[str] = None,
    wechat_dir: Optional[str] = None,
    source: Optional[str] = None,
    label: Optional[str] = None,
    avatar: Optional[str] = None,
    import_completed: Optional[bool] = None,
    clear_import_state: bool = False,
) -> dict[str, Any]:
    current = get_wechat_account(settings, wxid) or {"wxid": wxid}
    merged = dict(current)

    if db_key is not None:
        merged["db_key"] = db_key
    if wechat_dir is not None:
        merged["wechat_dir"] = wechat_dir
    if source is not None:
        merged["source"] = source
    if label is not None and str(label).strip():
        merged["label"] = str(label).strip()
    if avatar is not None:
        merged["avatar"] = str(avatar).strip()

    if clear_import_state:
        merged["import_completed"] = False
        merged["last_import_at"] = None
        merged["last_import_total_size"] = 0
        merged["last_import_files"] = []

    if snapshot is not None:
        merged["import_completed"] = True if import_completed is None else bool(import_completed)
        merged["last_import_at"] = snapshot.get("captured_at")
        merged["last_import_total_size"] = int(snapshot.get("total_size") or 0)
        merged["last_import_files"] = _normalize_snapshot_files(snapshot.get("files"))
    elif import_completed is not None:
        merged["import_completed"] = bool(import_completed)

    normalized = upsert_wechat_account(settings, merged)
    if not get_active_wechat_account_wxid(settings):
        settings[WECHAT_ACTIVE_ACCOUNT_KEY] = normalized["wxid"]
    return normalized


def load_settings_from_file(path: Optional[Path] = None) -> dict[str, Any]:
    settings_path = path or default_settings_path()
    if not settings_path.exists():
        settings: dict[str, Any] = {}
    else:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}

    migrate_legacy_wechat_settings(settings)
    try:
        from ..realtime.rag_config import apply_rag_defaults

        apply_rag_defaults(settings)
    except Exception:
        pass
    return settings


def save_settings_to_file(settings: dict[str, Any], path: Optional[Path] = None) -> None:
    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

