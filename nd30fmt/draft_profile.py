"""Bản nháp và thiết lập cá nhân theo mã hồ sơ bí mật, lưu trong DATA_DIR."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from . import jobs

_guard = threading.RLock()


class ProfileConflict(Exception):
    pass


def profile_path(code: str) -> Path:
    if not isinstance(code, str) or not re.fullmatch(r"[a-f0-9]{64}", code):
        raise ValueError("Mã hồ sơ không hợp lệ; hãy sao chép đủ mã đã tạo")
    return jobs.DATA_DIR / "draft_profiles" / (hashlib.sha256(code.encode("ascii")).hexdigest() + ".json")


def read_profile(code: str) -> dict | None:
    path = profile_path(code)
    with _guard:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"revision": data["revision"], "draft": data["draft"], "settings": data["settings"]}


def save_profile(code: str, payload: dict) -> dict:
    path = profile_path(code)
    if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict) or not isinstance(payload.get("settings"), dict):
        raise ValueError("Bản nháp hoặc cài đặt không hợp lệ")
    expected = payload.get("expected_revision")
    if type(expected) is not int or expected < 0:
        raise ValueError("Thiếu phiên bản hồ sơ hiện tại")
    data = json.dumps({"draft": payload["draft"], "settings": payload["settings"]}, ensure_ascii=False)
    if len(data.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Bản nháp vượt quá 2 MB")
    with _guard:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        revision = current["revision"] if current else 0
        if expected != revision:
            raise ProfileConflict("Hồ sơ đã thay đổi trên thiết bị khác; tải lại trước khi lưu")
        path.parent.mkdir(parents=True, exist_ok=True)
        next_revision = revision + 1
        stored = json.dumps({"revision": next_revision, "draft": payload["draft"],
                             "settings": payload["settings"]}, ensure_ascii=False)
        fd, temp = tempfile.mkstemp(prefix="draft-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(stored)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return {"revision": next_revision}
