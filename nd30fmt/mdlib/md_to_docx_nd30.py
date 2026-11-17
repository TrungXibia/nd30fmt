#!/usr/bin/env python3
"""
md_to_docx_nd30.py
Chuyen doi file Markdown (co YAML frontmatter) sang van ban hanh chinh .docx
dung the thuc va ky thuat trinh bay theo Nghi dinh 30/2020/ND-CP (Phu luc I).

Yeu cau: python-docx, pyyaml
    pip install python-docx pyyaml --break-system-packages

Cach dung:
    python3 md_to_docx_nd30.py input.md output.docx

Dinh dang input.md: xem file references/template_mau.md va references/huong_dan_frontmatter.md
"""

import sys
import re
import yaml
from pathlib import Path

from docx import Document
from docx.shared import Pt, Mm, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

FONT_NAME = "Times New Roman"

# --- Co chu theo Nghi dinh 30/2020/ND-CP, Phu luc I (van ban hanh chinh - Chinh phu) ---
SIZE_BODY = Pt(13)
SIZE_QUOCHIEU = Pt(13)
SIZE_TIEUNGU = Pt(14)
SIZE_COQUAN = Pt(13)
SIZE_SOKYHIEU = Pt(13)
SIZE_DIADANH = Pt(14)
SIZE_LOAIVB = Pt(14)
SIZE_TRICHYEU = Pt(14)

# --- Co chu theo Huong dan so 05-HD/VPTW ngay 27/5/2026 cua Van phong Trung
# uong Dang (van ban cua Dang) - thay the Huong dan 36-HD/VPTW 2018 ---
SIZE_BODY_DANG = Pt(14)
SIZE_DCSVN = Pt(15)          # "DANG CONG SAN VIET NAM"
SIZE_COQUAN_DANG = Pt(14)    # ten cap uy / co quan Dang ban hanh
SIZE_SOKYHIEU_DANG = Pt(14)
SIZE_DIADANH_DANG = Pt(14)
SIZE_LOAIVB_DANG = Pt(15)    # ten loai van ban + trich yeu, 15-16pt
SIZE_NOINHAN_DANG = Pt(12)

# --------------------------------------------------------------------------
# Nhan dien / loai bo noi dung the thuc da co san trong body Markdown, tranh
# lap lai voi cac khoi (quoc hieu, tieu de, noi nhan...) duoc tool tu sinh ra
# tu cac truong metadata. Cach lam nay gan voi cach cac add-in Word chuan
# NĐ30 hien co hoat dong: chung ap style truc tiep len noi dung nguoi dung da
# go san (chon doan -> bam nut dinh dang), thay vi tao van ban hoan toan moi.
# O day, do chay tren web/khong co thao tac "chon doan" thu cong, ta dung
# heuristic nhan dien theo mau cau truc pho bien de tu dong tach/bo trung.
# --------------------------------------------------------------------------

_QUOCHIEU_RE = re.compile(r"^CỘNG\s+HÒA\s+XÃ\s+HỘI\s+CHỦ\s+NGHĨA\s+VIỆT\s+NAM$", re.IGNORECASE)
_TIEUNGU_RE = re.compile(r"^Độc\s+lập\s*[-–—]\s*Tự\s+do\s*[-–—]\s*Hạnh\s+phúc$", re.IGNORECASE)
_DCSVN_RE = re.compile(r"^ĐẢNG\s+CỘNG\s+SẢN\s+VIỆT\s+NAM$", re.IGNORECASE)
_SOKYHIEU_RE = re.compile(r"^Số\s*[:\.]?\s*([0-9]+[0-9A-Za-zÀ-ỹ/\-\. ]*)$", re.IGNORECASE)
_DIADANH_NGAY_RE = re.compile(r"^([^,]{2,35}),\s*ngày\s+.+tháng\s+.+năm\s+.+$", re.IGNORECASE)
_NOINHAN_HEADER_RE = re.compile(r"^Nơi\s+nhận\s*:?\s*$", re.IGNORECASE)

_LOAI_VB_KEYWORDS = [
    "NGHỊ QUYẾT", "QUYẾT ĐỊNH", "CHỈ THỊ", "QUY CHẾ", "QUY ĐỊNH", "THÔNG CÁO",
    "THÔNG BÁO", "HƯỚNG DẪN", "CHƯƠNG TRÌNH", "KẾ HOẠCH", "PHƯƠNG ÁN", "ĐỀ ÁN",
    "BÁO CÁO", "BIÊN BẢN", "TỜ TRÌNH", "HỢP ĐỒNG", "CÔNG VĂN", "CÔNG ĐIỆN",
    "BẢN GHI NHỚ", "BẢN THỎA THUẬN", "GIẤY ỦY QUYỀN", "GIẤY MỜI",
    "GIẤY GIỚI THIỆU", "GIẤY NGHỈ PHÉP", "PHIẾU GỬI", "PHIẾU CHUYỂN",
    "PHIẾU BÁO", "THƯ CÔNG", "ĐƠN", "KẾT LUẬN",
]


def _norm_line(raw):
    return re.sub(r"^#{1,4}\s*", "", raw.strip()).strip().strip("*_").strip()


def strip_leading_boilerplate(body_md: str, meta: dict) -> str:
    """Bo cac dong o DAU noi dung da trung voi khoi quoc hieu/tieu ngu (hoac
    'DANG CONG SAN VIET NAM'), so ky hieu, dia danh-ngay thang, va dong
    loai_van_ban/trich_yeu - vi cac truong nay da duoc form/metadata sinh
    rieng thanh khoi the thuc o dau van ban. Neu khong bo, nguoi dung dan
    nguyen van ban da co san the thuc vao se bi lap thong tin 2 lan trong file
    .docx xuat ra. Chi xet trong vai dong dau tien de tranh xoa nham noi dung
    hop le o giua/cuoi van ban."""
    lines = body_md.split("\n")
    trich_yeu = (meta.get("trich_yeu") or "").strip().lower()
    loai = (meta.get("loai_van_ban") or "").strip().lower()
    n = len(lines)
    idx = 0
    scanned = 0
    while idx < n and scanned < 12:
        raw = lines[idx]
        if raw.strip() == "":
            idx += 1
            scanned += 1
            continue
        norm = _norm_line(raw)
        norm_l = norm.lower()
        is_boiler = bool(_QUOCHIEU_RE.match(norm) or _TIEUNGU_RE.match(norm)
                          or _DCSVN_RE.match(norm) or _SOKYHIEU_RE.match(norm)
                          or _DIADANH_NGAY_RE.match(norm))
        is_title_dup = bool(norm_l) and (norm_l == trich_yeu or norm_l == loai
                                          or norm_l == f"{loai} {trich_yeu}".strip())
        if is_boiler or is_title_dup:
            idx += 1
            scanned += 1
            continue
        break
    return "\n".join(lines[idx:]) if idx > 0 else body_md


def strip_trailing_noinhan(body_md: str) -> str:
    """Bo khoi 'Noi nhan: ...' neu co trong body - khoi nay duoc tool sinh
    rieng tu truong noi_nhan (nhap tay hoac tu dong nhan dien), giu lai trong
    body se bi lap 2 lan."""
    lines = body_md.split("\n")
    start = None
    for i, l in enumerate(lines):
        if _NOINHAN_HEADER_RE.match(l.strip()):
            start = i
            break
    if start is None:
        return body_md
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "" and j > start + 1:
            # dong trong lien tiep sau khi da co it nhat 1 dong noi nhan -> ket thuc khoi
            has_item = any(lines[k].strip() for k in range(start + 1, j))
            if has_item:
                end = j
                break
    return "\n".join(lines[:start] + lines[end:])


def auto_extract_fields(body_md: str) -> dict:
    """Do tim so ky hieu, dia danh/ngay thang, loai van ban + trich yeu, va
    khoi noi nhan tu noi dung van ban da soan/OCR san, dung de dien mac dinh
    cho form thay vi bat nguoi dung go lai thong tin da co trong tai lieu.
    Heuristic dua tren cach trinh bay pho bien, KHONG dam bao dung tuyet doi -
    nguoi dung can ra soat lai truoc khi xuat file chinh thuc."""
    result = {}
    lines = [l for l in body_md.split("\n")]
    non_empty = [(i, l.strip()) for i, l in enumerate(lines) if l.strip()]

    for i, l in non_empty[:15]:
        m = _DIADANH_NGAY_RE.match(_norm_line(l))
        if m:
            result["dia_danh"] = m.group(1).strip()
            result["ngay_thang"] = _norm_line(l).split(",", 1)[1].strip()
            break

    for i, l in non_empty[:15]:
        m = _SOKYHIEU_RE.match(_norm_line(l))
        if m and "/" in m.group(1):
            result["so_ky_hieu"] = m.group(1).strip().rstrip(".")
            break

    for i, l in non_empty[:15]:
        norm = _norm_line(l)
        if not norm or len(norm) > 100:
            continue
        if _QUOCHIEU_RE.match(norm) or _TIEUNGU_RE.match(norm) or _DCSVN_RE.match(norm):
            continue
        letters = re.sub(r"[^A-Za-zÀ-ỹ]", "", norm)
        if letters and norm == norm.upper() and len(letters) >= 4:
            matched_loai = next((kw for kw in _LOAI_VB_KEYWORDS if norm.startswith(kw)), None)
            if matched_loai:
                rest = norm[len(matched_loai):].strip(" :–-")
                result["loai_van_ban"] = matched_loai
                if rest:
                    result["trich_yeu"] = rest
            else:
                result["trich_yeu"] = norm
            break

    noi_nhan_items = []
    capture = False
    for l in lines:
        s = l.strip()
        if _NOINHAN_HEADER_RE.match(s):
            capture = True
            continue
        if capture:
            if s == "":
                if noi_nhan_items:
                    break
                continue
            noi_nhan_items.append(re.sub(r"^[-+*]\s*", "", s))
    if noi_nhan_items:
        result["noi_nhan"] = "\n".join(noi_nhan_items)

    return result


# --------------------------------------------------------------------------
# Tien ich cap thap
# --------------------------------------------------------------------------

def set_run_font(run, size=SIZE_BODY, bold=False, italic=False, name=FONT_NAME,
                  color=None, all_caps=False):
    run.font.name = name
    run.font.size = size
    run.font.bold = bold
    run.font.italic = italic
    run.font.all_caps = all_caps
    if color:
        run.font.color.rgb = RGBColor(*color)
    # ensure east-asian/complex-script font consistent (tranh loi font Unicode)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.append(rFonts)
    rFonts.set(qn('w:ascii'), name)
    rFonts.set(qn('w:hAnsi'), name)
    rFonts.set(qn('w:cs'), name)
    return run


def add_para(doc, text="", align=WD_ALIGN_PARAGRAPH.LEFT, size=SIZE_BODY,
             bold=False, italic=False, all_caps=False, space_after=6,
             space_before=0, line_spacing=1.5, indent_first=None):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = line_spacing
    if indent_first is not None:
        pf.first_line_indent = Cm(indent_first)
    if text:
        run = p.add_run(text)
        set_run_font(run, size=size, bold=bold, italic=italic, all_caps=all_caps)
    return p


def add_rich_para(doc, segments, align=WD_ALIGN_PARAGRAPH.LEFT, size=SIZE_BODY,
                   space_after=6, space_before=0, line_spacing=1.5,
                   indent_first=None):
    """segments: list of (text, {'bold':bool,'italic':bool,'code':bool})"""
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = line_spacing
    if indent_first is not None:
        pf.first_line_indent = Cm(indent_first)
    for text, fmt in segments:
        run = p.add_run(text)
        set_run_font(run, size=size, bold=fmt.get("bold", False),
                     italic=fmt.get("italic", False))
    return p


def set_margins_nd30(section):
    """Nghi dinh 30/2020, Phu luc I, muc II.1:
    Tren/duoi: 20-25mm ; Trai: 30-35mm ; Phai: 15-20mm.
    Dung gia tri pho bien: tren 20, duoi 20, trai 30, phai 20."""
    section.page_height = Mm(297)
    section.page_width = Mm(210)
    section.top_margin = Mm(20)
    section.bottom_margin = Mm(20)
    section.left_margin = Mm(30)
    section.right_margin = Mm(20)
    section.header_distance = Mm(10)
    section.footer_distance = Mm(10)


def add_horizontal_line(paragraph, width_pt=170):
    """Ke duong gach chan duoi 'Doc lap - Tu do - Hanh phuc'."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '000000')
    pBdr.append(bottom)
    pPr.append(pBdr)


# --------------------------------------------------------------------------
# Khoi thao van ban hanh chinh theo ND30
# --------------------------------------------------------------------------

def build_header_block(doc, meta):
    """O so 1 (Quoc hieu, tieu ngu) va O so 2 (ten co quan ban hanh) dat song
    song trong bang 2 cot khong vien de can chinh chuan the thuc."""
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.columns[0].width = Cm(7.5)
    table.columns[1].width = Cm(8.5)
    # tat vien bang
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        borders.append(el)
    tblPr.append(borders)

    # --- O trai: co quan chu quan + co quan ban hanh ---
    cell_left = table.rows[0].cells[0]
    cell_left.paragraphs[0].text = ""
    if meta.get("co_quan_chu_quan"):
        p1 = cell_left.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p1.paragraph_format.space_after = Pt(0)
        r1 = p1.add_run(meta["co_quan_chu_quan"].upper())
        set_run_font(r1, size=SIZE_COQUAN, bold=False)
    p2 = cell_left.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(0)
    r2 = p2.add_run(meta.get("co_quan_ban_hanh", "").upper())
    set_run_font(r2, size=SIZE_COQUAN, bold=True)
    # duong ke ngan duoi ten co quan ban hanh
    add_horizontal_line(p2, width_pt=90)
    # so ky hieu
    p3 = cell_left.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.paragraph_format.space_before = Pt(6)
    r3 = p3.add_run(f"Số: {meta.get('so_ky_hieu', '…/……-……')}")
    set_run_font(r3, size=SIZE_SOKYHIEU, italic=False)

    # --- O phai: quoc hieu tieu ngu ---
    cell_right = table.rows[0].cells[1]
    cell_right.paragraphs[0].text = ""
    pq = cell_right.paragraphs[0]
    pq.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pq.paragraph_format.space_after = Pt(0)
    rq = pq.add_run("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
    set_run_font(rq, size=SIZE_QUOCHIEU, bold=True)
    pt_ = cell_right.add_paragraph()
    pt_.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pt_.paragraph_format.space_before = Pt(2)
    pt_.paragraph_format.space_after = Pt(0)
    rt = pt_.add_run("Độc lập - Tự do - Hạnh phúc")
    set_run_font(rt, size=SIZE_TIEUNGU, bold=True)
    add_horizontal_line(pt_, width_pt=140)
    # dia danh, ngay thang
    pd = cell_right.add_paragraph()
    pd.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pd.paragraph_format.space_before = Pt(8)
    rd = pd.add_run(f"{meta.get('dia_danh', '……')}, ngày … tháng … năm ……"
                     if not meta.get("ngay_thang") else
                     f"{meta.get('dia_danh', '……')}, {meta.get('ngay_thang')}")
    set_run_font(rd, size=SIZE_DIADANH, italic=True)

    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build_title_block(doc, meta):
    """O so 5: Ten loai van ban (in hoa, dam) + Trich yeu (dam, khong hoa)."""
    loai = meta.get("loai_van_ban", "").strip()
    trich_yeu = meta.get("trich_yeu", "").strip()
    if loai:
        add_para(doc, loai.upper(), align=WD_ALIGN_PARAGRAPH.CENTER,
                 size=SIZE_LOAIVB, bold=True, space_after=0, space_before=6,
                 line_spacing=1.2)
    if trich_yeu:
        add_para(doc, trich_yeu, align=WD_ALIGN_PARAGRAPH.CENTER,
                 size=SIZE_TRICHYEU, bold=True, space_after=6, space_before=0,
                 line_spacing=1.2)
    # duong ke ngan duoi trich yeu (uoc le the thuc cong van/bao cao)
    if trich_yeu:
        p = doc.paragraphs[-1]
        add_horizontal_line(p, width_pt=110)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build_signature_block(doc, meta):
    """O so 7: Quyen han, chuc vu nguoi ky (phai) doi xung voi cot trai de trong
    hoac ghi TM./KT. neu co."""
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.columns[0].width = Cm(8)
    table.columns[1].width = Cm(8)
    tbl = table._tbl
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        borders.append(el)
    tbl.tblPr.append(borders)

    left_cell = table.rows[0].cells[0]
    left_cell.text = ""

    right_cell = table.rows[0].cells[1]
    right_cell.paragraphs[0].text = ""
    quyen_han = meta.get("quyen_han_ky", "")  # vd: "TM. ỦY BAN NHÂN DÂN" hoac "KT. GIÁM ĐỐC"
    chuc_vu = meta.get("chuc_vu_ky", "")
    ho_ten = meta.get("ho_ten_ky", "")

    p1 = right_cell.paragraphs[0]
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p1.paragraph_format.space_after = Pt(0)
    if quyen_han:
        r = p1.add_run(quyen_han.upper())
        set_run_font(r, size=SIZE_BODY, bold=True)
    if chuc_vu:
        p2 = right_cell.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.space_after = Pt(0)
        r2 = p2.add_run(chuc_vu.upper())
        set_run_font(r2, size=SIZE_BODY, bold=True)
    # khoang trong ky ten, dong dau
    for _ in range(3):
        blank = right_cell.add_paragraph()
        blank.paragraph_format.space_after = Pt(0)
    if ho_ten:
        p3 = right_cell.add_paragraph()
        p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r3 = p3.add_run(ho_ten)
        set_run_font(r3, size=SIZE_BODY, bold=True)


def build_noi_nhan_block(doc, meta):
    """O so 9: Noi nhan, dat ben trai, duoi chu ky, chu nghieng nho hon 1-2pt."""
    noi_nhan = meta.get("noi_nhan", [])
    if not noi_nhan:
        return
    add_para(doc, "Nơi nhận:", align=WD_ALIGN_PARAGRAPH.LEFT, size=Pt(12),
             bold=True, italic=True, space_after=0, space_before=12,
             line_spacing=1.0)
    for item in noi_nhan:
        add_para(doc, f"- {item}", align=WD_ALIGN_PARAGRAPH.LEFT, size=Pt(11),
                 italic=True, space_after=0, line_spacing=1.0)


# --------------------------------------------------------------------------
# The thuc van ban cua Dang (Huong dan so 05-HD/VPTW ngay 27/5/2026 cua
# Van phong Trung uong Dang, thay the Huong dan 36-HD/VPTW 2018)
# --------------------------------------------------------------------------

def build_header_block_dang(doc, meta):
    """O trai: cap uy/co quan Dang cap tren (neu co) + ten co quan Dang ban
    hanh + so ky hieu. O phai: 'DANG CONG SAN VIET NAM' (thay Quoc hieu-Tieu
    ngu) + dia danh, ngay thang."""
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.columns[0].width = Cm(7.5)
    table.columns[1].width = Cm(8.5)
    tbl = table._tbl
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        borders.append(el)
    tbl.tblPr.append(borders)

    cell_left = table.rows[0].cells[0]
    cell_left.paragraphs[0].text = ""
    if meta.get("co_quan_chu_quan"):
        p1 = cell_left.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p1.paragraph_format.space_after = Pt(0)
        r1 = p1.add_run(meta["co_quan_chu_quan"].upper())
        set_run_font(r1, size=SIZE_COQUAN_DANG, bold=False)
    p2 = cell_left.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(0)
    r2 = p2.add_run(meta.get("co_quan_ban_hanh", "").upper())
    set_run_font(r2, size=SIZE_COQUAN_DANG, bold=True)
    add_horizontal_line(p2, width_pt=90)
    p3 = cell_left.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.paragraph_format.space_before = Pt(6)
    r3 = p3.add_run(f"Số: {meta.get('so_ky_hieu', '…-…/…')}")
    set_run_font(r3, size=SIZE_SOKYHIEU_DANG)

    cell_right = table.rows[0].cells[1]
    cell_right.paragraphs[0].text = ""
    pq = cell_right.paragraphs[0]
    pq.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pq.paragraph_format.space_after = Pt(0)
    rq = pq.add_run("ĐẢNG CỘNG SẢN VIỆT NAM")
    set_run_font(rq, size=SIZE_DCSVN, bold=True)
    add_horizontal_line(pq, width_pt=140)
    pd = cell_right.add_paragraph()
    pd.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pd.paragraph_format.space_before = Pt(8)
    rd = pd.add_run(f"{meta.get('dia_danh', '……')}, ngày … tháng … năm ……"
                     if not meta.get("ngay_thang") else
                     f"{meta.get('dia_danh', '……')}, {meta.get('ngay_thang')}")
    set_run_font(rd, size=SIZE_DIADANH_DANG, italic=True)

    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build_title_block_dang(doc, meta):
    """Ten loai van ban (HUONG DAN/QUYET DINH/CHI THI/NGHI QUYET/KET LUAN/
    THONG BAO...) + trich yeu, co 15-16pt theo HD05-VPTW."""
    loai = meta.get("loai_van_ban", "").strip()
    trich_yeu = meta.get("trich_yeu", "").strip()
    if loai:
        add_para(doc, loai.upper(), align=WD_ALIGN_PARAGRAPH.CENTER,
                 size=SIZE_LOAIVB_DANG, bold=True, space_after=0, space_before=6,
                 line_spacing=1.2)
    if trich_yeu:
        add_para(doc, trich_yeu, align=WD_ALIGN_PARAGRAPH.CENTER,
                 size=SIZE_LOAIVB_DANG, bold=True, space_after=6, space_before=0,
                 line_spacing=1.2)
    if trich_yeu:
        add_horizontal_line(doc.paragraphs[-1], width_pt=110)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build_signature_block_dang(doc, meta):
    """Chuc vu/quyen han nguoi ky dat ben phai, cung 14pt theo HD05-VPTW."""
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.columns[0].width = Cm(8)
    table.columns[1].width = Cm(8)
    tbl = table._tbl
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        borders.append(el)
    tbl.tblPr.append(borders)

    table.rows[0].cells[0].text = ""

    right_cell = table.rows[0].cells[1]
    right_cell.paragraphs[0].text = ""
    quyen_han = meta.get("quyen_han_ky", "")  # vd: "T/M BAN CHẤP HÀNH", "T/L"
    chuc_vu = meta.get("chuc_vu_ky", "")
    ho_ten = meta.get("ho_ten_ky", "")

    p1 = right_cell.paragraphs[0]
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p1.paragraph_format.space_after = Pt(0)
    if quyen_han:
        r = p1.add_run(quyen_han.upper())
        set_run_font(r, size=SIZE_BODY_DANG, bold=True)
    if chuc_vu:
        p2 = right_cell.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.space_after = Pt(0)
        r2 = p2.add_run(chuc_vu.upper())
        set_run_font(r2, size=SIZE_BODY_DANG, bold=True)
    for _ in range(3):
        right_cell.add_paragraph().paragraph_format.space_after = Pt(0)
    if ho_ten:
        p3 = right_cell.add_paragraph()
        p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r3 = p3.add_run(ho_ten)
        set_run_font(r3, size=SIZE_BODY_DANG, bold=True)


def build_noi_nhan_block_dang(doc, meta):
    """Noi nhan, co 12-14pt theo HD05-VPTW (dung 12pt)."""
    noi_nhan = meta.get("noi_nhan", [])
    if not noi_nhan:
        return
    add_para(doc, "Nơi nhận:", align=WD_ALIGN_PARAGRAPH.LEFT, size=SIZE_NOINHAN_DANG,
             bold=True, italic=True, space_after=0, space_before=12,
             line_spacing=1.0)
    for item in noi_nhan:
        add_para(doc, f"- {item}", align=WD_ALIGN_PARAGRAPH.LEFT, size=SIZE_NOINHAN_DANG,
                 italic=True, space_after=0, line_spacing=1.0)


def build_document_dang(meta: dict, body_md: str) -> Document:
    """Dung cho van ban cua Dang theo Huong dan so 05-HD/VPTW ngay 27/5/2026
    (thay Huong dan 36-HD/VPTW 2018): khong Quoc hieu-Tieu ngu, dung 'DANG
    CONG SAN VIET NAM'; co chu 14-16pt thay vi 12-14pt cua van ban Chinh phu."""
    doc = Document()
    set_margins_nd30(doc.sections[0])  # cung kho A4, le 20/20/30/20mm nhu ND30

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = SIZE_BODY_DANG
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), FONT_NAME)

    body_md = strip_leading_boilerplate(body_md, meta)
    body_md = strip_trailing_noinhan(body_md)

    build_header_block_dang(doc, meta)
    build_title_block_dang(doc, meta)
    convert_body(doc, body_md, body_size=SIZE_BODY_DANG)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    build_signature_block_dang(doc, meta)
    build_noi_nhan_block_dang(doc, meta)
    return doc


# --------------------------------------------------------------------------
# Bo phan tich Markdown -> doan van ban co ban (khong dung thu vien nang)
# --------------------------------------------------------------------------

INLINE_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*"), {"bold": True}),
    (re.compile(r"__(.+?)__"), {"bold": True}),
    (re.compile(r"\*(.+?)\*"), {"italic": True}),
    (re.compile(r"_(.+?)_"), {"italic": True}),
]


def parse_inline(text):
    """Tra ve list (text, fmt) tach bold/italic co ban."""
    segments = [(text, {})]
    for pattern, fmt in INLINE_PATTERNS:
        new_segments = []
        for seg_text, seg_fmt in segments:
            if seg_fmt:  # da gan dinh dang roi thi khong tach tiep de tranh trung
                new_segments.append((seg_text, seg_fmt))
                continue
            pos = 0
            for m in pattern.finditer(seg_text):
                if m.start() > pos:
                    new_segments.append((seg_text[pos:m.start()], {}))
                merged_fmt = dict(seg_fmt)
                merged_fmt.update(fmt)
                new_segments.append((m.group(1), merged_fmt))
                pos = m.end()
            if pos < len(seg_text):
                new_segments.append((seg_text[pos:], seg_fmt))
        segments = new_segments
    return [s for s in segments if s[0] != ""]


def parse_markdown_table(lines, start_idx):
    """Tra ve (rows, next_idx) neu tim thay bang markdown tai start_idx."""
    rows = []
    i = start_idx
    header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
    rows.append(header)
    i += 1
    if i < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i]):
        i += 1  # bo qua dong gach ngan ---|---
    while i < len(lines) and lines[i].strip().startswith("|"):
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(row)
        i += 1
    return rows, i


def add_markdown_table(doc, rows):
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for ridx, row in enumerate(rows):
        for cidx in range(ncols):
            text = row[cidx] if cidx < len(row) else ""
            cell = table.rows[ridx].cells[cidx]
            cell.paragraphs[0].text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for seg_text, seg_fmt in parse_inline(text):
                r = p.add_run(seg_text)
                set_run_font(r, size=Pt(12), bold=seg_fmt.get("bold", ridx == 0))
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def convert_body(doc, md_text, body_size=SIZE_BODY):
    lines = md_text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped == "":
            i += 1
            continue

        # bang markdown
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            rows, i = parse_markdown_table(lines, i)
            add_markdown_table(doc, rows)
            continue

        # heading
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1:
                add_para(doc, text.upper(), align=WD_ALIGN_PARAGRAPH.CENTER,
                         size=Pt(14), bold=True, space_before=12, space_after=6,
                         line_spacing=1.3)
            elif level == 2:
                add_rich_para(doc, parse_inline(text), align=WD_ALIGN_PARAGRAPH.LEFT,
                              size=Pt(13.5), space_before=10, space_after=4)
                doc.paragraphs[-1].runs[0].bold = True
            else:
                add_rich_para(doc, parse_inline(text), align=WD_ALIGN_PARAGRAPH.LEFT,
                              size=Pt(13), space_before=8, space_after=4)
                for r in doc.paragraphs[-1].runs:
                    r.italic = True
            i += 1
            continue

        # danh sach gach dau dong
        m = re.match(r"^[-*+]\s+(.*)$", stripped)
        if m:
            text = m.group(1).strip()
            p = doc.add_paragraph(style=None)
            p.paragraph_format.left_indent = Cm(1.0)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            p.paragraph_format.line_spacing = 1.5
            bullet_run = p.add_run("- ")
            set_run_font(bullet_run, size=body_size)
            for seg_text, seg_fmt in parse_inline(text):
                r = p.add_run(seg_text)
                set_run_font(r, size=body_size, bold=seg_fmt.get("bold", False),
                             italic=seg_fmt.get("italic", False))
            i += 1
            continue

        # danh sach so thu tu
        m = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if m:
            num, text = m.group(1), m.group(2).strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(1.0)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            p.paragraph_format.line_spacing = 1.5
            r0 = p.add_run(f"{num}. ")
            set_run_font(r0, size=body_size, bold=True)
            for seg_text, seg_fmt in parse_inline(text):
                r = p.add_run(seg_text)
                set_run_font(r, size=body_size, bold=seg_fmt.get("bold", False),
                             italic=seg_fmt.get("italic", False))
            i += 1
            continue

        # doan van thuong - gop cac dong lien tiep khong rong thanh 1 doan
        para_lines = [stripped]
        j = i + 1
        while j < n and lines[j].strip() != "" and not re.match(r"^(#{1,4}\s|[-*+]\s|\d+[.)]\s|\|)", lines[j].strip()):
            para_lines.append(lines[j].strip())
            j += 1
        full_text = " ".join(para_lines)
        add_rich_para(doc, parse_inline(full_text), align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                      size=body_size, space_after=6, indent_first=1.0)
        i = j


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def split_frontmatter(md_text):
    """Frontmatter YAML chỉ khi dòng đầu đúng là '---' và có dòng '---' đóng; nội dung phải là bảng khoá-giá trị.
    (Trước đây dòng '--- Trang 1 ---' của PDF bị coi là frontmatter, làm mất cả trang 1 và gây lỗi 500.)"""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", md_text or "", re.S)
    if not m:
        return {}, md_text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, md_text
    if not isinstance(meta, dict):
        return {}, md_text
    return meta, md_text[m.end():]


def build_plain_document(body_md: str, title: str = None) -> Document:
    """Dung cho tai lieu KHONG can the thuc hanh chinh (bao cao noi bo, phieu
    lam viec, ghi chu...): chi chuyen Markdown -> Word co dinh dang (heading,
    danh sach, bang, dam/nghieng), khong Quoc hieu/Tieu ngu, khong khoi ky."""
    doc = Document()
    section = doc.sections[0]
    section.page_height = Mm(297)
    section.page_width = Mm(210)
    section.top_margin = Mm(20)
    section.bottom_margin = Mm(20)
    section.left_margin = Mm(25)
    section.right_margin = Mm(20)

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = SIZE_BODY
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), FONT_NAME)

    if title:
        add_para(doc, title.upper(), align=WD_ALIGN_PARAGRAPH.CENTER, size=Pt(15),
                 bold=True, space_after=14, line_spacing=1.3)

    convert_body(doc, body_md)
    return doc


def build_document(meta: dict, body_md: str) -> Document:
    """Dung logic chinh: nhan metadata (dict) + noi dung than bai (markdown text),
    tra ve doi tuong Document da day du the thuc ND30. Dung ham nay khi goi
    truc tiep tu code khac (vi du Flask app), khong can qua file trung gian."""
    doc = Document()
    set_margins_nd30(doc.sections[0])

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = SIZE_BODY
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), FONT_NAME)

    body_md = strip_leading_boilerplate(body_md, meta)
    body_md = strip_trailing_noinhan(body_md)

    build_header_block(doc, meta)
    build_title_block(doc, meta)
    convert_body(doc, body_md)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    build_signature_block(doc, meta)
    build_noi_nhan_block(doc, meta)
    return doc


def convert(input_path: str, output_path: str):
    """CLI / xu ly file: doc file .md (co frontmatter), ghi ra file .docx."""
    src = Path(input_path)
    text = src.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    doc = build_document(meta, body)
    doc.save(output_path)
    print(f"OK:{output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Dung: python3 md_to_docx_nd30.py <input.md> <output.docx>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
