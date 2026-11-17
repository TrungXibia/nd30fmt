"""Kiểm thử chuẩn Đề án/Luận văn thạc sĩ (Phụ lục 4.1) của bộ kiểm tra và chuẩn hoá."""
import importlib
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from nd30fmt.extract import extract
from nd30fmt.pipeline import process
from nd30fmt.spec import DEAN_SPEC_PATH, load_spec

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
H = {"X-App-Token": "t0k"}


def _mk_doc(path, items):
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


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not (SAMPLES / "dean_sai.docx").exists():
        import runpy
        runpy.run_path(str(ROOT / "tests" / "make_samples.py"), run_name="__main__")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "t0k")
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


def _upload(client, name, standard):
    with open(SAMPLES / name, "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", (name, f.read(), "application/octet-stream"))],
                        data={"standard": standard, "wait": "true"})
    assert r.status_code == 200, r.text
    j = r.json()["jobs"][0]
    assert j["ok"], j
    return j["id"]


def test_dean_standard_hint_not_guessed():
    from nd30fmt.extract import extract
    from nd30fmt.roles import detect_standard_hint
    hint = detect_standard_hint(extract(str(SAMPLES / "dean_sai.docx")))
    # Bìa luận văn/đề án thường không có quốc hiệu ngay đầu -> không chắc, không được đoán bừa
    assert hint["suggested"] in (None, "nd30")


def test_restandard_nd30_to_dean_and_back(client):
    import time
    jid = _upload(client, "bao_cao_sai.docx", "nd30")

    def switch(std):
        r = client.post(f"/api/jobs/{jid}/restandard", headers=H, json={"standard": std})
        assert r.status_code == 200, r.text
        for _ in range(200):
            st = client.get(f"/api/jobs/{jid}/status", headers=H).json()
            if st["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert st["status"] == "done", st
        return client.get(f"/api/jobs/{jid}", headers=H).json()

    q = switch("dean")
    assert q["standard"] == "dean" and any(r["role"].startswith("dean_") for r in q["roles"])
    q = switch("nd30")
    assert q["standard"] == "nd30" and not any(r["role"].startswith("dean_") for r in q["roles"])


def test_dean_thesis_standard(tmp_path):
    """Đề án thạc sĩ (Phụ lục 4.1): vai trò theo vùng, sửa hết lỗi sửa được, chỉ còn lỗi cấu trúc (không tự sửa)."""
    from nd30fmt.extract import extract
    from nd30fmt.spec import DEAN_SPEC_PATH
    r = process(str(SAMPLES / "dean_sai.docx"), load_spec(str(DEAN_SPEC_PATH)), str(tmp_path), standard="dean")
    roles = {d["pid"]: d["role"] for d in r["roles"]}
    texts = {p["id"]: p["text"] for p in r["paragraphs"]}
    by_text = {texts[k]: v for k, v in roles.items()}
    assert by_text["MỤC LỤC"] == "dean_tieu_de_phan"
    assert by_text["Chương 1. Cơ sở lý luận\t5"] == "dean_toc_entry"          # dòng mục lục, không phải tên chương
    assert by_text["CHƯƠNG 1. CƠ SỞ LÝ LUẬN VỀ CÔNG CHỨC CẤP XÃ"] == "dean_chuong"
    assert by_text["1.1. Giới thiệu tổng quan"] == "dean_muc_2"
    assert by_text["1.1.1. Một số khái niệm"] == "dean_muc_3"
    assert by_text["1.1.1.1. Tổng trực tiếp"] == "dean_muc_4"
    assert by_text["Bảng 1.1. Số lượng công chức giai đoạn 2022-2025"] == "dean_caption_table"
    assert by_text["BỘ GIÁO DỤC VÀ ĐÀO TẠO"] == "dean_bia"
    fields = {v["field"] for v in r["violations"]}
    assert {"margin", "size", "line_spacing", "char_spacing", "italic", "bold", "align", "position", "page_start"} <= fields
    left = r["violations_after"]
    assert all(not v["fixable"] for v in left), left
    assert {v["field"] for v in left} <= {"position", "page_start", "numbering"}
    ex = extract(str(tmp_path / r["fixed_file"]))
    s = ex.sections[0]
    assert (round(s.top_mm), round(s.bottom_mm), round(s.left_mm), round(s.right_mm)) == (30, 30, 35, 20)
    ch = next(p for p in ex.paragraphs if p.text.startswith("CHƯƠNG 1"))
    assert ch.sizes() == [15.0] and ch.align == "left" and (ch.line_rule, ch.line_value) == ("auto", 1.5)
    body = next(p for p in ex.paragraphs if p.text.startswith("Nội dung giới thiệu"))
    assert all(r.char_spacing == 0 and r.char_scale == 100 for r in body.runs)


def test_caption_needs_punctuation_after_number(tmp_path):
    """'Bảng 3.1 cho thấy...' (không có dấu sau số) là đoạn văn, không phải tên bảng - ở cả 3 chuẩn và khi tạo field SEQ."""
    from docx import Document
    from nd30fmt.roles import RE, RE_DEAN
    from nd30fmt.spec import DEAN_SPEC_PATH
    from nd30fmt.toc import CAPTION_RE
    for t in ("Bảng 3.1 cho thấy cơ chế FIT khác nhau.", "Hình 2 minh họa quy trình.", "Bảng 3 cho thấy"):
        assert not (RE["caption_table"].match(t) or RE["caption_figure"].match(t)), t
        assert not (RE_DEAN["caption_table"].match(t) or RE_DEAN["caption_figure"].match(t)), t
        assert not CAPTION_RE.match(t), t
    for t in ("Bảng 3.1. So sánh", "Bảng 3.1: So sánh", "Bảng 3.1 – So sánh", "Hình 2.4. Sơ đồ", "Bảng 3.1"):
        assert RE["caption_table"].match(t) or RE["caption_figure"].match(t), t
        assert RE_DEAN["caption_table"].match(t) or RE_DEAN["caption_figure"].match(t), t
    d = Document(str(SAMPLES / "dean_sai.docx"))
    d.add_paragraph("Bảng 3.1 cho thấy cơ chế FIT và khung năm 2025 khác nhau về cấu trúc giá.")
    src = tmp_path / "x.docx"
    d.save(src)
    r = process(str(src), load_spec(str(DEAN_SPEC_PATH)), str(tmp_path), standard="dean")
    last = r["paragraphs"][-1]["id"]
    assert {x["pid"]: x["role"] for x in r["roles"]}[last] != "dean_caption_table"


def test_dean_long_references_stay_in_region(tmp_path):
    from nd30fmt.extract import extract
    from nd30fmt.roles import propose_roles_dean
    long_ref = ("1. Bộ Nội vụ (2020), Báo cáo tổng kết công tác cán bộ, công chức, viên chức giai đoạn "
                "2015-2020 và phương hướng nhiệm vụ giai đoạn 2021-2025, Hà Nội, tháng 12 năm 2020, tài liệu "
                "lưu hành nội bộ phục vụ hội nghị toàn ngành.")
    src = tmp_path / "da.docx"
    _mk_doc(src, [("KẾT LUẬN", {"bold": True}), "Đề án đã hệ thống hóa cơ sở lý luận.",
                  ("DANH MỤC TÀI LIỆU THAM KHẢO", {"bold": True}), long_ref,
                  "2. Nguyễn Văn A (2021), \"Công chức cấp xã\", Tạp chí Quản lý nhà nước, số 305, tr. 45-50.",
                  ("PHỤ LỤC", {"bold": True}), "Phiếu khảo sát"])
    ex = extract(str(src))
    roles = [d.role for d in propose_roles_dean(ex)]
    assert roles[3:5] == ["dean_tai_lieu", "dean_tai_lieu"], roles
    assert roles[5] == "dean_tieu_de_phan" and roles[6] == "dean_phu_luc", roles


def test_dean_body_with_outline_level_style_not_chapter(tmp_path):
    """File chuyển đổi (ABBYY...) gắn outline level 1 cho cả style nội dung: câu văn KHÔNG được
    nhận thành tên chương (bị in hoa/đậm/cỡ 15) và phải bị gỡ cấp đề mục để không vào mục lục."""
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from nd30fmt.extract import extract
    from nd30fmt.spec import DEAN_SPEC_PATH
    d = Document()
    st = d.styles.add_style("1.", WD_STYLE_TYPE.PARAGRAPH)
    ol = OxmlElement("w:outlineLvl"); ol.set(qn("w:val"), "0"); st.element.get_or_add_pPr().append(ol)
    d.add_paragraph("CHƯƠNG 2. CAM KẾT CỦA HIỆP ĐỊNH CEPA", style="1.")
    body = ("Theo Hiệp định CEPA, hai bên cam kết mở cửa thị trường ở mức độ cao thông qua lộ trình "
            "cắt giảm và xóa bỏ thuế nhập khẩu đối với phần lớn các dòng thuế.")
    d.add_paragraph(body, style="1.")
    src = tmp_path / "abbyy.docx"; d.save(src)
    r = process(str(src), load_spec(str(DEAN_SPEC_PATH)), str(tmp_path), standard="dean")
    texts = {p["id"]: p["text"] for p in r["paragraphs"]}
    role = {texts[x["pid"]]: x["role"] for x in r["roles"]}
    assert role["CHƯƠNG 2. CAM KẾT CỦA HIỆP ĐỊNH CEPA"] == "dean_chuong"
    assert role[body] == "dean_body"
    ex2 = extract(str(tmp_path / r["fixed_file"]))
    bp = [p for p in ex2.paragraphs if p.text == body][0]
    assert bp.heading_level is None and not any(x.caps for x in bp.runs)


def test_list_lines_with_outline_level_kept_out_of_toc(tmp_path):
    """Dòng gạch đầu dòng mang style có cấp đề mục (file chuyển đổi), vai trò tin cậy thấp: bước sửa và
    chốt chặn khi tạo mục lục đều phải gỡ cấp đề mục; đề mục thật vẫn giữ."""
    from collections import Counter
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from nd30fmt.extract import extract
    from nd30fmt.fix import fix_heading_styles
    from nd30fmt.roles import RoleDecision
    from nd30fmt.spec import DEAN_SPEC_PATH
    from nd30fmt.toc import build_toc

    def mk(path):
        d = Document()
        st = d.styles.add_style("1.1", WD_STYLE_TYPE.PARAGRAPH)
        ol = OxmlElement("w:outlineLvl"); ol.set(qn("w:val"), "1"); st.element.get_or_add_pPr().append(ol)
        d.add_paragraph("MỤC LỤC")
        d.add_paragraph("2.3.2. Minh bạch hóa thủ tục hải quan", style="1.1")
        d.add_paragraph("- Tăng cường tính minh bạch của chính sách hải quan;", style="1.1")
        d.save(path)

    a = tmp_path / "a.docx"; mk(a)
    ex = extract(str(a))
    dec = [RoleDecision("P0001", "dean_tieu_de_phan", 1.0, "regex"), RoleDecision("P0002", "dean_muc_3", 1.0, "regex"),
           RoleDecision("P0003", "dean_body", 0.47, "heuristic", scores={"dean_body": 0.47, "dean_muc_3": 0.33, "other": 0.2})]
    fix_heading_styles(ex, dec, load_spec(str(DEAN_SPEC_PATH)), Counter(), 0.5)
    ex.doc.save(str(a))
    lv = [p.heading_level for p in extract(str(a)).paragraphs]
    assert lv == [None, 3, None], lv

    b = tmp_path / "b.docx"; mk(b)
    r = build_toc(str(b), str(b))
    assert r["toc"]["gate_removed"] == ["- Tăng cường tính minh bạch của chính sách hải quan;"]
    lv = {p.text: p.heading_level for p in extract(str(b)).paragraphs}
    assert lv["2.3.2. Minh bạch hóa thủ tục hải quan"] == 2
    assert lv["- Tăng cường tính minh bạch của chính sách hải quan;"] is None


def test_dean_cover_stops_at_numbered_content(tmp_path):
    """Thuyết minh nhiệm vụ (không phải luận văn) chọn nhầm chuẩn Đề án: trước đây mọi đoạn trước
    'CHƯƠNG 1' (nằm trong mục 11.1) bị coi là trang bìa -> không kiểm tra, số lỗi còn lại ảo."""
    from nd30fmt.jobs import _standard_hint
    from nd30fmt.roles import propose_roles_dean
    d = Document()
    for t in ("BM-02", "THUYẾT MINH NHIỆM VỤ KHOA HỌC, CÔNG NGHỆ", "1. Tên nhiệm vụ", "Nghiên cứu cơ chế giá",
              "7. Tổ chức chủ trì nhiệm vụ", "7.1. Tên tổ chức chủ trì: Viện X", "11.1. Nội dung của nghiên cứu",
              "CHƯƠNG 1. CƠ SỞ KHOA HỌC", "1.1. Tổng quan"):
        d.add_paragraph(t)
    src = tmp_path / "tm.docx"
    d.save(src)
    ex = extract(str(src))
    roles = [x.role for x in propose_roles_dean(ex)]
    assert roles[:2] == ["dean_bia", "dean_bia"], roles
    assert "dean_bia" not in roles[2:], roles
    hint = _standard_hint(ex, "dean")
    assert hint["mismatch"] and hint["suggested"] == "nd30" and hint.get("reason")


def test_dean_standard_web(client):
    jid = _upload(client, "dean_sai.docx", standard="dean")
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["standard"] == "dean" and "dean_chuong" in {r["key"] for r in p["role_keys"]}
    raw = client.get("/api/spec", headers=H, params={"standard": "dean"}).json()["raw"]
    assert raw["page"]["margins_mm"]["left"]["fix"] == 35 and raw["body"]["line_spacing_max"] == 1.5
