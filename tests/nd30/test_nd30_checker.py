"""Kiểm thử: python -m pytest -q tests/"""
from pathlib import Path

import pytest

from nd30fmt.pipeline import process
from nd30fmt.spec import load_spec

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
NAMES = ["bao_cao_sai", "quyet_dinh_sai", "chuyen_de_dai"]


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not all((SAMPLES / f"{n}.docx").exists() for n in NAMES):
        import runpy
        runpy.run_path(str(ROOT / "tests" / "make_samples.py"), run_name="__main__")


def _roles(r):
    return {d["pid"]: d["role"] for d in r["roles"]}


@pytest.mark.parametrize("name", NAMES)
def test_offline_fix(tmp_path, name):
    spec = load_spec()
    r = process(str(SAMPLES / f"{name}.docx"), spec, str(tmp_path))
    assert r["summary"]["total"] > 0
    # sau khi sửa chỉ còn lỗi ở đoạn có vai trò chưa chắc chắn (không tự sửa)
    low = {d["pid"] for d in r["roles"] if d["confidence"] < 0.5}
    assert all(v["target"] in low for v in r["violations_after"]), r["violations_after"]


def test_detect_standard_hint():
    """Gợi ý chuẩn thể thức: đoán được văn bản Đảng (bắt đầu bằng 'ĐẢNG CỘNG SẢN VIỆT NAM') và văn
    bản hành chính (bắt đầu bằng quốc hiệu NĐ 30), chỉ dựa vào các đoạn đầu văn bản."""
    from nd30fmt.extract import extract
    from nd30fmt.roles import detect_standard_hint
    ex_dang = extract(str(SAMPLES / "dang_quyet_dinh_sai.docx"))
    hint = detect_standard_hint(ex_dang)
    assert hint["suggested"] == "dang", hint

    ex_admin = extract(str(SAMPLES / "bao_cao_sai.docx"))
    hint2 = detect_standard_hint(ex_admin)
    assert hint2["suggested"] == "nd30", hint2


def test_standard_mismatch_warns_via_job(tmp_path, monkeypatch):
    """Tải văn bản Đảng lên nhưng chọn chuẩn NĐ 30 (và ngược lại) -> job phải báo standard_hint.mismatch."""
    import importlib
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import nd30fmt.jobs as jobs
    importlib.reload(jobs)
    jid = jobs.create_job("dang_quyet_dinh_sai.docx", (SAMPLES / "dang_quyet_dinh_sai.docx").read_bytes(), standard="nd30")
    payload = jobs.get_payload(jid)
    assert payload["standard_hint"]["mismatch"] is True
    assert payload["standard_hint"]["suggested"] == "dang"
    summ = jobs.job_summary(jid)
    assert summ["standard_mismatch"] is True

    jid2 = jobs.create_job("dang_quyet_dinh_sai.docx", (SAMPLES / "dang_quyet_dinh_sai.docx").read_bytes(), standard="dang")
    payload2 = jobs.get_payload(jid2)
    assert payload2["standard_hint"]["mismatch"] is False


# ---------------------------------------------------------------- nhận diện mục lục / liệt kê / tài liệu
def _mk_doc(path, items):
    from docx import Document
    from docx.shared import Pt
    d = Document()
    for it in items:
        text, kw = (it, {}) if isinstance(it, str) else it
        p = d.add_paragraph(style=kw.get("style")) if kw.get("style") else d.add_paragraph()
        r = p.add_run(text)
        r.bold = kw.get("bold", False)
        r.font.size = Pt(14)
        r.font.name = "Times New Roman"
    d.save(path)


def test_report_toc_list_refs_and_headings(tmp_path):
    """Mục lục gõ tay không bị nhận thành đề mục; 'a)'/'1.' sau câu kết thúc bằng ':' là liệt kê;
    câu văn mang nhầm style Heading bị gỡ; tài liệu tham khảo (có nhóm) được nhận diện; chỉ đề
    mục thật mang Heading N sau khi sửa (để mục lục field đúng và đủ)."""
    from nd30fmt.extract import extract
    B = {"bold": True}
    src = tmp_path / "bc.docx"
    _mk_doc(src, [("BÁO CÁO", B), ("MỤC LỤC", B), "I. ĐÁNH GIÁ CHUNG\t3", "1. Tổ chức bộ máy\t3",
                  ("I. ĐÁNH GIÁ CHUNG", B), ("1. Tổ chức bộ máy", B), "Đơn vị đã thực hiện các nội dung sau:",
                  "a) Rà soát chức năng, nhiệm vụ;", "b) Sắp xếp lại đội ngũ.",
                  ("Kết quả cho thấy công tác sắp xếp đã cơ bản hoàn thành đúng tiến độ đề ra, bảo đảm ổn định.",
                   {"style": "Heading 2"}),
                  ("TÀI LIỆU THAM KHẢO", B), ("A. Tài liệu tiếng Việt", B),
                  "1. Bộ Nội vụ (2020), Hướng dẫn về vị trí việc làm, Nxb. Chính trị quốc gia, Hà Nội.",
                  ("PHỤ LỤC", B)])
    r = process(str(src), load_spec(str(ROOT / "config" / "nd30_spec.yaml")), str(tmp_path))
    texts = {p["id"]: p["text"] for p in r["paragraphs"]}
    role = {texts[d["pid"]]: d["role"] for d in r["roles"]}
    assert role["MỤC LỤC"] == "other"
    assert role["I. ĐÁNH GIÁ CHUNG\t3"] == "toc_entry" and role["1. Tổ chức bộ máy\t3"] == "toc_entry"
    assert role["I. ĐÁNH GIÁ CHUNG"] == "heading_l1" and role["1. Tổ chức bộ máy"] == "heading_l2"
    assert role["a) Rà soát chức năng, nhiệm vụ;"] == "list_item"
    assert role["b) Sắp xếp lại đội ngũ."] == "list_item"
    assert role["TÀI LIỆU THAM KHẢO"] == "heading_l1"
    assert role["A. Tài liệu tiếng Việt"] == "other"
    assert role["1. Bộ Nội vụ (2020), Hướng dẫn về vị trí việc làm, Nxb. Chính trị quốc gia, Hà Nội."] == "tai_lieu_tham_khao"
    ex2 = extract(str(tmp_path / r["fixed_file"]))
    heads = [(p.text, p.heading_level) for p in ex2.paragraphs if p.heading_level]
    assert heads == [("I. ĐÁNH GIÁ CHUNG", 1), ("1. Tổ chức bộ máy", 2), ("TÀI LIỆU THAM KHẢO", 1)], heads


# ---------------------------------------------------------------- làm lại mục lục: xoá khối cũ, không trùng
def _toc_texts(path):
    from docx import Document
    from docx.oxml.ns import qn
    from nd30fmt.toc import _para_text
    out = []
    for p in Document(path).paragraphs:
        instr = " ".join(it.text for it in p._p.iter(qn("w:instrText"))).strip()
        out.append(("FIELD:" + instr) if instr.startswith("TOC") else _para_text(p._p))
    return out


def test_rebuild_toc_removes_old_manual_toc(tmp_path):
    """Mục lục cũ gõ tay (có dòng dính số 'UAE.40', dòng bị ngắt còn trơ '50') bị xoá rồi mới chèn
    field mới; chạy 2 lần không trùng; ngắt trang, danh mục chữ viết tắt, thân bài giữ nguyên;
    chú thích 'Bảng 2.1.' được gắn SEQ ẩn để vào danh mục bảng."""
    from docx import Document
    from docx.enum.text import WD_BREAK
    from nd30fmt.toc import build_toc
    path = tmp_path / "toc.docx"
    d = Document()
    for t in ["MỤC LỤC", "CHƯƠNG 2: CAM KẾT CỦA HIỆP ĐỊNH CEPA VIỆT NAM - UAE.40",
              "2.1. Cam kết về thương mại hàng hóa\t40",
              "2.4. Cam kết về các biện pháp an toàn thực phẩm và kiểm dịch động, thực vật (SPS)", "50",
              "3.3. Thách thức và rủi ro đối với DNNVV\t83"]:
        d.add_paragraph(t)
    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    for t in ["DANH MỤC BẢNG", "Bảng 2.1. Lộ trình cắt giảm thuế\t41", "DANH MỤC CHỮ VIẾT TẮT", "UAE\tCác Tiểu vương quốc",
              "MỞ ĐẦU", "Bảng 2.1. Lộ trình cắt giảm thuế"]:
        d.add_paragraph(t)
    d.save(path)
    build_toc(str(path), str(path))
    st = build_toc(str(path), str(path))
    assert st["captions"]["tagged"] == {"Hinh": 0, "Bang": 0}      # lần 2 không gắn lặp
    got = _toc_texts(path)
    assert got == ["MỤC LỤC", 'FIELD:TOC \\o "1-3" \\h \\z \\u', "\n",
                   "DANH MỤC BẢNG", 'FIELD:TOC \\c "Bang" \\h \\z', "DANH MỤC CHỮ VIẾT TẮT", "UAE\tCác Tiểu vương quốc",
                   "MỞ ĐẦU", "Bảng 2.1. Lộ trình cắt giảm thuế"], got


def test_rebuild_toc_keeps_body_without_page_break(tmp_path):
    from docx import Document
    from nd30fmt.toc import build_toc
    path = tmp_path / "toc2.docx"
    d = Document()
    for t in ["MỤC LỤC", "1. Mở đầu\t1", "2. Kết quả\t3", "MỞ ĐẦU", "Số liệu tổng hợp của năm 2025"]:
        d.add_paragraph(t)
    d.save(path)
    build_toc(str(path), str(path))
    assert _toc_texts(path) == ["MỤC LỤC", 'FIELD:TOC \\o "1-3" \\h \\z \\u', "MỞ ĐẦU", "Số liệu tổng hợp của năm 2025"]


def test_toc_merges_chapter_label_and_title(tmp_path):
    """'CHƯƠNG 1' và tên chương ở 2 đoạn -> gộp thành 1 đề mục cấp 1 (ngắt dòng mềm) để mục lục
    hiện 1 dòng; nhãn chương / đề mục kết thúc bằng số không bị coi là dòng mục lục."""
    from docx import Document
    from nd30fmt.extract import extract
    from nd30fmt.toc import build_toc
    path = tmp_path / "ch.docx"
    d = Document()
    d.add_paragraph("MỤC LỤC")
    d.add_paragraph("1. Mục tiêu đến năm 2030", style="Heading 2")
    d.add_paragraph("CHƯƠNG 1", style="Heading 1")
    d.add_paragraph("TỔNG QUAN VỀ HIỆP ĐỊNH CEPA", style="Heading 1")
    d.add_paragraph("1.1. Bối cảnh", style="Heading 2")
    d.save(path)
    r = build_toc(str(path), str(path))
    assert r["toc"]["merged_chapters"] == ["CHƯƠNG 1 + TỔNG QUAN VỀ HIỆP ĐỊNH CEPA"]
    assert r["toc"]["gate_removed"] == []
    heads = [(p.text, p.heading_level) for p in extract(str(path)).paragraphs if p.heading_level]
    assert heads == [("1. Mục tiêu đến năm 2030", 2), ("CHƯƠNG 1\nTỔNG QUAN VỀ HIỆP ĐỊNH CEPA", 1), ("1.1. Bối cảnh", 2)], heads
    assert build_toc(str(path), str(path))["toc"]["merged_chapters"] == []      # chạy lại không gộp lặp
