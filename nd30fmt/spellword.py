"""Áp bộ sửa chính tả (vspell) vào file Word: sửa thẳng chữ, chỗ nào sửa chữ thì đổi màu chữ để nhận biết.

Nguyên tắc:
- Chỉ đổi màu đúng đoạn chữ mới thay vào (run được tách ra, giữ nguyên mọi định dạng khác của run gốc);
  sửa dấu cách / chuẩn Unicode không đổi màu vì không nhìn thấy được.
- Không đụng tới chữ trong trường tự động của Word (số trang, mục lục, SEQ, hyperlink dạng trường...), run đặt
  "không kiểm tra chính tả" (noProof), run ẩn, run dùng phông chữ lập trình, chữ trong hộp văn bản (như phần còn lại
  của công cụ này), và đoạn chữ nằm cạnh dấu gạch chéo, chấm, @, gạch dưới (đường dẫn, email, số hiệu văn bản).
- Mỗi chỗ sửa có mã ổn định ("mã đoạn:vị trí:loại") để người dùng tắt/bật từng chỗ, tắt cả nhóm, hoặc khai báo
  từ không sửa; chạy lại luôn dựng từ file gốc nên kết quả giống nhau với cùng lựa chọn.
- Mức "an toàn" (mặc định) chỉ ghi các chỗ chắc chắn; mức "rộng" ghi thêm các chỗ nghi ngờ có gợi ý (màu khác).
"""
from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass

from docx.oxml import OxmlElement

from . import vspell
from .extract import iter_runs, qn

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
RED = "FF0000"
ORANGE = "ED7D31"
OBJ = "￼"                      # thay cho phần không phải chữ (hình, trường, ký hiệu...): không ghép chữ qua nó
MAX_ITEMS = 3000
MONO = re.compile(r"consolas|courier|mono|code|menlo|lucida console|symbol|wingdings|webdings", re.I)
GROUPS = {
    "nfc": "Chuẩn Unicode (chữ tổ hợp)", "space": "Dấu cách", "dup": "Lặp từ", "placement": "Dấu thanh đặt sai chỗ",
    "tone": "Âm tiết sai dấu/chính tả", "edit": "Gõ thừa/thiếu/nhầm chữ cái", "edit_rare": "Chữ hiếm, gần một chữ phổ biến",
    "context": "Sai theo ngữ cảnh", "telex": "Sót phím Telex", "pair": "Cặp sai–đúng thường gặp",
    "style": "Thống nhất cách viết",
}
UNMARKED = {"nfc", "space"}


@dataclass
class _Piece:
    node: object          # w:t
    run: object
    start: int
    end: int


def _hex(c: str | None, default: str) -> str:
    c = (c or "").strip().lstrip("#").upper()
    return c if re.fullmatch(r"[0-9A-F]{6}", c) else default


def _run_protected(r) -> bool:
    rpr = r.find(qn("w:rPr"))
    if rpr is None:
        return False
    if rpr.find(qn("w:noProof")) is not None or rpr.find(qn("w:vanish")) is not None:
        return True
    rs = rpr.find(qn("w:rStyle"))
    if rs is not None and "hyperlink" in (rs.get(qn("w:val")) or "").lower():
        return True
    rf = rpr.find(qn("w:rFonts"))
    if rf is not None:
        for k in ("w:ascii", "w:hAnsi", "w:cs"):
            if MONO.search(rf.get(qn(k)) or ""):
                return True
    return False


def _in_simple_field(r, p_el) -> bool:
    a = r.getparent()
    while a is not None and a is not p_el:
        if a.tag in (qn("w:fldSimple"), qn("w:instrText")):
            return True
        a = a.getparent()
    return False


def _build(p_el) -> tuple[str, list[_Piece]]:
    """Chuỗi chữ của đoạn (chỗ không sửa được thay bằng OBJ để giữ độ dài) và danh sách mảnh w:t."""
    parts: list[str] = []
    pieces: list[_Piece] = []
    pos = 0
    depth = 0
    for r in iter_runs(p_el):
        prot = _run_protected(r) or _in_simple_field(r, p_el)
        for ch in r:
            tag = ch.tag
            if tag == qn("w:fldChar"):
                typ = ch.get(qn("w:fldCharType"))
                if typ == "begin":
                    depth += 1
                elif typ == "end":
                    depth = max(0, depth - 1)
                parts.append(OBJ)
                pos += 1
            elif tag == qn("w:t"):
                tx = ch.text or ""
                if depth or prot:
                    parts.append(OBJ * len(tx))
                else:
                    parts.append(tx)
                    pieces.append(_Piece(ch, r, pos, pos + len(tx)))
                pos += len(tx)
            elif tag == qn("w:tab"):
                parts.append("\t")
                pos += 1
            elif tag in (qn("w:br"), qn("w:cr")):
                parts.append("\n")
                pos += 1
            elif tag in (qn("w:rPr"), qn("w:instrText"), qn("w:delText")):
                continue
            else:
                parts.append(OBJ)
                pos += 1
    return "".join(parts), pieces


def _set_text(node, s: str) -> None:
    node.text = s
    node.set(XML_SPACE, "preserve")


def _colorize(run, color: str) -> None:
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run.insert(0, rpr)
    col = rpr.find(qn("w:color"))
    if col is None:
        col = OxmlElement("w:color")
        rpr.append(col)
    for k in list(col.attrib):
        del col.attrib[k]
    col.set(qn("w:val"), color)


def _new_run_like(run):
    nr = OxmlElement("w:r")
    rpr = run.find(qn("w:rPr"))
    if rpr is not None:
        nr.append(copy.deepcopy(rpr))
    return nr


def _apply_fix(pieces: list[_Piece], f: vspell.Fix, color: str | None) -> bool:
    cov = [pc for pc in pieces if pc.start < f.end and f.start < pc.end]
    if not cov:
        return False
    first = cov[0]
    for pc in cov[1:]:
        a, b = max(f.start, pc.start) - pc.start, min(f.end, pc.end) - pc.start
        s = pc.node.text or ""
        _set_text(pc.node, s[:a] + s[b:])
    a, b = f.start - first.start, min(f.end, first.end) - first.start
    a = max(a, 0)
    s = first.node.text or ""
    if color is None or not f.mark:
        _set_text(first.node, s[:a] + f.new + s[b:])
        return True
    run, node = first.run, first.node
    pre, post = s[:a], s[b:]
    tail = []                                   # phần tử đứng sau w:t trong cùng run (tab, hình...) đi theo phần "sau"
    after = False
    for ch in list(run):
        if ch is node:
            after = True
            continue
        if after:
            tail.append(ch)
    mid = _new_run_like(run)
    t = OxmlElement("w:t")
    _set_text(t, f.new)
    mid.append(t)
    _colorize(mid, color)
    _set_text(node, pre)
    anchor = run
    anchor.addnext(mid)
    anchor = mid
    if post or tail:
        pr = _new_run_like(run)
        if post:
            t2 = OxmlElement("w:t")
            _set_text(t2, post)
            pr.append(t2)
        for ch in tail:
            pr.append(ch)                       # lxml chuyển phần tử sang run mới
        mid.addnext(pr)
    if not pre and not [c for c in run if c.tag != qn("w:rPr") and not (c.tag == qn("w:t") and not (c.text or ""))]:
        run.getparent().remove(run)
    return True


def _nfc_pass(paras) -> int:
    n = 0
    for p in paras:
        for r in iter_runs(p.element):
            for t in r.iter(qn("w:t")):
                s = t.text or ""
                if s and not s.isascii():
                    ns = unicodedata.normalize("NFC", s)
                    if ns != s:
                        _set_text(t, ns)
                        n += 1
    return n


def _context(text: str, f: vspell.Fix, w: int = 28) -> str:
    a = text[max(0, f.start - w):f.start].replace(OBJ, "").replace("\n", " ").replace("\t", " ")
    b = text[f.end:f.end + w].replace(OBJ, "").replace("\n", " ").replace("\t", " ")
    return ("…" if f.start > w else "") + a + "[" + f.old + "]" + b + ("…" if f.end + w < len(text) else "")


def process_document(ex, opts: dict | None = None, mark: bool = True) -> dict:
    """Sửa chính tả trực tiếp trong ex.doc (người gọi tự lưu). Trả về báo cáo cho giao diện.

    opts: level 'safe'|'wide'; color, color_maybe (hex 6 ký tự); force_off / force_on: mã từng chỗ sửa bị tắt / bật thêm;
    off_kinds: nhóm bị tắt; ignore_words: chữ không sửa. mark=False: không đổi màu (bản sạch)."""
    opts = opts or {}
    if not vspell.available():
        return {"available": False, "applied": 0, "items": [], "counts": {}, "groups": GROUPS}
    level = "wide" if opts.get("level") == "wide" else "safe"
    color = _hex(opts.get("color"), RED) if mark else None
    color_maybe = _hex(opts.get("color_maybe"), ORANGE) if mark else None
    off = set(opts.get("force_off") or [])
    on = set(opts.get("force_on") or [])
    off_kinds = set(opts.get("off_kinds") or [])
    ignore = {unicodedata.normalize("NFC", w).lower() for w in (opts.get("ignore_words") or []) if isinstance(w, str)}

    paras = ex.paragraphs
    nfc_n = _nfc_pass(paras)
    built = [_build(p.element) for p in paras]
    texts = [b[0] for b in built]
    style = vspell.tone_style_of_document(t.replace(OBJ, " ") for t in texts)
    style_by_para = vspell.style_fixes([t for t in texts])

    items: list[dict] = []
    counts: dict[str, int] = {}
    applied = 0
    total_found = 0
    per_para: list[tuple[int, list[tuple[vspell.Fix, bool]]]] = []
    todo_idx = [i for i, b in enumerate(built) if b[1]]
    analysed = dict(zip(todo_idx, vspell.analyze_many([texts[i] for i in todo_idx], style=style)))
    for idx, (p, (text, pieces)) in enumerate(zip(paras, built)):
        if not pieces:
            continue
        res = analysed[idx]
        fixes = list(res.fixes)
        for sf in style_by_para[idx]:
            if not any(vspell._overlap(sf, g) for g in fixes):
                fixes.append(sf)
        todo: list[tuple[vspell.Fix, bool]] = []
        for f in sorted(fixes, key=lambda f: f.start):
            key = f"{p.pid}:{f.start}:{f.kind}"
            default = f.tier == 2 or (f.tier == 1 and level == "wide")
            use = (key in on) or (default and key not in off)
            if f.kind in off_kinds or f.old.lower() in ignore:
                use = False
            total_found += 1
            counts[f.kind] = counts.get(f.kind, 0) + 1
            if len(items) < MAX_ITEMS and (f.kind not in UNMARKED or len(items) < MAX_ITEMS // 2):
                items.append({"key": key, "pid": p.pid, "kind": f.kind, "old": f.old, "new": f.new, "tier": f.tier,
                              "applied": bool(use), "reason": f.reason, "ctx": _context(text, f)})
            if use:
                todo.append((f, f.tier == 1 and f.kind not in ("space", "dup")))
        per_para.append((idx, todo))
        for sp in res.suspects:
            if len(items) < MAX_ITEMS and sp.word.lower() not in ignore:
                items.append({"key": f"{p.pid}:{sp.start}:flag", "pid": p.pid, "kind": "flag", "old": sp.word, "new": "",
                              "tier": 0, "applied": False, "reason": sp.reason,
                              "ctx": _context(text, vspell.Fix(sp.start, sp.end, sp.word, "", "flag"))})
    for idx, todo in per_para:
        pieces = built[idx][1]
        for f, maybe in sorted(todo, key=lambda x: -x[0].start):
            if _apply_fix(pieces, f, color_maybe if maybe else color):
                applied += 1
    applied_by = {}
    for it in items:
        if it["applied"]:
            applied_by[it["kind"]] = applied_by.get(it["kind"], 0) + 1
    return {"available": True, "level": level, "style": style, "applied": applied, "found": total_found,
            "nfc": nfc_n, "counts": counts, "applied_by": applied_by, "items": items, "groups": GROUPS,
            "color": color or "", "color_maybe": color_maybe or "", "truncated": total_found > len(items)}


def validate_opts(raw) -> dict:
    """Chuẩn hoá lựa chọn của người dùng (từ JSON) -> dict an toàn. Ném ValueError nếu sai kiểu."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("spell phải là object")
    out: dict = {"on": bool(raw.get("on", True))}
    lv = raw.get("level", "safe")
    if lv not in ("safe", "wide"):
        raise ValueError("spell.level phải là 'safe' hoặc 'wide'")
    out["level"] = lv
    for k in ("color", "color_maybe"):
        v = raw.get(k)
        if v is not None and not re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(v)):
            raise ValueError(f"spell.{k} phải là mã màu 6 ký tự hex")
        if v is not None:
            out[k] = str(v).lstrip("#").upper()
    for k, limit in (("force_off", 6000), ("force_on", 6000), ("off_kinds", 40), ("ignore_words", 500)):
        v = raw.get(k) or []
        if not isinstance(v, list) or len(v) > limit or not all(isinstance(x, str) and len(x) <= 80 for x in v):
            raise ValueError(f"spell.{k} phải là danh sách chuỗi (tối đa {limit})")
        out[k] = sorted(set(v))
    bad = [k for k in out["off_kinds"] if k not in GROUPS]
    if bad:
        raise ValueError(f"spell.off_kinds có nhóm không hợp lệ: {bad}")
    return out


def run_on_fixed(ex, fixed_path, out_dir, stem: str, opts: dict) -> dict:
    """Bước cuối của evaluate: ghi bản có đổi màu vào fixed_path (thay thế) và bản sạch (không màu) cạnh nó.
    `ex` là bản trích xuất của fixed_path, sẽ bị sửa tại chỗ."""
    from pathlib import Path
    from .extract import extract
    from .ooxml_order import save_docx
    clean_name = f"{stem}_da_sua_khong_mau.docx"
    clean_path = Path(out_dir) / clean_name
    exc = extract(str(fixed_path))
    rc = process_document(exc, opts, mark=False)
    rep = process_document(ex, opts, mark=True)
    marked = sum(n for k, n in (rep.get("applied_by") or {}).items() if k not in UNMARKED)
    if rep.get("available") and rep["applied"]:
        save_docx(ex.doc, fixed_path)
    if rep.get("available") and marked:
        save_docx(exc.doc, clean_path)
        rep["clean_file"] = clean_name
    elif clean_path.exists():
        clean_path.unlink()
    rep["marked"] = marked
    return rep
