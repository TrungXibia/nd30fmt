"""Mã truy cập nhiều người dùng.

- Mã quản trị: biến môi trường APP_TOKEN (mã đang dùng từ trước) -> quyền quản trị, chủ sở hữu "admin".
- Mã người dùng: quản trị viên tạo trong giao diện; chỉ lưu BĂM SHA-256 của mã (không lưu mã gốc),
  nên mã chỉ hiện một lần lúc tạo / cấp lại. Mỗi mã là một chủ sở hữu riêng: phiên làm việc (file tải
  lên, bản đã sửa, báo cáo) chỉ mã đó thấy được.
- Không đặt APP_TOKEN: chạy chế độ mở như trước (mọi người dùng chung chủ sở hữu "public"),
  không có chức năng quản trị.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from . import jobs

_guard = threading.RLock()
ADMIN_ID = "admin"
PUBLIC_ID = "public"


class UserError(RuntimeError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _path() -> Path:
    return jobs.DATA_DIR / "users.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> list[dict]:
    p = _path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(users: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _new_token() -> str:
    # 24 ký tự dễ đọc, không có ký tự dễ nhầm (0/O, 1/l/I)
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "vb-" + "".join(secrets.choice(alphabet) for _ in range(21))


def admin_token() -> str:
    return os.getenv("APP_TOKEN") or ""


def identify(token: str | None) -> dict | None:
    """Mã -> {"id", "name", "role"}; None nếu sai/khoá. Không đặt APP_TOKEN -> chế độ mở."""
    need = admin_token()
    if not need:
        return {"id": PUBLIC_ID, "name": "", "role": "open"}
    if not token:
        return None
    if hmac.compare_digest(token.encode("utf-8", "surrogateescape"), need.encode("utf-8", "surrogateescape")):
        return {"id": ADMIN_ID, "name": "Quản trị viên", "role": "admin"}
    h = hashlib.sha256(token.encode("utf-8", "surrogateescape")).hexdigest()
    with _guard:
        for u in _load():
            if hmac.compare_digest(u.get("token_hash", ""), h):
                if not u.get("active", True):
                    return None
                return {"id": u["id"], "name": u.get("name", ""), "role": "user"}
    return None


def _public(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "name", "note", "active", "created", "last_reset", "hint")}


def list_users() -> list[dict]:
    counts: dict[str, int] = {}
    if jobs.JOBS_DIR.exists():
        for d in jobs.JOBS_DIR.iterdir():
            try:
                owner = json.loads((d / "meta.json").read_text(encoding="utf-8")).get("owner") or ADMIN_ID
            except (OSError, json.JSONDecodeError):
                continue
            counts[owner] = counts.get(owner, 0) + 1
    with _guard:
        out = [dict(_public(u), jobs=counts.get(u["id"], 0)) for u in _load()]
    out.sort(key=lambda u: u.get("created") or 0)
    return out


def _clean_name(name) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise UserError("Nhập tên người dùng / đơn vị")
    if len(name) > 80:
        raise UserError("Tên tối đa 80 ký tự")
    return name


def create_user(name: str, note: str = "") -> dict:
    name = _clean_name(name)
    token = _new_token()
    with _guard:
        users = _load()
        if any(u.get("name", "").lower() == name.lower() for u in users):
            raise UserError("Đã có người dùng trùng tên")
        u = {"id": uuid.uuid4().hex[:12], "name": name, "note": str(note or "")[:200], "active": True,
             "created": time.time(), "token_hash": _hash(token), "hint": token[-4:]}
        users.append(u)
        _save(users)
    return dict(_public(u), token=token, jobs=0)


def _find(users: list[dict], uid: str) -> dict:
    for u in users:
        if u.get("id") == uid:
            return u
    raise UserError("Không tìm thấy người dùng", 404)


def update_user(uid: str, name=None, note=None, active=None) -> dict:
    with _guard:
        users = _load()
        u = _find(users, uid)
        if name is not None:
            name = _clean_name(name)
            if any(x is not u and x.get("name", "").lower() == name.lower() for x in users):
                raise UserError("Đã có người dùng trùng tên")
            u["name"] = name
        if note is not None:
            u["note"] = str(note)[:200]
        if active is not None:
            u["active"] = bool(active)
        _save(users)
        return _public(u)


def reset_token(uid: str) -> dict:
    token = _new_token()
    with _guard:
        users = _load()
        u = _find(users, uid)
        u["token_hash"], u["hint"], u["last_reset"] = _hash(token), token[-4:], time.time()
        _save(users)
        return dict(_public(u), token=token)


def delete_user(uid: str, purge: bool = False) -> int:
    """Xoá mã. purge=True: xoá luôn mọi phiên (tài liệu) của mã đó; ngược lại chuyển cho quản trị viên."""
    with _guard:
        users = _load()
        _find(users, uid)
        _save([u for u in users if u.get("id") != uid])
    moved = 0
    try:  # thư viện Markdown của mã này: xoá cùng hoặc chuyển cho quản trị viên
        from .mdlib import store as md_store
        moved += md_store.delete_owner(uid) if purge else md_store.reassign_owner(uid, ADMIN_ID)
    except Exception:  # noqa: BLE001 - không chặn việc xoá mã
        pass
    if jobs.JOBS_DIR.exists():
        for d in list(jobs.JOBS_DIR.iterdir()):
            meta_p = d / "meta.json"
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("owner") != uid:
                continue
            if purge:
                jobs.delete_job(d.name)
            else:
                meta["owner"] = ADMIN_ID
                meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            moved += 1
    return moved
