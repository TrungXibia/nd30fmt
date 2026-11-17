"""Thư viện Markdown: lưu file gốc, bản Markdown, ảnh trích xuất và chỉ mục tìm kiếm toàn văn.

Mỗi mã truy cập (chủ sở hữu) chỉ thấy tài liệu của mình – cùng nguyên tắc với phiên Chuẩn hoá.
Dữ liệu nằm trong DATA_DIR/markdown/ (SQLite FTS5 + thư mục theo chủ sở hữu).
"""
from __future__ import annotations

import hashlib
import json
import html
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .. import jobs

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
IMG_PLACEHOLDER = "{IMGBASE}/"
SHARE_TTL_DAYS = float(__import__("os").getenv("SHARE_TTL_DAYS", "30"))   # 0 = link chia sẻ không hết hạn
_guard = threading.RLock()


class MdError(RuntimeError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def root() -> Path:
    return jobs.DATA_DIR / "markdown"


def _owner_dir(owner: str) -> Path:
    safe = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]
    return root() / safe


def _db() -> sqlite3.Connection:
    root().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root() / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, filename TEXT NOT NULL, ext TEXT NOT NULL,
        uploaded_at TEXT NOT NULL, updated_at TEXT, char_count INTEGER DEFAULT 0,
        orig_path TEXT, md_path TEXT NOT NULL, label TEXT, share_token TEXT, img_key TEXT NOT NULL)""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    if "share_at" not in cols:      # CSDL tạo trước khi link chia sẻ có hạn: link cũ tính hạn từ lúc nâng cấp
        conn.execute("ALTER TABLE documents ADD COLUMN share_at REAL")
        conn.execute("UPDATE documents SET share_at=? WHERE share_token IS NOT NULL", (time.time(),))
        conn.commit()
    conn.execute("CREATE INDEX IF NOT EXISTS ix_doc_owner ON documents(owner, uploaded_at)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(doc_id UNINDEXED, owner UNINDEXED, "
                 "filename, content, orig UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    return conn


def _fold(text: str) -> str:
    """unicode61 bỏ dấu thanh nhưng coi "đ" là chữ riêng: đổi đ/Đ → d/D (giữ nguyên độ dài) để gõ "dinh" tìm được "định"."""
    return (text or "").replace("đ", "d").replace("Đ", "D")


_M1, _M2 = "\x01", "\x02"


def _restore_snippet(snip: str, orig: str) -> str:
    """Đoạn trích lấy từ cột đã đổi đ→d; ánh xạ lại sang văn bản gốc (cùng vị trí) để hiển thị đúng chữ "đ"."""
    plain = snip.replace(_M1, "").replace(_M2, "")
    core = plain.strip("…")
    lead = len(plain) - len(plain.lstrip("…"))
    pos = _fold(orig).find(core)
    if pos < 0 or not core:
        return snip
    out, i = [], pos - lead
    for ch in snip:
        if ch in (_M1, _M2):
            out.append(ch)
            continue
        out.append(orig[i] if 0 <= i < len(orig) and ch != "…" else ch)
        i += 1
    return "".join(out)


def _images_dir(row) -> Path:
    return Path(row["md_path"]).parent.parent / "images" / row["id"]


def reassign_owner(old: str, new: str) -> int:
    """Chuyển tài liệu của một mã đã xoá sang chủ sở hữu khác (đường dẫn file giữ nguyên)."""
    with _guard:
        conn = _db()
        try:
            n = conn.execute("UPDATE documents SET owner=? WHERE owner=?", (new, old)).rowcount
            conn.execute("UPDATE documents_fts SET owner=? WHERE owner=?", (new, old))
            conn.commit()
        finally:
            conn.close()
    return n


def _public(row) -> dict:
    d = dict(row)
    for k in ("orig_path", "md_path", "owner", "img_key"):
        d.pop(k, None)
    d["shared"] = bool(d.pop("share_token", None)) and _share_alive(d.get("share_at"))
    d.pop("share_at", None)
    return d


def _safe_name(name: str) -> str:
    name = Path(str(name or "tai-lieu")).name
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "_", name).strip(" .") or "tai-lieu"
    return name[:150]


def convert_bytes(filename: str, data: bytes, images_dir: Path, progress=None) -> str:
    """File -> Markdown (PDF, DOCX, DOC, TXT/MD, ảnh qua OCR)."""
    from . import doc_to_md
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise MdError(f"Định dạng {ext or '(không có đuôi)'} chưa hỗ trợ")
    if ext == ".docx":
        bad = jobs.check_docx_bytes(data)
        if bad:
            raise MdError(f"“{filename}”: {bad}")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / ("input" + ext)
        src.write_bytes(data)
        try:
            text = doc_to_md.convert(src, images_dir=images_dir, image_url_prefix=IMG_PLACEHOLDER, progress=progress)
        except ImportError as e:
            raise MdError(f"Máy chủ thiếu thư viện chuyển đổi: {e}", 500) from e
        except (RuntimeError, ValueError) as e:
            raise MdError(str(e)) from e
    return text.replace("\r\n", "\n").strip() + "\n"


# ---------------------------------------------------------------- sửa lỗi dấu OCR (tự sửa, có hoàn tác)
def _ocr_paths(row) -> tuple[Path, Path]:
    d = Path(row["md_path"]).parent.parent / "ocr"
    return d / f"{row['id']}.raw.md", d / f"{row['id']}.json"


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _finalize_ocr(raw: str, disabled: set) -> tuple[str, list[dict]]:
    """Bản OCR thô (có ký hiệu vùng) -> (Markdown đã sửa, các chỗ sửa theo vị trí trong Markdown)."""
    import bisect
    from . import vnfix
    try:
        fixed, fixes = vnfix.correct_regions(raw, disabled)
    except Exception:  # noqa: BLE001 - thiếu dữ liệu mô hình: vẫn lưu bản OCR, không sửa
        fixed, fixes = raw, []
    marks = [i for i, c in enumerate(fixed) if c in (vnfix.OCR_OPEN, vnfix.OCR_CLOSE)]
    out = vnfix.strip_regions(fixed)
    moved = [{**f, "start": f["start"] - bisect.bisect_left(marks, f["start"]),
              "end": f["end"] - bisect.bisect_left(marks, f["end"])} for f in fixes]
    return out, moved


def ocr_info(owner: str, doc_id: str, current: str | None = None) -> dict | None:
    """Thông tin sửa dấu của tài liệu chuyển bằng OCR; None nếu tài liệu không qua OCR."""
    from . import vnfix
    row = _row(owner, doc_id)
    raw_p, meta_p = _ocr_paths(row)
    if not meta_p.exists():
        return None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    if current is None:
        current = Path(row["md_path"]).read_text(encoding="utf-8", errors="replace")
    disabled = {tuple(x) for x in meta.get("disabled", [])}
    edited = _sha(current) != meta.get("md_sha")
    try:
        sus = [] if edited else vnfix.suspicious_spans(current)
    except Exception:  # noqa: BLE001
        sus = []
    return {"groups": [{**g, "on": (g["from"], g["to"]) not in disabled} for g in meta.get("groups", [])],
            "fixed": len(meta.get("fixes", [])), "suspicious": len(sus), "edited": edited,
            "_fixes": [] if edited else meta.get("fixes", []), "_sus": sus}


def set_ocr_fix(owner: str, doc_id: str, disabled: list) -> dict:
    """Bật/tắt từng nhóm sửa (dựng lại từ bản OCR thô). disabled: [[sai, đúng], …]; mọi nhóm = khôi phục bản gốc."""
    from . import vnfix
    row = _row(owner, doc_id)
    raw_p, meta_p = _ocr_paths(row)
    if not raw_p.exists() or not meta_p.exists():
        raise MdError("Tài liệu này không chuyển bằng nhận dạng chữ nên không có bản gốc để khôi phục", 400)
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    dis = {tuple(x) for x in disabled if isinstance(x, (list, tuple)) and len(x) == 2}
    final, fixes = _finalize_ocr(raw_p.read_text(encoding="utf-8"), dis)
    update_markdown(owner, doc_id, final)
    meta.update({"disabled": sorted(list(x) for x in dis), "fixes": fixes, "md_sha": _sha(final)})
    meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return ocr_info(owner, doc_id, final)


def add_document(owner: str, filename: str, data: bytes, label_fn=None, progress=None) -> dict:
    filename = _safe_name(filename)
    ext = Path(filename).suffix.lower()
    doc_id = uuid.uuid4().hex[:12]
    base = _owner_dir(owner)
    images_dir = base / "images" / doc_id
    try:
        text = convert_bytes(filename, data, images_dir, progress)
    except Exception:
        shutil.rmtree(images_dir, ignore_errors=True)
        raise
    raw_ocr = None
    from .vnfix import OCR_OPEN, group as _group_fixes
    if OCR_OPEN in text:
        raw_ocr = text
        text, ocr_fixes = _finalize_ocr(raw_ocr, set())
    if not text.strip():
        shutil.rmtree(images_dir, ignore_errors=True)
        raise MdError(f"“{filename}”: không trích được nội dung (file rỗng hoặc ảnh không đọc được chữ)")
    (base / "originals").mkdir(parents=True, exist_ok=True)
    (base / "md").mkdir(parents=True, exist_ok=True)
    orig = base / "originals" / f"{doc_id}{ext}"
    orig.write_bytes(data)
    md = base / "md" / f"{doc_id}.md"
    md.write_text(text, encoding="utf-8")
    if raw_ocr is not None:
        (base / "ocr").mkdir(parents=True, exist_ok=True)
        (base / "ocr" / f"{doc_id}.raw.md").write_text(raw_ocr, encoding="utf-8")
        (base / "ocr" / f"{doc_id}.json").write_text(json.dumps(
            {"disabled": [], "groups": _group_fixes(ocr_fixes), "fixes": ocr_fixes, "md_sha": _sha(text)},
            ensure_ascii=False), encoding="utf-8")
    label = None
    if label_fn:
        try:
            label = label_fn(text)
        except Exception:  # noqa: BLE001 - nhãn chỉ là phụ trợ
            label = None
    now = datetime.now().isoformat(timespec="seconds")
    with _guard:
        conn = _db()
        try:
            conn.execute("INSERT INTO documents (id, owner, filename, ext, uploaded_at, updated_at, char_count, orig_path,"
                         " md_path, label, img_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (doc_id, owner, filename, ext, now, now, len(text), str(orig), str(md), label,
                          secrets.token_urlsafe(16)))
            conn.execute("INSERT INTO documents_fts (doc_id, owner, filename, content, orig) VALUES (?,?,?,?,?)",
                         (doc_id, owner, _fold(filename), _fold(text), text))
            conn.commit()
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            conn.close()
    out = _public(row)
    from .doc_to_md import TRUNCATED_MARK
    out["truncated"] = text.lstrip().startswith("> " + TRUNCATED_MARK)
    return out


def add_text(owner: str, name: str, markdown: str) -> dict:
    name = _safe_name(name or "ghi-chu")
    if not name.lower().endswith((".md", ".markdown")):
        name += ".md"
    return add_document(owner, name, (markdown or "").encode("utf-8"))


def list_documents(owner: str, query: str = "") -> list[dict]:
    q = (query or "").strip()
    with _guard:
        conn = _db()
        try:
            if not q:
                rows = conn.execute("SELECT * FROM documents WHERE owner=? ORDER BY uploaded_at DESC", (owner,)).fetchall()
                return [_public(r) for r in rows]
            terms = [t for t in re.findall(r"\w+", _fold(q), re.UNICODE) if t]
            if not terms:
                return []
            match = " AND ".join(f'"{t}"*' for t in terms)
            rows = conn.execute(
                "SELECT d.*, snippet(documents_fts, 3, char(1), char(2), '…', 14) AS snippet, f.orig AS orig FROM documents_fts f "
                "JOIN documents d ON d.id = f.doc_id WHERE documents_fts MATCH ? AND f.owner = ? ORDER BY rank",
                (match, owner)).fetchall()
            out = []
            for r in rows:
                d = _public(r)
                # đoạn trích an toàn: escape rồi mới đánh dấu từ khớp
                snip = _restore_snippet(r["snippet"] or "", r["orig"] or "")
                d["snippet"] = html.escape(snip.replace("<br>", " · ")).replace(_M1, "<mark>").replace(_M2, "</mark>")
                out.append(d)
            return out
        except sqlite3.OperationalError as e:
            raise MdError(f"Từ khoá tìm kiếm không hợp lệ: {e}") from e
        finally:
            conn.close()


def _row(owner: str, doc_id: str):
    with _guard:
        conn = _db()
        try:
            row = conn.execute("SELECT * FROM documents WHERE id=? AND owner=?", (doc_id, owner)).fetchone()
        finally:
            conn.close()
    if row is None:
        raise MdError("Không có tài liệu này", 404)
    return row


def get_document(owner: str, doc_id: str) -> tuple[dict, str, dict]:
    row = _row(owner, doc_id)
    text = Path(row["md_path"]).read_text(encoding="utf-8", errors="replace")
    return _public(row), text, {"img_key": row["img_key"]}


def update_markdown(owner: str, doc_id: str, markdown: str) -> dict:
    row = _row(owner, doc_id)
    if len(markdown.encode("utf-8")) > 20 * 1024 * 1024:
        raise MdError("Nội dung quá lớn (tối đa 20 MB)")
    Path(row["md_path"]).write_text(markdown, encoding="utf-8")
    now = datetime.now().isoformat(timespec="seconds")
    with _guard:
        conn = _db()
        try:
            conn.execute("UPDATE documents SET char_count=?, updated_at=? WHERE id=?", (len(markdown), now, doc_id))
            conn.execute("UPDATE documents_fts SET content=?, orig=? WHERE doc_id=?", (_fold(markdown), markdown, doc_id))
            conn.commit()
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            conn.close()
    return _public(row)


def rename(owner: str, doc_id: str, filename: str) -> dict:
    _row(owner, doc_id)
    filename = _safe_name(filename)
    with _guard:
        conn = _db()
        try:
            conn.execute("UPDATE documents SET filename=? WHERE id=?", (filename, doc_id))
            conn.execute("UPDATE documents_fts SET filename=? WHERE doc_id=?", (_fold(filename), doc_id))
            conn.commit()
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            conn.close()
    return _public(row)


def delete_document(owner: str, doc_id: str) -> None:
    row = _row(owner, doc_id)
    for p in (row["orig_path"], row["md_path"], *_ocr_paths(row)):
        if p:
            Path(p).unlink(missing_ok=True)
    shutil.rmtree(_images_dir(row), ignore_errors=True)
    with _guard:
        conn = _db()
        try:
            conn.execute("DELETE FROM documents_fts WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.commit()
        finally:
            conn.close()


def delete_owner(owner: str) -> int:
    with _guard:
        conn = _db()
        try:
            ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE owner=?", (owner,))]
        finally:
            conn.close()
    for i in ids:
        delete_document(owner, i)
    shutil.rmtree(_owner_dir(owner), ignore_errors=True)
    return len(ids)


def set_share(owner: str, doc_id: str, on: bool) -> str | None:
    _row(owner, doc_id)
    token = secrets.token_urlsafe(24) if on else None
    with _guard:
        conn = _db()
        try:
            conn.execute("UPDATE documents SET share_token=?, share_at=? WHERE id=?",
                         (token, time.time() if token else None, doc_id))
            conn.commit()
        finally:
            conn.close()
    return token


def _share_alive(share_at) -> bool:
    if SHARE_TTL_DAYS <= 0:
        return True
    return share_at is not None and time.time() - float(share_at) < SHARE_TTL_DAYS * 86400


def share_token(owner: str, doc_id: str) -> str | None:
    row = _row(owner, doc_id)
    return row["share_token"] if row["share_token"] and _share_alive(row["share_at"]) else None


def public_document(doc_id: str, token: str):
    with _guard:
        conn = _db()
        try:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            conn.close()
    if row is None or not row["share_token"] or not secrets.compare_digest(row["share_token"], token or ""):
        raise MdError("Không tồn tại", 404)
    if not _share_alive(row["share_at"]):
        raise MdError("Link chia sẻ đã hết hạn", 404)
    return row


def image_path(doc_id: str, key: str, fname: str, public: bool = False) -> Path:
    with _guard:
        conn = _db()
        try:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            conn.close()
    secret = (row["share_token"] if public else row["img_key"]) if row else None
    if not secret or not secrets.compare_digest(secret, key or ""):
        raise MdError("Không tồn tại", 404)
    if public and not _share_alive(row["share_at"]):
        raise MdError("Không tồn tại", 404)
    folder = _images_dir(row).resolve()
    p = (folder / fname).resolve()
    if p.parent != folder or not p.is_file():
        raise MdError("Không tồn tại", 404)
    return p


def original_path(owner: str, doc_id: str) -> tuple[Path, str]:
    row = _row(owner, doc_id)
    return Path(row["orig_path"]), row["filename"]


def mark_ocr(text: str, info: dict | None) -> str:
    """Chèn ký hiệu (vùng riêng Unicode) quanh chỗ đã sửa / nghi sai để render_html tô màu."""
    if not info:
        return text
    from . import vnfix
    spans = [(f["start"], f["end"], vnfix.MARK_FIX_OPEN, vnfix.MARK_FIX_CLOSE) for f in info.get("_fixes", [])]
    spans += [(a, b, vnfix.MARK_SUS_OPEN, vnfix.MARK_SUS_CLOSE) for a, b in info.get("_sus", [])]
    spans.sort()
    out, last = [], 0
    for a, b, o, c in spans:
        if a < last or b > len(text):
            continue
        out += [text[last:a], o, text[a:b], c]
        last = b
    out.append(text[last:])
    return "".join(out)


def render_html(markdown_text: str, info: dict | None = None) -> str:
    """Markdown -> HTML an toàn: không cho HTML thô trong nội dung (chống chèn mã).
    info (từ ocr_info): tô chỗ đã tự sửa dấu (xanh, rê chuột thấy chữ OCR gốc) và chỗ nghi sai (gạch đỏ)."""
    import markdown as md_lib
    from . import vnfix
    safe = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace("&lt;br>", "<br>")
    out = md_lib.markdown(safe, extensions=["tables", "fenced_code", "sane_lists"])
    if info:
        olds = iter(f["from"] for f in sorted(info.get("_fixes", []), key=lambda f: f["start"]))
        out = re.sub(re.escape(vnfix.MARK_FIX_OPEN) + "(.*?)" + re.escape(vnfix.MARK_FIX_CLOSE),
                     lambda m: f'<mark class="ocrfix" title="Đã sửa từ bản nhận dạng: '
                               f'{html.escape(next(olds, ""), quote=True)}">{m.group(1)}</mark>', out, flags=re.S)
        out = re.sub(re.escape(vnfix.MARK_SUS_OPEN) + "(.*?)" + re.escape(vnfix.MARK_SUS_CLOSE),
                     r'<span class="ocrsus" title="Có thể nhận dạng sai – hãy đối chiếu bản gốc">\1</span>', out, flags=re.S)
    for ch in (vnfix.MARK_FIX_OPEN, vnfix.MARK_FIX_CLOSE, vnfix.MARK_SUS_OPEN, vnfix.MARK_SUS_CLOSE):
        out = out.replace(ch, "")
    return re.sub(r'\b(href|src)="([^"]*)"', _safe_url_attr, out, flags=re.I)


# Trình duyệt bỏ mọi ký tự điều khiển/khoảng trắng ASCII khi đọc scheme ("java\tscript:", "\x01javascript:"),
# nên phải bỏ chúng trước khi xét; chỉ cho link tương đối, http(s), mailto và ảnh data:image.
_URL_JUNK = re.compile(r"[\x00-\x20\x7f]+")
_URL_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.I)
_SAFE_SCHEMES = {"http", "https", "mailto"}
_SAFE_DATA_IMG = re.compile(r"^data:image/(png|jpe?g|gif|webp);", re.I)


def safe_url(value: str, attr: str = "href") -> str:
    """URL an toàn để đặt vào href/src, hoặc "#" nếu scheme không được phép (javascript:, vbscript:, data:...)."""
    url = _URL_JUNK.sub("", html.unescape(value or ""))
    m = _URL_SCHEME.match(url)
    if not m:
        return value
    scheme = m.group(1).lower()
    if scheme in _SAFE_SCHEMES or (attr.lower() == "src" and _SAFE_DATA_IMG.match(url)):
        return value
    return "#"


def _safe_url_attr(m: re.Match) -> str:
    return f'{m.group(1)}="{safe_url(m.group(2), m.group(1))}"'


def resolve_images(text: str, base: str) -> str:
    return text.replace(IMG_PLACEHOLDER, base)


def dated_name(uploaded_at: str, filename: str) -> str:
    date_part = (uploaded_at or "").split("T")[0].replace("-", "") or "tai-lieu"
    return f"{date_part}_{filename}"
