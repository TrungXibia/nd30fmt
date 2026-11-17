"""Nhận diện đúng đề mục khi dựng mục lục: loại đoạn nội dung mang cấp đề mục; xoá đúng khối mục lục cũ gõ tay."""
from docx import Document

from nd30fmt.extract import extract
from nd30fmt.toc import build_toc, toc_candidates


def _in_toc(path):
    return [p.text for p in extract(str(path)).paragraphs if p.heading_level and p.heading_level <= 3]


def _doc_with_noise(tmp_path):
    d = Document()
    H = d.add_heading
    H("CHƯƠNG 1. TỔNG QUAN", 1)
    H("1.1. Bối cảnh nghiên cứu", 2)
    for t in ["Các nội dung chính gồm:", "a) Về quy mô thị trường", "1) Điểm thứ nhất", "Kính gửi: Bộ X",
              "Hình 1. Biểu đồ GDP giai đoạn 2015-2020", "Bảng 2.1. Cơ cấu xuất khẩu", "Nguồn: Tổng cục Thống kê",
              "Ghi chú: số liệu ước tính", "Nơi nhận:", "- Gạch đầu dòng nhầm cấp", "Nội dung liệt kê kết thúc bằng chấm phẩy;",
              "5", "***", "",
              "Việt Nam tiếp tục duy trì tăng trưởng ổn định trong bối cảnh kinh tế toàn cầu nhiều biến động và rủi ro gia tăng"]:
        H(t, 3)
    H("Viện trưởng", 3)
    H("Nguyễn Văn An", 3)
    H("1.2. Mục tiêu đến năm 2030", 2)
    tbl = d.add_table(rows=1, cols=1)
    tbl.cell(0, 0).paragraphs[0].text = "Tiêu đề trong ô bảng"
    tbl.cell(0, 0).paragraphs[0].style = d.styles["Heading 2"]
    H("CHƯƠNG 2. THỰC TRẠNG", 1)
    H("2.1.1. Xuất khẩu hàng hoá", 3)
    p = tmp_path / "noise.docx"
    d.save(p)
    return p


def test_content_lines_do_not_enter_toc(tmp_path):
    src = _doc_with_noise(tmp_path)
    out = tmp_path / "o.docx"
    st = build_toc(str(src), str(out), {"toc": True, "hinh": False, "bang": False})["toc"]
    assert _in_toc(out) == ["CHƯƠNG 1. TỔNG QUAN", "1.1. Bối cảnh nghiên cứu", "1.2. Mục tiêu đến năm 2030",
                            "CHƯƠNG 2. THỰC TRẠNG", "2.1.1. Xuất khẩu hàng hoá"]
    assert len(st["gate_removed"]) >= 17
    # chữ hiển thị không đổi, chỉ gỡ cấp đề mục
    assert "Các nội dung chính gồm:" in [p.text for p in extract(str(out)).paragraphs]


def test_candidates_list_reasons(tmp_path):
    cs = toc_candidates(str(_doc_with_noise(tmp_path)))
    by = {c["text"]: c for c in cs}
    assert by["1.1. Bối cảnh nghiên cứu"]["reason"] == ""
    assert "hai chấm" in by["Các nội dung chính gồm:"]["reason"]
    assert "chú thích" in by["Hình 1. Biểu đồ GDP giai đoạn 2015-2020"]["reason"]
    assert "chú thích" in by["Bảng 2.1. Cơ cấu xuất khẩu"]["reason"]
    assert "Nguồn" in by["Nguồn: Tổng cục Thống kê"]["reason"]
    assert "điểm liệt kê" in by["a) Về quy mô thị trường"]["reason"]
    assert "ô bảng" in by["Tiêu đề trong ô bảng"]["reason"]
    assert "chức danh" in by["Viện trưởng"]["reason"] and "người ký" in by["Nguyễn Văn An"]["reason"]
    assert "quá dài" in next(c["reason"] for c in cs if c["text"].startswith("Việt Nam tiếp tục"))
    assert all(c["text"] for c in cs)                     # dòng trống/ký hiệu không hiện trong danh sách


def test_user_include_exclude_overrides(tmp_path):
    src = _doc_with_noise(tmp_path)
    cs = {c["text"]: c["key"] for c in toc_candidates(str(src))}
    out = tmp_path / "o.docx"
    build_toc(str(src), str(out), {"toc": True, "hinh": False, "bang": False},
              exclude=[cs["1.2. Mục tiêu đến năm 2030"]], include=[cs["a) Về quy mô thị trường"], cs["Viện trưởng"]])
    got = _in_toc(out)
    assert "a) Về quy mô thị trường" in got and "Viện trưởng" in got
    assert "1.2. Mục tiêu đến năm 2030" not in got and "1.1. Bối cảnh nghiên cứu" in got
    assert "Các nội dung chính gồm:" not in got           # lý do mềm nhưng không được tích giữ -> vẫn loại


def test_duplicate_heading_text_keys_are_distinct(tmp_path):
    d = Document()
    d.add_heading("Kết luận", 2)
    d.add_heading("Kết luận", 2)
    p = tmp_path / "dup.docx"
    d.save(p)
    keys = [c["key"] for c in toc_candidates(str(p))]
    assert len(set(keys)) == 2
    out = tmp_path / "o.docx"
    build_toc(str(p), str(out), {"toc": True, "hinh": False, "bang": False}, exclude=[keys[1]])
    assert _in_toc(out) == ["Kết luận"]


def test_old_typed_toc_without_page_numbers_is_replaced(tmp_path):
    d = Document()
    d.add_paragraph("Mục lục")
    for t in ["Chương 1. Tổng quan", "1.1. Bối cảnh", "1.2. Mục tiêu", "Chương 2. Thực trạng"]:
        d.add_paragraph(t)
    d.add_paragraph("Danh mục hình")
    d.add_paragraph("Hình 1. Biểu đồ GDP")
    d.add_paragraph("Hình 2. Cơ cấu xuất khẩu")
    d.add_page_break()
    d.add_heading("Chương 1. Tổng quan", 1)
    d.add_heading("1.1. Bối cảnh", 2)
    d.add_paragraph("Hình 1. Biểu đồ GDP")
    d.add_paragraph("Hình 2. Cơ cấu xuất khẩu")
    d.add_heading("1.2. Mục tiêu", 2)
    d.add_heading("Chương 2. Thực trạng", 1)
    p = tmp_path / "typed.docx"
    d.save(p)
    out = tmp_path / "o.docx"
    st = build_toc(str(p), str(out), {"toc": True, "hinh": True, "bang": False})["toc"]
    assert st["removed_old"]["toc"] == 4 and st["removed_old"]["hinh"] == 2
    texts = [q.text for q in extract(str(out)).paragraphs]
    assert texts.count("Chương 1. Tổng quan") == 1 and texts.count("1.2. Mục tiêu") == 1
    assert texts.count("Hình 1. Biểu đồ GDP") == 1                 # chú thích thật, không đếm cả dòng danh mục cũ


def test_plain_paragraphs_after_toc_title_are_kept(tmp_path):
    """Đoạn văn bình thường đứng sau tiêu đề 'Mục lục' (không khớp đề mục nào phía sau) không bị xoá nhầm."""
    d = Document()
    d.add_paragraph("MỤC LỤC")
    d.add_paragraph("Phần này trình bày lời giới thiệu của báo cáo.")
    d.add_paragraph("Đây là đoạn ghi chú khác của tác giả.")
    d.add_heading("1. Mở đầu", 1)
    p = tmp_path / "keep.docx"
    d.save(p)
    out = tmp_path / "o.docx"
    st = build_toc(str(p), str(out), {"toc": True, "hinh": False, "bang": False})["toc"]
    assert st["removed_old"]["toc"] == 0
    texts = [q.text for q in extract(str(out)).paragraphs]
    assert "Phần này trình bày lời giới thiệu của báo cáo." in texts and "Đoạn" not in texts


def test_toc_title_inside_textbox_not_used(tmp_path):
    from docx.oxml import parse_xml
    d = Document()
    d.add_heading("1. Mở đầu", 1)
    p = d.add_paragraph()
    p._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:pict><w:txbxContent>'
        '<w:p><w:r><w:t>MỤC LỤC</w:t></w:r></w:p></w:txbxContent></w:pict></w:r>'))
    f = tmp_path / "tb.docx"
    d.save(f)
    out = tmp_path / "o.docx"
    st = build_toc(str(f), str(out), {"toc": True, "hinh": False, "bang": False}, create=True)["toc"]
    assert st["created"]["toc"] is True               # không coi chữ trong khung văn bản là tiêu đề có sẵn


def test_decimal_depth_gives_toc_hierarchy(tmp_path):
    """'1.1.' và '1.1.1.' cùng mang cấp 3 (cách bộ nhận vai trò xếp) -> mục lục vẫn phải phân tầng, không mất dòng."""
    d = Document()
    d.add_heading("CHƯƠNG 1. TỔNG QUAN", 1)
    d.add_heading("1.1. Bối cảnh", 3)
    d.add_heading("1.1.1. Trong nước", 3)
    d.add_heading("1.1.2. Quốc tế", 3)
    d.add_heading("1.2. Mục tiêu", 3)
    d.add_heading("KẾT LUẬN", 1)
    p = tmp_path / "lv.docx"
    d.save(p)
    assert [c["level"] for c in toc_candidates(str(p))] == [1, 2, 3, 3, 2, 1]
    out = tmp_path / "o.docx"
    st = build_toc(str(p), str(out), {"toc": True, "hinh": False, "bang": False})["toc"]
    assert st["releveled"] == 2
    got = [(q.heading_level, q.text) for q in extract(str(out)).paragraphs if q.heading_level]
    assert got == [(1, "CHƯƠNG 1. TỔNG QUAN"), (2, "1.1. Bối cảnh"), (3, "1.1.1. Trong nước"), (3, "1.1.2. Quốc tế"),
                   (2, "1.2. Mục tiêu"), (1, "KẾT LUẬN")]


def test_levels_untouched_when_already_consistent(tmp_path):
    d = Document()
    d.add_heading("CHƯƠNG 1. TỔNG QUAN", 1)
    d.add_heading("1.1. Bối cảnh", 2)
    d.add_heading("1.1.1. Trong nước", 3)
    p = tmp_path / "ok.docx"
    d.save(p)
    out = tmp_path / "o.docx"
    assert build_toc(str(p), str(out), {"toc": True, "hinh": False, "bang": False})["toc"]["releveled"] == 0
