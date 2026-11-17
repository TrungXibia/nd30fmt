"""Dịch vụ web: tải Word lên -> xem trước bản gốc/bản đã sửa, tô lỗi, chỉnh thông số, sửa lại.

Chạy:  uvicorn nd30fmt.web:app --host 0.0.0.0 --port 8030
Biến môi trường:
  APP_TOKEN          nếu đặt: bắt buộc gửi token (header X-App-Token)
  ND30_SPEC          file quy chuẩn gốc (mặc định config/nd30_spec.yaml)
  DATA_DIR           thư mục dữ liệu (phiên làm việc, quy chuẩn đã lưu) – mặc định /tmp/nd30fmt
  JOB_TTL_HOURS      thời gian giữ phiên (mặc định 24 giờ)
  MAX_UPLOAD_MB      giới hạn dung lượng mỗi file (mặc định 20)
  MAX_FILES          số file tối đa mỗi lần (mặc định 20)
  ROOT_PATH          tiền tố URL khi chạy sau reverse proxy (vd /nd30)
"""
from __future__ import annotations

import base64
import logging
import hmac
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import threading
import time
from collections import deque

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__, core, jobs, users
from .draft_profile import ProfileConflict, read_profile, save_profile
from .composer_spec import party_composer_spec
from .import_draft import parse_draft_bytes
from .pipeline import process
from .composer import classify as compose_classify
from .composer import docx_writer as compose_docx
from .composer import importer as compose_importer
from .composer import layout as compose_layout
from .composer import schema as compose_schema
from .composer.validate import validate_draft
from .mdlib import compose as md_compose
from .mdlib import store as md_store
from .mdlib import tasks as md_tasks

log = logging.getLogger("nd30fmt")
from .spec import SpecKeyError, build_spec, public_raw

MAX_MB = float(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_FILES = int(os.getenv("MAX_FILES", "20"))
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ND30 Format Checker", version=__version__, root_path=os.getenv("ROOT_PATH", ""))
# dữ liệu xem trước của văn bản dài có thể vài MB JSON -> nén giảm ~10 lần khi truyền về trình duyệt
app.add_middleware(GZipMiddleware, minimum_size=2048)


# ------------------------------------------------------------------ bảo mật chung
# Trang chia sẻ công khai hiển thị nội dung người dùng: chạy trong sandbox (origin riêng, không script),
# nên dù nội dung có lọt mã độc cũng không đọc được mã truy cập lưu trong trình duyệt.
_PUBLIC_CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'none'; sandbox allow-popups allow-popups-to-escape-sandbox")
_APP_CSP = "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"


_WEAK_TOKENS = {"doi-ma-nay", "changeme", "admin", "123456", "password"}


def _warn_config() -> None:
    tok = os.getenv("APP_TOKEN") or ""
    if os.getenv("ND30_DESKTOP") == "1":
        return
    if not tok:
        log.warning("APP_TOKEN chưa đặt: ai truy cập được trang đều dùng được công cụ. Đặt APP_TOKEN khi mở ra Internet.")
    elif tok in _WEAK_TOKENS or len(tok) < 16:
        log.warning("APP_TOKEN quá ngắn hoặc là giá trị mẫu: hãy đổi sang mã ngẫu nhiên >= 16 ký tự "
                    "(python -c \"import secrets;print(secrets.token_urlsafe(24))\").")


_warn_config()


@app.exception_handler(SpecKeyError)
async def _spec_key_missing(request: Request, exc: SpecKeyError):
    log.error("%s", exc)
    return JSONResponse({"detail": "Máy chủ chưa cấu hình khoá giải mã quy chuẩn (ND30_SPEC_KEY)."}, status_code=503)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    path = request.url.path
    if path.startswith(("/md/p/", "/md/pimg/")) or "/md/p/" in path or "/md/pimg/" in path:
        h["Content-Security-Policy"] = _PUBLIC_CSP
        h["Referrer-Policy"] = "no-referrer"       # link chia sẻ chứa khoá: không gửi sang trang khác
        h["X-Frame-Options"] = "DENY"
    else:
        h.setdefault("Content-Security-Policy", _APP_CSP)
        h.setdefault("Referrer-Policy", "same-origin")
    return resp


# Chặn dò mã truy cập: quá AUTH_MAX_FAILS lần sai trong AUTH_WINDOW_S giây từ một địa chỉ -> 429.
AUTH_MAX_FAILS = int(os.getenv("AUTH_MAX_FAILS", "20"))
AUTH_WINDOW_S = float(os.getenv("AUTH_WINDOW_S", "600"))
_fails: dict[str, deque] = {}
_fails_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _too_many_fails(ip: str, now: float) -> bool:
    with _fails_lock:
        q = _fails.get(ip)
        while q and q[0] < now - AUTH_WINDOW_S:
            q.popleft()
        if q is not None and not q:
            _fails.pop(ip, None)
        return bool(q) and len(q) >= AUTH_MAX_FAILS


def _record_fail(ip: str, now: float) -> None:
    with _fails_lock:
        if len(_fails) > 10000:           # giới hạn bộ nhớ khi bị dò từ rất nhiều địa chỉ
            _fails.clear()
        _fails.setdefault(ip, deque()).append(now)


# ------------------------------------------------------------------ tiện ích
def auth(request: Request, x_app_token: str | None = Header(None)) -> dict:
    """Danh tính theo mã truy cập: quản trị viên (APP_TOKEN), người dùng do quản trị viên cấp, hoặc
    chế độ mở (không đặt APP_TOKEN)."""
    ip, now = _client_ip(request), time.time()
    if x_app_token and _too_many_fails(ip, now):
        raise HTTPException(429, "Nhập sai mã quá nhiều lần, thử lại sau ít phút")
    who = users.identify(x_app_token)
    if who is None:
        if x_app_token:
            _record_fail(ip, now)
        raise HTTPException(401, "Sai hoặc thiếu mã truy cập")
    return who


OPEN_ADMIN = os.getenv("OPEN_ADMIN") == "1"


def admin_only(who: dict = Depends(auth)) -> dict:
    # chế độ mở (không đặt APP_TOKEN) chỉ được sửa cấu hình dùng chung ở bản máy tính hoặc khi bật OPEN_ADMIN=1
    if who["role"] == "admin" or (who["role"] == "open" and (DESKTOP or OPEN_ADMIN)):
        return who
    raise HTTPException(403, "Chỉ quản trị viên được dùng chức năng này (đặt APP_TOKEN trên máy chủ)")


def own_job(jid: str, who: dict = Depends(auth)) -> dict:
    """Mỗi mã truy cập chỉ thấy phiên (tài liệu) của chính mình; phiên của mã khác -> 404 như không tồn tại."""
    if who["role"] == "open":
        return who
    try:
        owner = jobs.job_owner(jid)
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    if owner != who["id"]:
        raise HTTPException(404, "Phiên không tồn tại hoặc đã hết hạn")
    return who


def _safe_name(name: str) -> str:
    base = Path(name or "tai_lieu.docx").name
    base = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip() or "tai_lieu.docx"
    return base if base.lower().endswith(".docx") else base + ".docx"


async def _read_docx(f: UploadFile) -> bytes:
    data = await f.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"{f.filename}: vượt quá {MAX_MB:g} MB")
    bad = jobs.check_docx_bytes(data)
    if bad:
        raise HTTPException(400, f"{f.filename}: {bad}")
    return data


def _job_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e


# ------------------------------------------------------------------ trang & cấu hình
@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/soan-thao", response_class=HTMLResponse)
def composer():
    """Trình soạn thảo độc lập, hiển thị trong tab của ứng dụng chuẩn hoá."""
    raw = json.dumps(public_raw(party_composer_spec()), ensure_ascii=False).replace("<", "\\u003c")
    return (STATIC / "soan_thao.html").read_text(encoding="utf-8").replace(
        "<!--PARTY_COMPOSER_SPEC-->", f'<script type="application/json" id="partyComposerSpec">{raw}</script>')


_STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}


@app.get("/static/{name}")
def static_file(name: str):
    """Phục vụ file giao diện. Không dùng StaticFiles vì khi chạy sau nginx có ROOT_PATH (vd /nd30)
    mà nginx đã cắt tiền tố, StaticFiles của Starlette tính sai đường dẫn -> 404."""
    p = (STATIC / name).resolve()
    if p.parent != STATIC.resolve() or p.suffix not in _STATIC_TYPES or not p.is_file():
        raise HTTPException(404, "Không có file")
    return FileResponse(p, media_type=_STATIC_TYPES[p.suffix], headers={"Cache-Control": "public, max-age=300"})


@app.get("/huong-dan", response_class=HTMLResponse)
def guide():
    return (STATIC / "huong_dan.html").read_text(encoding="utf-8")


DESKTOP = os.getenv("ND30_DESKTOP") == "1"          # bản cài trên máy tính (nd30fmt/desktop.py)
APP_NAME = os.getenv("APP_NAME", "Công cụ văn bản NĐ30")


def _org() -> dict:
    """Thông tin cơ quan hiển thị ở đầu trang (đổi bằng biến môi trường, không cần sửa mã)."""
    if DESKTOP:     # bản máy tính: chỉ tên ứng dụng, không logo/tên cơ quan
        return {"parent": "", "name": APP_NAME, "tagline": "", "unit": "", "logo": ""}
    return {"parent": os.getenv("ORG_PARENT", ""),
            "name": os.getenv("ORG_NAME", APP_NAME),
            "tagline": os.getenv("ORG_TAGLINE", "Công cụ soạn thảo, kiểm tra và chuẩn hoá thể thức văn bản hành chính, "
                                 "văn bản của Đảng và luận văn/đề án thạc sĩ"),
            "unit": os.getenv("ORG_UNIT", ""),
            "logo": _logo_src()}


# Logo: đặt ORG_LOGO (link hoặc đường dẫn tệp) hoặc tệp config/logo.*; mặc định là biểu tượng dựng sẵn.
# ORG_LOGO = link http(s) -> dùng link; = đường dẫn file -> phục vụ file đó; để trống -> config/logo.* hoặc biểu tượng mặc định.
DEFAULT_LOGO_URL = ""


def _logo_src() -> str:
    v = os.getenv("ORG_LOGO", DEFAULT_LOGO_URL).strip()
    return v if v.startswith(("http://", "https://")) else "branding/logo"


_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="31" fill="#2e86c1"/>
<path d="M22 14h15l9 9v27H22z" fill="#fff"/><path d="M37 14v9h9" fill="#d6e8f5"/>
<path d="M26 30h16M26 36h16M26 42h11" stroke="#2e86c1" stroke-width="2.4" stroke-linecap="round"/></svg>"""


@app.get("/branding/logo")
def logo():
    """Logo cơ quan: đặt file logo.png|svg|jpg|webp vào thư mục config/ (hoặc biến ORG_LOGO) để thay."""
    v = (os.getenv("ORG_LOGO") or "").strip()
    cands = [v] if v and not v.startswith(("http://", "https://")) else []
    cfg_dir = Path(jobs.BASE_SPEC["nd30"]).parent
    cands += [str(cfg_dir / f"logo.{ext}") for ext in ("png", "svg", "jpg", "jpeg", "webp")]
    for c in cands:
        if c and Path(c).is_file():
            return FileResponse(c, headers={"Cache-Control": "public, max-age=3600"})
    return Response(_LOGO_SVG, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


_last_ping = {"t": 0.0}


@app.get("/api/desktop/ping")
def desktop_ping():
    """Bản máy tính: trang đang mở báo còn dùng; trình chạy tắt máy chủ khi không còn cửa sổ nào."""
    import time
    _last_ping["t"] = time.time()
    return {"ok": True}


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "office": jobs.office_available(),
            "audio": _audio_ready(), "core": core.name()}


@app.get("/api/config")
def config():
    return {"token_required": bool(os.getenv("APP_TOKEN")), "office": jobs.office_available(),
            "org": _org(), "desktop": DESKTOP, "audio": _audio_on(),
            "max_mb": MAX_MB, "max_files": MAX_FILES, "version": __version__}


@app.post("/api/import-draft", dependencies=[Depends(auth)])
async def import_word_draft(file: UploadFile = File(...)):
    """Nhận file Word và trả về các trường/đoạn để người dùng kiểm tra trong form."""
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Chọn file Word .docx")
    data = await _read_docx(file)
    try:
        return await run_in_threadpool(parse_draft_bytes, data)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Không đọc được nội dung file Word: {e}") from e


# ------------------------------------------------------------------ trình soạn thảo theo schema (v40)
def _compose_call(fn, *a):
    try:
        return fn(*a)
    except (compose_layout.LayoutError, compose_schema.SchemaError) as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/compose/templates", dependencies=[Depends(auth)])
def compose_templates():
    """Schema Mẫu 1.1–1.10 (NĐ30), danh mục loại, thông số định dạng và schema văn bản Đảng (không kèm nguồn)."""
    return public_raw(_compose_call(compose_schema.public_templates))


@app.post("/api/compose/layout", dependencies=[Depends(auth)])
async def compose_layout_api(draft: dict = Body(...)):
    """Bố cục dùng chung cho xem trước và Word + kết quả kiểm tra theo schema."""
    def run():
        return {"layout": compose_layout.build_layout(draft), "validation": public_raw(validate_draft(draft))}
    return await run_in_threadpool(_compose_call, run)


def _docx_name(draft: dict) -> str:
    try:
        label = compose_schema.type_info(draft.get("standard"), draft.get("type_id"))["label"]
    except compose_schema.SchemaError:
        label = "Van ban"
    import unicodedata
    base = unicodedata.normalize("NFD", label.replace("Đ", "D").replace("đ", "d"))
    base = re.sub(r"[^A-Za-z0-9]+", "-", "".join(c for c in base if not unicodedata.combining(c))).strip("-")[:45]
    return (base or "Van-ban") + ".docx"


@app.post("/api/compose/docx", dependencies=[Depends(auth)])
async def compose_docx_api(draft: dict = Body(...)):
    def run():
        return compose_docx.build_docx(compose_layout.build_layout(draft))
    data = await run_in_threadpool(_compose_call, run)
    name = _docx_name(draft)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.post("/api/compose/import", dependencies=[Depends(auth)])
async def compose_import_api(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Chọn file Word .docx")
    data = await _read_docx(file)
    try:
        return await run_in_threadpool(compose_importer.parse_docx, data)
    except (ValueError, KeyError, zipfile.BadZipFile) as e:
        raise HTTPException(400, f"Không đọc được file Word: {e}") from e


@app.post("/api/compose/classify", dependencies=[Depends(auth)])
async def compose_classify_api(payload: dict = Body(...)):
    """Quy tắc cho dòng có dấu hiệu rõ ràng; dòng mơ hồ giữ là đoạn thường (tin cậy thấp)."""
    try:
        return await run_in_threadpool(compose_classify.classify_lines, payload.get("lines"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ tab Chuyển đổi Âm thanh
# Phiên âm bằng Groq Whisper (GROQ_API_KEY trên máy chủ, cần ffmpeg). Nếu không đặt GROQ_API_KEY thì quay về
# cách cũ: chuyển tiếp tới máy Whisper trên Google Colab (WHISPER_TOKEN + link trong WHISPER_URL_FILE).
# Trình duyệt chỉ gửi mã truy cập của ứng dụng (X-App-Token).
# Tệp tải lên được ghi thẳng ra đĩa (không giữ trong bộ nhớ: VPS 1 GB RAM vẫn nhận được tệp 90 MB), các việc
# chạy lần lượt theo thứ tự gửi, trạng thái có số đoạn đã xong để giao diện báo tiến độ.
import secrets as _secrets
import shutil as _shutil
import threading as _threading
import time as _time
import urllib.error as _urlerr
import urllib.request as _urlreq
from concurrent.futures import ThreadPoolExecutor as _Pool

AUDIO_MAX_MB = float(os.getenv("AUDIO_MAX_MB", "90"))
AUDIO_MAX_QUEUE = int(os.getenv("AUDIO_MAX_QUEUE", "5"))
WHISPER_TOKEN = os.getenv("WHISPER_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
_AUDIO_SECRET = WHISPER_TOKEN or GROQ_API_KEY      # khoá ký mã việc
_groq_jobs: dict[str, dict] = {}
_groq_lock = _threading.Lock()
_groq_pool = _Pool(max_workers=1, thread_name_prefix="audio")   # mỗi lần một việc, tránh vượt hạn mức của Groq
_GROQ_TTL = 1800
WHISPER_URL_FILE = os.getenv("WHISPER_URL_FILE", "/whisper/whisper_url.txt")
_WHISPER_HOST = re.compile(r"^https://[a-z0-9.-]+\.trycloudflare\.com$")
_AUDIO_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}\.[0-9a-f]{16}$")


def _audio_ready() -> bool:
    """Tab Âm thanh dùng được ngay (đã có khoá và ffmpeg, hoặc đã cấu hình máy Colab)."""
    if not _audio_on():
        return False
    if GROQ_API_KEY:
        return _shutil.which("ffmpeg") is not None
    return bool(WHISPER_TOKEN and _whisper_base())


def _audio_on() -> bool:
    """Tab Âm thanh có trong bản này không (bản cài trên máy tính không có)."""
    return not DESKTOP


def _whisper_base() -> str:
    try:
        url = Path(WHISPER_URL_FILE).read_text(encoding="utf-8").strip().rstrip("/")
    except OSError:
        return ""
    return url if _WHISPER_HOST.match(url) else ""


def _audio_sign(jid: str, who: dict) -> str:
    # mã việc công khai = mã việc + chữ ký theo người dùng: mỗi người chỉ xem được việc của chính mình
    owner = "open" if who.get("role") == "open" else str(who.get("id"))
    return hmac.new(_AUDIO_SECRET.encode(), f"{jid}|{owner}".encode(), "sha256").hexdigest()[:16]


def _whisper_call(method: str, path: str, data: bytes | None = None, timeout: float = 30):
    base = _whisper_base()
    if not WHISPER_TOKEN:
        raise HTTPException(503, "Máy chủ chưa cấu hình WHISPER_TOKEN.")
    if not base:
        raise HTTPException(503, "Chưa có link máy phiên âm (đặt GROQ_API_KEY, hoặc ghi link máy Whisper vào WHISPER_URL_FILE).")
    headers = {"X-Token": WHISPER_TOKEN}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = _urlreq.Request(base + path, data=data, method=method, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        try:
            msg = str(json.loads(e.read().decode("utf-8")).get("error", ""))
        except Exception:  # noqa: BLE001
            msg = ""
        if e.code == 401:
            raise HTTPException(502, "Token Whisper trên máy chủ không khớp với Colab.") from e
        if e.code == 404:
            raise HTTPException(404, "Colab không còn nhớ việc này (có thể vừa khởi động lại). Hãy tải lên lại.") from e
        if e.code in (413, 429):
            raise HTTPException(e.code, msg or "Máy phiên âm từ chối tệp này.") from e
        raise HTTPException(503, f"Máy phiên âm báo lỗi HTTP {e.code}. Máy Whisper có thể đã dừng hoặc link đã đổi.") from e
    except (OSError, ValueError) as e:
        raise HTTPException(503, "Không kết nối được tới máy phiên âm. Colab có thể đã dừng hoặc link đã hết hạn.") from e


@app.get("/chuyen-am-thanh", response_class=HTMLResponse)
def audio_page():
    if not _audio_on():
        raise HTTPException(404, "Bản này không có tab Chuyển đổi Âm thanh.")
    return (STATIC / "chuyen_am_thanh.html").read_text(encoding="utf-8")


def _groq_set(jid: str, **kw) -> bool:
    # người dùng có thể đã bấm "Chuyển âm thanh khác" (xóa việc) trong lúc đang chờ/chạy: khi đó bỏ qua kết quả
    with _groq_lock:
        job = _groq_jobs.get(jid)
        if job is None:
            return False
        job.update(kw)
        return True


def _groq_run(jid: str, workdir: str, src: str) -> None:
    from . import groq_whisper

    def progress(done: int, total: int) -> None:
        if not _groq_set(jid, part=done, parts=total):
            raise groq_whisper.Cancelled()      # việc đã bị xóa: dừng, không gửi tiếp các đoạn còn lại

    try:
        if not _groq_set(jid, status="running"):
            return
        t0 = _time.time()
        res = groq_whisper.transcribe_file(src, GROQ_API_KEY, GROQ_MODEL, progress=progress, workdir=workdir)
        res["seconds"] = round(_time.time() - t0, 1)
        _groq_set(jid, status="done", result=res, finished=_time.time())
    except groq_whisper.Cancelled:
        pass
    except groq_whisper.GroqError as e:
        _groq_set(jid, status="error", error=str(e), finished=_time.time())
    except Exception as e:  # noqa: BLE001
        logging.getLogger("nd30fmt").warning("audio job lỗi: %s", type(e).__name__)
        _groq_set(jid, status="error", error="Phiên âm thất bại: " + type(e).__name__, finished=_time.time())
    finally:
        groq_whisper.release_workdir(workdir)   # không giữ âm thanh trên máy chủ sau khi xong


def _groq_prune(now: float) -> None:
    """Bỏ kết quả đã xong quá _GROQ_TTL giây (gọi khi đang giữ _groq_lock)."""
    for k in [k for k, v in _groq_jobs.items()
              if v["status"] in ("done", "error") and now - v.get("finished", v["created"]) > _GROQ_TTL]:
        del _groq_jobs[k]


async def _audio_save(file: UploadFile, dest: str) -> int:
    """Ghi tệp tải lên ra đĩa theo từng khối 1 MB; vượt AUDIO_MAX_MB thì dừng ngay."""
    limit = AUDIO_MAX_MB * 1024 * 1024
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"{file.filename or 'Tệp'}: vượt quá {AUDIO_MAX_MB:g} MB")
            f.write(chunk)
    if not size:
        raise HTTPException(400, "Tệp rỗng")
    return size


@app.get("/api/audio/status")
async def audio_status(who: dict = Depends(auth)):
    if not _audio_on():
        return {"configured": False, "alive": False, "max_mb": AUDIO_MAX_MB}
    if GROQ_API_KEY:
        from . import groq_whisper
        ok = groq_whisper.available()
        return {"configured": ok, "alive": ok, "max_mb": AUDIO_MAX_MB, "backend": "groq"}
    base = _whisper_base()
    if not WHISPER_TOKEN or not base:
        return {"configured": False, "alive": False, "max_mb": AUDIO_MAX_MB}

    def ping() -> bool:
        try:
            with _urlreq.urlopen(base + "/health", timeout=8) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    return {"configured": True, "alive": await run_in_threadpool(ping), "max_mb": AUDIO_MAX_MB, "backend": "colab"}


@app.post("/api/audio/jobs")
async def audio_submit(file: UploadFile = File(...), who: dict = Depends(auth)):
    if not _audio_on():
        raise HTTPException(404, "Bản này không có tab Chuyển đổi Âm thanh.")
    from . import groq_whisper
    if GROQ_API_KEY:
        now = _time.time()
        with _groq_lock:
            _groq_prune(now)
            if sum(1 for v in _groq_jobs.values() if v["status"] in ("queued", "running")) >= AUDIO_MAX_QUEUE:
                raise HTTPException(429, "Đang có quá nhiều việc chờ, thử lại sau.")
        groq_whisper.sweep_stale()
        workdir = groq_whisper.new_workdir()
        src = os.path.join(workdir, "in.bin")
        try:
            await _audio_save(file, src)
            jid = _secrets.token_urlsafe(8)
            with _groq_lock:     # kiểm tra lại: trong lúc tệp này đang tải lên có thể đã có việc khác vào hàng đợi
                if sum(1 for v in _groq_jobs.values() if v["status"] in ("queued", "running")) >= AUDIO_MAX_QUEUE:
                    raise HTTPException(429, "Đang có quá nhiều việc chờ, thử lại sau.")
                _groq_jobs[jid] = {"status": "queued", "created": _time.time(), "part": 0, "parts": 0}
            _groq_pool.submit(_groq_run, jid, workdir, src)
        except BaseException:
            groq_whisper.release_workdir(workdir)
            raise
        return {"id": f"{jid}.{_audio_sign(jid, who)}"}
    # cách cũ (Colab): máy phiên âm nhận cả tệp trong một yêu cầu
    data = await file.read()
    if not data:
        raise HTTPException(400, "Tệp rỗng")
    if len(data) > AUDIO_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"{file.filename or 'Tệp'}: vượt quá {AUDIO_MAX_MB:g} MB")
    res = await run_in_threadpool(_whisper_call, "POST", "/jobs", data, 300)
    jid = str(res.get("id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", jid):
        raise HTTPException(502, "Máy phiên âm trả về dữ liệu không hợp lệ.")
    return {"id": f"{jid}.{_audio_sign(jid, who)}"}


@app.get("/api/audio/jobs/{pid}")
async def audio_job(pid: str, who: dict = Depends(auth)):
    if not _AUDIO_SECRET or not _AUDIO_ID.match(pid):
        raise HTTPException(404, "Việc không tồn tại hoặc đã hết hạn.")
    jid, sig = pid.split(".", 1)
    if not hmac.compare_digest(sig, _audio_sign(jid, who)):
        raise HTTPException(404, "Việc không tồn tại hoặc đã hết hạn.")
    if GROQ_API_KEY:
        with _groq_lock:
            job = dict(_groq_jobs.get(jid) or {})
            ahead = sum(1 for v in _groq_jobs.values()
                        if v["status"] in ("queued", "running") and v["created"] < job.get("created", 0))
        if not job:
            raise HTTPException(404, "Việc không tồn tại hoặc máy chủ vừa khởi động lại. Hãy tải lên lại.")
        out = {"status": job["status"]}
        if job["status"] == "queued":
            out["ahead"] = ahead
        if job["status"] == "running" and job.get("parts"):
            out["part"] = min(job["part"] + 1, job["parts"])
            out["parts"] = job["parts"]
        if job["status"] == "done":
            out["result"] = job["result"]
        if job["status"] == "error":
            out["error"] = job["error"]
        return out
    return await run_in_threadpool(_whisper_call, "GET", "/jobs/" + jid)


@app.delete("/api/audio/jobs/{pid}")
async def audio_delete(pid: str, who: dict = Depends(auth)):
    """Xóa kết quả của việc khỏi máy chủ (trình duyệt gọi sau khi nhận kết quả hoặc khi bấm Chuyển âm thanh khác).

    Việc đang chờ thì không chạy nữa; việc đang chạy dừng trước đoạn kế tiếp."""
    if not _AUDIO_SECRET or not _AUDIO_ID.match(pid):
        return {"ok": True}
    jid, sig = pid.split(".", 1)
    if hmac.compare_digest(sig, _audio_sign(jid, who)):
        with _groq_lock:
            _groq_jobs.pop(jid, None)
    return {"ok": True}


# ------------------------------------------------------------------ tab Chuyển Markdown
@app.get("/chuyen-md", response_class=HTMLResponse)
def markdown_page():
    return (STATIC / "chuyen_md.html").read_text(encoding="utf-8")


def _md_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except md_store.MdError as e:
        raise HTTPException(e.status, str(e)) from e


@app.get("/api/md/docs")
def md_list(q: str = "", who: dict = Depends(auth)):
    return {"docs": _md_call(md_store.list_documents, who["id"], q)}


@app.post("/api/md/docs")
async def md_upload(files: list[UploadFile] = File(...), who: dict = Depends(auth)):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Tối đa {MAX_FILES} file mỗi lần")
    results = []
    for f in files:
        name = f.filename or "tai-lieu"
        data = await f.read()
        if len(data) > MAX_MB * 1024 * 1024:
            results.append({"ok": False, "filename": name, "message": f"Vượt {MAX_MB:g} MB"})
            continue
        try:
            doc = await run_in_threadpool(md_store.add_document, who["id"], name, data)
            results.append({"ok": True, "filename": name, "doc": doc})
        except md_store.MdError as e:
            results.append({"ok": False, "filename": name, "message": str(e)})
        except Exception as e:  # noqa: BLE001 - báo lỗi từng file, không dừng cả lô
            results.append({"ok": False, "filename": name, "message": f"Lỗi chuyển đổi: {e}"})
    return {"results": results}


@app.post("/api/md/jobs")
async def md_job_submit(files: list[UploadFile] = File(...), who: dict = Depends(auth)):
    """Tải lên rồi chuyển đổi chạy nền: trả về ngay mã việc; giao diện hỏi tiến độ ở GET /api/md/jobs/{id}."""
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Tối đa {MAX_FILES} file mỗi lần")
    items = []
    for f in files:
        name = f.filename or "tai-lieu"
        data = await f.read()
        if len(data) > MAX_MB * 1024 * 1024:
            items.append((name, None, f"Vượt {MAX_MB:g} MB"))
        else:
            items.append((name, data, None))
    return md_tasks.submit(who["id"], items)


@app.get("/api/md/jobs/{job_id}")
def md_job_status(job_id: str, who: dict = Depends(auth)):
    st = md_tasks.status(who["id"], job_id)
    if st is None:
        raise HTTPException(404, "Không còn thông tin việc chuyển đổi này (máy chủ vừa khởi động lại?). Hãy tải lên lại.")
    return st


@app.post("/api/md/text")
async def md_from_text(body: dict = Body(...), who: dict = Depends(auth)):
    text = str(body.get("markdown") or "")
    if not text.strip():
        raise HTTPException(400, "Nội dung Markdown trống")
    return await run_in_threadpool(_md_call, md_store.add_text, who["id"], str(body.get("name") or "ghi-chu"), text)


@app.get("/api/md/docs/{doc_id}")
def md_get(doc_id: str, who: dict = Depends(auth)):
    doc, text, extra = _md_call(md_store.get_document, who["id"], doc_id)
    info = _md_call(md_store.ocr_info, who["id"], doc_id, text)
    shown = md_store.resolve_images(md_store.mark_ocr(text, info), f"api/md/img/{doc_id}/{extra['img_key']}/")
    token = md_store.share_token(who["id"], doc_id)
    pub = {k: v for k, v in info.items() if not k.startswith("_")} if info else None
    return {"doc": doc, "markdown": text, "html": md_store.render_html(shown, info), "ocr": pub,
            "share_url": f"md/p/{doc_id}/{token}" if token else None}


@app.post("/api/md/docs/{doc_id}/ocrfix")
def md_ocr_fix(doc_id: str, body: dict = Body(...), who: dict = Depends(auth)):
    """Hoàn tác/áp dụng lại các nhóm sửa dấu OCR. body: {"disabled": [[sai, đúng], …]} hoặc {"mode": "raw"|"all"}."""
    info = _md_call(md_store.ocr_info, who["id"], doc_id)
    if info is None:
        raise HTTPException(400, "Tài liệu này không chuyển bằng nhận dạng chữ")
    mode = body.get("mode")
    if mode == "raw":
        disabled = [[g["from"], g["to"]] for g in info["groups"]]
    elif mode == "all":
        disabled = []
    else:
        disabled = body.get("disabled") or []
    _md_call(md_store.set_ocr_fix, who["id"], doc_id, disabled)
    return md_get(doc_id, who)


@app.put("/api/md/docs/{doc_id}")
def md_update(doc_id: str, body: dict = Body(...), who: dict = Depends(auth)):
    doc = None
    if "markdown" in body:
        doc = _md_call(md_store.update_markdown, who["id"], doc_id, str(body["markdown"] or ""))
    if body.get("filename"):
        doc = _md_call(md_store.rename, who["id"], doc_id, str(body["filename"]))
    if doc is None:
        raise HTTPException(400, "Không có gì để cập nhật")
    return doc


@app.delete("/api/md/docs/{doc_id}")
def md_delete(doc_id: str, who: dict = Depends(auth)):
    _md_call(md_store.delete_document, who["id"], doc_id)
    return {"ok": True}


@app.get("/api/md/docs/{doc_id}/download/{kind}")
def md_download(doc_id: str, kind: str, who: dict = Depends(auth)):
    doc, text, _ = _md_call(md_store.get_document, who["id"], doc_id)
    stem = Path(doc["filename"]).stem
    if kind == "md":
        body = md_store.resolve_images(text, "")
        name = md_store.dated_name(doc["uploaded_at"], stem + ".md")
        return Response(body.encode("utf-8"), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
    if kind == "original":
        path, filename = _md_call(md_store.original_path, who["id"], doc_id)
        if not path.is_file():
            raise HTTPException(404, "File gốc không còn")
        return FileResponse(path, filename=md_store.dated_name(doc["uploaded_at"], filename))
    if kind == "docx":
        from .mdlib import md_to_docx_nd30 as mdx
        from .ooxml_order import normalize_document
        body = md_store.resolve_images(text, "")
        d = mdx.build_plain_document(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body),
                                     title=stem.replace("_", " ").replace("-", " "))
        normalize_document(d)
        buf = io.BytesIO()
        d.save(buf)
        name = md_store.dated_name(doc["uploaded_at"], stem + ".docx")
        return Response(buf.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
    raise HTTPException(404, "Loại tải về không hợp lệ")


@app.post("/api/md/docs/{doc_id}/share")
def md_share(doc_id: str, body: dict = Body(...), who: dict = Depends(auth)):
    token = _md_call(md_store.set_share, who["id"], doc_id, bool(body.get("on")))
    return {"share_url": f"md/p/{doc_id}/{token}" if token else None}


@app.get("/api/md/docs/{doc_id}/compose")
def md_to_compose(doc_id: str, standard: str = "nd30", who: dict = Depends(auth)):
    """Markdown -> bản thảo cho tab Soạn thảo (nhận diện thể thức, Điều/khoản/điểm)."""
    _, text, _ = _md_call(md_store.get_document, who["id"], doc_id)
    return _md_compose_safe(text, standard)


@app.post("/api/md/compose", dependencies=[Depends(auth)])
def md_text_to_compose(body: dict = Body(...)):
    return _md_compose_safe(str(body.get("markdown") or ""), str(body.get("standard") or "nd30"))


def _md_compose_safe(text: str, standard: str):
    try:
        return md_compose.markdown_to_draft(text, standard)
    except (ValueError, compose_schema.SchemaError) as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001 - báo rõ thay vì "HTTP 500" trống
        log.exception("markdown_to_draft")
        raise HTTPException(422, f"Không nhận diện được thể thức từ nội dung này ({type(e).__name__}). "
                                 "Có thể sửa Markdown rồi thử lại, hoặc tải Word thường.") from e


@app.get("/api/md/img/{doc_id}/{key}/{fname}")
def md_image(doc_id: str, key: str, fname: str):
    """Ảnh trích từ PDF/DOCX; khoá ngẫu nhiên riêng từng tài liệu thay cho mã truy cập (thẻ <img> không gửi header)."""
    return FileResponse(_md_call(md_store.image_path, doc_id, key, fname),
                        headers={"Cache-Control": "private, max-age=3600"})


_PUBLIC_PAGE = """<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{title}</title><style>
body{{margin:0;background:#edf1f6;font:16px/1.65 "Times New Roman",Georgia,serif;color:#1d2939}}
main{{max-width:860px;margin:24px auto;background:#fff;padding:32px 40px;border-radius:10px;box-shadow:0 2px 10px #0001}}
h1.t{{font:700 18px/1.4 system-ui,sans-serif;color:#1b3a5c;margin:0 0 18px}} table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #cfd6de;padding:4px 8px;vertical-align:top}} img{{max-width:100%}} pre{{white-space:pre-wrap}}
@media(max-width:600px){{main{{margin:0;padding:18px;border-radius:0}}}}</style></head>
<body><main><h1 class="t">{title}</h1>{content}</main></body></html>"""


@app.get("/md/p/{doc_id}/{token}", response_class=HTMLResponse)
def md_public(doc_id: str, token: str):
    row = _md_call(md_store.public_document, doc_id, token)
    text = Path(row["md_path"]).read_text(encoding="utf-8", errors="replace")
    text = md_store.resolve_images(text, f"../../pimg/{doc_id}/{token}/")
    import html as _html
    return _PUBLIC_PAGE.format(title=_html.escape(row["filename"]), content=md_store.render_html(text))


@app.get("/md/pimg/{doc_id}/{token}/{fname}")
def md_public_image(doc_id: str, token: str, fname: str):
    return FileResponse(_md_call(md_store.image_path, doc_id, token, fname, True))


@app.get("/api/draft-profile", dependencies=[Depends(auth)])
async def get_draft_profile(x_draft_profile: str = Header(...)):
    try:
        data = await run_in_threadpool(read_profile, x_draft_profile)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if data is None:
        raise HTTPException(404, "Chưa có hồ sơ cho mã này")
    return data


@app.put("/api/draft-profile", dependencies=[Depends(auth)])
async def put_draft_profile(payload: dict = Body(...), x_draft_profile: str = Header(...)):
    try:
        return await run_in_threadpool(save_profile, x_draft_profile, payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except ProfileConflict as e:
        raise HTTPException(409, str(e)) from e


# ------------------------------------------------------------------ quy chuẩn
@app.get("/api/spec", dependencies=[Depends(auth)])
def get_spec(base: bool = False, standard: str = "nd30"):
    try:
        raw = jobs.base_raw(standard) if base else jobs.default_raw(standard)
        custom = jobs.CUSTOM_SPEC[standard].exists() and not base  # standard đã được default_raw() kiểm tra
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"raw": public_raw(raw), "custom": custom}


@app.put("/api/spec", dependencies=[Depends(admin_only)])   # quy chuẩn mặc định dùng chung: chỉ quản trị viên
def put_spec(raw: dict = Body(...), standard: str = "nd30"):
    try:
        notes = jobs.save_default(raw, standard)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, f"Thông số không hợp lệ: {e}") from e
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"ok": True, "notes": notes}


@app.delete("/api/spec", dependencies=[Depends(admin_only)])
def delete_spec(standard: str = "nd30"):
    try:
        jobs.reset_default(standard)
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"ok": True}


# ------------------------------------------------------------------ phiên làm việc (preview + sửa lại)
@app.post("/api/jobs")
async def create_jobs(files: list[UploadFile] = File(...),
                      only_nd30: bool = Form(False), standard: str = Form("nd30"), wait: bool = Form(False),
                      spell: bool = Form(True), spell_level: str = Form("safe"),
                      who: dict = Depends(auth)):
    """Nhận file và trả mã phiên ngay (xử lý chạy nền; trình duyệt hỏi /api/jobs/{id}/status).
    wait=true: chờ xử lý xong mới trả về (cho script/kiểm thử)."""
    if not files:
        raise HTTPException(400, "Chưa chọn file")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Tối đa {MAX_FILES} file mỗi lần")
    try:
        jobs._std(standard)
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    if spell_level not in ("safe", "wide"):
        raise HTTPException(400, "spell_level phải là safe hoặc wide")
    spell_opts = {"on": bool(spell), "level": spell_level}
    out = []
    for f in files:
        name = _safe_name(f.filename)
        try:
            data = await _read_docx(f)
        except HTTPException as e:
            out.append({"file": name, "ok": False, "status": "error", "message": str(e.detail)})
            continue
        try:
            if wait:
                jid = await run_in_threadpool(jobs.create_job, name, data, only_nd30, standard, who["id"], spell_opts)
            else:
                jid = await run_in_threadpool(jobs.submit_job, name, data, only_nd30, standard, who["id"], spell_opts)
            out.append(jobs.job_summary(jid))
        except Exception as e:  # noqa: BLE001
            out.append({"file": name, "ok": False, "status": "error", "message": jobs.friendly_error(e)})
    return {"jobs": out}


@app.get("/api/jobs/{jid}/status", dependencies=[Depends(own_job)])
def get_job_status(jid: str):
    return _job_call(jobs.job_summary, jid)


@app.get("/api/jobs")
async def list_jobs(who: dict = Depends(auth)):
    return {"jobs": await run_in_threadpool(jobs.list_jobs, None if who["role"] == "open" else who["id"])}


@app.get("/api/me")
def me(who: dict = Depends(auth)):
    return {"role": who["role"], "name": who["name"]}


# ------------------------------------------------------------------ quản trị mã truy cập
def _user_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except users.UserError as e:
        raise HTTPException(e.status, str(e)) from e


def _need_admin_mode():
    if not users.admin_token():
        raise HTTPException(400, "Máy chủ chưa đặt APP_TOKEN (mã quản trị) nên không cấp mã riêng được")


@app.get("/api/admin/users", dependencies=[Depends(admin_only)])
def admin_list_users():
    _need_admin_mode()
    return {"users": users.list_users()}


@app.post("/api/admin/users", dependencies=[Depends(admin_only)])
def admin_create_user(body: dict = Body(...)):
    _need_admin_mode()
    return _user_call(users.create_user, body.get("name"), body.get("note") or "")


@app.patch("/api/admin/users/{uid}", dependencies=[Depends(admin_only)])
def admin_update_user(uid: str, body: dict = Body(...)):
    _need_admin_mode()
    active = body.get("active")
    if active is not None and not isinstance(active, bool):
        raise HTTPException(400, "active phải là true hoặc false")
    return _user_call(users.update_user, uid, body.get("name"), body.get("note"), active)


@app.post("/api/admin/users/{uid}/reset", dependencies=[Depends(admin_only)])
def admin_reset_user(uid: str):
    _need_admin_mode()
    return _user_call(users.reset_token, uid)


@app.delete("/api/admin/users/{uid}", dependencies=[Depends(admin_only)])
def admin_delete_user(uid: str, purge: bool = False):
    _need_admin_mode()
    return {"ok": True, "jobs": _user_call(users.delete_user, uid, purge)}


@app.get("/api/jobs/{jid}", dependencies=[Depends(own_job)])
def get_job(jid: str):
    return _job_call(jobs.get_payload, jid)


@app.delete("/api/jobs/{jid}", dependencies=[Depends(own_job)])
async def delete_job(jid: str):
    await run_in_threadpool(_job_call, jobs.delete_job, jid)
    return {"ok": True}


@app.post("/api/jobs/{jid}/apply", dependencies=[Depends(own_job)])
async def apply_job(jid: str, body: dict = Body(...)):
    raw = body.get("spec")
    overrides = body.get("role_overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise HTTPException(400, "role_overrides phải là object {pid: role}")
    skip = body.get("only_nd30")
    edits = body.get("text_edits")
    if edits is not None and not isinstance(edits, dict):
        raise HTTPException(400, "text_edits phải là object {mã đoạn: chữ mới}")
    ignored = body.get("ignored")
    if ignored is not None and not isinstance(ignored, list):
        raise HTTPException(400, "ignored phải là danh sách")
    manual = body.get("manual_format")
    if manual is not None and not isinstance(manual, dict):
        raise HTTPException(400, "manual_format phải là object {mã đoạn: định dạng}")
    spell = body.get("spell")
    if spell is not None and not isinstance(spell, dict):
        raise HTTPException(400, "spell phải là object")
    toc = body.get("toc")
    if toc is not None and not isinstance(toc, dict):
        raise HTTPException(400, "toc phải là object")
    return await run_in_threadpool(_job_call, jobs.run_job, jid, raw, overrides, skip, edits, ignored, manual, spell, toc)


@app.post("/api/jobs/{jid}/restandard", dependencies=[Depends(own_job)])
async def restandard(jid: str, body: dict = Body(...)):
    """Đổi chuẩn thể thức (nd30 | dang | dean) cho file đã tải lên và kiểm tra lại, chạy nền như khi
    tải lên; trình duyệt hỏi /api/jobs/{id}/status rồi mở lại khi xong."""
    std = body.get("standard")
    skip = body.get("only_nd30")
    if not isinstance(std, str):
        raise HTTPException(400, "Thiếu chuẩn thể thức")
    if skip is not None and not isinstance(skip, bool):
        raise HTTPException(400, "only_nd30 phải là true hoặc false")
    await run_in_threadpool(_job_call, jobs.restandard_job, jid, std, skip)
    return _job_call(jobs.job_summary, jid)


@app.post("/api/jobs/{jid}/toc", dependencies=[Depends(own_job)])
async def job_toc(jid: str, body: dict | None = Body(None)):
    """Tab Mục lục: tạo Mục lục / Danh mục hình / Danh mục bảng theo lựa chọn {toc, hinh, bang} (mặc định chỉ
    Mục lục; mục chưa có tiêu đề thì tạo mới) và đánh số Hình/Bảng bằng field tự cập nhật, trên bản đã sửa."""
    if body is not None and not isinstance(body, dict):
        raise HTTPException(400, "Body phải là object {toc, hinh, bang}")
    return await run_in_threadpool(_job_call, jobs.add_toc, jid, body)


@app.post("/api/jobs/{jid}/toc/remove", dependencies=[Depends(own_job)])
async def job_toc_remove(jid: str):
    """Bỏ mục lục: dựng lại bản đã sửa không có Mục lục/Danh mục do công cụ tạo; trả về dữ liệu phiên mới."""
    return await run_in_threadpool(_job_call, jobs.remove_toc, jid)


@app.get("/api/jobs/{jid}/file/{kind}", dependencies=[Depends(own_job)])
async def job_file(jid: str, kind: str):
    data, name, mime = await run_in_threadpool(_job_call, jobs.read_file, jid, kind)
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename*=utf-8''{quote(name)}",
        "Cache-Control": "no-store"})


@app.get("/api/jobs/{jid}/pages/{which}", dependencies=[Depends(own_job)])
async def job_pages(jid: str, which: str):
    info = await run_in_threadpool(_job_call, jobs.render_pages, jid, which)
    return {"count": info["count"], "version": info["version"]}


@app.get("/api/jobs/{jid}/page/{which}/{n}", dependencies=[Depends(own_job)])
async def job_page(jid: str, which: str, n: int):
    path = await run_in_threadpool(_job_call, jobs.page_file, jid, which, n)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@app.get("/api/jobs/{jid}/pdf/{which}", dependencies=[Depends(own_job)])
async def job_pdf(jid: str, which: str):
    path = await run_in_threadpool(_job_call, jobs.pdf_file, jid, which)
    return FileResponse(path, media_type="application/pdf", filename=f"{which}.pdf")


# ------------------------------------------------------------------ API xử lý hàng loạt (giữ tương thích)
async def _batch(files: list[UploadFile], do_fix: bool, only_nd30: bool, standard: str = "nd30"):
    if not files:
        raise HTTPException(400, "Chưa chọn file")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Tối đa {MAX_FILES} file mỗi lần")
    try:
        spec = build_spec(jobs.default_raw(standard), only_nd30)
    except jobs.JobError as e:
        raise HTTPException(e.status, str(e)) from e
    results = []
    tmp = tempfile.TemporaryDirectory(prefix="nd30_")
    root = Path(tmp.name)
    (root / "in").mkdir()
    (root / "out").mkdir()
    used = set()
    for f in files:
        data = await _read_docx(f)
        name = _safe_name(f.filename)
        stem, k = Path(name).stem, 1
        while name in used:
            k += 1
            name = f"{stem}_{k}.docx"
        used.add(name)
        path = root / "in" / name
        path.write_bytes(data)
        try:
            r = await run_in_threadpool(process, str(path), spec, str(root / "out"), do_fix, True, standard)
            results.append({"file": name, "ok": True, "errors": r["summary"]["total"],
                            "errors_after": (r.get("summary_after") or {}).get("total"),
                            "fixed_file": r.get("fixed_file"), "report": r.get("report_html")})
        except Exception as e:  # noqa: BLE001
            results.append({"file": name, "ok": False, "message": str(e)[:300]})
    return tmp, root, results


@app.post("/api/process", dependencies=[Depends(auth)])
async def api_process(files: list[UploadFile] = File(...), fix: bool = Form(True), only_nd30: bool = Form(False),
                      standard: str = Form("nd30")):
    """Trả về file zip gồm: *_da_sua.docx, *_bao_cao.html, *_bao_cao.json, tong_hop.json."""
    tmp, root, results = await _batch(files, fix, only_nd30, standard)
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted((root / "out").iterdir()):
                z.write(p, p.name)
            z.writestr("tong_hop.json", json.dumps({"files": results}, ensure_ascii=False, indent=1))
        summary = base64.b64encode(json.dumps({"files": results}, ensure_ascii=False).encode()).decode()
        return Response(buf.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="ket_qua_dinh_dang.zip"',
            "X-Summary": summary, "Access-Control-Expose-Headers": "X-Summary"})
    finally:
        tmp.cleanup()


@app.post("/api/check", dependencies=[Depends(auth)])
async def api_check(files: list[UploadFile] = File(...), only_nd30: bool = Form(False),
                    standard: str = Form("nd30")):
    """Chỉ kiểm tra; trả JSON chi tiết (vai trò từng đoạn + danh sách lỗi)."""
    tmp, root, results = await _batch(files, False, only_nd30, standard)
    try:
        detail = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (root / "out").glob("*_bao_cao.json")}
        return JSONResponse({"files": results, "detail": detail})
    finally:
        tmp.cleanup()
