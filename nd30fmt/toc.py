"""Mục lục (TOC) + Danh mục hình/bảng, và đánh số Hình/Bảng bằng field Word (SEQ) tự cập nhật.

Độc lập với bộ máy kiểm tra/sửa NĐ30-Đảng: đây là tiện ích Word thuần tuý, chạy như bước
cuối cùng (theo yêu cầu), sau khi người dùng đã ưng ý với việc sửa lỗi định dạng.

Nguyên tắc an toàn (giống fix.py):
  - Không đổi nội dung chữ, chỉ thay phần SỐ của chú thích Hình/Bảng bằng field { SEQ ... }.
  - Nếu cấu trúc run quá phức tạp để tách an toàn -> bỏ qua đoạn đó, báo lại cho người dùng.
  - Chạy lại nhiều lần không bị lặp: đoạn đã có field thì bỏ qua, tiêu đề đã có field theo sau
    thì không chèn thêm.

Cách người dùng chuẩn bị file: gõ caption dạng "Hình 1. ..." / "Bảng 1: ..." ở đầu đoạn (kiểu
đang dùng phổ biến ở báo cáo hành chính) và đặt sẵn các dòng tiêu đề "MỤC LỤC", "DANH MỤC HÌNH",
"DANH MỤC BẢNG" ở nơi muốn chèn - công cụ sẽ chèn field ngay sau các tiêu đề đó.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Optional

from docx import Document
from docx.oxml import OxmlElement

from .extract import qn
from .ooxml_order import insert_update_fields, save_docx

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# số đơn (Hình 1, Bảng 3). Số theo chương (Bảng 2.1) KHÔNG khớp -> giữ nguyên, tránh biến "2.1" thành "field.1"
# sau số PHẢI có dấu (. : - – —) hoặc hết dòng: "Hình 1 cho thấy..." là câu văn, không đổi thành field
CAPTION_RE = re.compile(r"^\s*(?P<label>Hình|Bảng)[ \t]+(?P<num>\d+)(?!\.?\d)\s*(?:[.:\-–—](?!\d)|$)", re.IGNORECASE)

# nhãn hiển thị (đã chuẩn hoá NFC, viết thường) -> (định danh SEQ hợp lệ trong Word, không dấu/khoảng trắng)
SEQ_MAP = {"hình": "Hinh", "bảng": "Bang"}

_UP = lambda s: re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip().upper().rstrip(":.").strip()

TOC_HEADS = {"MỤC LỤC"}
HINH_HEADS = {"DANH MỤC HÌNH", "DANH MỤC HÌNH ẢNH", "DANH MỤC HÌNH VẼ", "DANH MỤC CÁC HÌNH",
             "DANH MỤC CÁC HÌNH VẼ", "DANH MỤC HÌNH VÀ ĐỒ THỊ", "DANH MỤC HÌNH, BIỂU ĐỒ",
             "DANH MỤC HÌNH ẢNH, SƠ ĐỒ"}
BANG_HEADS = {"DANH MỤC BẢNG", "DANH MỤC BẢNG BIỂU", "DANH MỤC CÁC BẢNG", "DANH MỤC CÁC BẢNG BIỂU"}
_NOT_FIGTAB = re.compile(r"VIẾT TẮT|KÝ HIỆU|THUẬT NGỮ|TỪ NGỮ|CHỮ CÁI|TÀI LIỆU|CÔNG TRÌNH|PHỤ LỤC|VĂN BẢN")


def _list_kind(txt: str):
    """Phân loại dòng tiêu đề (đã _UP): 'toc' | 'hinh' | 'bang' | 'both' | None.
    Nhận cả biến thể: DANH MỤC BIỂU ĐỒ, DANH MỤC SƠ ĐỒ/HÌNH VẼ, DANH MỤC CÁC HÌNH ẢNH, DANH MỤC HÌNH VÀ BẢNG..."""
    if txt in TOC_HEADS:
        return "toc"
    if txt in HINH_HEADS:
        return "hinh"
    if txt in BANG_HEADS:
        return "bang"
    if not txt.startswith("DANH MỤC") or _NOT_FIGTAB.search(txt):
        return None
    fig = bool(re.search(r"HÌNH|BIỂU ĐỒ|SƠ ĐỒ|ĐỒ THỊ|ẢNH", txt))
    tab = bool(re.search(r"BẢNG|BIỂU(?! ĐỒ)", txt))
    return "both" if fig and tab else "hinh" if fig else "bang" if tab else None


# --------------------------------------------------------------------- đọc text thô (không chuẩn hoá)
def iter_runs(p_el):
    skip = {qn("w:txbxContent"), "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback",
            qn("w:del")}
    for r in p_el.iter(qn("w:r")):
        a = r.getparent()
        ok = True
        while a is not None and a is not p_el:
            if a.tag in skip:
                ok = False
                break
            a = a.getparent()
        if ok:
            yield r


def _run_text(r_el) -> str:
    parts = []
    for node in r_el:
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
    return "".join(parts)


def _para_text(p_el) -> str:
    return "".join(_run_text(r) for r in iter_runs(p_el))


def _has_field(p_el) -> bool:
    return any(True for _ in p_el.iter(qn("w:fldChar")))


def _simple_text(r_el) -> Optional[str]:
    """Text nếu run chỉ có đúng 1 phần tử con w:t (đơn giản, tách được an toàn); ngược lại None."""
    kids = [c for c in r_el if c.tag != qn("w:rPr")]
    if len(kids) == 1 and kids[0].tag == qn("w:t"):
        return kids[0].text or ""
    return None


def _locate_span(p_el, start: int, end: int):
    """Tìm run đơn giản chứa trọn khoảng ký tự [start,end) của toàn bộ text hiển thị của đoạn.
    Trả về (run, start_cục_bộ, end_cục_bộ) hoặc None nếu số bị chia cắt giữa nhiều run / nằm
    trong run phức tạp (không an toàn để tách)."""
    pos = 0
    for r in iter_runs(p_el):
        simple = _simple_text(r)
        txt = simple if simple is not None else _run_text(r)
        rlen = len(txt)
        if simple is not None and pos <= start and end <= pos + rlen:
            return r, start - pos, end - pos
        if pos < end and pos + rlen > start:
            return None  # chồng lấn nhưng không nằm trọn trong 1 run đơn giản
        pos += rlen
    return None


# --------------------------------------------------------------------- chèn field SEQ vào chú thích
def _insert_seq_field(run_el, local_start: int, local_end: int, seq_name: str, display_number: int):
    t = run_el.find(qn("w:t"))
    full = t.text or ""
    left, right = full[:local_start], full[local_end:]
    t.text = left
    t.set(XML_SPACE, "preserve")
    rpr_src = run_el.find(qn("w:rPr"))

    def mk_run():
        r = OxmlElement("w:r")
        if rpr_src is not None:
            r.append(copy.deepcopy(rpr_src))
        return r

    r1 = mk_run()
    fc1 = OxmlElement("w:fldChar")
    fc1.set(qn("w:fldCharType"), "begin")
    r1.append(fc1)
    r2 = mk_run()
    it = OxmlElement("w:instrText")
    it.set(XML_SPACE, "preserve")
    it.text = f" SEQ {seq_name} \\* ARABIC "
    r2.append(it)
    r3 = mk_run()
    fc2 = OxmlElement("w:fldChar")
    fc2.set(qn("w:fldCharType"), "separate")
    r3.append(fc2)
    r4 = mk_run()
    t4 = OxmlElement("w:t")
    t4.text = str(display_number)
    t4.set(XML_SPACE, "preserve")
    r4.append(t4)
    r5 = mk_run()
    fc3 = OxmlElement("w:fldChar")
    fc3.set(qn("w:fldCharType"), "end")
    r5.append(fc3)

    cur = run_el
    for nr in (r1, r2, r3, r4, r5):
        cur.addnext(nr)
        cur = nr
    if right:
        right_run = copy.deepcopy(run_el)
        right_run.find(qn("w:t")).text = right
        right_run.find(qn("w:t")).set(XML_SPACE, "preserve")
        cur.addnext(right_run)


def convert_captions(doc, only: set | None = None) -> dict:
    """Chuyển số trong chú thích "Hình N."/"Bảng N:" (ở đầu đoạn) thành field { SEQ Hinh|Bang }.
    Bỏ qua đoạn đã có field (đã chạy trước đó), giữ nguyên toàn bộ phần chữ còn lại.
    only: chỉ đổi loại này ({"Hinh"}, {"Bang"}); mặc định cả hai."""
    word_captions = normalize_word_captions(doc)
    counters = {"Hinh": 0, "Bang": 0}
    converted = {"Hinh": 0, "Bang": 0}
    skipped = []
    body = doc.element.body
    for p_el in list(body.iter(qn("w:p"))):
        if _has_field(p_el):
            continue
        text = _para_text(p_el)
        m = CAPTION_RE.match(text)
        if not m:
            continue
        key = unicodedata.normalize("NFC", m.group("label")).strip().lower()
        seq_name = SEQ_MAP.get(key)
        if seq_name is not None and only is not None and seq_name not in only:
            continue
        if seq_name is None:
            continue
        span = _locate_span(p_el, m.start("num"), m.end("num"))
        if span is None:
            skipped.append(text[:70])
            continue
        counters[seq_name] += 1
        run_el, ls, le = span
        _insert_seq_field(run_el, ls, le, seq_name, counters[seq_name])
        converted[seq_name] += 1
    tagged = _tag_chapter_captions(doc, only)
    return {"converted": converted, "skipped": skipped, "tagged": tagged, "word_captions": word_captions}


# chú thích đánh số theo chương / kiểu khác: "Bảng 2.1.", "Hình 3.2:", "Biểu đồ 1.4 -", "Sơ đồ 2"
CAPTION_ANY_RE = re.compile(
    r"^\s*(?P<label>Bảng|Hình|Biểu\s+đồ|Sơ\s+đồ|Đồ\s+thị|Biểu)[ \t]+\d+(?:\.\d+)*\s*(?:[.:\-–—](?!\d)|$)",
    re.IGNORECASE)
_SEQ_OF = {"bảng": "Bang", "hình": "Hinh", "biểu đồ": "Hinh", "sơ đồ": "Hinh", "đồ thị": "Hinh", "biểu": "Bang"}


def _seq_group(name: str):
    """Tên nhãn SEQ do Word tạo (Insert Caption) -> Hinh | Bang | None."""
    n = unicodedata.normalize("NFD", (name or "").strip('"').lower())
    n = "".join(ch for ch in n if not unicodedata.combining(ch)).replace("đ", "d").replace("_", " ").strip()
    if n in ("hinh", "hinh anh", "hinh ve", "figure", "fig", "bieu do", "so do", "do thi", "anh", "chart", "diagram"):
        return "Hinh"
    if n in ("bang", "bang bieu", "table", "bieu"):
        return "Bang"
    return None


def normalize_word_captions(doc) -> dict:
    """Chú thích tạo bằng Insert Caption của Word dùng field { SEQ Hình } / { SEQ Figure } / { SEQ Table }...
    Danh mục chỉ gom được MỘT tên nhãn (TOC \\c "Hinh" / "Bang"), nên đổi tên nhãn về Hinh/Bang,
    giữ nguyên các khoá chuyển (\\* ARABIC, \\s 1 đánh số theo chương...) và số đang hiển thị."""
    changed = {"Hinh": 0, "Bang": 0}
    for it in doc.element.body.iter(qn("w:instrText")):
        m = re.match(r'^(\s*SEQ\s+)("[^"]+"|\S+)(.*)$', it.text or "", re.I | re.S)
        if not m or m.group(2) in ("Hinh", "Bang"):
            continue
        group = _seq_group(m.group(2))
        if group:
            it.text = f"{m.group(1)}{group}{m.group(3)}"
            changed[group] += 1
    return changed


def _append_hidden_seq(p_el, seq_name: str):
    """Thêm { SEQ <tên> \\c \\h } vào cuối đoạn: \\c không tăng bộ đếm, \\h không hiện chữ.
    Chữ/số chú thích giữ nguyên, nhưng TOC \\c "<tên>" (danh mục bảng/hình) sẽ thu thập được đoạn."""
    def run_with(child):
        # chữ ẩn (vanish): Word đã ẩn nhờ \\h, nhưng LibreOffice (bản in/PDF) bỏ qua \\h và in số "1"
        # dính vào cuối chú thích -> đánh dấu ẩn cả run để mọi trình hiển thị đều không in ra
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        rpr.append(OxmlElement("w:vanish"))
        r.append(rpr)
        r.append(child)
        return r
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(XML_SPACE, "preserve"); it.text = f" SEQ {seq_name} \\c \\h "
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end")
    for r in (run_with(b), run_with(it), run_with(e)):
        p_el.append(r)


def _tag_chapter_captions(doc, only: set | None = None) -> dict:
    """Chú thích không đổi được số thành field (số theo chương, run phức tạp): gắn SEQ ẩn để vẫn
    vào Danh mục bảng/hình. Bỏ qua đoạn đã có field SEQ (chạy lại không bị lặp), dòng mục lục, câu dài."""
    tagged = {"Hinh": 0, "Bang": 0}
    for p_el in list(doc.element.body.iter(qn("w:p"))):
        if any("SEQ" in (it.text or "").upper() for it in p_el.iter(qn("w:instrText"))):
            continue
        if _is_toc_like_para(p_el):
            continue
        text = _para_text(p_el)
        if len(text) > 250:
            continue
        m = CAPTION_ANY_RE.match(text)
        if not m:
            continue
        key = re.sub(r"\s+", " ", unicodedata.normalize("NFC", m.group("label")).strip().lower())
        seq = _SEQ_OF.get(key)
        if seq and (only is None or seq in only):
            _append_hidden_seq(p_el, seq)
            tagged[seq] += 1
    return tagged


# --------------------------------------------------------------------- chèn Mục lục / Danh mục
def _next_p_has_field_marker(p_el, marker: str) -> bool:
    nxt = p_el.getnext()
    if nxt is None or nxt.tag != qn("w:p"):
        return False
    for it in nxt.iter(qn("w:instrText")):
        if marker in (it.text or "").upper():
            return True
    return False


def _insert_field_paragraph(after_p_el, instr: str):
    new_p = OxmlElement("w:p")

    def mk_run():
        return OxmlElement("w:r")

    r1 = mk_run()
    fc1 = OxmlElement("w:fldChar")
    fc1.set(qn("w:fldCharType"), "begin")
    fc1.set(qn("w:dirty"), "true")
    r1.append(fc1)
    r2 = mk_run()
    it = OxmlElement("w:instrText")
    it.set(XML_SPACE, "preserve")
    it.text = f" {instr} "
    r2.append(it)
    r3 = mk_run()
    fc2 = OxmlElement("w:fldChar")
    fc2.set(qn("w:fldCharType"), "separate")
    r3.append(fc2)
    r4 = mk_run()
    t4 = OxmlElement("w:t")
    t4.text = 'Bấm chuột phải rồi chọn "Update Field" (hoặc Ctrl+A rồi F9) để hiện nội dung.'
    t4.set(XML_SPACE, "preserve")
    r4.append(t4)
    r5 = mk_run()
    fc3 = OxmlElement("w:fldChar")
    fc3.set(qn("w:fldCharType"), "end")
    r5.append(fc3)
    for r in (r1, r2, r3, r4, r5):
        new_p.append(r)
    after_p_el.addnext(new_p)
    return new_p


# dòng mục lục: kết thúc bằng số trang (sau tab / dấu dẫn / khoảng trắng, hoặc dính liền "UAE.40")
_PAGE_TAIL_RE = re.compile(r"(?:(?:[\t ]|\.{2,}|…+)\s*(?:\d{1,4}|[ivxlc]{1,6})|(?<=[.)\w])\d{1,4})\s*$", re.I)


def _pstyle(p_el) -> str:
    ppr = p_el.find(qn("w:pPr"))
    st = ppr.find(qn("w:pStyle")) if ppr is not None else None
    return (st.get(qn("w:val")) or "").lower() if st is not None else ""


def _instr(el) -> str:
    return " ".join((it.text or "") for it in el.iter(qn("w:instrText"))).upper()


# nhãn đứng riêng một dòng: "CHƯƠNG 1", "Chương II.", "PHẦN 2", "PHỤ LỤC 3" - số ở cuối KHÔNG phải số trang
_LABEL_ONLY_RE = re.compile(r"^(CHƯƠNG|PHẦN|PHỤ\s+LỤC|MỤC|TIỂU\s+MỤC)\s+([IVXLC]+|\d+)\s*[.:]?$", re.I)


def _is_label_only(text: str) -> bool:
    return bool(_LABEL_ONLY_RE.match(unicodedata.normalize("NFC", text or "").strip()))


def _is_toc_like_strict(p_el) -> bool:
    """Chỉ tín hiệu CHẮC CHẮN của dòng mục lục (tab/dấu dẫn + số trang, PAGEREF, style mục lục,
    liên kết _Toc) - không dựa vào 'số đứng sau dấu cách' vì đề mục như 'Mục tiêu đến năm 2030'."""
    st = _pstyle(p_el)
    if st.startswith("toc") or st.startswith("tableoffigures") or st.startswith("table of figures"):
        return True
    if "PAGEREF" in _instr(p_el):
        return True
    for h in p_el.iter(qn("w:hyperlink")):
        if (h.get(qn("w:anchor")) or "").startswith("_Toc"):
            return True
    t = _para_text(p_el).strip()
    return bool(re.search(r"(\t|\.{3,}|…+)\s*(\d{1,4}|[ivxlc]{1,6})\s*$", t, re.I))


def _is_toc_like_para(p_el) -> bool:
    if _is_label_only(_para_text(p_el)):
        return False
    st = _pstyle(p_el)
    if st.startswith("toc") or st.startswith("tableoffigures") or st.startswith("table of figures"):
        return True
    if "PAGEREF" in _instr(p_el):
        return True
    for h in p_el.iter(qn("w:hyperlink")):
        if (h.get(qn("w:anchor")) or "").startswith("_Toc"):
            return True
    t = _para_text(p_el).strip()
    if not t or len(t) >= 400 or not _PAGE_TAIL_RE.search(t):
        return False
    if _is_toc_like_strict(p_el):
        return True
    # chỉ có "số đứng cuối" (tín hiệu yếu): năm (19xx/20xx) không phải số trang; đoạn mang style
    # Heading thật là đề mục thân bài chứ không phải dòng mục lục gõ tay
    if re.search(r"(?<!\d)(19|20)\d{2}\s*$", t):
        return False
    return not st.startswith("heading")


def _protected(p_el) -> bool:
    """Đoạn mang ngắt trang / ngắt section: không được xoá (sẽ làm lệch bố cục trang/section)."""
    ppr = p_el.find(qn("w:pPr"))
    if ppr is not None and ppr.find(qn("w:sectPr")) is not None:
        return True
    return any(br.get(qn("w:type")) == "page" for br in p_el.iter(qn("w:br")))


def _strip_text_keep_breaks(p_el):
    for r in list(p_el.iter(qn("w:r"))):
        if any(br.get(qn("w:type")) == "page" for br in r.iter(qn("w:br"))):
            for c in list(r):
                if c.tag not in (qn("w:rPr"), qn("w:br")):
                    r.remove(c)
            continue
        r.getparent().remove(r)
    for h in list(p_el.iter(qn("w:hyperlink"))):
        if not len(h):
            h.getparent().remove(h)


def _fld_balance(el) -> int:
    n = 0
    for fc in el.iter(qn("w:fldChar")):
        t = fc.get(qn("w:fldCharType"))
        n += 1 if t == "begin" else (-1 if t == "end" else 0)
    return n


_SECTION_TITLE_RE = re.compile(
    r"^(DANH\s+MỤC|MỤC\s+LỤC|MỞ\s+ĐẦU|LỜI\s+(MỞ\s+ĐẦU|CAM\s+ĐOAN|CẢM\s+ƠN|NÓI\s+ĐẦU)|TÓM\s+TẮT|"
    r"CHƯƠNG\s+[IVXLC\d]+|PHẦN\s+[IVXLC\d]+|PHẦN\s+MỞ\s+ĐẦU|KẾT\s+LUẬN|TÀI\s+LIỆU\s+THAM\s+KHẢO|PHỤ\s+LỤC)\b")


def _is_section_title(text: str) -> bool:
    """Tiêu đề phần/danh mục đứng riêng (không kèm số trang) -> ranh giới kết thúc khối mục lục cũ."""
    t = _UP(text)
    if _is_label_only(text):
        return True
    return len(t) <= 120 and bool(_SECTION_TITLE_RE.match(t)) and not _PAGE_TAIL_RE.search(text.strip())


# ---- Khối mục lục cũ gõ tay KHÔNG có số trang: nhận ra bằng cách đối chiếu với các đề mục/chú thích phía sau --
_LEAD_NUM_RE = re.compile(
    r"^\s*((chương|phần|mục|phụ\s+lục|hình|bảng|biểu\s+đồ|biểu|sơ\s+đồ|đồ\s+thị)\s+)?"
    r"([ivxlc]+|\d+(\.\d+)*|[a-zđ])\s*[.:)\-–—]*\s+", re.I)


def _norm_entry(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").replace("\t", " ").strip()
    t = _PAGE_TAIL_RE.sub("", t).strip()
    t = _LEAD_NUM_RE.sub("", t, count=1)
    return re.sub(r"[\W_]+", "", t.casefold())


def _is_heading_el(p_el) -> bool:
    if _pstyle(p_el).startswith(("heading", "title")):
        return True
    ppr = p_el.find(qn("w:pPr"))
    ol = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    try:
        return ol is not None and int(ol.get(qn("w:val"))) < 9
    except (TypeError, ValueError):
        return False


def _untyped_block(head_p, kind: str) -> set:
    """Các đoạn ngay sau tiêu đề 'MỤC LỤC/DANH MỤC...' là dòng mục lục gõ tay không kèm số trang: từng dòng (bỏ số thứ tự
    đầu dòng) trùng với một đề mục (Mục lục) hoặc chú thích Hình/Bảng (Danh mục) xuất hiện SAU khối đó. Cần >= 2 dòng
    liên tiếp khớp; đoạn mang style đề mục không bao giờ bị coi là dòng mục lục."""
    body_ps = []
    el = head_p.getparent()
    while el is not None and el.tag != qn("w:body"):
        el = el.getparent()
    if el is None:
        return set()
    after = False
    refs = set()
    run: list = []
    for p_el in el.iter(qn("w:p")):
        if p_el is head_p:
            after = True
            continue
        if not after:
            continue
        body_ps.append(p_el)
    # ứng viên: chuỗi đoạn liền kề ngay sau tiêu đề
    nxt = head_p.getnext()
    while nxt is not None and nxt.tag == qn("w:p") and len(run) < 400:
        tx = _para_text(nxt).strip()
        if not tx or len(tx) > 200 or _is_heading_el(nxt) or _list_kind(_UP(tx)) or _protected(nxt):
            break
        run.append(nxt)
        nxt = nxt.getnext()
    if len(run) < 2:
        return set()
    run_ids = {id(x) for x in run}
    for p_el in body_ps:
        if id(p_el) in run_ids:
            continue
        tx = _para_text(p_el).strip()
        if not tx or len(tx) > 300:
            continue
        if kind == "toc":
            if _is_heading_el(p_el):
                refs.add(_norm_entry(tx))
        elif _CAPTION_ANY_RE.match(tx):
            refs.add(_norm_entry(tx))
    refs.discard("")
    def hit(n: str) -> bool:
        return bool(n) and (n in refs or (len(n) >= 12 and any(r.startswith(n) or n.startswith(r) for r in refs if len(r) >= 12)))
    block = []
    for x in run:
        if hit(_norm_entry(_para_text(x))):
            block.append(x)
        else:
            break
    return {id(x) for x in block} if len(block) >= 2 else set()


def _remove_old_list(head_p, kind: str = "toc") -> int:
    """Xoá mục lục/danh mục CŨ nằm ngay sau dòng tiêu đề (field TOC cũ, khối content control mục lục,
    dòng gõ tay có số trang ở cuối). Dừng ở đoạn đầu tiên không còn giống dòng mục lục. Đoạn mang
    ngắt trang/section chỉ bị xoá chữ, giữ lại dấu ngắt. Trả về số đoạn đã xoá/làm sạch."""
    removed, depth = 0, 0
    untyped = _untyped_block(head_p, kind)
    nxt = head_p.getnext()
    while nxt is not None:
        cur, nxt = nxt, nxt.getnext()
        if id(cur) in untyped:
            cur.getparent().remove(cur); removed += 1; continue
        if cur.tag == qn("w:sdt"):
            if "TOC" in _instr(cur) or _is_toc_like_para(cur) or cur.find(".//" + qn("w:docPartGallery")) is not None:
                cur.getparent().remove(cur); removed += 1; continue
            break
        if cur.tag != qn("w:p"):
            break
        in_field = depth > 0 or " TOC " in f" {_instr(cur)} "
        ppr = cur.find(qn("w:pPr"))
        if not in_field and ppr is not None and ppr.find(qn("w:pageBreakBefore")) is not None:
            break                             # đoạn sang trang mới: đã ra khỏi khối mục lục
        text = _para_text(cur).strip()
        if not in_field:
            if text and _is_section_title(text):
                break                         # tiêu đề phần/danh mục kế tiếp
            if text and not _is_toc_like_para(cur):
                # dòng mục lục cũ bị ngắt làm 2 đoạn: "2.4. ... (SPS)" + "50" -> vẫn thuộc khối
                nt = _para_text(nxt).strip() if (nxt is not None and nxt.tag == qn("w:p")) else ""
                strong_next = nxt is not None and nxt.tag == qn("w:p") and _is_toc_like_para(nxt) and (
                    len(nt) <= 12                                         # mẩu số trang trơ: "50"
                    or "\t" in nt or re.search(r"\.{3,}|…", nt) or "PAGEREF" in _instr(nxt)
                    or _pstyle(nxt).startswith("toc"))
                wrapped = len(text) < 300 and not text.endswith((".", ";", ":")) and bool(strong_next)
                if not wrapped:
                    break                     # hết khối mục lục cũ
            if not text and not _is_toc_like_para(cur):
                # đoạn trống: chỉ xoá nếu đoạn kế tiếp vẫn còn là dòng mục lục (trống xen giữa khối)
                if nxt is None or nxt.tag != qn("w:p") or not _is_toc_like_para(nxt) or not _para_text(nxt).strip():
                    break
        depth = max(0, depth + _fld_balance(cur))
        if _protected(cur):
            _strip_text_keep_breaks(cur); removed += 1
            if depth == 0:
                break
            continue
        cur.getparent().remove(cur); removed += 1
    return removed


def insert_toc_fields(doc, want: dict | None = None, create: bool = False, anchor_el=None) -> dict:
    """Làm lại Mục lục / Danh mục hình / Danh mục bảng ngay sau các dòng tiêu đề tương ứng
    ("MỤC LỤC", "DANH MỤC HÌNH", "DANH MỤC BẢNG"...): XOÁ khối cũ (field cũ hoặc dòng gõ tay) rồi
    chèn field mới. Nếu không xoá khối cũ, field mới sẽ lấy luôn các dòng mục lục cũ làm đề mục
    (dòng nào cũng trỏ về trang đặt mục lục cũ, chữ dính số trang cũ) -> trùng lặp.
    Danh mục chữ viết tắt là nội dung gõ tay, không phải field -> giữ nguyên.

    want: {"toc","hinh","bang"} -> chỉ làm mục được chọn (mặc định cả ba); mục không chọn thì để nguyên, kể cả
    tiêu đề đã có. create=True: mục được chọn mà văn bản chưa có tiêu đề thì TẠO tiêu đề + field (xem _create_blocks)."""
    want = {"toc": True, "hinh": True, "bang": True} if want is None else {k: bool(want.get(k)) for k in ("toc", "hinh", "bang")}
    body = doc.element.body
    last_field = None
    inserted = {"toc": False, "hinh": False, "bang": False}
    removed = {"toc": 0, "hinh": 0, "bang": 0}
    already = {"toc": False, "hinh": False, "bang": False}
    spec = {"toc": 'TOC \\o "1-3" \\h \\z \\u', "hinh": 'TOC \\c "Hinh" \\h \\z', "bang": 'TOC \\c "Bang" \\h \\z'}
    for p_el in list(body.iter(qn("w:p"))):
        if p_el.getparent() is None:
            continue                          # đã bị xoá cùng khối cũ
        if any(a.tag == qn("w:txbxContent") for a in p_el.iterancestors()):
            continue                          # chữ trong khung văn bản không phải tiêu đề thân bài
        txt = _UP(_para_text(p_el))
        if not txt or len(txt) > 60:
            continue
        kind = _list_kind(txt)
        if kind is None:
            continue
        kinds = [k for k in (["hinh", "bang"] if kind == "both" else [kind]) if want[k]]
        if not kinds or all(inserted[k] for k in kinds):
            continue
        was = _next_p_has_field_marker(p_el, "TOC")   # đã có field TOC -> làm mới
        old = _remove_old_list(p_el, "toc" if kind == "toc" else "fig")
        # "DANH MỤC HÌNH VÀ BẢNG": chèn danh mục hình rồi danh mục bảng ngay dưới cùng một tiêu đề
        for k in reversed(kinds):
            if not inserted[k]:
                fp = _insert_field_paragraph(p_el, spec[k])
                inserted[k], already[k], removed[k] = True, was, old
                if last_field is None or _doc_order(body, last_field, fp) < 0:
                    last_field = fp
    created = {"toc": False, "hinh": False, "bang": False}
    if create:
        missing = [k for k in ("toc", "hinh", "bang") if want[k] and not inserted[k]]
        if missing:
            _create_blocks(doc, missing, spec, last_field, anchor_el)
            for k in missing:
                inserted[k] = created[k] = True
    return {"inserted": inserted, "removed_old": removed, "already": already, "created": created}


def _doc_order(body, a, b) -> int:
    """<0 nếu a đứng trước b trong văn bản."""
    for el in body.iter():
        if el is a:
            return -1
        if el is b:
            return 1
    return 0


_HEAD_TEXT = {"toc": "MỤC LỤC", "hinh": "DANH MỤC HÌNH", "bang": "DANH MỤC BẢNG"}


def _heading_paragraph(text: str):
    """Dòng tiêu đề tạo mới: căn giữa, đậm, Times New Roman 14, bắt đầu trang mới; KHÔNG dùng style Heading
    (để không tự lọt vào chính mục lục)."""
    p = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    pb = OxmlElement("w:pageBreakBefore")
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:before"), "0")
    sp.set(qn("w:after"), "240")
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "center")
    for el in (pb, sp, jc):
        ppr.append(el)
    p.append(ppr)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rf = OxmlElement("w:rFonts")
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(k), "Times New Roman")
    b = OxmlElement("w:b")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "28")
    for el in (rf, b, sz):
        rpr.append(el)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    p.append(r)
    return p


def _page_break_before(p_el) -> None:
    """Cho đoạn p_el bắt đầu trang mới (nếu chưa)."""
    if p_el is None or p_el.tag != qn("w:p"):
        return
    if any(br.get(qn("w:type")) == "page" for br in p_el.iter(qn("w:br"))):
        return
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p_el.insert(0, ppr)
    if ppr.find(qn("w:pageBreakBefore")) is None:
        ppr.append(OxmlElement("w:pageBreakBefore"))


def _create_blocks(doc, kinds, spec, after_el, anchor_el) -> None:
    """Tạo tiêu đề + field cho các mục `kinds` (theo thứ tự Mục lục, Danh mục hình, Danh mục bảng).
    Vị trí: ngay sau khối mục lục/danh mục đã có (after_el); nếu chưa có khối nào thì ngay TRƯỚC anchor_el
    (đề mục đầu tiên của nội dung); không có cả hai thì ở đầu văn bản. Mỗi khối bắt đầu trang mới và phần nội
    dung đứng sau khối cuối cùng cũng bắt đầu trang mới."""
    body = doc.element.body
    heads = [_heading_paragraph(_HEAD_TEXT[k]) for k in kinds]
    if after_el is not None:
        ref = after_el
    elif anchor_el is not None and anchor_el.getparent() is not None:
        ref = anchor_el.getprevious()
        if ref is None:                                   # đứng đầu body: chèn tiêu đề đầu rồi nối tiếp sau nó
            anchor_el.addprevious(heads[0])
            _insert_field_paragraph(heads[0], spec[kinds[0]])
            ref = heads[0].getnext()
            heads = heads[1:]
            kinds = kinds[1:]
    else:
        ref = None
    last = ref
    for k, h in zip(kinds, heads):
        if ref is None:                                   # không có điểm neo: đầu văn bản
            body.insert(0, h)
        else:
            ref.addnext(h)
        last = _insert_field_paragraph(h, spec[k])
        ref = last
    if last is None and anchor_el is not None:
        last = anchor_el.getprevious()
    _page_break_before(last.getnext() if last is not None else None)


def set_update_fields(doc):
    """Đặt cờ để Word tự cập nhật mọi field (mục lục, danh mục, số hình/bảng) khi mở lại file -
    không thì người dùng phải tự bấm Ctrl+A rồi F9."""
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is not None:
        return
    insert_update_fields(settings)   # phải đứng đúng vị trí trong CT_Settings, không phải đầu file


# ---- Nhận diện đoạn KHÔNG nên vào mục lục (dù đang mang cấp đề mục / style Heading) ------------------
_CAPTION_ANY_RE = re.compile(
    r"^(hình|bảng|biểu\s+đồ|biểu|sơ\s+đồ|đồ\s+thị|ảnh|hộp|phụ\s+biểu)\s+(\d+|[ivxlc]+)([.\-]\d+)*\s*([.:\-–—)]|$)", re.I)
_LABEL_LINE_RE = re.compile(
    r"^(nơi\s+nhận|kính\s+gửi|trích\s+yếu|nguồn|ghi\s+chú|chú\s+thích|lưu\s+ý|ví\s+dụ|đơn\s+vị\s+tính|"
    r"căn\s+cứ|dẫn\s+nguồn|ký\s+hiệu)\s*:|^(nơi\s+nhận|kính\s+gửi)\s*:?\s*$", re.I)
_SIGN_TITLES = {
    "viện trưởng", "phó viện trưởng", "bộ trưởng", "thứ trưởng", "cục trưởng", "vụ trưởng", "tổng cục trưởng",
    "giám đốc", "phó giám đốc", "tổng giám đốc", "chủ tịch", "phó chủ tịch", "chủ nhiệm", "chủ nhiệm đề tài",
    "trưởng phòng", "thủ trưởng đơn vị", "người thực hiện", "người soạn thảo", "người ký", "chánh văn phòng"}
_SIGN_PREFIX_RE = re.compile(r"^(tm|kt|tl|tuq|q)\.\s*\S", re.I)
_LIST_POINT_RE = re.compile(r"^\(?([a-zđ]|\d{1,2})\)\s*\S", re.I)


def _is_sign_title(t: str) -> bool:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", t or "")).strip().rstrip(":.").lower()
    s = re.sub(r"\s*\(.*\)$", "", s)
    return len(s.split()) <= 6 and (s in _SIGN_TITLES or bool(_SIGN_PREFIX_RE.match(s)))


def _is_person_name(t: str) -> bool:
    w = (t or "").split()
    return 2 <= len(w) <= 6 and not any(re.search(r"\d", x) for x in w) and all(x[:1].isupper() for x in w)


def _head_reason(p, t: str, prev_sign: bool) -> tuple[str | None, bool]:
    """Lý do một đoạn mang cấp đề mục KHÔNG nên vào mục lục -> (lý do | None, cứng?). 'Cứng' = luôn loại
    (dòng trống, không có chữ, tiêu đề Mục lục/Danh mục, dòng mục lục cũ); còn lại người dùng có thể tích giữ lại."""
    from .roles import content_signal, is_toc_heading
    if not t:
        return "dòng trống", True
    if not re.search(r"[^\W\d_]", t):
        return "không có chữ", True
    if is_toc_heading(t):
        return "tiêu đề Mục lục/Danh mục", True
    if _is_toc_like_strict(p.element):
        return "dòng mục lục cũ", True
    flat = re.sub(r"\s+", " ", t)
    if p.where != "body":
        return "nằm trong ô bảng", False
    if _CAPTION_ANY_RE.match(flat):
        return "chú thích hình/bảng", False
    if _LABEL_LINE_RE.match(flat):
        return "nhãn Nguồn/Ghi chú/Nơi nhận/Kính gửi", False
    if _is_sign_title(flat):
        return "chức danh ký", False
    if prev_sign and _is_person_name(flat):
        return "tên người ký", False
    if flat.endswith(":"):
        return "câu dẫn kết thúc bằng dấu hai chấm", False
    if _LIST_POINT_RE.match(flat):
        return "điểm liệt kê a) b) / 1)", False
    if content_signal(flat):
        return "dáng nội dung (gạch đầu dòng, ';', câu văn)", False
    is_caps = flat == flat.upper()
    if not is_caps and (len(flat.split()) >= 24 or len(flat) > 160):
        return "quá dài so với một đề mục", False
    return None, False


def _cand_key(text: str, counts: dict) -> str:
    base = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()[:100]
    n = counts.get(base, 0)
    counts[base] = n + 1
    return f"{base}#{n}"


def analyze_headings(ex) -> list[dict]:
    """Mọi đoạn đang mang cấp đề mục 1-3 (sẽ vào mục lục nếu không chặn), theo thứ tự văn bản, kèm lý do chặn tự động.
    key = chữ + số thứ tự lần xuất hiện: ổn định giữa các lần dựng lại nên dùng để người dùng tích chọn giữ/bỏ."""
    out, counts, prev_sign = [], {}, False
    for p in ex.paragraphs:
        if not p.heading_level or p.heading_level > 3 or p.element.getparent() is None:
            continue
        t = _para_text(p.element).strip()
        reason, hard = _head_reason(p, t, prev_sign)
        prev_sign = _is_sign_title(re.sub(r"\s+", " ", t)) if t else False
        out.append({"key": _cand_key(t, counts), "p": p, "text": t, "level": p.heading_level,
                    "where": p.where, "reason": reason, "hard": hard})
    return out


def _decide(item: dict, exclude, include) -> str | None:
    """Lý do loại cuối cùng (None = vào mục lục) sau khi áp lựa chọn của người dùng."""
    if item["hard"]:
        return item["reason"]
    if item["key"] in exclude:
        return "người dùng bỏ"
    if item["reason"] and item["key"] not in include:
        return item["reason"]
    return None


_DECIMAL_HEAD_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s")


def _relevel_plan(items: list[dict]) -> dict[str, int]:
    """Cấp mục lục hợp lý cho các đề mục ĐƯỢC GIỮ: {key: cấp mới}.
    Bộ nhận vai trò xếp '1.1.' và '1.1.1.' cùng một cấp (cấp 3) nên mục lục bị phẳng; ở đây tách theo số tầng của số
    thứ tự (1.1 nông hơn 1.1.1), rồi dồn các cấp đang dùng về 1, 2, 3... (không để trống cấp ở giữa)."""
    by_level: dict[int, list] = {}
    for it in items:
        m = _DECIMAL_HEAD_RE.match(it["text"]) if it["where"] == "body" else None
        it["_depth"] = m.group(1).count(".") + 1 if m else 0
        by_level.setdefault(it["level"], []).append(it)
    rank = {}
    for lv, its in by_level.items():
        depths = sorted({it["_depth"] for it in its if it["_depth"]})
        base = depths[0] if depths else 0
        for it in its:
            rank[it["key"]] = (lv, it["_depth"] - base if it["_depth"] else 0)
    if not any(extra for _, extra in rank.values()):
        return {k: lv for k, (lv, _) in rank.items()}            # không có gì phải tách -> giữ nguyên mọi cấp
    plain = {k: lv + extra for k, (lv, extra) in rank.items()}
    if max(plain.values()) <= 3:
        return plain
    # tách xong mà có đề mục rơi quá cấp 3 (ra khỏi mục lục): dồn các cấp đang dùng về 1, 2, 3...
    order = {r: i + 1 for i, r in enumerate(sorted(set(rank.values())))}
    return {k: min(order[r], 9) for k, r in rank.items()}


def _apply_relevel(ex, kept: list[dict]) -> int:
    """Ghi cấp mới (xem _relevel_plan) vào các đề mục được giữ; hình thức hiển thị giữ nguyên. Trả về số đoạn đổi cấp."""
    from types import SimpleNamespace
    from docx.text.paragraph import Paragraph
    from .fix import _freeze_format, _set_outline_level, normal_style
    plan = _relevel_plan(kept)
    spec = SimpleNamespace(font_name="Times New Roman")
    n = 0
    for it in kept:
        new = plan[it["key"]]
        if new == it["level"]:
            continue
        p = it["p"]
        if p.num_label:                                 # số tự động: không đổi style (tránh mất số)
            _set_outline_level(p.element, new)
        else:
            # không chuyển sang style Heading khác (style đó có thể kèm ngắt trang/đánh số riêng của template):
            # đóng băng hình thức, đưa về Normal và ghi cấp trực tiếp - field TOC có \\u nên vẫn nhận đúng cấp
            _freeze_format(p.element, p, spec)
            Paragraph(p.element, ex.doc).style = normal_style(ex.doc)
            _set_outline_level(p.element, new)
        n += 1
    return n


def toc_candidates_of(ex) -> list[dict]:
    """Danh sách đề mục để hiện ở tab Mục lục (không gồm các dòng 'cứng': trống, tiêu đề Mục lục, dòng mục lục cũ)."""
    items = analyze_headings(ex)
    plan = _relevel_plan([it for it in items if not it["reason"]])     # cấp sẽ hiện trong mục lục (theo mặc định)
    return [{"key": it["key"], "text": re.sub(r"\s+", " ", it["text"])[:120], "level": plan.get(it["key"], it["level"]),
             "where": it["where"], "reason": it["reason"] or ""}
            for it in items if not it["hard"]]


def toc_gate(ex, exclude=(), include=()) -> list[str]:
    """Chốt chặn cuối: các đoạn SẼ vào mục lục (cấp đề mục 1-3) mà có dấu hiệu KHÔNG phải đề mục (xem _head_reason)
    thì gỡ cấp đề mục (giữ nguyên hình thức hiển thị) để không lọt vào mục lục. exclude/include: khoá do người dùng
    tích bỏ/giữ (include chỉ có tác dụng với lý do 'mềm'). Trả về danh sách chữ các đoạn đã gỡ."""
    from types import SimpleNamespace
    from docx.text.paragraph import Paragraph
    from .fix import _freeze_format, _set_outline_level, normal_style
    exclude, include = set(exclude or ()), set(include or ())
    out = []
    spec = SimpleNamespace(font_name="Times New Roman")
    kept = []
    for it in analyze_headings(ex):
        if _decide(it, exclude, include) is None:
            kept.append(it)
            continue
        p, t = it["p"], it["text"]
        if (p.style_name or "").lower().startswith("heading"):
            _freeze_format(p.element, p, spec)          # Word không cho đổi outline level của style Heading
            Paragraph(p.element, ex.doc).style = normal_style(ex.doc)
            _set_outline_level(p.element, None)
        else:
            _set_outline_level(p.element, 10)           # val=9: Body Text
        out.append(t[:80] or "(dòng trống)")
    toc_gate.releveled = _apply_relevel(ex, kept)
    return out


def _merge_label_title(ex) -> list[str]:
    """'CHƯƠNG 1' (một đoạn) + 'TÊN CHƯƠNG' (đoạn kế) -> MỘT đoạn đề mục cấp 1, hai dòng nối bằng
    ngắt dòng mềm (Shift+Enter). Trang in vẫn hiện 2 dòng như cũ; mục lục hiện 1 dòng
    'CHƯƠNG 1 TÊN CHƯƠNG' với 1 số trang. Không gộp nếu đoạn kế là đề mục có số (1.1.), câu văn
    hay đoạn trống kéo dài."""
    from .extract import iter_runs as _ir
    from .fix import _set_outline_level
    from .roles import content_signal
    paras = [p for p in ex.paragraphs if p.where == "body"]
    merged = []
    i = 0
    while i < len(paras) - 1:
        p = paras[i]
        if not _is_label_only(p.text) or p.element.getparent() is None:
            i += 1
            continue
        j, gap = i + 1, []
        while j < len(paras) and not paras[j].text.strip() and len(gap) < 1:
            gap.append(paras[j]); j += 1
        if j >= len(paras):
            break
        q = paras[j]
        t = q.text.strip()
        ok = (q.element.getparent() is p.element.getparent() and t and len(t) <= 200
              and not re.match(r"^\d+(\.\d+)*\.?\s", t) and not content_signal(t)
              and not _is_label_only(t) and not _is_toc_like_strict(q.element)
              and (q.heading_level == 1 or p.heading_level == 1 or t == t.upper()))
        # các đoạn phải liền kề thật trong XML (không có bảng/ngắt section xen giữa)
        chain = [p.element] + [g.element for g in gap] + [q.element]
        ok = ok and all(a.getnext() is b for a, b in zip(chain, chain[1:]))
        ok = ok and all(g.element.find(qn("w:pPr") + "/" + qn("w:sectPr")) is None for g in gap)
        if not ok:
            i += 1
            continue
        # giữ nguyên hình thức hiển thị của cả 2 dòng (định dạng kế thừa từ style -> ghi trực tiếp vào run)
        from types import SimpleNamespace
        from .fix import _freeze_format
        _spec = SimpleNamespace(font_name="Times New Roman")
        _freeze_format(q.element, q, _spec)
        _freeze_format(p.element, p, _spec)
        runs = list(_ir(p.element))
        br_run = OxmlElement("w:r")
        if runs and runs[-1].find(qn("w:rPr")) is not None:
            br_run.append(copy.deepcopy(runs[-1].find(qn("w:rPr"))))
        br_run.append(OxmlElement("w:br"))
        p.element.append(br_run)
        for child in list(q.element):
            if child.tag != qn("w:pPr"):
                p.element.append(child)
        for g in gap:
            g.element.getparent().remove(g.element)
        q.element.getparent().remove(q.element)
        _set_outline_level(p.element, 1)
        merged.append(f"{p.text.strip()} + {t[:60]}")
        i = j + 1
    return merged


def _first_heading_el(ex):
    """Đoạn đề mục (cấp 1-3) đầu tiên ở thân văn bản không phải tiêu đề MỤC LỤC/DANH MỤC: điểm neo để tạo mục lục."""
    for p in ex.paragraphs:
        if p.where != "body" or not p.heading_level or p.heading_level > 3 or p.element.getparent() is None:
            continue
        if _list_kind(_UP(p.text or "")) is not None:
            continue
        if p.element.getparent() is ex.doc.element.body:
            return p.element
    return None


def _load_merged(src_path: str):
    """Đọc file, gộp 'CHƯƠNG n' + tên chương (trong bộ nhớ) rồi đọc lại để ParaInfo khớp với XML sau khi gộp.
    Trả về (ex, danh sách đã gộp). Dùng chung cho dựng mục lục và lập danh sách đề mục để người dùng tích chọn."""
    import os
    import tempfile
    from .extract import extract
    ex = extract(src_path)
    merged = _merge_label_title(ex)
    if merged:
        fd, tmp = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            save_docx(ex.doc, tmp)
            ex = extract(tmp)
        finally:
            os.unlink(tmp)
    return ex, merged


def toc_candidates(src_path: str) -> list[dict]:
    """Các đề mục sẽ/không vào mục lục của file (để hiện danh sách tích chọn)."""
    ex, _ = _load_merged(src_path)
    return toc_candidates_of(ex)


def build_toc(src_path: str, out_path: str, want: dict | None = None, create: bool = False,
              exclude=(), include=()) -> dict:
    """Đọc file .docx tại src_path, chuyển số Hình/Bảng thành field, chèn Mục lục/Danh mục vào
    các tiêu đề có sẵn, rồi ghi ra out_path (có thể trùng src_path để ghi đè tại chỗ).

    want: {"toc","hinh","bang"} -> mục nào làm (mặc định cả ba, như trước). Chỉ đổi số Hình/Bảng thành field khi
    có chọn danh mục hình hoặc bảng. create=True: mục chọn mà chưa có tiêu đề thì tạo mới.
    exclude/include: khoá đề mục (xem analyze_headings) người dùng tích bỏ/giữ lại trong mục lục."""
    w = {"toc": True, "hinh": True, "bang": True} if want is None else {k: bool(want.get(k)) for k in ("toc", "hinh", "bang")}
    if w["toc"]:
        ex, merged = _load_merged(src_path)
    else:
        from .extract import extract
        ex, merged = extract(src_path), []
    doc = ex.doc
    cands = toc_candidates_of(ex) if w["toc"] else None      # trước khi gỡ cấp đề mục: dùng lại cho giao diện
    gate = toc_gate(ex, exclude, include) if w["toc"] else []
    anchor = _first_heading_el(ex) if create else None
    # làm Mục lục/Danh mục TRƯỚC (xoá khối cũ gõ tay) rồi mới đánh số field cho chú thích: nếu đổi trước, các dòng
    # "Hình 1..." của danh mục cũ cũng bị đếm vào SEQ làm lệch số của chú thích thật (Hình 3, 4...)
    toc_stats = insert_toc_fields(doc, w, create, anchor)
    cap_stats = convert_captions(doc, {n for n, k in (('Hinh', 'hinh'), ('Bang', 'bang')) if w[k]}) if (w["hinh"] or w["bang"]) else {
        "converted": {"Hinh": 0, "Bang": 0}, "skipped": [], "tagged": {"Hinh": 0, "Bang": 0}, "word_captions": {"Hinh": 0, "Bang": 0}}
    set_update_fields(doc)
    save_docx(doc, out_path)
    toc_stats["gate_removed"] = gate
    toc_stats["releveled"] = getattr(toc_gate, "releveled", 0) if w["toc"] else 0
    toc_stats["merged_chapters"] = merged
    return {"captions": cap_stats, "toc": toc_stats, "candidates": cands}
