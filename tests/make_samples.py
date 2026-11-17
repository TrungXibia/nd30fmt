"""Tạo 3 file Word mẫu CỐ Ý SAI định dạng để kiểm thử công cụ."""
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Mm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)


def para(container, text, size=None, bold=None, italic=None, align=None, font=None, color=None,
         first=None, line=None, before=None, after=None, style=None):
    p = container.add_paragraph(style=style) if style else container.add_paragraph()
    if text:
        r = p.add_run(text)
        if size: r.font.size = Pt(size)
        if bold is not None: r.font.bold = bold
        if italic is not None: r.font.italic = italic
        if font: r.font.name = font
        if color: r.font.color.rgb = RGBColor.from_string(color)
    if align is not None: p.alignment = align
    pf = p.paragraph_format
    if first is not None: pf.first_line_indent = Cm(first)
    if line is not None: pf.line_spacing = line
    if before is not None: pf.space_before = Pt(before)
    if after is not None: pf.space_after = Pt(after)
    return p


def cell_para(cell, text, first=False, **kw):
    if first:
        p = cell.paragraphs[0]
        r = p.add_run(text)
        if kw.get("size"): r.font.size = Pt(kw["size"])
        if kw.get("bold") is not None: r.font.bold = kw["bold"]
        if kw.get("italic") is not None: r.font.italic = kw["italic"]
        if kw.get("align") is not None: p.alignment = kw["align"]
        return p
    return para(cell, text, **kw)


def no_borders(table):
    tbl = table._tbl
    tblPr = tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for e in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{e}")
        el.set(qn("w:val"), "nil")
        b.append(el)
    tblPr.append(b)


def add_footer_page(section, align=AL.RIGHT):
    p = section.footer.paragraphs[0]
    p.alignment = align
    for kind, val in (("begin", None), ("instr", " PAGE "), ("separate", None), ("text", "1"), ("end", None)):
        r = p.add_run()
        if kind == "instr":
            it = OxmlElement("w:instrText"); it.text = val; r._r.append(it)
        elif kind == "text":
            r.text = val
        else:
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), kind); r._r.append(fc)


# ---------------------------------------------------------------------------
def bao_cao():
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(12)
    s = d.sections[0]
    s.page_width, s.page_height = Inches(8.5), Inches(11)          # Letter (sai)
    s.top_margin, s.bottom_margin, s.left_margin, s.right_margin = Mm(15), Mm(15), Mm(25), Mm(25)

    t = d.add_table(rows=1, cols=2); no_borders(t)
    L, R = t.rows[0].cells
    cell_para(L, "UBND TỈNH NAM ĐỊNH", first=True, size=13, bold=True, align=AL.CENTER)     # sai: đậm
    cell_para(L, "SỞ NỘI VỤ", size=13, bold=False, align=AL.CENTER)                       # sai: không đậm
    cell_para(L, "Số: 125/BC-SNV", size=13, italic=True, align=AL.CENTER)                 # sai: nghiêng
    cell_para(R, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", first=True, size=14, bold=True, align=AL.CENTER)  # sai cỡ 14
    cell_para(R, "Độc lập - Tự do - Hạnh phúc", size=14, bold=False, align=AL.CENTER)     # sai: không đậm
    cell_para(R, "Nam Định, ngày 15 tháng 9 năm 2026", size=14, italic=False, align=AL.CENTER)  # sai: không nghiêng

    para(d, "BÁO CÁO", size=16, bold=True, align=AL.CENTER)                                # sai cỡ 16
    para(d, "Kết quả thực hiện công tác cải cách hành chính 9 tháng đầu năm 2026", size=14, bold=False, align=AL.CENTER)
    para(d, "Thực hiện Công văn số 456/UBND-VP ngày 01/9/2026 của UBND tỉnh, Sở Nội vụ báo cáo kết quả như sau:",
         size=14, align=AL.LEFT, line=2.0)
    para(d, "I. KẾT QUẢ ĐẠT ĐƯỢC", size=14, bold=False)                                     # sai: không đậm
    para(d, "1. Công tác chỉ đạo, điều hành", size=14, bold=False)
    para(d, "Trong 9 tháng đầu năm, Sở đã ban hành 12 văn bản chỉ đạo, hướng dẫn các đơn vị triển khai nhiệm vụ "
            "cải cách hành chính; tổ chức 03 đợt kiểm tra tại các huyện, thành phố.", size=12, align=AL.LEFT, line=2.0,
         before=0, after=0)
    para(d, "1. Sở đã tham mưu UBND tỉnh ban hành Kế hoạch cải cách hành chính năm 2026 và tổ chức triển khai "
            "đến 100% cơ quan, đơn vị trực thuộc.", size=14, align=AL.JUSTIFY, first=1.27, line=1.2, before=6)
    para(d, "a) Về tổ chức bộ máy", size=14, italic=False)
    para(d, "- Đã rà soát, sắp xếp 05 đơn vị sự nghiệp công lập theo đúng lộ trình.", size=14, first=1.27,
         align=AL.JUSTIFY, before=6, line=1.2, font="Calibri", color="1F4E79")          # sai phông + màu
    para(d, "2. Cải cách thủ tục hành chính", size=14, bold=True, first=1.27, before=6)
    para(d, "Tỷ lệ hồ sơ giải quyết đúng hạn đạt 98,7%, tăng 1,2 điểm phần trăm so với cùng kỳ.", size=14,
         align=AL.JUSTIFY, first=1.27, before=6, line=1.2)
    para(d, "II. PHƯƠNG HƯỚNG, NHIỆM VỤ QUÝ IV NĂM 2026", size=14, bold=True, first=1.27, before=6)
    para(d, "Tiếp tục đẩy mạnh chuyển đổi số trong giải quyết thủ tục hành chính, phấn đấu 100% hồ sơ được "
            "số hóa theo quy định.", size=14, align=AL.JUSTIFY, first=0.5, before=6, line=1.2)   # sai lùi dòng

    t2 = d.add_table(rows=1, cols=2); no_borders(t2)
    L, R = t2.rows[0].cells
    cell_para(L, "Nơi nhận:", first=True, size=13, bold=True, italic=False)                # sai
    cell_para(L, "- UBND tỉnh (để b/c);", size=13)                                          # sai cỡ
    cell_para(L, "- Lưu: VT, VP.", size=11)
    cell_para(R, "KT. GIÁM ĐỐC", first=True, size=14, bold=False, align=AL.CENTER)         # sai không đậm
    cell_para(R, "PHÓ GIÁM ĐỐC", size=14, bold=True, align=AL.CENTER)
    cell_para(R, "", size=14)
    cell_para(R, "Nguyễn Văn An", size=14, bold=False, align=AL.CENTER)                    # sai không đậm
    add_footer_page(s)                                                                      # sai: số trang ở chân trang
    d.save(OUT / "bao_cao_sai.docx")


# ---------------------------------------------------------------------------
def quyet_dinh():
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(14)
    s = d.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.top_margin, s.bottom_margin, s.left_margin, s.right_margin = Mm(20), Mm(20), Mm(30), Mm(15)
    t = d.add_table(rows=1, cols=2); no_borders(t)
    L, R = t.rows[0].cells
    cell_para(L, "UBND TỈNH NAM ĐỊNH", first=True, size=13, align=AL.CENTER)
    cell_para(L, "SỞ NỘI VỤ", size=13, bold=True, align=AL.CENTER)
    cell_para(L, "Số: 78/QĐ-SNV", size=13, align=AL.CENTER)
    cell_para(R, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", first=True, size=13, bold=True, align=AL.CENTER)
    cell_para(R, "Độc lập - Tự do - Hạnh phúc", size=14, bold=True, align=AL.CENTER)
    cell_para(R, "Nam Định, ngày 10 tháng 9 năm 2026", size=14, italic=True, align=AL.CENTER)
    para(d, "QUYẾT ĐỊNH", size=14, bold=True, align=AL.CENTER)
    para(d, "Ban hành Quy chế làm việc của Sở Nội vụ tỉnh Nam Định", size=14, bold=True, align=AL.CENTER)
    para(d, "GIÁM ĐỐC SỞ NỘI VỤ TỈNH NAM ĐỊNH", size=14, bold=True, align=AL.CENTER)
    para(d, "Căn cứ Luật Tổ chức chính quyền địa phương ngày 19 tháng 02 năm 2025;", size=14, italic=False,
         align=AL.JUSTIFY, first=1.27, before=6)                                              # sai: không nghiêng
    para(d, "Căn cứ Quyết định số 12/2025/QĐ-UBND ngày 15 tháng 3 năm 2025 của UBND tỉnh quy định chức năng, "
            "nhiệm vụ, quyền hạn và cơ cấu tổ chức của Sở Nội vụ;", size=14, italic=True, align=AL.JUSTIFY, first=1.27, before=6)
    para(d, "Theo đề nghị của Chánh Văn phòng Sở.", size=14, italic=True, align=AL.JUSTIFY, first=1.27, before=6)
    para(d, "QUYẾT ĐỊNH:", size=14, bold=True, align=AL.CENTER)
    p = para(d, "", align=AL.JUSTIFY, first=1.27, before=6)
    r = p.add_run("Điều 1. "); r.font.size = Pt(14); r.font.bold = False                    # sai: không đậm
    r = p.add_run("Ban hành kèm theo Quyết định này Quy chế làm việc của Sở Nội vụ tỉnh Nam Định."); r.font.size = Pt(14)
    p = para(d, "", align=AL.JUSTIFY, first=1.27, before=6)
    r = p.add_run("Điều 2. "); r.font.size = Pt(14); r.font.bold = True
    r = p.add_run("Quyết định này có hiệu lực kể từ ngày ký."); r.font.size = Pt(14)
    p = para(d, "", align=AL.LEFT, first=0, before=6)                                        # sai căn lề, lùi dòng
    r = p.add_run("Điều 3. "); r.font.size = Pt(14); r.font.bold = True
    r = p.add_run("Chánh Văn phòng, Trưởng các phòng thuộc Sở và các cá nhân có liên quan chịu trách nhiệm thi hành "
                  "Quyết định này."); r.font.size = Pt(14)
    t2 = d.add_table(rows=1, cols=2); no_borders(t2)
    L, R = t2.rows[0].cells
    cell_para(L, "Nơi nhận:", first=True, size=12, bold=True, italic=True)
    cell_para(L, "- Như Điều 3;", size=11)
    cell_para(L, "- Lưu: VT, VP.", size=11)
    cell_para(R, "GIÁM ĐỐC", first=True, size=14, bold=True, align=AL.CENTER)
    cell_para(R, "", size=14)
    cell_para(R, "Trần Thị Bình", size=14, bold=True, align=AL.CENTER)

    # Phụ lục: Quy chế
    d.add_page_break()
    para(d, "QUY CHẾ", size=14, bold=True, align=AL.CENTER)
    para(d, "Làm việc của Sở Nội vụ tỉnh Nam Định", size=14, bold=True, align=AL.CENTER)
    para(d, "CHƯƠNG I", size=14, bold=True, align=AL.CENTER)                                  # sai: in hoa
    para(d, "Quy định chung", size=14, bold=True, align=AL.CENTER)                            # sai: không in hoa
    para(d, "Điều 1. Phạm vi điều chỉnh", size=14, bold=True, align=AL.JUSTIFY, first=1.27, before=6)
    para(d, "1. Quy chế này quy định về nguyên tắc, chế độ trách nhiệm, lề lối làm việc, quan hệ công tác của "
            "Sở Nội vụ.", size=14, align=AL.JUSTIFY, first=1.27, before=6, line=1.2)
    para(d, "2. Công chức, viên chức và người lao động thuộc Sở chịu sự điều chỉnh của Quy chế này.",
         size=13, align=AL.JUSTIFY, first=1.27, before=6, line=1.7)                             # sai giãn dòng
    s.different_first_page_header_footer = False
    hp = s.header.paragraphs[0]; hp.alignment = AL.CENTER
    for kind, val in (("begin", None), ("instr", " PAGE "), ("separate", None), ("text", "1"), ("end", None)):
        r = hp.add_run(); r.font.size = Pt(14)
        if kind == "instr":
            it = OxmlElement("w:instrText"); it.text = val; r._r.append(it)
        elif kind == "text":
            r.text = val
        else:
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), kind); r._r.append(fc)
    d.save(OUT / "quyet_dinh_sai.docx")


# ---------------------------------------------------------------------------
def chuyen_de():
    d = Document()   # template mặc định: Normal = phông theme (Calibri), Heading = Calibri Light xanh
    s = d.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.top_margin, s.bottom_margin, s.left_margin, s.right_margin = Mm(25), Mm(25), Mm(35), Mm(20)
    d.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
    para(d, "CHUYÊN ĐỀ", size=14, bold=True, align=AL.CENTER)
    para(d, "Thực trạng và giải pháp nâng cao chất lượng đội ngũ công chức cấp xã", size=14, bold=True, align=AL.CENTER)
    para(d, "MỤC LỤC", size=14, bold=True, align=AL.CENTER)
    para(d, "MỞ ĐẦU\t1", style="toc 1")
    para(d, "Chương 1. Cơ sở lý luận\t3", style="toc 1")
    d.add_heading("MỞ ĐẦU", level=1)
    d.add_heading("1. Tính cấp thiết của đề tài", level=2)
    para(d, "Đội ngũ công chức cấp xã có vai trò quan trọng trong việc triển khai chủ trương, chính sách tại cơ sở. "
            "Tuy nhiên, chất lượng đội ngũ còn chưa đồng đều giữa các địa phương.", align=AL.JUSTIFY)
    d.add_heading("1.1. Bối cảnh chung", level=3)
    para(d, "Nội dung bối cảnh được trình bày với cỡ chữ mặc định của mẫu, chưa đúng quy chuẩn.")
    para(d, "Mục tiêu nghiên cứu", size=14)
    para(d, "Đánh giá thực trạng và đề xuất giải pháp khả thi, phù hợp điều kiện của tỉnh.", size=14)
    para(d, "Bảng 1.1. Số lượng công chức cấp xã giai đoạn 2022–2025", size=12, italic=True)   # sai
    tb = d.add_table(rows=3, cols=3); tb.style = "Table Grid"
    for i, row in enumerate([("Năm", "Số lượng", "Tỷ lệ đạt chuẩn"), ("2022", "1.245", "91,2%"), ("2025", "1.198", "97,5%")]):
        for j, v in enumerate(row):
            tb.cell(i, j).paragraphs[0].add_run(v).font.size = Pt(10)                       # sai cỡ
    para(d, "Nguồn: Sở Nội vụ tỉnh (2025)", size=12, italic=False)
    para(d, "Hình 1.1. Cơ cấu trình độ chuyên môn của công chức cấp xã năm 2025", size=13, bold=True, align=AL.CENTER)
    para(d, "Số liệu tại Bảng 1.1 cho thấy tỷ lệ đạt chuẩn tăng 6,3 điểm phần trăm trong giai đoạn 2022–2025, "
            "phản ánh hiệu quả của công tác đào tạo, bồi dưỡng.", size=14, align=AL.JUSTIFY, first=1.27, before=6, line=1.3)
    d.add_paragraph("Hoàn thiện khung năng lực vị trí việc làm cho từng chức danh công chức cấp xã.", style="List Number")
    d.add_paragraph("Đổi mới nội dung, phương pháp bồi dưỡng theo hướng thực hành.", style="List Number")
    d.add_heading("KẾT LUẬN", level=1)
    para(d, "Chuyên đề đã hệ thống hóa cơ sở lý luận, đánh giá thực trạng và đề xuất 05 nhóm giải pháp.",
         size=14, align=AL.JUSTIFY, first=1.27, before=6, line=1.3)
    # section ngang chứa bảng lớn
    ns = d.add_section()
    ns.orientation = WD_ORIENT.LANDSCAPE
    ns.page_width, ns.page_height = Mm(297), Mm(210)
    para(d, "PHỤ LỤC", size=14, bold=True, align=AL.CENTER)
    tb2 = d.add_table(rows=2, cols=4); tb2.style = "Table Grid"
    for j, v in enumerate(["Huyện", "2022", "2023", "2025"]):
        tb2.cell(0, j).paragraphs[0].add_run(v)
    d.save(OUT / "chuyen_de_dai.docx")


# ---------------------------------------------------------------------------
def dang_quyet_dinh():
    """Quyết định của Đảng uỷ, cố ý sai định dạng theo Hướng dẫn 05-HD/VPTW."""
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(14)
    s = d.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.top_margin, s.bottom_margin, s.left_margin, s.right_margin = Mm(20), Mm(20), Mm(30), Mm(15)

    t = d.add_table(rows=1, cols=2); no_borders(t)
    L, R = t.rows[0].cells
    cell_para(L, "ĐẢNG BỘ TỈNH LÂM ĐỒNG", first=True, size=14, bold=True, align=AL.CENTER)   # sai: đậm
    cell_para(L, "ĐẢNG UỶ ĐẶC KHU PHÚ QUÝ", size=13, bold=True, align=AL.CENTER)              # sai cỡ 13
    cell_para(L, "*", size=14, align=AL.CENTER)
    cell_para(L, "Số 127-QĐ/TW", size=14, italic=True, align=AL.CENTER)                       # sai: nghiêng
    cell_para(R, "ĐẢNG CỘNG SẢN VIỆT NAM", first=True, size=14, bold=True, align=AL.RIGHT)    # sai cỡ 14
    cell_para(R, "Phú Quý, ngày 20 tháng 10 năm 2025", size=14, italic=False, align=AL.RIGHT)  # sai: không nghiêng

    para(d, "QUYẾT ĐỊNH", size=14, bold=True, align=AL.CENTER)                                # sai cỡ 14 (cần 15-16)
    para(d, "Về việc ban hành Quy chế làm việc của Đảng uỷ Đặc khu Phú Quý", size=15, bold=False, align=AL.CENTER)  # sai: không đậm
    para(d, "- Căn cứ Điều lệ Đảng Cộng sản Việt Nam;", size=14, italic=True, align=AL.JUSTIFY, first=1.0, before=6)  # sai: nghiêng
    para(d, "- Theo đề nghị của Văn phòng Đảng uỷ.", size=14, align=AL.JUSTIFY, first=1.0, before=6)
    para(d, "QUYẾT ĐỊNH:", size=14, bold=True, align=AL.CENTER)
    p = para(d, "", align=AL.JUSTIFY, first=1.0, before=6)
    r = p.add_run("Điều 1. "); r.font.size = Pt(14); r.font.bold = False                      # sai: không đậm
    r = p.add_run("Ban hành kèm theo Quyết định này Quy chế làm việc của Đảng uỷ Đặc khu Phú Quý."); r.font.size = Pt(14)
    para(d, "1. Quy chế gồm 3 chương, 10 điều.", size=14, align=AL.JUSTIFY, first=0.5, before=6)  # sai lùi dòng
    para(d, "a) Chương I quy định chung.", size=14, align=AL.JUSTIFY, first=1.0, before=6)
    p2 = para(d, "", align=AL.JUSTIFY, first=1.0, before=6)
    r = p2.add_run("Điều 2. "); r.font.size = Pt(14); r.font.bold = True
    r = p2.add_run("Quyết định này có hiệu lực kể từ ngày ký."); r.font.size = Pt(14)

    t2 = d.add_table(rows=1, cols=2); no_borders(t2)
    L, R = t2.rows[0].cells
    cell_para(L, "Nơi nhận:", first=True, size=14, bold=True)                                 # sai: đậm
    cell_para(L, "- Như Điều 2;", size=14)                                                    # sai cỡ (cần 12)
    cell_para(L, "- Lưu Văn phòng Đảng uỷ.", size=12)
    cell_para(R, "T/M ĐẢNG UỶ", first=True, size=14, bold=False, align=AL.RIGHT)              # sai: không đậm
    cell_para(R, "BÍ THƯ", size=14, bold=True, align=AL.RIGHT)                                # sai: đậm
    cell_para(R, "", size=14)
    cell_para(R, "Nguyễn Văn A", size=14, bold=True, align=AL.RIGHT)
    d.save(OUT / "dang_quyet_dinh_sai.docx")


def dean_de_an():
    """Đề án thạc sĩ, cố ý sai định dạng theo Phụ lục 4.1 (lề, cỡ chữ, giãn dòng, đề mục, tên bảng/hình...)."""
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(14)
    s = d.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.top_margin, s.bottom_margin, s.left_margin, s.right_margin = Mm(20), Mm(20), Mm(30), Mm(15)  # sai lề
    # bìa
    para(d, "BỘ GIÁO DỤC VÀ ĐÀO TẠO", size=14, bold=True, align=AL.CENTER)
    para(d, "TRƯỜNG ĐẠI HỌC QUY NHƠN", size=14, bold=True, align=AL.CENTER)
    para(d, "NGUYỄN VĂN A", size=14, bold=True, align=AL.CENTER)
    para(d, "NÂNG CAO CHẤT LƯỢNG ĐỘI NGŨ CÔNG CHỨC CẤP XÃ", size=16, bold=True, align=AL.CENTER)
    para(d, "Gia Lai - Năm 2026", size=14, align=AL.CENTER)
    # mục lục
    para(d, "MỤC LỤC", size=14, bold=True, align=AL.CENTER)
    para(d, "Chương 1. Cơ sở lý luận\t5", size=14)
    para(d, "Bảng 1.1. Số lượng công chức\t12", size=14)          # không được nhận nhầm là tên bảng
    para(d, "DANH MỤC CÁC BẢNG", size=14, bold=True, align=AL.CENTER)
    para(d, "Bảng 1.1. Số lượng công chức\t12", size=14)
    # mở đầu
    para(d, "MỞ ĐẦU", size=14, bold=True, align=AL.CENTER)
    para(d, "1. Tính cấp thiết của đề tài", size=14, bold=True, before=6, line=1.5)
    para(d, "Đội ngũ công chức cấp xã có vai trò quan trọng trong việc triển khai chủ trương, chính sách ở cơ sở.",
         size=12, align=AL.JUSTIFY, before=0, line=1.0)                                          # sai cỡ, cách đoạn, giãn dòng
    # chương
    para(d, "CHƯƠNG 1. CƠ SỞ LÝ LUẬN VỀ CÔNG CHỨC CẤP XÃ", size=14, bold=True, align=AL.CENTER, line=1.0)  # sai cỡ, căn, giãn
    para(d, "1.1. Giới thiệu tổng quan", size=13, bold=True, italic=True, before=6, line=1.5)      # sai: nghiêng
    p = para(d, "Nội dung giới thiệu tổng quan với mật độ chữ bị nén để vừa dòng.", size=13, before=6, line=1.3)
    rpr = p.runs[0]._r.get_or_add_rPr(); sp = OxmlElement("w:spacing"); sp.set(qn("w:val"), "-10")
    rpr.insert_element_before(sp, "w:w", "w:kern", "w:position", "w:sz", "w:szCs")                # sai: nén chữ
    para(d, "1.1.1. Một số khái niệm", size=13, bold=True, italic=False, before=6, line=1.5)       # sai: không nghiêng
    para(d, "1.1.1.1. Tổng trực tiếp", size=13, bold=True, italic=True, before=6, line=1.5)       # sai: đậm
    para(d, "1.1.1.2. Tổng gián tiếp", size=13, italic=True, before=6, line=1.5)
    para(d, "1.1.2. Vai trò", size=13, bold=True, italic=True, before=6, line=1.5)
    para(d, "1.2. Đặc điểm", size=13, bold=True, before=6, line=1.5)
    para(d, "Bảng 1.1. Số lượng công chức giai đoạn 2022-2025", size=13, bold=False, align=AL.LEFT, line=1.0)  # sai nhiều
    t = d.add_table(rows=2, cols=2); t.style = "Table Grid"
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Năm", "Số lượng", "2025", "1.198"
    para(d, "Nguồn: Sở Nội vụ (2025)", size=12, italic=True)
    para(d, "Hình 1.1. Sơ đồ tổ chức", size=12, bold=True, align=AL.CENTER, line=1.5)             # sai: không có hình ở trên
    para(d, "KẾT LUẬN VÀ KIẾN NGHỊ", size=14, bold=True, align=AL.CENTER)
    para(d, "Đề án đã hệ thống hoá cơ sở lý luận về công chức cấp xã.", size=13, before=6, line=1.5)
    para(d, "DANH MỤC TÀI LIỆU THAM KHẢO", size=14, bold=True, align=AL.CENTER)
    para(d, "1. Lê Nguyên Cẩn. Cái kỳ ảo trong tác phẩm Balzac, Nxb Giáo dục, Hà Nội, 1999.", size=12, before=6, line=1.5)  # sai cỡ
    d.save(OUT / "dean_sai.docx")


if __name__ == "__main__":
    bao_cao(); quyet_dinh(); chuyen_de(); dang_quyet_dinh(); dean_de_an()
    print("Đã tạo:", *sorted(p.name for p in OUT.glob("*.docx")))
