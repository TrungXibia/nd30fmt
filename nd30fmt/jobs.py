"""Phiên làm việc (job) cho giao diện web.

Tải file lên 1 lần -> trích xuất + xác định vai trò -> lưu vai trò.
Mỗi lần người dùng đổi thông số hoặc sửa vai trò thủ công -> chỉ chạy lại so sánh + sửa bằng Python
(không xác định lại vai trò) -> trả dữ liệu preview bản gốc/bản đã sửa.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from .extract import extract
from .pipeline import analyze_roles, evaluate
from .roles import RoleDecision, detect_dean_fit, detect_standard_hint
from .spec import (DANG_SPEC_PATH, DEAN_SPEC_PATH, DEFAULT_SPEC_PATH, STANDARDS, build_spec, load_raw, normalize_raw,
                   public_raw, restore_hidden)
from .textedit import apply_text_edits
from .manual_format import validate_manual_format
from .ooxml_order import save_docx
from .toc import build_toc, toc_candidates

DATA_DIR = Path(os.getenv("DATA_DIR") or (Path(tempfile.gettempdir()) / "nd30fmt"))
JOBS_DIR = DATA_DIR / "jobs"
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "24"))
_ID_OK = set("0123456789abcdef")

# Mỗi chuẩn thể thức có quy chuẩn gốc + quy chuẩn tuỳ chỉnh (lưu trên máy chủ) riêng.
BASE_SPEC = {"nd30": os.getenv("ND30_SPEC") or str(DEFAULT_SPEC_PATH),
            "dang": os.getenv("DANG_SPEC") or str(DANG_SPEC_PATH),
            "dean": os.getenv("DEAN_SPEC") or str(DEAN_SPEC_PATH)}
CUSTOM_SPEC = {"nd30": DATA_DIR / "spec_custom.json", "dang": DATA_DIR / "spec_custom_dang.json",
               "dean": DATA_DIR / "spec_custom_dean.json"}

_job_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_office_lock = threading.Lock()
# xử lý nền: giới hạn số file chạy song song để VPS ít RAM không bị quá tải
_executor = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("JOB_WORKERS", "2"))))
_active: set[str] = set()   # phiên đang chờ/đang chạy trong tiến trình này


class JobError(RuntimeError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _std(standard: str | None) -> str:
    s = standard or "nd30"
    if s not in STANDARDS:
        raise JobError(f"Chuẩn thể thức không hợp lệ: {s!r} (chỉ nhận {STANDARDS})")
    return s


# ------------------------------------------------------------------ quy chuẩn mặc định trên server
def default_raw(standard: str | None = "nd30") -> dict:
    std = _std(standard)
    custom = CUSTOM_SPEC[std]
    if custom.exists():
        return json.loads(custom.read_text(encoding="utf-8"))
    return load_raw(BASE_SPEC[std])


def base_raw(standard: str | None = "nd30") -> dict:
    return load_raw(BASE_SPEC[_std(standard)])


def save_default(raw: dict, standard: str | None = "nd30") -> list[str]:
    std = _std(standard)
    raw = restore_hidden(raw, default_raw(std))      # giao diện không thấy trường nguồn: ghép lại từ quy chuẩn gốc
    notes = normalize_raw(raw)
    build_spec(raw)  # kiểm tra dựng được
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    custom = CUSTOM_SPEC[std]
    tmp = custom.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(custom)
    return notes


def reset_default(standard: str | None = "nd30"):
    custom = CUSTOM_SPEC[_std(standard)]
    if custom.exists():
        custom.unlink()


# ------------------------------------------------------------------ job
def _lock(jid: str) -> threading.RLock:
    with _locks_guard:
        return _job_locks.setdefault(jid, threading.RLock())


def _dir(jid: str) -> Path:
    if not jid or len(jid) != 16 or not set(jid) <= _ID_OK:
        raise JobError("Mã phiên không hợp lệ", 404)
    d = JOBS_DIR / jid
    if not (d / "meta.json").exists():
        raise JobError("Phiên không tồn tại hoặc đã hết hạn", 404)
    return d


def cleanup_old():
    if not JOBS_DIR.exists():
        return
    limit = time.time() - JOB_TTL_HOURS * 3600
    for d in JOBS_DIR.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _write_json(path: Path, obj) -> None:
    """Ghi JSON nguyên tử (ghi file tạm rồi đổi tên) để trình duyệt hỏi trạng thái không đọc phải file dở."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _set_status(d: Path, status: str, stage: str = "", error: str = "") -> None:
    _write_json(d / "status.json", {"status": status, "stage": stage, "error": error, "t": time.time()})


def job_status(jid: str) -> dict:
    d = _dir(jid)
    st = d / "status.json"
    if not st.exists():  # phiên tạo từ bản cũ (xử lý đồng bộ) -> đã xong
        return {"status": "done", "stage": "", "error": ""}
    s = json.loads(st.read_text(encoding="utf-8"))
    # máy chủ khởi động lại giữa chừng -> phiên treo mãi ở "đang xử lý"
    if s["status"] in ("queued", "running") and jid not in _active:
        s = {"status": "error", "stage": "", "error": "Máy chủ đã khởi động lại khi đang xử lý – hãy tải file lên lại"}
    return s


def friendly_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    if isinstance(e, JobError):
        return msg
    if "package not found" in low or "not a zip file" in low or "badzipfile" in type(e).__name__.lower() \
            or "no item named" in low or "is not a word file" in low:
        return "File Word bị hỏng hoặc không đúng định dạng .docx"
    return f"Lỗi xử lý: {msg[:300]}"


# Giới hạn sau giải nén: tệp .docx vài MB có thể chứa XML hàng trăm MB (tệp nén "bom") làm cạn RAM máy chủ.
MAX_UNZIP_MB = float(os.getenv("DOCX_MAX_UNZIP_MB", "150"))
MAX_ZIP_MEMBERS = 5000


def zip_bomb_error(z: zipfile.ZipFile) -> str | None:
    """Báo lỗi nếu tổng dung lượng sau giải nén hoặc số tệp con vượt giới hạn (đọc mục lục zip, không giải nén)."""
    infos = z.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        return f"File chứa quá nhiều thành phần ({len(infos)})"
    total = sum(i.file_size for i in infos)
    if total > MAX_UNZIP_MB * 1024 * 1024:
        return f"File giải nén ra quá lớn ({total / 2**20:.0f} MB, tối đa {MAX_UNZIP_MB:g} MB)"
    return None


def check_docx_bytes(data: bytes) -> str | None:
    """Kiểm tra nhanh trước khi nhận file. Trả về câu báo lỗi dễ hiểu, hoặc None nếu ổn."""
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "Đây là file .doc (Word 97-2003). Hãy mở bằng Word và chọn Lưu thành .docx rồi tải lại"
    if not data.startswith(b"PK"):
        return "Không phải file .docx hợp lệ"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                return "File nén không chứa nội dung Word (word/document.xml)"
            bomb = zip_bomb_error(z)
            if bomb:
                return bomb
    except zipfile.BadZipFile:
        return "File .docx bị hỏng (không giải nén được)"
    return None


def _standard_hint(ex, std: str) -> dict:
    """Gợi ý chuẩn thể thức dựa vào nội dung văn bản, kèm cờ mismatch nếu khác chuẩn đang chọn.
    Chỉ cảnh báo giữa nd30 <-> dang (Phụ lục 4.1 "dean" là thể loại khác hẳn, không so ở đây)."""
    hint = detect_standard_hint(ex)
    mismatch = bool(hint["suggested"] and hint["suggested"] in ("nd30", "dang")
                    and std in ("nd30", "dang") and hint["suggested"] != std)
    hint = dict(hint, current=std, mismatch=mismatch)
    if std == "dean":
        fit = detect_dean_fit(ex)
        if not fit["fits"]:
            hint.update(mismatch=True, suggested=hint["suggested"] if hint["suggested"] in ("nd30", "dang") else "nd30",
                        evidence=fit["evidence"] or hint["evidence"],
                        reason=("Không thấy cấu trúc luận văn/đề án thạc sĩ (không có dòng “LUẬN VĂN/ĐỀ ÁN THẠC SĨ”, "
                                "không có các phần MỞ ĐẦU, KẾT LUẬN, TÀI LIỆU THAM KHẢO). Vai trò đoạn theo chuẩn "
                                "“Đề án” sẽ không đúng với loại văn bản này."))
    return hint


def _build_job(d: Path, meta: dict, skip_conventions: bool) -> None:
    std = meta["standard"]
    raw = default_raw(std)
    build_spec(raw, skip_conventions)      # kiểm tra quy chuẩn hợp lệ trước khi đọc file
    _set_status(d, "running", "Đang đọc văn bản")
    ex = extract(str(d / "original.docx"))
    _set_status(d, "running", "Đang xác định vai trò đoạn")
    decisions = analyze_roles(ex, std)
    meta.update({"decisions": [x.to_json() for x in decisions if x is not None],
                 "role_overrides": {}, "skip_conventions": skip_conventions,
                 "standard_hint": _standard_hint(ex, std)})
    _write_json(d / "meta.json", meta)
    _set_status(d, "running", "Đang so sánh và sửa định dạng")
    run_job(meta["id"], None, None, skip_conventions)


def _new_job_dir(filename: str, data: bytes, standard: str, owner: str = "admin",
                 spell: dict | None = None) -> tuple[Path, dict]:
    std = _std(standard)
    cleanup_old()
    jid = uuid.uuid4().hex[:16]
    d = JOBS_DIR / jid
    d.mkdir(parents=True)
    (d / "original.docx").write_bytes(data)
    meta = {"id": jid, "file": filename, "stem": Path(filename).stem or "tai_lieu", "created": time.time(),
            "version": 0, "standard": std, "owner": owner}
    if spell is not None:
        from .spellword import validate_opts
        try:
            meta["spell"] = validate_opts(spell)
        except ValueError as e:
            raise JobError(str(e)) from e
    _set_status(d, "queued", "Đang chờ xử lý")
    _write_json(d / "meta.json", meta)
    return d, meta


def _worker(d: Path, meta: dict, skip_conventions: bool) -> None:
    jid = meta["id"]
    try:
        with _lock(jid):
            _build_job(d, meta, skip_conventions)
        _set_status(d, "done")
    except Exception as e:  # noqa: BLE001 - mọi lỗi đều phải báo về giao diện, không để phiên treo
        _set_status(d, "error", "", friendly_error(e))
    finally:
        _active.discard(jid)


def submit_job(filename: str, data: bytes, skip_conventions: bool = False,
               standard: str | None = "nd30", owner: str = "admin", spell: dict | None = None) -> str:
    """Nhận file, trả mã phiên ngay; xử lý chạy nền (không bị proxy cắt khi nhiều file)."""
    d, meta = _new_job_dir(filename, data, standard, owner, spell)
    _active.add(meta["id"])
    _executor.submit(_worker, d, meta, skip_conventions)
    return meta["id"]


def create_job(filename: str, data: bytes, skip_conventions: bool = False,
               standard: str | None = "nd30", owner: str = "admin", spell: dict | None = None) -> str:
    """Như submit_job nhưng chờ xử lý xong (dùng cho API đồng bộ/kiểm thử). Lỗi -> JobError."""
    d, meta = _new_job_dir(filename, data, standard, owner, spell)
    _active.add(meta["id"])
    _worker(d, meta, skip_conventions)
    st = job_status(meta["id"])
    if st["status"] != "done":
        raise JobError(st["error"] or "Xử lý thất bại", 422)
    return meta["id"]


def restandard_job(jid: str, standard: str, skip_conventions: bool | None = None) -> str:
    """Kiểm tra lại file ĐÃ tải lên theo chuẩn khác (NĐ 30 / Đảng / Đề án) – không cần tải lại file gốc.
    Vai trò đoạn được xác định lại từ đầu theo chuẩn mới, quy chuẩn lấy theo chuẩn mới.
    Giữ: chữ đã sửa, định dạng chỉnh tay, mục lục đã tạo. Bỏ: vai trò chỉnh tay và lỗi đã bỏ qua
    (gắn với vai trò của chuẩn cũ nên không còn đúng)."""
    d = _dir(jid)
    std = _std(standard)
    with _lock(jid):
        if jid in _active:
            raise JobError("File đang được xử lý, vui lòng đợi", 409)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if skip_conventions is None:
            skip_conventions = bool(meta.get("skip_conventions", False))
        for k in ("spec", "decisions", "role_overrides", "ignored", "summary", "summary_after",
                  "standard_hint"):
            meta.pop(k, None)
        meta["standard"] = std
        _active.add(jid)
        _write_json(d / "meta.json", meta)
        _set_status(d, "queued", "Đang chờ kiểm tra lại theo chuẩn mới")
    _executor.submit(_worker, d, meta, bool(skip_conventions))
    return jid


def run_job(jid: str, raw: dict | None, role_overrides: dict | None, skip_conventions: bool | None = None,
            text_edits: dict | None = None, ignored: list | None = None, manual_format: dict | None = None,
            spell: dict | None = None, toc: dict | None = None) -> dict:
    d = _dir(jid)
    with _lock(jid):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        std = meta.get("standard") or "nd30"
        if raw is None:
            raw = meta.get("spec") or default_raw(std)
        else:
            raw = restore_hidden(raw, meta.get("spec") or default_raw(std))
        try:
            notes = normalize_raw(raw)
            if skip_conventions is None:
                skip_conventions = bool(meta.get("skip_conventions"))
            spec = build_spec(raw, skip_conventions)
        except (ValueError, TypeError, KeyError) as e:
            raise JobError(f"Thông số không hợp lệ: {e}") from e
        if role_overrides is not None:
            valid = set(spec.roles) | {"empty"}
            bad = [r for r in role_overrides.values() if r not in valid]
            if bad:
                raise JobError(f"Vai trò không hợp lệ: {bad}")
            meta["role_overrides"] = role_overrides
        if text_edits is not None:
            if not isinstance(text_edits, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) and len(v) <= 20000 for k, v in text_edits.items()):
                raise JobError("text_edits phải là object {mã đoạn: chữ mới}")
            meta["text_edits"] = text_edits
        if ignored is not None:
            if not isinstance(ignored, list) or not all(isinstance(k, str) and "|" in k and len(k) < 200 for k in ignored):
                raise JobError("ignored phải là danh sách mã lỗi dạng 'mục tiêu|trường'")
            meta["ignored"] = sorted(set(ignored))
        if manual_format is not None:
            try:
                meta["manual_format"] = validate_manual_format(manual_format)
            except ValueError as e:
                raise JobError(str(e)) from e
        if spell is not None:
            from .spellword import validate_opts
            try:
                meta["spell"] = validate_opts(spell)
            except ValueError as e:
                raise JobError(str(e)) from e
        if toc is not None:
            meta["toc_opts"] = validate_toc_opts(toc)
        if "decisions" not in meta:
            raise JobError("File đang được xử lý, vui lòng đợi", 409)
        decisions = [RoleDecision.from_json(x) for x in meta["decisions"]]
        for dec in decisions:
            if dec.pid in meta["role_overrides"]:
                dec.role = meta["role_overrides"][dec.pid]
                dec.confidence, dec.method = 1.0, "user"
                dec.note = "Người dùng chỉnh vai trò"
        out = d / "out"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir()
        src = out / f"{meta['stem']}.docx"
        shutil.copyfile(d / "original.docx", src)
        ex = extract(str(src))
        edit_notes = []
        if meta.get("text_edits"):
            # chữ người dùng sửa trên bản xem trước: ghi vào bản sao của file gốc rồi kiểm tra/sửa như bình thường
            edit_notes = apply_text_edits(ex, meta["text_edits"])
            save_docx(ex.doc, src)
            ex = extract(str(src))
        if len(ex.paragraphs) != len(decisions):
            raise JobError("Cấu trúc file thay đổi, hãy tải lại", 409)
        result = evaluate(src, ex, decisions, spec, out, fix=True, write=True, with_preview=True,
                          ignored=meta.get("ignored"), manual_format=meta.get("manual_format"), spell=meta.get("spell"))
        src.unlink()
        topts = _toc_opts_of(meta)
        fixed_fp = out / f"{meta['stem']}_da_sua.docx"
        cands = None
        if topts.get("on"):
            # mục lục làm SAU cùng (trên bản đã sửa + sửa chính tả); cả bản không màu cũng có mục lục
            want = {k: topts[k] for k in ("toc", "hinh", "bang")}
            toc_stats = None
            for fp in (fixed_fp, out / f"{meta['stem']}_da_sua_khong_mau.docx"):
                if fp.exists():
                    st = build_toc(str(fp), str(fp), want, create=not topts.get("legacy"),
                                   exclude=topts.get("exclude") or (), include=topts.get("include") or ())
                    c = st.pop("candidates", None)
                    if toc_stats is None:
                        toc_stats, cands = st, c
            if toc_stats is not None:
                meta["toc_stats"] = toc_stats
                result["toc_stats"] = toc_stats
                for old in d.glob("pages_fixed_v*"):
                    shutil.rmtree(old, ignore_errors=True)
        else:
            meta.pop("toc_stats", None)
        if cands is None:
            try:
                # danh sách đề mục để tab Mục lục cho người dùng tích giữ/bỏ từng dòng (khi chưa dựng Mục lục)
                cands = toc_candidates(str(fixed_fp)) if fixed_fp.exists() else []
            except Exception:  # noqa: BLE001  - danh sách chỉ để tham khảo, không được làm hỏng việc sửa file
                cands = []
        result["toc_candidates"] = cands
        meta["version"] += 1
        meta["spec"] = raw
        meta["skip_conventions"] = skip_conventions
        meta["summary"] = result.get("summary")
        meta["summary_after"] = result.get("summary_after")
        result.update({"id": jid, "file": meta["file"], "version": meta["version"], "notes": notes + edit_notes,
                       "spec_raw": public_raw(raw), "text_edits": meta.get("text_edits") or {},
                       "ignored": meta.get("ignored") or [],
                       "manual_format": meta.get("manual_format") or {},
                       "spell_opts": meta.get("spell") or {"on": False},
                       "toc_opts": _toc_opts_of(meta),
                       "role_overrides": meta["role_overrides"], "skip_conventions": skip_conventions,
                       "standard": std,
                       "standard_hint": meta.get("standard_hint"),
                       "role_keys": [{"key": k, "label": r.label} for k, r in spec.roles.items()]})
        _write_json(d / "payload.json", result)
        _write_json(d / "meta.json", meta)
        return result


TOC_DEFAULT = {"on": False, "toc": True, "hinh": False, "bang": False}


def validate_toc_opts(raw) -> dict:
    """Lựa chọn mục lục từ người dùng: on (có làm hay không) + toc/hinh/bang (mục nào). Mặc định chỉ Mục lục.
    exclude/include: danh sách khoá đề mục người dùng tích bỏ/giữ lại (xem toc.analyze_headings)."""
    if not isinstance(raw, dict):
        raise JobError("toc phải là object {on, toc, hinh, bang}")
    out = dict(TOC_DEFAULT)
    for k in out:
        if k in raw:
            if not isinstance(raw[k], bool):
                raise JobError(f"toc.{k} phải là true hoặc false")
            out[k] = raw[k]
    for k in ("exclude", "include"):
        v = raw.get(k)
        if v is None:
            continue
        if not isinstance(v, list) or len(v) > 1000 or not all(isinstance(x, str) and 0 < len(x) <= 140 for x in v):
            raise JobError(f"toc.{k} phải là danh sách khoá đề mục (chuỗi)")
        if v:
            out[k] = sorted(set(v) - set(raw.get("include" if k == "exclude" else "exclude") or []))
    if out["on"] and not (out["toc"] or out["hinh"] or out["bang"]):
        raise JobError("Chưa chọn mục nào: hãy tick Mục lục, Danh mục hình hoặc Danh mục bảng")
    return out


def _toc_opts_of(meta: dict) -> dict:
    if meta.get("toc_opts"):
        return meta["toc_opts"]
    if meta.get("toc_applied"):            # phiên cũ (trước v43): đã bấm nút "Mục lục & danh mục" = làm cả ba, không tạo mới
        return {"on": True, "toc": True, "hinh": True, "bang": True, "legacy": True}
    return dict(TOC_DEFAULT)


def add_toc(jid: str, opts: dict | None = None) -> dict:
    """Tab "Mục lục": làm Mục lục / Danh mục hình / Danh mục bảng theo lựa chọn (mặc định chỉ Mục lục) và đánh số
    Hình/Bảng bằng field { SEQ ... } khi có chọn danh mục hình/bảng. Mục được chọn mà văn bản chưa có tiêu đề thì
    tạo mới trước đề mục đầu tiên. Dựng lại bản đã sửa từ file gốc theo đúng lựa chọn (nên bỏ tick rồi bấm lại là
    gỡ được; chạy lại nhiều lần cho cùng kết quả) và ghi nhớ để tự áp lại khi người dùng "Áp dụng & sửa lại"."""
    d = _dir(jid)
    with _lock(jid):
        o = dict(TOC_DEFAULT, on=True)
        if opts is not None:
            o = validate_toc_opts(dict(opts, on=True))
        if not (d / "meta.json").exists() or not (d / "out").exists():
            raise JobError("Chưa có file đã sửa để tạo mục lục", 409)
        run_job(jid, None, None, toc=o)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return meta.get("toc_stats") or {"captions": {}, "toc": {"inserted": {}, "created": {}, "already": {}, "removed_old": {}}}


def remove_toc(jid: str) -> dict:
    """Bỏ mục lục (dựng lại bản đã sửa không có Mục lục/Danh mục do công cụ tạo)."""
    d = _dir(jid)
    with _lock(jid):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        o = dict(_toc_opts_of(meta), on=False)
        o.pop("legacy", None)
        meta["toc_applied"] = False
        _write_json(d / "meta.json", meta)
        return run_job(jid, None, None, toc={k: o[k] for k in ("on", "toc", "hinh", "bang")})


def get_payload(jid: str) -> dict:
    d = _dir(jid)
    st = job_status(jid)
    if st["status"] == "error":
        raise JobError(st["error"] or "Xử lý thất bại", 422)
    p = d / "payload.json"
    if st["status"] != "done" or not p.exists():
        raise JobError("File đang được xử lý, vui lòng đợi", 409)
    return json.loads(p.read_text(encoding="utf-8"))


def job_summary(jid: str) -> dict:
    """Thông tin gọn của 1 phiên cho danh sách file / hỏi trạng thái khi đang xử lý nền."""
    d = _dir(jid)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    st = job_status(jid)
    summ = meta.get("summary") or {}
    summ_after = meta.get("summary_after") or {}
    out = {"id": meta["id"], "file": meta["file"], "status": st["status"], "stage": st.get("stage", ""),
           "ok": st["status"] != "error", "message": st.get("error", ""),
           "errors": summ.get("total", 0), "errors_after": summ_after.get("total", 0),
           "created": meta.get("created", 0), "standard": meta.get("standard", "nd30")}
    if st["status"] == "done":
        hint = meta.get("standard_hint") or {}
        out["standard_mismatch"] = bool(hint.get("mismatch"))
    return out


def job_owner(jid: str) -> str:
    """Chủ sở hữu của phiên. Phiên tạo trước khi có nhiều mã truy cập thuộc quản trị viên."""
    d = _dir(jid)
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8")).get("owner") or "admin"
    except (OSError, json.JSONDecodeError):
        return "admin"


def list_jobs(owner: str | None = None) -> list[dict]:
    """Danh sách các phiên của một chủ sở hữu (None = tất cả) để nạp lại danh sách file khi mở lại trang."""
    cleanup_old()
    out = []
    if not JOBS_DIR.exists():
        return out
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or not (d / "meta.json").exists():
            continue
        if owner is not None:
            try:
                if (json.loads((d / "meta.json").read_text(encoding="utf-8")).get("owner") or "admin") != owner:
                    continue
            except (OSError, json.JSONDecodeError):
                continue
        try:
            out.append(job_summary(d.name))
        except (OSError, json.JSONDecodeError, KeyError, JobError):
            continue
    out.sort(key=lambda x: x["created"], reverse=True)
    return out


def delete_job(jid: str) -> None:
    d = _dir(jid)
    with _lock(jid):
        shutil.rmtree(d, ignore_errors=True)
    with _locks_guard:
        _job_locks.pop(jid, None)


def file_path(jid: str, kind: str) -> tuple[Path, str, str]:
    d = _dir(jid)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    stem = meta["stem"]
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if kind == "original":
        return d / "original.docx", f"{stem}.docx", docx
    if kind == "fixed":
        return d / "out" / f"{stem}_da_sua.docx", f"{stem}_da_sua.docx", docx
    if kind == "fixed_clean":
        return d / "out" / f"{stem}_da_sua_khong_mau.docx", f"{stem}_da_sua_khong_mau.docx", docx
    if kind == "report":
        return d / "out" / f"{stem}_bao_cao.html", f"{stem}_bao_cao.html", "text/html; charset=utf-8"
    if kind == "json":
        return d / "out" / f"{stem}_bao_cao.json", f"{stem}_bao_cao.json", "application/json"
    if kind == "zip":
        z = d / "ket_qua.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted((d / "out").iterdir()):
                if p.suffix in (".docx", ".html", ".json"):
                    zf.write(p, p.name)
        return z, f"{stem}_ket_qua.zip", "application/zip"
    raise JobError("Loại file không hợp lệ", 404)


def read_file(jid: str, kind: str) -> tuple[bytes, str, str]:
    """Đọc file tải về TRONG khóa phiên: "Áp dụng & sửa lại"/"Tạo mục lục" xoá rồi ghi lại thư mục out/
    và ghi đè file đã sửa tại chỗ; tải về đúng lúc đó sẽ nhận file dở dang (Word báo hỏng) hoặc 404."""
    with _lock(jid):
        path, name, mime = file_path(jid, kind)
        if not path.exists():
            raise JobError("Chưa có file", 404)
        return path.read_bytes(), name, mime


# ------------------------------------------------------------------ bản in (LibreOffice -> PDF -> PNG)
def _have_pymupdf() -> bool:
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        return False


def office_available() -> bool:
    """Cần LibreOffice (đổi Word -> PDF) và pdftoppm hoặc PyMuPDF (đổi PDF -> ảnh trang)."""
    return bool(shutil.which("soffice") or shutil.which("libreoffice")) and bool(shutil.which("pdftoppm") or _have_pymupdf())


_EXTERNAL_REL = re.compile(rb'<Relationship\b(?=[^>]*\bTargetMode="External")[^>]*/>')
_KEEP_EXTERNAL = re.compile(rb'Type="[^"]*/hyperlink"')
_REMOTE_FIELD = re.compile(rb'\b(INCLUDEPICTURE|INCLUDETEXT|LINK|IMPORT)\b([^"<&]*?)(?:"|&quot;)'
                           rb'(?:[a-z][a-z0-9+.\-]*:|\\\\)[^"<&]*(?:"|&quot;)', re.I)


def strip_external_refs(path: Path) -> int:
    """Gỡ tham chiếu ra ngoài (ảnh/mẫu/OLE liên kết, trường INCLUDEPICTURE/INCLUDETEXT/LINK) khỏi BẢN SAO trước khi
    LibreOffice mở, để tệp người dùng không khiến máy chủ gọi tới địa chỉ khác (SSRF). Giữ siêu liên kết thường."""
    removed = 0
    out = path.with_suffix(".clean")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info)
            if info.filename.endswith(".rels"):
                def drop(m):
                    nonlocal removed
                    if _KEEP_EXTERNAL.search(m.group(0)):
                        return m.group(0)
                    removed += 1
                    return b""
                data = _EXTERNAL_REL.sub(drop, data)
            elif info.filename.endswith(".xml") and b"://" in data:
                data, n = _REMOTE_FIELD.subn(lambda m: m.group(1) + m.group(2) + b'""', data)
                removed += n
            zout.writestr(info, data)
    out.replace(path)
    return removed


def render_pages(jid: str, which: str, dpi: int = 110) -> dict:
    if which not in ("original", "fixed"):
        raise JobError("Chỉ có bản gốc hoặc bản đã sửa", 404)
    if not office_available():
        raise JobError("Máy chủ chưa cài LibreOffice/poppler-utils để dựng bản in", 501)
    d = _dir(jid)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    ver = meta["version"] if which == "fixed" else 0
    pdir = d / f"pages_{which}_v{ver}"
    done = pdir / "done.json"
    if done.exists():
        return json.loads(done.read_text())
    src, _, _ = file_path(jid, which)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    with _office_lock:  # LibreOffice không chạy song song an toàn với cùng profile
        if done.exists():
            return json.loads(done.read_text())
        for old in d.glob(f"pages_{which}_v*"):
            shutil.rmtree(old, ignore_errors=True)
        pdir.mkdir()
        work = Path(tempfile.mkdtemp(prefix="nd30_lo_"))
        try:
            tmp_doc = work / "doc.docx"
            with _lock(jid):   # tránh chép đúng lúc bản đã sửa đang được ghi lại
                shutil.copyfile(src, tmp_doc)
            strip_external_refs(tmp_doc)
            profile = (work / "profile").as_uri()
            cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                   "--convert-to", "pdf", "--outdir", str(work), str(tmp_doc)]
            subprocess.run(cmd, check=True, timeout=180, capture_output=True)
            pdf = work / "doc.pdf"
            if not pdf.exists():
                raise JobError("LibreOffice không tạo được PDF", 500)
            shutil.copyfile(pdf, pdir / "doc.pdf")
            if shutil.which("pdftoppm"):
                subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(pdir / "page")],
                               check=True, timeout=180, capture_output=True)
            else:   # máy không có poppler (VD bản cài trên Windows): dựng ảnh trang bằng PyMuPDF
                import pymupdf
                with pymupdf.open(str(pdf)) as pd:
                    for i, pg in enumerate(pd, 1):
                        pg.get_pixmap(dpi=dpi).save(str(pdir / f"page-{i}.png"))
        except subprocess.TimeoutExpired as e:
            raise JobError("Dựng bản in quá thời gian", 504) from e
        except subprocess.CalledProcessError as e:
            raise JobError(f"Lỗi dựng bản in: {e.stderr[-300:]!r}", 500) from e
        finally:
            shutil.rmtree(work, ignore_errors=True)
        pages = sorted(pdir.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        info = {"count": len(pages), "version": ver, "files": [p.name for p in pages]}
        done.write_text(json.dumps(info))
        return info


def page_file(jid: str, which: str, n: int) -> Path:
    info = render_pages(jid, which)
    if not 1 <= n <= info["count"]:
        raise JobError("Không có trang này", 404)
    ver = info["version"]
    return _dir(jid) / f"pages_{which}_v{ver}" / info["files"][n - 1]


def pdf_file(jid: str, which: str) -> Path:
    info = render_pages(jid, which)
    return _dir(jid) / f"pages_{which}_v{info['version']}" / "doc.pdf"
