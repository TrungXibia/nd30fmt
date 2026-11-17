"""Nhận diện bản Word và tách ý gạch sát dấu hai chấm."""
import io

from docx import Document

from nd30fmt.import_draft import parse_draft_bytes


def test_import_quyet_dinh_and_first_bullet_after_colon():
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "BỘ X\nVIỆN NGHIÊN CỨU\nSố: 01/QĐ-VNCY"
    table.cell(0, 1).text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nHà Nội, ngày 26 tháng 9 năm 2026"
    doc.add_paragraph("QUYẾT ĐỊNH")
    doc.add_paragraph("Điều 1. Tổ chức lớp, cụ thể như sau:- Thời gian: ngày 25/9/2026")
    doc.add_paragraph("- Địa điểm: Hà Nội")
    doc.add_paragraph("Điều 2. Giao phòng Kế hoạch – Tổng hợp.")
    doc.add_paragraph("Nơi nhận:")
    data = io.BytesIO()
    doc.save(data)

    out = parse_draft_bytes(data.getvalue())
    assert out["detected"] == {"form": "ADMINISTRATIVE", "doc_type": "QUYET_DINH", "contract_type": None}
    assert out["fields"]["cqChuQuan"] == "BỘ X"
    assert out["fields"]["cqBanHanh"] == "VIỆN NGHIÊN CỨU"
    assert out["fields"]["maDonVi"] == "VNCY"
    assert out["fields"]["ngayBanHanh"] == "2026-09-26"
    # "Điều n." thành khối Điều (trình soạn thảo tự đánh số) -> bỏ tiền tố số khỏi nội dung
    assert [block["type"] for block in out["blocks"]] == ["dieu", "bullet", "bullet", "dieu"]
    assert out["blocks"][0]["html"] == "Tổ chức lớp, cụ thể như sau:"
    assert out["blocks"][3]["html"] == "Giao phòng Kế hoạch – Tổng hợp."
    assert out["blocks"][1]["html"].startswith("Thời gian:")


def test_import_keeps_headings_kinh_gui_and_subject():
    doc = Document()
    for text, bold in [("BỘ X", 0), ("Số: 12/CV-VNCY", 0), ("V/v góp ý dự thảo", 0), ("Kính gửi:", 0),
                       ("- Vụ Kế hoạch;", 0), ("- Vụ Pháp chế.", 0), ("I. MỤC ĐÍCH", 1), ("1. Về chuyên môn", 1),
                       ("1.1. Nội dung chi tiết", 1), ("Căn cứ Luật Tổ chức;", 0), ("Nơi nhận:", 0)]:
        doc.add_paragraph().add_run(text).bold = bool(bold)
    data = io.BytesIO()
    doc.save(data)
    out = parse_draft_bytes(data.getvalue())
    assert out["fields"]["trichYeu"] == "góp ý dự thảo"
    assert out["fields"]["kinhGui"] == "Vụ Kế hoạch;\nVụ Pháp chế."
    assert [(b["type"], b["html"]) for b in out["blocks"]] == [
        ("h1", "<strong>MỤC ĐÍCH</strong>"), ("h2", "<strong>Về chuyên môn</strong>"),
        ("h3", "<strong>Nội dung chi tiết</strong>"), ("cancu", "Căn cứ Luật Tổ chức;")]


def test_import_party_heading_switches_form():
    doc = Document()
    doc.add_paragraph("ĐẢNG CỘNG SẢN VIỆT NAM")
    doc.add_paragraph("THÔNG BÁO")
    doc.add_paragraph("Điều 1. Nội dung")
    data = io.BytesIO()
    doc.save(data)
    out = parse_draft_bytes(data.getvalue())
    assert out["fields"]["hinhThuc"] == "PARTY"
    assert out["fields"]["loaiVanBan"] == "THONG_BAO"
