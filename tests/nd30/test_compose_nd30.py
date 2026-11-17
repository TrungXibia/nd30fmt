"""Trình soạn thảo v40 – chuẩn NĐ 30/2020 (Mẫu 1.1–1.10): schema, bố cục, Word, nhập Word."""
import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from compose_samples import ALL_ND30, BIEN_BAN, CONG_VAN, GIAY_NGHI_PHEP, QD_GIAN_TIEP, QD_TRUC_TIEP, TO_TRINH
from nd30fmt.composer import docx_writer, importer, layout, schema
from nd30fmt.composer.validate import validate_draft

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Path("/mnt/skills/public/docx/scripts/office/validate.py")


def _texts(items):
    out = []
    for it in items:
        if it["t"] == "p":
            out.append("".join(r["t"] for r in it["runs"]))
        else:
            for row in it["rows"]:
                for cell in row:
                    out.extend(_texts(cell["items"]))
    return out


def _build(d):
    return layout.build_layout(d)


# ------------------------------------------------------------------ schema, mapping
def test_schema_files_machine_readable():
    base = ROOT / "config" / "templates" / "nd30"
    for i in range(1, 11):
        data = json.loads((base / f"mau_1_{i}.json").read_text(encoding="utf-8"))
        assert data["id"] == f"1.{i}" and data["standard"] == "nd30"
        for key in ("layout", "fields", "validation", "docx", "source", "geometry"):
            assert key in data, (i, key)
    fmt = json.loads((base / "_format.json").read_text(encoding="utf-8"))
    assert fmt["page"]["margins_mm"]["left"]["range"] == [30, 35]
    assert fmt["roles"]["quoc_hieu"]["size"] == [12, 13] and fmt["roles"]["noi_nhan_item"]["size"] == [11, 11]


def test_mapping_1_1_to_1_10():
    cat = {t["id"]: t for t in schema.catalog("nd30")["types"]}
    assert cat["NGHI_QUYET"]["template"] == "1.1"
    assert cat["QUYET_DINH_TRUC_TIEP"]["template"] == "1.2"
    assert cat["QUYET_DINH_GIAN_TIEP"]["template"] == "1.3"
    only_14 = {"CHI_THI", "QUY_CHE", "QUY_DINH", "THONG_CAO", "THONG_BAO", "HUONG_DAN", "CHUONG_TRINH", "KE_HOACH",
               "PHUONG_AN", "DE_AN", "DU_AN", "BAO_CAO", "TO_TRINH", "GIAY_UY_QUYEN", "PHIEU_GUI", "PHIEU_CHUYEN",
               "PHIEU_BAO"}
    assert {k for k, v in cat.items() if v["template"] == "1.4"} == only_14
    for t, m in [("CONG_VAN", "1.5"), ("CONG_DIEN", "1.6"), ("GIAY_MOI", "1.7"), ("GIAY_GIOI_THIEU", "1.8"),
                 ("BIEN_BAN", "1.9"), ("GIAY_NGHI_PHEP", "1.10")]:
        assert cat[t]["template"] == m
    for t in ("HOP_DONG", "BAN_GHI_NHO", "BAN_THOA_THUAN", "THU_CONG"):
        assert cat[t]["template_status"] == "unsupported" and cat[t]["template"] is None
    # 29 loại của Điều 7 (quyết định tách 2 mẫu -> 30 mục)
    assert len(cat) == 30


def test_unsupported_type_has_no_fake_layout():
    with pytest.raises(layout.LayoutError, match="Chưa có mẫu chuẩn"):
        _build({"standard": "nd30", "type_id": "HOP_DONG", "fields": {}})
    v = validate_draft({"standard": "nd30", "type_id": "THU_CONG", "fields": {}})
    assert v[0]["level"] == "error"


def test_no_extra_standards():
    assert schema.STANDARDS == ("nd30", "hd05")
    names = {p.name for p in (ROOT / "config" / "templates").iterdir()}
    assert names == {"nd30", "hd05", "font_metrics_tnr.json", "README.md"}


# ------------------------------------------------------------------ trường theo mẫu
def _field_ids(type_id):
    return [f["id"] for f in schema.template_for("nd30", type_id)["fields"]]


def test_form_fields_change_per_template():
    qd12 = _field_ids("QUYET_DINH_TRUC_TIEP")
    for f in ("co_quan_chu_quan", "co_quan_ban_hanh", "so", "dia_danh", "ngay", "trich_yeu", "tham_quyen", "can_cu",
              "de_nghi", "noi_dung", "noi_nhan", "quyen_han", "chuc_vu", "ho_ten"):
        assert f in qd12
    assert "van_ban_kem_theo" in _field_ids("QUYET_DINH_GIAN_TIEP") and "van_ban_kem_theo" not in qd12
    cv = _field_ids("CONG_VAN")
    assert {"trich_yeu", "kinh_gui", "noi_dung", "lien_he", "ma_don_vi"} <= set(cv)
    gm = _field_ids("GIAY_MOI")
    assert {"nguoi_duoc_moi", "cuoc_hop", "chu_tri", "thoi_gian", "dia_diem", "luu_y"} <= set(gm)
    bb = _field_ids("BIEN_BAN")
    assert {"thoi_gian_bat_dau", "dia_diem", "thanh_phan", "chu_toa", "thu_ky", "noi_dung", "ket_thuc"} <= set(bb)
    assert "chuc_vu" not in bb and "ngay" not in bb
    np_ = _field_ids("GIAY_NGHI_PHEP")
    assert {"nguoi_nghi", "chuc_vu_nguoi_nghi", "thoi_gian_nghi", "tu_ngay", "den_ngay", "noi_nghi", "tinh_vao",
            "hien_xac_nhan"} <= set(np_)


def test_cong_van_has_no_ten_loai_and_vv_under_number():
    L = _build(CONG_VAN)
    texts = _texts(L["items"])
    assert "CÔNG VĂN" not in texts
    header = L["items"][0]
    left_row2 = [("".join(r["t"] for r in p["runs"]), p["role"]) for p in header["rows"][1][0]["items"]]
    assert left_row2[0] == ("Số: 07/VNCY-NL", "so_ky_hieu")
    assert left_row2[1][0].startswith("V/v góp ý") and left_row2[1][1] == "trich_yeu_cong_van"
    vv = header["rows"][1][0]["items"][1]
    assert vv["size"] == 13 and vv["sp"]["before"] == 6 and not vv["runs"][0]["b"]
    # Kính gửi nhiều nơi: gạch đầu dòng, “;” và dòng cuối “.”
    assert "- Vụ Kế hoạch – Tài chính;" in texts and "- Cục Điện lực." in texts
    assert L["first_footer"] and "border" in L["first_footer"][0]


def test_qd_1_2_differs_from_1_3():
    a, b = _build(QD_TRUC_TIEP), _build(QD_GIAN_TIEP)
    ta, tb = _texts(a["items"]), _texts(b["items"])
    assert a["meta"]["template"] == "1.2" and b["meta"]["template"] == "1.3"
    assert any(t.startswith("Điều 1. Ban hành kèm theo Quyết định này Quy chế") for t in tb)
    assert not any("kèm theo Quyết định này" in t for t in ta)
    assert "Điều 2. Quyết định này có hiệu lực kể từ ngày ký." in tb   # các Điều tiếp theo đánh từ 2
    assert "QUYẾT ĐỊNH:" in ta and "QUYẾT ĐỊNH:" in tb


# ------------------------------------------------------------------ bố cục, đường kẻ
def test_lines_are_borders_not_dashes():
    for d in ALL_ND30.values():
        L = _build(d)
        texts = _texts(L["items"])
        assert not any(re.fullmatch(r"[-_]{3,}", t) for t in texts)
        header = L["items"][0]
        tn = header["rows"][0][1]["items"][1]
        assert tn["role"] == "tieu_ngu" and tn["border"]["bottom"]
        # PL I: đường kẻ dưới Tiêu ngữ dài bằng dòng chữ
        from nd30fmt.composer.text import text_width_pt
        assert abs(tn["border"]["bottom"]["len"] - text_width_pt("Độc lập - Tự do - Hạnh phúc", tn["size"], True)) < 3
        line_cq = header["rows"][0][0]["items"][-1]
        assert line_cq["role"] == "line_co_quan" and "bottom" in line_cq["border"]


def test_header_two_columns_and_date_same_row_as_number():
    L = _build(QD_TRUC_TIEP)
    h = L["items"][0]
    assert h["t"] == "table" and len(h["cols"]) == 2 and len(h["rows"]) == 2
    assert abs(sum(h["cols"]) - L["page"]["content_width"]) < 0.1
    right2 = h["rows"][1][1]["items"][0]
    assert right2["role"] == "dia_danh_ngay" and right2["runs"][0]["i"]
    assert "".join(r["t"] for r in right2["runs"]) == "Hà Nội, ngày 05 tháng 01 năm 2026"   # tháng 1 -> 01


def test_leading_zero_and_date_padding():
    d = json.loads(json.dumps(CONG_VAN))
    d["fields"].update(so="3", ngay="2026-03-09")
    L = _build(d)
    assert L["meta"]["number_text"] == "Số: 03/VNCY-NL"
    date = "".join(r["t"] for r in L["items"][0]["rows"][1][1]["items"][0]["runs"])
    assert date == "Hà Nội, ngày 09 tháng 3 năm 2026"   # PL I: chỉ tháng 1, 2 thêm số 0


def test_dieu_khoan_diem_numbering_and_manual_override():
    blocks = [{"type": "dieu"}, {"type": "khoan"}, {"type": "diem"}, {"type": "diem"}, {"type": "khoan"},
              {"type": "dieu", "number": "5"}, {"type": "khoan"}, {"type": "dieu"}, {"type": "diem"}]
    assert layout.number_blocks(blocks) == ["Điều 1.", "1.", "a)", "b)", "2.", "Điều 5.", "1.", "Điều 6.", "a)"]
    assert layout.number_blocks([{"type": "la_ma"}, {"type": "khoan"}, {"type": "la_ma"}, {"type": "khoan"}]) == \
        ["I.", "1.", "II.", "1."]
    many = layout.number_blocks([{"type": "diem"}] * 6)
    assert many == ["a)", "b)", "c)", "d)", "đ)", "e)"]   # bảng chữ cái tiếng Việt


def test_body_indent_spacing_and_trimmed_text():
    d = json.loads(json.dumps(QD_TRUC_TIEP))
    d["fields"]["noi_dung"] = [{"type": "dieu", "html": "   Nội dung   có   khoảng trắng thừa   "}]
    L = _build(d)
    p = next(it for it in L["items"] if it.get("role") == "dieu")
    text = "".join(r["t"] for r in p["runs"])
    assert text == "Điều 1. Nội dung có khoảng trắng thừa./."
    assert abs(p["ind"]["first"] - 1.27 / 2.54 * 72) < 0.01 and p["sp"]["before"] == 6 and p["align"] == "justify"
    assert p["runs"][0]["b"] and not p["runs"][-1]["b"]   # “Điều n.” đậm


def test_can_cu_punctuation_normalized():
    L = _build(QD_TRUC_TIEP)
    cc = [("".join(r["t"] for r in it["runs"])) for it in L["items"] if it.get("role") == "can_cu"]
    assert cc[0].endswith(";") and cc[-1] == "Theo đề nghị của Trưởng phòng Tổ chức – Hành chính."
    assert all(it["runs"][0]["i"] for it in L["items"] if it.get("role") == "can_cu")


def test_bien_ban_two_signature_zones_no_generic_signer():
    L = _build(BIEN_BAN)
    sign = next(it for it in L["items"] if it.get("role") == "bien_ban_sign")
    left = _texts(sign["rows"][0][0]["items"])
    right = _texts(sign["rows"][0][1]["items"])
    assert left[0] == "THƯ KÝ" and left[-1] == "Lê Thị E"
    assert right[0] == "CHỦ TỌA" and right[-1] == "Nguyễn Văn A"
    assert not any(it.get("role") == "sign" for it in L["items"])
    texts = _texts(L["items"])
    assert texts[-1] == "- Lưu: VT, Hồ sơ." and "Nơi nhận:" in texts
    # Mẫu 1.9: không có dòng địa danh, ngày tháng ở đầu trang
    assert not any("ngày" in t and "năm" in t and "Hà Nội" in t for t in _texts([L["items"][0]]))


def test_giay_nghi_phep_confirmation_zone():
    L = _build(GIAY_NGHI_PHEP)
    t = next(it for it in L["items"] if it.get("role") == "nghi_phep_sign")
    assert len(t["rows"]) == 2
    zone = _texts(t["rows"][1][0]["items"])
    assert zone[0] == "Xác nhận của cơ quan (tổ chức) hoặc chính quyền địa phương nơi nghỉ phép (nếu cần)"
    assert t["rows"][1][0]["items"][0]["runs"][0]["i"]
    d = json.loads(json.dumps(GIAY_NGHI_PHEP))
    d["fields"]["hien_xac_nhan"] = False
    t2 = next(it for it in _build(d)["items"] if it.get("role") == "nghi_phep_sign")
    assert len(t2["rows"]) == 1


def test_signer_authority_lines():
    d = json.loads(json.dumps(QD_TRUC_TIEP))
    d["fields"].update(quyen_han="KT.", quyen_han_cua="Viện trưởng", chuc_vu="Phó Viện trưởng", ho_ten="Trần B")
    sign = next(it for it in _build(d)["items"] if it.get("role") == "sign")
    right = [t for t in _texts(sign["rows"][0][1]["items"]) if t]
    assert right == ["KT. VIỆN TRƯỞNG", "PHÓ VIỆN TRƯỞNG", "Trần B"]
    left = _texts(sign["rows"][0][0]["items"])
    assert left[0] == "Nơi nhận:" and left[-1] == "- Lưu: VT, VP, NVB(05)."
    lab = sign["rows"][0][0]["items"][0]
    assert lab["size"] == 12 and lab["runs"][0]["b"] and lab["runs"][0]["i"]
    assert all(p["size"] == 11 for p in sign["rows"][0][0]["items"][1:])


def test_to_trinh_kinh_gui_only_for_allowed_types():
    L = _build(TO_TRINH)
    assert "Kính gửi: Bộ trưởng Bộ X." in _texts(L["items"])
    d = json.loads(json.dumps(TO_TRINH))
    d["type_id"] = "KE_HOACH"
    assert not any(t.startswith("Kính gửi") for t in _texts(_build(d)["items"]))


def test_settings_clamped_to_nd30_ranges():
    d = json.loads(json.dumps(CONG_VAN))
    d["settings"] = {"margins": {"left": 40, "top": 22}, "body_size": 12, "line_spacing": 2, "indent_cm": 1.1}
    L = _build(d)
    assert L["page"]["margins_mm"]["left"] == 35 and L["page"]["margins_mm"]["top"] == 22
    s = L["meta"]["settings"]
    assert s["body_size"] == 13 and s["line"]["value"] == 1.5 and s["indent_cm"] == 1.0
    assert s["sizes"]["quoc_hieu"] == 12 and s["sizes"]["tieu_ngu"] == 13     # bộ cỡ chữ đồng bộ
    assert any("ngoài khoảng" in n for n in L["notices"])


def test_validation_required_fields():
    d = json.loads(json.dumps(CONG_VAN))
    d["fields"]["kinh_gui"] = []
    d["fields"]["trich_yeu"] = ""
    errs = {v["field"] for v in validate_draft(d) if v["level"] == "error"}
    assert {"kinh_gui", "trich_yeu"} <= errs
    assert not [v for v in validate_draft(CONG_VAN) if v["level"] == "error"]


# ------------------------------------------------------------------ Word
@pytest.mark.parametrize("num", list(ALL_ND30))
def test_docx_export_all_templates(num, tmp_path):
    L = _build(ALL_ND30[num])
    data = docx_writer.build_docx(L)
    path = tmp_path / f"mau_{num}.docx"
    path.write_bytes(data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        xml = z.read("word/document.xml").decode("utf-8")
    assert "-----" not in xml
    doc = Document(str(path))
    sec = doc.sections[0]
    assert (sec.page_width.twips, sec.page_height.twips) == (11906, 16838)
    m = L["page"]["margins"]
    assert abs(sec.left_margin.pt - m["left"]) < 0.1 and abs(sec.right_margin.pt - m["right"]) < 0.1
    assert sec.different_first_page_header_footer
    assert "PAGE" in "".join(x.text or "" for x in sec.header._element.iter(qn("w:instrText")))
    hdr = doc.tables[0]
    borders = hdr._tbl.tblPr.find(qn("w:tblBorders"))
    assert borders is not None and all(b.get(qn("w:val")) == "nil" for b in borders)
    assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in hdr.cell(0, 1).text
    assert re.search(r"Số: 0\d/", hdr.cell(1, 0).text)      # giữ số 0 đầu
    tn = hdr.cell(0, 1).paragraphs[1]
    assert tn._p.pPr.find(qn("w:pBdr")) is not None
    fonts = {r.font.name for p in doc.paragraphs for r in p.runs}
    assert fonts <= {"Times New Roman"}
    if VALIDATOR.exists():
        out = subprocess.run(["python3", str(VALIDATOR), str(path)], capture_output=True, text=True)
        assert "PASSED" in out.stdout, out.stdout + out.stderr


def test_docx_indentation_and_signature(tmp_path):
    doc = Document(io.BytesIO(docx_writer.build_docx(_build(QD_TRUC_TIEP))))
    dieu = next(p for p in doc.paragraphs if p.text.startswith("Điều 1."))
    assert abs(dieu.paragraph_format.first_line_indent.cm - 1.27) < 0.01
    assert dieu.runs[0].bold and dieu.alignment == 3
    sign = doc.tables[-1]
    assert sign.cell(0, 0).paragraphs[0].text == "Nơi nhận:"
    assert "VIỆN TRƯỞNG" in sign.cell(0, 1).text and "Nguyễn Văn A" in sign.cell(0, 1).text


@pytest.mark.skipif(not shutil.which("soffice"), reason="không có LibreOffice")
def test_docx_opens_in_libreoffice_one_a4_page(tmp_path):
    src = tmp_path / "cv.docx"
    src.write_bytes(docx_writer.build_docx(_build(CONG_VAN)))
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
                   capture_output=True, timeout=120)
    pdf = tmp_path / "cv.pdf"
    assert pdf.exists()
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    assert re.search(r"Pages:\s+1\n", info) and "595" in info and "841" in info


# ------------------------------------------------------------------ nhập Word
@pytest.mark.parametrize("num", list(ALL_ND30))
def test_import_roundtrip(num):
    src = ALL_ND30[num]
    res = importer.parse_docx(docx_writer.build_docx(_build(src)))
    got = res["draft"]
    assert got["standard"] == "nd30" and got["type_id"] == src["type_id"], res["detected"]
    assert res["detected"]["template"] == num
    f = got["fields"]
    for key in ("co_quan_ban_hanh", "ma_co_quan", "dia_danh", "ngay", "trich_yeu", "chuc_vu", "ho_ten"):
        if key in src["fields"]:
            assert f.get(key) == src["fields"][key], (num, key, f.get(key))
    assert f.get("so") == src["fields"]["so"].zfill(2)
    body = next((c["field"] for c in schema.template_for("nd30", src["type_id"])["layout"] if c["kind"] == "body"), None)
    if body and src["fields"].get(body):
        assert [b["type"] for b in f[body]] == [b["type"] for b in src["fields"][body]]
    # xuất lại từ bản nhập vẫn hợp lệ
    docx_writer.build_docx(layout.build_layout(got))


def test_import_distinguishes_qd_1_2_and_1_3():
    a = importer.parse_docx(docx_writer.build_docx(_build(QD_TRUC_TIEP)))
    b = importer.parse_docx(docx_writer.build_docx(_build(QD_GIAN_TIEP)))
    assert a["draft"]["type_id"] == "QUYET_DINH_TRUC_TIEP" and b["draft"]["type_id"] == "QUYET_DINH_GIAN_TIEP"
    assert b["draft"]["fields"]["van_ban_kem_theo"].startswith("Quy chế chi tiêu nội bộ")


def test_import_plain_word_without_header_table():
    d = Document()
    for t in ["BỘ X", "VIỆN NGHIÊN CỨU", "Số: 5/TB-VNCY", "Hà Nội, ngày 3 tháng 2 năm 2026", "THÔNG BÁO",
              "Kết quả họp", "1. Nội dung thứ nhất", "a) chi tiết", "- ý phụ", "Nơi nhận:", "- Các phòng;", "- Lưu: VT, VP."]:
        d.add_paragraph(t)
    buf = io.BytesIO()
    d.save(buf)
    res = importer.parse_docx(buf.getvalue())
    f = res["draft"]["fields"]
    assert res["draft"]["type_id"] == "THONG_BAO" and f["so"] == "5" and f["ma_co_quan"] == "VNCY"
    assert f["ngay"] == "2026-02-03" and f["noi_nhan"] == ["Các phòng"] and f["luu"] == "VP"
    assert [b["type"] for b in f["noi_dung"]] == ["khoan", "diem", "bullet"]
    assert res["warnings"]


# ------------------------------------------------------------------ API + giao diện
@pytest.fixture()
def client(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "t0k")
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


H = {"X-App-Token": "t0k"}


def test_compose_api(client):
    assert client.get("/api/compose/templates").status_code == 401
    t = client.get("/api/compose/templates", headers=H).json()
    assert set(t["nd30"]["templates"]) == {f"1.{i}" for i in range(1, 11)}
    r = client.post("/api/compose/layout", headers=H, json=CONG_VAN).json()
    assert r["layout"]["meta"]["template"] == "1.5" and isinstance(r["validation"], list)
    d = client.post("/api/compose/docx", headers=H, json=CONG_VAN)
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert "Cong-van.docx" in d.headers["content-disposition"]
    bad = client.post("/api/compose/layout", headers=H, json={"standard": "nd30", "type_id": "HOP_DONG", "fields": {}})
    assert bad.status_code == 400
    imp = client.post("/api/compose/import", headers=H, files={"file": ("a.docx", d.content)}).json()
    assert imp["draft"]["type_id"] == "CONG_VAN"
    cl = client.post("/api/compose/classify", headers=H, json={"lines": ["Điều 2. X", "1. Y", "a) Z", "- W", "thường"]}).json()
    assert [x["kind"] for x in cl["lines"]] == ["dieu", "khoan", "diem", "bullet", "p"]


def test_composer_html_is_schema_driven():
    html = (ROOT / "nd30fmt" / "static" / "soan_thao.html").read_text(encoding="utf-8")
    assert html.index('id="formPane"') < html.index('id="previewPane"')          # xem trước bên phải
    for token in ('data-zoom="80"', 'data-zoom="100"', 'data-zoom="120"', 'id="zoomRange"',
                  "Khôi phục chuẩn NĐ30", "Khôi phục chuẩn HD05", "api/compose/layout", "api/compose/docx"):
        assert token in html
    assert not re.search(r"[\"'`]-{3,}", html)          # không vẽ đường kẻ bằng ký tự
    assert "wrapLoaiHD" not in html      # bỏ tham chiếu phần tử cũ của v39
    assert not re.search(r"Độc lập - Tự do", html)   # quốc hiệu/tiêu ngữ lấy từ bố cục máy chủ


def test_classify_confidence_levels():
    from nd30fmt.composer.classify import classify_lines
    r = classify_lines(["Điều 1. A", "Thời gian: 8 giờ", "Nội dung khác"])
    lv = [(x["kind"], x["level"], x["source"]) for x in r["lines"]]
    assert lv == [("dieu", "high", "rule"), ("p", "low", "default"), ("p", "low", "default")]


@pytest.mark.parametrize("num", list(ALL_ND30))
def test_composed_document_passes_nd30_checker(num, tmp_path):
    """Văn bản do trình soạn thảo tạo ra phải qua được bộ kiểm tra thể thức NĐ30."""
    from nd30fmt.pipeline import process
    from nd30fmt.spec import load_spec
    src = tmp_path / "m.docx"
    src.write_bytes(docx_writer.build_docx(_build(ALL_ND30[num])))
    r = process(str(src), load_spec(str(ROOT / "config" / "nd30_spec.yaml")), str(tmp_path), standard="nd30")
    assert r["violations"] == [], [(v["role"], v["field"], v["actual"]) for v in r["violations"]]


@pytest.mark.parametrize("name,vv,so", [("cv191", "thực hiện một số nội dung theo Nghị định số 30/2020/NĐ-CP", "191"),
                                        ("cv236", "thực hiện Nghị định số 30/2020/NĐ-CP ngày 05/3/2020 của Chính phủ", "236")])
def test_import_real_cong_van(name, vv, so):
    res = importer.parse_docx((Path(__file__).parent / "fixtures" / f"{name}.docx").read_bytes())
    f = res["draft"]["fields"]
    assert res["draft"]["type_id"] == "CONG_VAN" and f["trich_yeu"] == vv and f["so"] == so
    assert not set(f.get("co_quan_ban_hanh", "")) <= set("_")
    assert f["noi_dung"] and f["ho_ten"]
    docx_writer.build_docx(layout.build_layout(res["draft"]))
