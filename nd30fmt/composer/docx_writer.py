"""Ghi mô hình bố cục (layout.py) ra file Word .docx bằng python-docx.

- Khổ A4, lề theo layout; phông Times New Roman (w:rFonts ascii/hAnsi/cs/eastAsia).
- Bảng đầu trang / chữ ký: bảng không viền, lề ô trái/phải = 0, độ rộng cố định (tblLayout fixed).
- Đường kẻ (dưới Tiêu ngữ, dưới tên cơ quan, dưới trích yếu, trên địa chỉ liên hệ): viền đoạn văn
  (w:pBdr) – không dùng ký tự '-' hay hình vẽ, mở được trong Word/LibreOffice.
- Số trang: đầu trang, canh giữa, trường PAGE; trang đầu không hiện số (w:titlePg).
- Mọi phần tử pPr/rPr được sắp đúng thứ tự lược đồ bằng ooxml_order.save_docx.
"""
from __future__ import annotations

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

from ..ooxml_order import normalize_document

FONT = "Times New Roman"
ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
         "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def _tw(pt: float) -> int:
    return int(round(pt * 20))


def _set_fonts(rpr_parent):
    rpr = rpr_parent.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(k), FONT)


def _base_styles(doc, body_size):
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(body_size)
    _set_fonts(st.element)
    pf = st.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    # tắt lưới tài liệu / tự giãn cách châu Á để khoảng cách dòng đúng như thiết lập
    rpr = st.element.get_or_add_rPr()
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "vi-VN")
    rpr.append(lang)


def _border(ppr, side: str, width_pt: float):
    bdr = ppr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        ppr.append(bdr)
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(max(2, int(round(width_pt * 8)))))  # đơn vị 1/8 pt
    el.set(qn("w:space"), "1" if side == "bottom" else "4")
    el.set(qn("w:color"), "000000")
    bdr.append(el)


def _write_para(p, item):
    pf = p.paragraph_format
    p.alignment = ALIGN.get(item.get("align"), WD_ALIGN_PARAGRAPH.LEFT)
    ind = item.get("ind", {})
    if ind.get("left"):
        pf.left_indent = Twips(_tw(ind["left"]))
    if ind.get("right"):
        pf.right_indent = Twips(_tw(ind["right"]))
    if ind.get("first"):
        pf.first_line_indent = Twips(_tw(ind["first"]))
    sp = item.get("sp", {})
    pf.space_before = Pt(sp.get("before", 0))
    pf.space_after = Pt(sp.get("after", 0))
    line = sp.get("line") or {"rule": "multiple", "value": 1.0}
    if line["rule"] == "exact":
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(line["value"])
    else:
        pf.line_spacing = float(line["value"])
    pf.widow_control = True
    if item.get("keep_next"):
        pf.keep_with_next = True
    ppr = p._p.get_or_add_pPr()
    for side in ("top", "bottom"):
        b = (item.get("border") or {}).get(side)
        if b:
            _border(ppr, side, b.get("w", 0.75))
    size = item.get("size", 14)
    # dấu đoạn cùng cỡ chữ để chiều cao dòng rỗng (khoảng ký, đường kẻ) đúng như xem trước
    mark = ppr.get_or_add_rPr() if hasattr(ppr, "get_or_add_rPr") else None
    if mark is None:
        mark = OxmlElement("w:rPr")
        ppr.append(mark)
    for tag, val in (("w:sz", size), ("w:szCs", size)):
        el = OxmlElement(tag)
        el.set(qn("w:val"), str(int(round(val * 2))))
        mark.append(el)
    for r in item.get("runs", []):
        text = r.get("t", "")
        if not text:
            continue
        run = p.add_run(text)
        run.font.name = FONT
        _set_fonts(run._r)
        run.font.size = Pt(r.get("size", size))
        if r.get("b"):
            run.bold = True
        if r.get("i"):
            run.italic = True
        if r.get("u"):
            run.underline = True


def _no_borders(tbl):
    tblPr = tbl._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    _insert_tblpr(tblPr, borders)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    _insert_tblpr(tblPr, layout)
    mar = OxmlElement("w:tblCellMar")
    for side in ("left", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), "0")
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    _insert_tblpr(tblPr, mar)


_TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
                "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
                "tblCaption", "tblDescription"]


def _insert_tblpr(tblPr, el):
    name = el.tag.split("}")[1]
    old = tblPr.find(qn(f"w:{name}"))
    if old is not None:
        tblPr.remove(old)
    rank = _TBLPR_ORDER.index(name)
    for i, child in enumerate(list(tblPr)):
        cname = child.tag.split("}")[1]
        if cname in _TBLPR_ORDER and _TBLPR_ORDER.index(cname) > rank:
            child.addprevious(el)
            return
    tblPr.append(el)


def _write_table(doc_or_cell, item, first_container=None):
    cols = item["cols"]
    rows = item["rows"]
    tbl = doc_or_cell.add_table(rows=len(rows), cols=len(cols))
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl.autofit = False
    tblPr = tbl._tbl.tblPr
    w = tblPr.find(qn("w:tblW"))
    if w is None:
        w = OxmlElement("w:tblW")
        _insert_tblpr(tblPr, w)
    w.set(qn("w:w"), str(sum(_tw(c) for c in cols)))
    w.set(qn("w:type"), "dxa")
    _no_borders(tbl)
    grid = tbl._tbl.tblGrid
    for gc, c in zip(grid.findall(qn("w:gridCol")), cols):
        gc.set(qn("w:w"), str(_tw(c)))
    for ri, row in enumerate(rows):
        for ci, cell_data in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.width = Twips(_tw(cols[ci]))
            items = cell_data.get("items") or []
            first = True
            for it in items:
                if it.get("t") != "p":
                    continue
                para = cell.paragraphs[0] if first else cell.add_paragraph()
                first = False
                _write_para(para, it)
    return tbl


def _page_number_header(section, size, hide_first):
    section.different_first_page_header_footer = bool(hide_first)
    hdr = section.header
    hdr.is_linked_to_previous = False
    p = hdr.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    _set_fonts(run._r)
    run.font.name = FONT
    run.font.size = Pt(size)
    for kind, text in (("begin", None), (None, " PAGE "), ("separate", None), (None, "2"), ("end", None)):
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            run._r.append(fc)
        elif text == " PAGE ":
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = text
            run._r.append(it)
        else:
            t = OxmlElement("w:t")
            t.text = text
            run._r.append(t)


def _insert_setting(settings_el, el):
    """Chèn phần tử vào settings.xml đúng thứ tự lược đồ CT_Settings."""
    from ..ooxml_order import SETTINGS_SEQ
    name = el.tag.split("}")[1]
    rank = SETTINGS_SEQ.index(name)
    for child in settings_el:
        cname = child.tag.split("}")[1] if isinstance(child.tag, str) else ""
        if cname in SETTINGS_SEQ and SETTINGS_SEQ.index(cname) > rank:
            child.addprevious(el)
            return
    settings_el.append(el)


def build_docx(layout: dict) -> bytes:
    doc = Document()
    body_size = layout["meta"]["settings"].get("body_size", 14)
    _base_styles(doc, body_size)
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width = Twips(11906)
    sec.page_height = Twips(16838)
    m = layout["page"]["margins"]
    sec.top_margin, sec.bottom_margin = Twips(_tw(m["top"])), Twips(_tw(m["bottom"]))
    sec.left_margin, sec.right_margin = Twips(_tw(m["left"])), Twips(_tw(m["right"]))
    sec.header_distance = Twips(_tw(layout["page"]["header_distance"]))
    sec.footer_distance = Twips(_tw(min(m["bottom"] / 2, 28.35)))
    sec.gutter = Twips(0)
    pn = layout["header"]["page_number"]
    _page_number_header(sec, pn["size"], pn["hide_first_page"])
    if layout.get("first_header"):
        sec.different_first_page_header_footer = True
        fh = sec.first_page_header
        fh.is_linked_to_previous = False
        first = True
        for it in layout["first_header"]:
            para = fh.paragraphs[0] if first else fh.add_paragraph()
            first = False
            _write_para(para, it)
    if layout["page"].get("mirror"):
        from ..ooxml_order import SETTINGS_SEQ  # noqa: F401 – thứ tự do normalize xử lý
        st = doc.settings.element
        if st.find(qn("w:mirrorMargins")) is None:
            el = OxmlElement("w:mirrorMargins")
            _insert_setting(st, el)
    if layout.get("first_footer"):
        sec.different_first_page_header_footer = True
        ff = sec.first_page_footer
        ff.is_linked_to_previous = False
        first = True
        for it in layout["first_footer"]:
            para = ff.paragraphs[0] if first else ff.add_paragraph()
            first = False
            _write_para(para, it)
    # xoá đoạn rỗng mặc định của Document()
    body = doc.element.body
    for p in list(body.findall(qn("w:p"))):
        body.remove(p)
    last_table = False
    for it in layout["items"]:
        if it["t"] == "p":
            _write_para(doc.add_paragraph(), it)
            last_table = False
        elif it["t"] == "table":
            _write_table(doc, it)
            last_table = True
    if last_table:
        # Word yêu cầu đoạn văn sau bảng cuối; đoạn cỡ 1 pt không làm thêm trang
        _write_para(doc.add_paragraph(), {"runs": [], "size": 1, "sp": {"line": {"rule": "exact", "value": 1}}})
    props = doc.core_properties
    props.title = layout["meta"].get("template_name", "")
    props.author = "nd30fmt – Soạn thảo văn bản"
    props.comments = f"Mẫu {layout['meta']['template']} ({layout['meta']['standard']})"
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    normalize_document(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
