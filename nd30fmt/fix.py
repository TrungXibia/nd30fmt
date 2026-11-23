"""Sửa định dạng theo quy chuẩn bằng python-docx/lxml.

Nguyên tắc an toàn:
  - Không thêm/xóa đoạn trong thân văn bản (giữ nguyên nội dung và thứ tự).
  - Chỉ sửa đúng thuộc tính bị lỗi của đoạn bị lỗi.
  - Nhấn mạnh cục bộ (vài từ in đậm/nghiêng trong đoạn nội dung) được giữ nguyên.
  - Đoạn có độ tin cậy vai trò thấp: chỉ sửa phông/màu, không sửa theo vai trò.
"""
from __future__ import annotations

import copy
import re
from collections import Counter

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Cm, Mm, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .check import LABEL_KW, LABEL_ROLES, Violation, _dieu_prefix_len
from .extract import ExtractedDoc, _has_page_field, iter_runs, qn
from .ooxml_order import save_docx
from .roles import RoleDecision, content_signal, is_toc_heading
from .spec import Spec

ALIGN = {"center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
         "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}


def _set_font(r_el, name: str):
    run = Run(r_el, None)
    run.font.name = name
    rpr = r_el.get_or_add_rPr()
    rf = rpr.get_or_add_rFonts()
    for slot in ("ascii", "hAnsi", "cs", "eastAsia"):
        rf.set(qn(f"w:{slot}"), name)
    for slot in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        if rf.get(qn(f"w:{slot}")) is not None:
            del rf.attrib[qn(f"w:{slot}")]


# thứ tự phần tử con của w:rPr theo lược đồ OOXML (CT_RPr)
_RPR_SEQ = ("w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike",
            "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish",
            "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight",
            "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
            "w:eastAsianLayout", "w:specVanish", "w:oMath")


def set_line_spacing(p_el, spec: Spec, rule=None):
    """Ghi giãn dòng TRỰC TIẾP vào w:spacing của đoạn, luôn kèm lineRule tường minh.
    Không dùng ParagraphFormat.line_spacing = Pt(x): python-docx giữ nguyên lineRule="atLeast" cũ
    (chỉ đổi số), nên đoạn "At least 11.7pt" thành "At least 20pt" thay vì "Exactly 20pt"."""
    sp = p_el.get_or_add_pPr().get_or_add_spacing()
    if rule is not None and rule.line_spacing and not rule.body_like:   # giãn dòng riêng của vai trò (lines)
        sp.set(qn("w:line"), str(round(float(rule.fix_line_spacing or rule.line_spacing[1]) * 240)))
        sp.set(qn("w:lineRule"), "auto")
    elif spec.body.get("line_spacing_mode") == "exact_pt":
        sp.set(qn("w:line"), str(round(float(spec.body.get("fix_line_spacing_pt", 20)) * 20)))
        sp.set(qn("w:lineRule"), "exact")
    else:
        sp.set(qn("w:line"), str(round(float(spec.body.get("fix_line_spacing", 1.15)) * 240)))
        sp.set(qn("w:lineRule"), "auto")


def _text_runs(p_el):
    for r in iter_runs(p_el):
        if any((t.text or "").strip() for t in r.findall(qn("w:t"))):
            yield r


def _split_run(r_el, k: int):
    """Tách run có đúng một w:t tại vị trí ký tự k. Trả về (run_trái, run_phải)."""
    ts = r_el.findall(qn("w:t"))
    if len(ts) != 1 or len([c for c in r_el if c.tag != qn("w:rPr")]) != 1:
        return None
    t = ts[0]
    text = t.text or ""
    if k <= 0 or k >= len(text):
        return None
    right = copy.deepcopy(r_el)
    t.text = text[:k]
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    rt = right.find(qn("w:t"))
    rt.text = text[k:]
    rt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r_el.addnext(right)
    return r_el, right


def _bold_prefix(p_el, nchars: int):
    seen = 0
    for r in list(iter_runs(p_el)):
        txt = "".join(t.text or "" for t in r.findall(qn("w:t")))
        if not txt:
            continue
        if seen >= nchars:
            break
        if seen + len(txt) <= nchars:
            Run(r, None).font.bold = True
        else:
            parts = _split_run(r, nchars - seen)
            if parts:
                Run(parts[0], None).font.bold = True
        seen += len(txt)


# ---------------------------------------------------------------------------
def fix_paragraph(p_info, d: RoleDecision, viols: list[Violation], spec: Spec, stats: Counter,
                  extra_fields: set | None = None, normalize: bool = False):
    p_el = p_info.element
    fx = spec.fix
    fields = {v.field for v in viols if v.fixable} | (extra_fields or set())
    rule = spec.roles.get(d.role) or spec.roles["other"]
    para = Paragraph(p_el, None)
    pf = para.paragraph_format

    if "font" in fields and fx.get("font_name", True):
        for r in iter_runs(p_el):
            _set_font(r, spec.font_name)
        stats["font"] += 1
    if "color" in fields and fx.get("font_color", True):
        for r in iter_runs(p_el):
            Run(r, None).font.color.rgb = RGBColor(0, 0, 0)
        stats["color"] += 1

    if "size" in fields and fx.get("size", True) and rule.size:
        lo, hi = rule.size
        cnt = Counter()
        for r in p_info.runs:
            if r.size and lo <= r.size <= hi:
                cnt[r.size] += len(r.text.strip())
        # cỡ chữ luôn ghi theo giá trị "Sửa về" đã cài đặt (13 nằm trong khoảng 13–14 vẫn đưa về 14 nếu Sửa về = 14);
        # khoảng Từ–Đến chỉ quyết định có báo lỗi hay không
        target = rule.fix_size or (cnt.most_common(1)[0][0] if cnt else hi)
        for r in _text_runs(p_el):
            Run(r, None).font.size = Pt(target)
        stats["size"] += 1

    if "bold" in fields and fx.get("bold_italic", True):
        if d.role == "dieu":
            _bold_prefix(p_el, _dieu_prefix_len(p_info.text))
        elif rule.bold in (True, False):
            for r in _text_runs(p_el):
                Run(r, None).font.bold = bool(rule.bold)
        stats["bold"] += 1
    if "italic" in fields and fx.get("bold_italic", True) and rule.italic in (True, False):
        for r in _text_runs(p_el):
            Run(r, None).font.italic = bool(rule.italic)
        stats["italic"] += 1
    if "underline" in fields and rule.underline is True:
        for r in _text_runs(p_el):
            Run(r, None).font.underline = True
        stats["underline"] += 1

    if "caps" in fields and fx.get("caps_text", True) and rule.caps is True:
        for r in iter_runs(p_el):
            for t in r.findall(qn("w:t")):
                if t.text:
                    t.text = t.text.upper()
        stats["caps"] += 1
    elif "caps" in fields and rule.caps is False and d.role in LABEL_ROLES:
        # CHƯƠNG I -> Chương I ; PHỤ LỤC II -> Phụ lục II (chỉ đổi từ khóa)
        for r in iter_runs(p_el):
            for t in r.findall(qn("w:t")):
                if t.text:
                    t.text = LABEL_KW.sub(lambda m: m.group(0).capitalize(), t.text, count=1)
                    break
            else:
                continue
            break
        for r in iter_runs(p_el):
            rpr = r.find(qn("w:rPr"))
            if rpr is not None and rpr.find(qn("w:caps")) is not None:
                rpr.remove(rpr.find(qn("w:caps")))
        stats["caps"] += 1

    if "align" in fields and fx.get("alignment", True) and rule.align in ALIGN:
        pf.alignment = ALIGN[rule.align]
        stats["align"] += 1

    if "indent" in fields and fx.get("indent", True):
        # danh sách tự động / thụt treo: đưa lề trái về 0 để số thứ tự bắt đầu tại vị trí lùi đầu dòng
        if p_info.num_label or p_info.first_line_cm < 0:
            pf.left_indent = Cm(0)
        pf.first_line_indent = Cm(float(spec.body.get("fix_first_line_indent_cm", 1.27)))
        ind = p_el.get_or_add_pPr().find(qn("w:ind"))
        if ind is not None:
            for a in ("hanging", "hangingChars", "firstLineChars"):
                if ind.get(qn(f"w:{a}")) is not None:
                    del ind.attrib[qn(f"w:{a}")]
        stats["indent"] += 1

    if "spacing" in fields and fx.get("spacing", True):
        pf.space_before = Pt(float(spec.body.get("fix_space_before_pt", 6)))
        pf.space_after = Pt(float(spec.body.get("fix_space_after_pt", 0)))
        sp = p_el.get_or_add_pPr().find(qn("w:spacing"))
        if sp is not None:
            for a in ("beforeAutospacing", "afterAutospacing", "beforeLines", "afterLines"):
                if sp.get(qn(f"w:{a}")) is not None:
                    del sp.attrib[qn(f"w:{a}")]
        stats["spacing"] += 1

    if "line_spacing" in fields and fx.get("line_spacing", True):
        set_line_spacing(p_el, spec, rule)
        stats["line_spacing"] += 1

    if "char_spacing" in fields and fx.get("char_spacing", True):
        # mật độ chữ bình thường: ghi tường minh 0pt / 100% để đè cả giá trị kế thừa từ style
        for r in iter_runs(p_el):
            rpr = r.get_or_add_rPr()
            for tag, val in (("w:spacing", "0"), ("w:w", "100")):
                el = rpr.find(qn(tag))
                if el is None:   # chèn đúng thứ tự phần tử trong w:rPr (Word báo lỗi file nếu sai thứ tự)
                    el = OxmlElement(tag)
                    rpr.insert_element_before(el, *_RPR_SEQ[_RPR_SEQ.index(tag) + 1:])
                el.set(qn("w:val"), val)
        stats["char_spacing"] += 1

    for v in viols:
        if v.fixable and v.field in fields:
            v.fixed = True


# ---------------------------------------------------------------------------
def _add_page_field(paragraph: Paragraph, font: str, size: float):
    def mk_run():
        r = paragraph.add_run()
        r.font.name = font
        r.font.size = Pt(size)
        _set_font(r._r, font)
        return r

    r1 = mk_run()
    fc1 = OxmlElement("w:fldChar")
    fc1.set(qn("w:fldCharType"), "begin")
    r1._r.append(fc1)
    r2 = mk_run()
    it = OxmlElement("w:instrText")
    it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    it.text = " PAGE "
    r2._r.append(it)
    r3 = mk_run()
    fc2 = OxmlElement("w:fldChar")
    fc2.set(qn("w:fldCharType"), "separate")
    r3._r.append(fc2)
    r4 = mk_run()
    r4.text = "2"
    r5 = mk_run()
    fc3 = OxmlElement("w:fldChar")
    fc3.set(qn("w:fldCharType"), "end")
    r5._r.append(fc3)


def _remove_footer_page_numbers(section) -> int:
    removed = 0
    for ftr in (section.footer, section.first_page_footer, section.even_page_footer):
        if ftr.is_linked_to_previous:
            continue
        for p in list(ftr.paragraphs):
            if _has_page_field(p._p):
                other = "".join(t.text or "" for t in p._p.iter(qn("w:t"))).strip()
                if len(other) <= 12:
                    p._p.getparent().remove(p._p)
                    removed += 1
    return removed


def fix_page(ex: ExtractedDoc, viols: list[Violation], spec: Spec, stats: Counter, normalize: bool = False,
             ignored=frozenset()):
    doc = ex.doc
    pg = spec.page
    fx = spec.fix
    by_sec = {}
    for v in viols:
        if v.scope == "page":
            by_sec.setdefault(v.target, []).append(v)
    for si, sec in enumerate(doc.sections):
        vs = by_sec.get(f"Section {si + 1}", [])
        fields = {v.field for v in vs}
        if normalize:
            fields.add("margin")
        if "paper" in fields and fx.get("paper", True):
            w, h = Mm(pg["paper"]["width_mm"]), Mm(pg["paper"]["height_mm"])
            if (sec.page_width or 0) > (sec.page_height or 0):
                w, h = h, w
            sec.page_width, sec.page_height = w, h
            stats["paper"] += 1
        if "margin" in fields and fx.get("margins", True):
            m = pg["margins_mm"]
            for side in ("top", "bottom", "left", "right"):
                if f"Section {si + 1}|margin_{side}" in ignored:
                    continue
                cur = getattr(sec, f"{side}_margin") or 0
                lo, hi = m[side]["range"]
                cur_mm = cur / 36000
                if normalize or cur_mm < lo - m.get("tolerance_mm", 0.3) or cur_mm > hi + m.get("tolerance_mm", 0.3):
                    setattr(sec, f"{side}_margin", Mm(m[side]["fix"]))
            stats["margin"] += 1
        for v in vs:
            if v.field in ("paper", "margin") and v.fixable:
                v.fixed = True

    # ---- số trang ----
    pn = pg.get("page_number", {})
    pv = [v for v in viols if v.field == "page_number"]
    if pv and fx.get("page_number", True) and pn.get("required"):
        sec0 = doc.sections[0]
        size = float(pn.get("fix_size", 14))
        font = spec.font_name
        if pn.get("hide_first_page"):
            sec0.different_first_page_header_footer = True
        for si, sec in enumerate(doc.sections):
            hdr = sec.header
            if si > 0 and hdr.is_linked_to_previous:
                continue
            hdr.is_linked_to_previous = False
            target = None
            for p in hdr.paragraphs:
                if _has_page_field(p._p):
                    target = p
                    break
            if target is None:
                empty = [p for p in hdr.paragraphs if not p.text.strip()]
                target = empty[0] if empty else hdr.add_paragraph()
                _add_page_field(target, font, size)
            target.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in target._p.iter(qn("w:r")):
                Run(r, None).font.size = Pt(size)
                _set_font(r, font)
            _remove_footer_page_numbers(sec)
        stats["page_number"] += 1
        for v in pv:
            v.fixed = True


def normal_style(doc):
    """Style đoạn văn mặc định. Không phải file nào cũng có style tên "Normal": file tạo bằng WPS,
    LibreOffice, Google Docs, phần mềm quản lý văn bản... đặt tên khác ("Default", "Standard",
    "Văn bản thường"...). Tìm theo tên -> style mặc định (w:default="1") -> styleId Normal -> tạo mới."""
    try:
        return doc.styles["Normal"]
    except KeyError:
        pass
    paras = [s for s in doc.styles if s.type == WD_STYLE_TYPE.PARAGRAPH]
    for s in paras:
        if (s.element.get(qn("w:default")) or "").lower() in ("1", "true", "on"):
            return s
    for s in paras:
        if (s.style_id or "").lower() == "normal":
            return s
    st = doc.styles.add_style("Normal", WD_STYLE_TYPE.PARAGRAPH)
    st.element.set(qn("w:default"), "1")
    return st


def fix_normal_style(doc, spec: Spec):
    font = spec.font_name
    try:
        st = normal_style(doc)
        st.font.name = font
        st.font.size = Pt(float(spec.body.get("fix_size", 14)))
        rpr = st.element.get_or_add_rPr()
        rf = rpr.get_or_add_rFonts()
        for slot in ("ascii", "hAnsi", "cs", "eastAsia"):
            rf.set(qn(f"w:{slot}"), font)
        for slot in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
            if rf.get(qn(f"w:{slot}")) is not None:
                del rf.attrib[qn(f"w:{slot}")]
    except KeyError:
        pass
    dd = doc.styles.element.find(qn("w:docDefaults"))
    if dd is not None:
        rpr = dd.find(qn("w:rPrDefault") + "/" + qn("w:rPr"))
        if rpr is not None:
            rf = rpr.find(qn("w:rFonts"))
            if rf is None:
                rf = OxmlElement("w:rFonts")
                rpr.insert(0, rf)
            for slot in ("ascii", "hAnsi", "cs", "eastAsia"):
                rf.set(qn(f"w:{slot}"), font)
            for slot in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
                if rf.get(qn(f"w:{slot}")) is not None:
                    del rf.attrib[qn(f"w:{slot}")]


def _normalize_fields(p, d: RoleDecision, spec: Spec) -> set:
    """Chế độ 'áp dụng đồng loạt': các thuộc tính cần đưa về đúng GIÁ TRỊ SỬA dù đang nằm trong khoảng cho phép."""
    if d.role in ("empty", "other") or not p.text.strip():
        return set()
    rule = spec.roles.get(d.role)
    if rule is None:
        return set()
    b = spec.body
    out = set()
    if rule.size and rule.fix_size and any(r.size != rule.fix_size for r in p.runs if r.text.strip()):
        out.add("size")
    if rule.align in ALIGN and p.align != rule.align:
        out.add("align")
    if p.where == "body" and rule.first_line_indent_cm and \
            abs(p.first_line_cm - float(b.get("fix_first_line_indent_cm", 1.27))) > 0.02:
        out.add("indent")
    if rule.line_spacing and not rule.body_like and (
            p.line_rule != "auto" or abs(p.line_value - float(rule.fix_line_spacing or rule.line_spacing[1])) > 0.01):
        out.add("line_spacing")
    if rule.body_like and p.where == "body":
        if abs(p.before_pt - float(b.get("fix_space_before_pt", 6))) > 0.1 or \
                abs(p.after_pt - float(b.get("fix_space_after_pt", 0))) > 0.1:
            out.add("spacing")
        if b.get("line_spacing_mode") == "exact_pt":
            if p.line_rule != "exact" or abs(p.line_value - float(b.get("fix_line_spacing_pt", 20))) > 0.05:
                out.add("line_spacing")
        elif p.line_rule != "auto" or abs(p.line_value - float(b.get("fix_line_spacing", 1.15))) > 0.01:
            out.add("line_spacing")
    return out


# Vai trò -> cấp Heading thật của Word (outline level 1-4) mà đoạn PHẢI mang, để field
# Mục lục (TOC \o "1-3"/"1-4" trong toc.py) nhận đúng và đủ mục. Đây là kiến trúc gốc của
# Word: field mục lục chỉ đọc đoạn có style Heading N/outlineLvl, không đọc "vai trò" nội bộ
# của nd30fmt. Vai trò KHÔNG có trong bảng này mà đoạn lại đang mang style Heading (vd. copy
# dán từ file khác, hoặc bị gán nhầm từ trước) sẽ bị hạ về Normal để không lây vào mục lục.
_INLINE_LABEL_LEVEL = {"phan_chuong_label": 1, "dang_phan_chuong_label": 1, "muc_label": 2, "dang_muc_label": 2}
HEADING_LEVEL_BY_ROLE = {
    # NĐ 30 hành chính / báo cáo
    "phan_chuong_title": 1, "muc_title": 2,
    "heading_l1": 1, "heading_l2": 2, "heading_l3": 3,
    # Văn bản Đảng
    "dang_phan_chuong_title": 1, "dang_muc_title": 2,
    "dang_heading_l1": 1, "dang_heading_l2": 2, "dang_heading_l3": 3,
    # Luận văn / đề án
    "dean_tieu_de_phan": 1, "dean_chuong": 1,
    "dean_muc_2": 2, "dean_muc_3": 3, "dean_muc_4": 4,
}


def _get_or_create_heading_style(doc, level: int):
    name = f"Heading {level}"
    try:
        return doc.styles[name]
    except KeyError:
        # Một số file .docx tối giản (vd. xuất từ công cụ khác) không có sẵn style Heading
        # trong template -> tạo mới, kế thừa Normal, để không đổi hiển thị ngoài ý muốn.
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = normal_style(doc)
        return st


def _current_outline_level(p_el) -> int | None:
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        return None
    node = pPr.find(qn("w:outlineLvl"))
    if node is None:
        return None
    try:
        return int(node.get(qn("w:val"))) + 1
    except (TypeError, ValueError):
        return None


def _set_outline_level(p_el, level: int | None):
    """level 1-9: ghi w:outlineLvl (0-based). None: xoá override -> coi là văn bản thường,
    không bị field TOC gom vào."""
    pPr = p_el.get_or_add_pPr()
    node = pPr.find(qn("w:outlineLvl"))
    if level is None:
        if node is not None:
            pPr.remove(node)
        return
    if node is None:   # chèn đúng thứ tự lược đồ (trước w:rPr/w:sectPr của dấu đoạn), không append cuối
        node = pPr.get_or_add_outlineLvl()
    node.set(qn("w:val"), str(level - 1))


def _freeze_format(p_el, p_info, spec: Spec) -> None:
    """Ghi định dạng HIỂN THỊ hiện tại của đoạn (đã tính kế thừa, lấy từ bản trích xuất) thành
    định dạng trực tiếp, để việc đổi style (Heading N <-> Normal) không làm đổi hình thức đoạn."""
    para = Paragraph(p_el, None)
    pf = para.paragraph_format
    align_map = {"center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
                 "both": WD_ALIGN_PARAGRAPH.JUSTIFY, "right": WD_ALIGN_PARAGRAPH.RIGHT,
                 "left": WD_ALIGN_PARAGRAPH.LEFT}
    pf.alignment = align_map.get(p_info.align, WD_ALIGN_PARAGRAPH.LEFT)
    pf.first_line_indent = Cm(p_info.first_line_cm)
    pf.left_indent = Cm(p_info.left_indent_cm)
    pf.space_before = Pt(p_info.before_pt)
    pf.space_after = Pt(p_info.after_pt)
    sp = p_el.get_or_add_pPr().get_or_add_spacing()
    if p_info.line_rule == "auto":
        sp.set(qn("w:line"), str(round(p_info.line_value * 240)))
    else:
        sp.set(qn("w:line"), str(round(p_info.line_value * 20)))
    sp.set(qn("w:lineRule"), p_info.line_rule or "auto")
    text_runs = [r for r in iter_runs(p_el) if _run_text_plain(r)]
    for r_el, ri in zip(text_runs, p_info.runs):
        _set_font(r_el, ri.font_ascii or ri.font_hansi or spec.font_name)
        run = Run(r_el, None)
        if ri.size:
            run.font.size = Pt(ri.size)
        run.font.bold = bool(ri.bold)
        run.font.italic = bool(ri.italic)
        run.font.all_caps = bool(ri.caps)
        if ri.color and ri.color.lower() not in ("auto",):
            try:
                run.font.color.rgb = RGBColor.from_string(ri.color.upper())
            except ValueError:
                run.font.color.rgb = RGBColor(0, 0, 0)
        else:
            run.font.color.rgb = RGBColor(0, 0, 0)


def _run_text_plain(r_el) -> str:
    out = []
    for node in r_el:
        if node.tag == qn("w:t"):
            out.append(node.text or "")
        elif node.tag == qn("w:tab"):
            out.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            out.append("\n")
    return "".join(out)


def _style_has_numbering(style) -> bool:
    el = style.element
    ppr = el.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _suppress_style_numbering(p_el) -> None:
    """Style Heading của một số template gắn sẵn đánh số đa cấp (vd. 'Chương 1') -> chặn ở
    cấp đoạn (numId=0) để không tự sinh thêm số đầu dòng mà văn bản gốc không có."""
    pPr = p_el.get_or_add_pPr()
    if pPr.find(qn("w:numPr")) is not None:
        return
    numPr = pPr.get_or_add_numPr()   # python-docx đặt đúng vị trí (sau keepNext/keepLines/...)
    ilvl = OxmlElement("w:ilvl"); ilvl.set(qn("w:val"), "0")
    num = OxmlElement("w:numId"); num.set(qn("w:val"), "0")
    numPr.append(ilvl); numPr.append(num)


def heading_prob(d: RoleDecision) -> float:
    """Xác suất đoạn là ĐỀ MỤC: tổng điểm của các vai trò đề mục (nếu có điểm), nếu không
    có điểm thì suy từ độ tin cậy của vai trò đã chọn."""
    if d.scores:
        return float(sum(v for k, v in d.scores.items() if k in HEADING_LEVEL_BY_ROLE))
    return d.confidence if d.role in HEADING_LEVEL_BY_ROLE else 1.0 - d.confidence


def fix_heading_styles(ex: ExtractedDoc, decisions: list[RoleDecision], spec: Spec, stats: Counter,
                       min_conf: float) -> None:
    """Đồng bộ cấp đề mục thật của Word với vai trò đã nhận diện chắc chắn, để Mục lục (field
    TOC \\o "1-3" \\u trong toc.py) nhận ĐÚNG và ĐỦ tiêu đề; đồng thời gỡ cấp đề mục bị gán
    thừa vào đoạn nội dung/liệt kê/tài liệu tham khảo (nguyên nhân mục lục lẫn câu văn).

    Chạy TRƯỚC bước sửa định dạng từng đoạn. Khi phải đổi style, định dạng hiển thị gốc được
    đóng băng thành định dạng trực tiếp, nên hình thức đoạn không đổi; sau đó fix_paragraph
    mới sửa những gì sai quy chuẩn như bình thường.
    Đoạn đang có số tự động (num_label) thì KHÔNG đổi style (tránh mất số), chỉ gán outline level."""
    if not spec.fix.get("heading_styles", True):
        return
    for p, d in zip(ex.paragraphs, decisions):
        if d is None or p.where != "body":
            continue
        p_el = p.element
        want = HEADING_LEVEL_BY_ROLE.get(d.role)
        # "CHƯƠNG 1. TÊN CHƯƠNG" / "Mục 2. Tên mục" viết trên MỘT dòng: nhãn kèm tên -> vẫn là đề mục
        if want is None and d.role in _INLINE_LABEL_LEVEL and re.match(
                r"^(Phần|Chương|Mục|Tiểu\s+mục)\s+([IVXLCDM]+|\d+)\s*[.:\-–]\s*\S", p.text.strip(), re.I):
            want = _INLINE_LABEL_LEVEL[d.role]
        low = d.confidence < min_conf
        content = content_signal(p.text)
        hp = heading_prob(d)
        if want is not None and (is_toc_heading(p.text) or content or (low and hp < 0.5)):
            want = None      # "MỤC LỤC"/"DANH MỤC..." hoặc nội dung: không đưa vào mục lục
        if want is not None and low and p.heading_level is None:
            continue         # chưa chắc là đề mục -> không tự THÊM cấp đề mục
        if want is None and low and not content and hp >= 0.5:
            continue         # điểm nghiêng về đề mục dù vai trò mặc định khác -> giữ nguyên, để người dùng xem
        sname = (p.style_name or "").strip().lower()
        m = re.match(r"heading\s*(\d)", sname)
        style_level = int(m.group(1)) if m else None
        cur_level = p.heading_level          # đã tính cả outlineLvl trực tiếp/kế thừa
        if want is not None:
            if cur_level == want and (style_level in (None, want)):
                continue
            if p.num_label or style_level == want:
                _set_outline_level(p_el, want)
            else:
                _freeze_format(p_el, p, spec)
                st = _get_or_create_heading_style(ex.doc, want)
                Paragraph(p_el, ex.doc).style = st
                if _style_has_numbering(st):
                    _suppress_style_numbering(p_el)
                _set_outline_level(p_el, want)
            stats["heading_applied"] += 1
        elif cur_level is not None or style_level is not None or sname.startswith("title"):
            if p.num_label:
                _set_outline_level(p_el, 10)     # val=9: Body Text -> loại khỏi mục lục, giữ số
            else:
                _freeze_format(p_el, p, spec)
                Paragraph(p_el, ex.doc).style = normal_style(ex.doc)
                _set_outline_level(p_el, None)
            stats["heading_removed"] += 1


def apply_fixes(ex: ExtractedDoc, decisions: list[RoleDecision], viols: list[Violation], spec: Spec,
                out_path: str, ignored=None) -> dict:
    stats: Counter = Counter()
    ignored = set(ignored or ())
    viols = [v for v in viols if not v.ignored]      # lỗi người dùng đã bỏ qua: không sửa
    by_pid: dict[str, list[Violation]] = {}
    for v in viols:
        if v.scope == "paragraph":
            by_pid.setdefault(v.target, []).append(v)
    if spec.fix.get("normal_style", True):
        fix_normal_style(ex.doc, spec)
    normalize = spec.fix.get("mode", "violations") == "normalize"
    min_conf = float(spec.fix.get("min_role_confidence", 0.5))
    fix_heading_styles(ex, decisions, spec, stats, min_conf)
    for p, d in zip(ex.paragraphs, decisions):
        if d is None:
            continue
        vs = by_pid.get(p.pid, [])
        extra = _normalize_fields(p, d, spec) if d.confidence >= min_conf else set()
        if not normalize:
            extra &= {"size"}      # chế độ thường: chỉ cỡ chữ luôn đưa về giá trị "Sửa về"
        extra = {f for f in extra if f"{p.pid}|{f}" not in ignored}
        if vs or extra:
            fix_paragraph(p, d, vs, spec, stats, extra, normalize)
    fix_page(ex, viols, spec, stats, normalize, ignored)
    save_docx(ex.doc, out_path)
    return dict(stats)
