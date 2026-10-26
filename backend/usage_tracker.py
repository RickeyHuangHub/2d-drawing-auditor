"""
Token 用量跟踪与每日限额控制（部署模式）。
- 记录每次 AI 调用的 usage 到 data/usage.json（按日期累积）
- 普通用户受每日限额限制，管理员无限额
- 单进程内线程安全；文件原子写入（临时文件替换）
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, ACCESS_CONFIG

USAGE_PATH = DATA_DIR / "usage.json"
_lock = threading.Lock()
_usages_cache: dict = {}
_loaded = False


def _load() -> dict:
    global _loaded
    if _loaded:
        return _usages_cache
    if USAGE_PATH.exists():
        try:
            with open(USAGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _usages_cache.update(data)
        except Exception:
            pass
    _loaded = True
    return _usages_cache


def _save() -> None:
    tmp = USAGE_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_usages_cache, f, ensure_ascii=False, indent=2)
        tmp.replace(USAGE_PATH)
    except Exception:
        pass


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_today_usage() -> dict:
    """当日用量：{"date","prompt","completion","total","calls"}"""
    with _lock:
        _load()
        d = _usages_cache.get(_today(), {})
        return {
            "date": _today(),
            "prompt": int(d.get("prompt", 0)),
            "completion": int(d.get("completion", 0)),
            "total": int(d.get("total", 0)),
            "calls": int(d.get("calls", 0)),
        }


def record_usage(prompt_tokens: int, completion_tokens: int) -> dict:
    """记录一次 AI 调用用量，返回累计后的当日用量"""
    with _lock:
        _load()
        key = _today()
        d = _usages_cache.setdefault(key, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        d["prompt"] = int(d.get("prompt", 0)) + int(prompt_tokens or 0)
        d["completion"] = int(d.get("completion", 0)) + int(completion_tokens or 0)
        d["total"] = int(d.get("total", 0)) + int(prompt_tokens or 0) + int(completion_tokens or 0)
        d["calls"] = int(d.get("calls", 0)) + 1
        _save()
        return {
            "date": key,
            "prompt": d["prompt"],
            "completion": d["completion"],
            "total": d["total"],
            "calls": d["calls"],
        }


def get_daily_token_limit() -> int:
    return int(ACCESS_CONFIG.get("daily_token_limit", 2000000))


def quota_exceeded() -> bool:
    """当日普通用户额度是否已用尽"""
    return get_today_usage()["total"] >= get_daily_token_limit()


def quota_info() -> dict:
    """前端展示用：当日用量与限额"""
    u = get_today_usage()
    limit = get_daily_token_limit()
    return {
        "date": u["date"],
        "prompt": u["prompt"],
        "completion": u["completion"],
        "total": u["total"],
        "calls": u["calls"],
        "daily_token_limit": limit,
        "exceeded": quota_exceeded(),
        "remaining": max(limit - u["total"], 0),
    }