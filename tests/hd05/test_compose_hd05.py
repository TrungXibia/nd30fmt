"""Trình soạn thảo v40 – văn bản Đảng: thông số lấy từ quy chuẩn Đảng (dang_spec.yaml), không lẫn NĐ30."""
import io
import json

from docx import Document

from compose_samples import CONG_VAN, PARTY
from nd30fmt import jobs
from nd30fmt.composer import docx_writer, importer, layout, schema


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


def test_party_format_comes_from_party_spec_not_nd30():
    fmt = schema.party_format()
    raw = jobs.default_raw("dang")
    assert fmt["roles"]["tieu_de"]["default"] == raw["roles"]["dang_tieu_de"]["fix_size"]
    assert fmt["body"]["line_spacing_pt"]["default"] == raw["body"]["fix_line_spacing_pt"]
    L = layout.build_layout(PARTY)
    s = L["meta"]["settings"]
    assert s["line"] == {"rule": "exact", "value": raw["body"]["fix_line_spacing_pt"]}   # Exactly, không phải “lines” của NĐ30
    assert abs(s["indent_cm"] - raw["body"]["fix_first_line_indent_cm"]) < 1e-9
    assert L["header"]["page_number"]["size"] == raw["page"]["page_number"]["fix_size"]
    nd = layout.build_layout(CONG_VAN)["meta"]["settings"]
    assert nd["line"]["rule"] == "multiple"


def test_party_layout_header_and_number():
    L = layout.build_layout(PARTY)
    h = L["items"][0]
    right = _texts(h["rows"][0][1]["items"])
    left = _texts(h["rows"][0][0]["items"])
    assert right == ["ĐẢNG CỘNG SẢN VIỆT NAM"] and "*" in left
    assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" not in _texts(L["items"])
    assert L["meta"]["number_text"] == "Số 12-NQ/ĐU"
    texts = _texts(L["items"])
    assert "NGHỊ QUYẾT" in texts and "- Lưu Văn phòng Đảng ủy." in texts
    lab = next(it for it in L["items"][-1]["rows"][0][0]["items"] if it["role"] == "noi_nhan_label")
    assert lab["runs"][0]["u"]      # “Nơi nhận” gạch chân theo quy chuẩn Đảng
    assert not texts[-1].endswith("/.")   # dấu “/.” của Mẫu NĐ30 không áp cho văn bản Đảng


def test_party_settings_separate_and_clamped():
    d = json.loads(json.dumps(PARTY))
    d["settings"] = {"line_spacing_pt": 30, "margins": {"left": 35}}
    L = layout.build_layout(d)
    rng = schema.party_format()["body"]["line_spacing_pt"]["range"]
    assert L["meta"]["settings"]["line"]["value"] == rng[1]
    assert L["page"]["margins_mm"]["left"] == schema.party_format()["margins_mm"]["left"]["range"][1]


def test_party_docx_and_import_roundtrip():
    data = docx_writer.build_docx(layout.build_layout(PARTY))
    doc = Document(io.BytesIO(data))
    assert "ĐẢNG CỘNG SẢN VIỆT NAM" in doc.tables[0].cell(0, 1).text
    body = [p for p in doc.paragraphs if p.text.startswith("Năm 2025")][0]
    assert body.paragraph_format.line_spacing_rule == 4     # EXACTLY
    res = importer.parse_docx(data)
    assert res["draft"]["standard"] == "hd05" and res["draft"]["type_id"] == "NGHI_QUYET"
    f = res["draft"]["fields"]
    assert f["so"] == "12" and f["ma_co_quan"] == "ĐU" and f["chuc_vu"] == "BÍ THƯ" and f["ho_ten"] == "Nguyễn Văn H"


def test_party_type_codes_follow_hd05():
    """HD05 mục 3.1.2.a: Quyết định, Quy định: QĐ; Chỉ thị CT; Chương trình CTr; Thông tri TT; Tờ trình TTr."""
    codes = {t["id"]: t["ma_loai"] for t in schema.catalog("hd05")["types"]}
    assert codes["QUYET_DINH"] == codes["QUY_DINH"] == "QĐ"
    assert (codes["CHI_THI"], codes["CHUONG_TRINH"], codes["THONG_TRI"], codes["TO_TRINH"], codes["KET_LUAN"]) == \
        ("CT", "CTr", "TT", "TTr", "KL")


def _party(type_id="NGHI_QUYET", **fields):
    d = json.loads(json.dumps(PARTY))
    d["type_id"] = type_id
    d["fields"].update(fields)
    return d


def test_party_title_rule_star_number_and_summary_dashes():
    L = layout.build_layout(_party(so="5"))
    h = L["items"][0]
    title = h["rows"][0][1]["items"][0]
    assert title["border"]["bottom"]["len"] > 100 and title["align"] == "center"          # mục 1.2
    assert _texts(h["rows"][0][0]["items"])[-1] == "*"                                       # mục 2.2.1
    assert _texts(h["rows"][1][0]["items"])[0] == "Số 05-NQ/ĐU"                            # mục 3.2.2
    texts = _texts(L["items"])
    i = texts.index("NGHỊ QUYẾT")
    assert texts[i + 2] == "-----"                                                           # mục 5.2.1


def test_party_cong_van_and_to_trinh_recipients():
    cv = layout.build_layout(_party("CONG_VAN", trich_yeu="về việc chuẩn bị hội nghị", noi_nhan=[],
                                    kinh_gui=["Ban Thường vụ Đảng ủy Bộ", "Văn phòng Đảng ủy Bộ"]))
    texts = _texts(cv["items"])
    assert "NGHỊ QUYẾT" not in texts and "CÔNG VĂN" not in texts                            # mục 5.1.1
    left2 = _texts(cv["items"][0]["rows"][1][0]["items"])
    assert left2 == ["Số 12-CV/ĐU", "về việc chuẩn bị hội nghị"]                             # mục 5.2.3
    assert "Kính gửi: Ban Thường vụ Đảng ủy Bộ;" in texts and "Văn phòng Đảng ủy Bộ;" in texts   # mục 9.2.5
    assert "- Như trên;" in texts                                                            # mục 9.2.3
    tt = layout.build_layout(_party("TO_TRINH", kinh_gui=["Ban Thường vụ Đảng ủy Bộ"]))
    assert "Kính trình: Ban Thường vụ Đảng ủy Bộ;" in _texts(tt["items"])                 # mục 9.2.4
    nq = layout.build_layout(_party(kinh_gui=["X"]))
    assert not any(t.startswith("Kính") for t in _texts(nq["items"]))


def test_party_noi_nhan_semicolons_and_luu():
    texts = _texts(layout.build_layout(PARTY)["items"])
    assert "- Đảng ủy Bộ;" in texts and "- Các chi bộ;" in texts and texts.count("- Lưu Văn phòng Đảng ủy.") == 1


def test_party_signature_variants():
    def sign(**kw):
        L = layout.build_layout(_party(**kw))
        t = next(it for it in L["items"] if it.get("role") == "sign")
        return [x for x in _texts(t["rows"][0][1]["items"]) if x]
    assert sign(quyen_han="T/M", quyen_han_cua="Ban Thường vụ", chuc_vu="Bí thư") == ["T/M BAN THƯỜNG VỤ", "BÍ THƯ", "Nguyễn Văn H"]
    assert sign(quyen_han="K/T", quyen_han_cua="Trưởng ban", chuc_vu="Phó trưởng ban") == ["K/T TRƯỞNG BAN", "PHÓ TRƯỞNG BAN", "Nguyễn Văn H"]
    assert sign(quyen_han="Q.", chuc_vu="Trưởng ban") == ["Q. TRƯỞNG BAN", "Nguyễn Văn H"]
    assert sign(quyen_han="", chuc_vu="Bí thư\nkiêm\nTrưởng ban chỉ đạo") == ["BÍ THƯ", "kiêm", "TRƯỞNG BAN CHỈ ĐẠO", "Nguyễn Văn H"]
    L = layout.build_layout(_party(quyen_han="T/M", quyen_han_cua="Chi bộ"))
    t = next(it for it in L["items"] if it.get("role") == "sign")
    first = t["rows"][0][1]["items"][0]
    assert first["runs"][0]["b"] and not t["rows"][0][1]["items"][1]["runs"][0]["b"]   # quyền hạn đậm, chức vụ không đậm


def test_party_bien_ban_signature_sides():
    L = layout.build_layout(_party("BIEN_BAN", ho_ten_nguoi_ghi="Lê E", ho_ten_chu_tri="Nguyễn Văn H"))
    t = next(it for it in L["items"] if it.get("role") == "sign")
    assert [x for x in _texts(t["rows"][0][0]["items"]) if x] == ["NGƯỜI GHI BIÊN BẢN", "Lê E"]
    assert [x for x in _texts(t["rows"][0][1]["items"]) if x] == ["CHỦ TRÌ HỘI NGHỊ", "Nguyễn Văn H"]


def test_party_optional_components_and_ending():
    L = layout.build_layout(_party(do_khan="THƯỢNG KHẨN", du_thao="Dự thảo lần 2", pham_vi="Lưu hành nội bộ",
                                   lien_he="Số 1 Hùng Vương, Hà Nội", can_cu=["Điều lệ Đảng", "Quy định số 01-QĐ/TW"],
                                   noi_dung=[{"type": "p", "html": "Nội dung không có dấu chấm"}]))
    left2 = _texts(L["items"][0]["rows"][1][0]["items"])
    assert left2 == ["Số 12-NQ/ĐU", "THƯỢNG KHẨN", "Dự thảo lần 2"]
    assert _texts(L["first_header"]) == ["LƯU HÀNH NỘI BỘ"] and L["first_header"][0]["align"] == "right"
    texts = _texts(L["items"])
    assert "- Căn cứ Điều lệ Đảng;" in texts and "- Căn cứ Quy định số 01-QĐ/TW." in texts          # mục 6.2.3
    assert "Nội dung không có dấu chấm." in texts                                                  # mục 6.2.2
    last = L["items"][-1]
    assert last["role"] == "dang_thong_tin_lien_he" and last["border"]["top"]                    # mục II.6
    L2 = layout.build_layout(_party(pham_vi="Không phổ biến trên phương tiện thông tin đại chúng"))
    assert not L2["first_header"] and L2["items"][-1]["align"] == "center"


def test_party_two_sided_mirror_margins():
    d = _party()
    d["settings"] = {"in_hai_mat": True}
    L = layout.build_layout(d)
    assert L["page"]["mirror"]
    import zipfile
    data = docx_writer.build_docx(L)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert b"mirrorMargins" in z.read("word/settings.xml")


def test_party_import_roundtrip_all_types():
    for t in schema.catalog("hd05")["types"]:
        d = _party(t["id"], trich_yeu="về việc thử nghiệm", kinh_gui=["Ban Thường vụ"], ho_ten_nguoi_ghi="Lê E",
                   ho_ten_chu_tri="Nguyễn Văn H", do_khan="KHẨN")
        res = importer.parse_docx(docx_writer.build_docx(layout.build_layout(d)))
        assert res["draft"]["standard"] == "hd05" and res["draft"]["type_id"] == t["id"], (t["id"], res["detected"])
        f = res["draft"]["fields"]
        assert f["so"] == "12" and f["ma_co_quan"] == "ĐU" and f["do_khan"] == "KHẨN"
        if t["id"] == "BIEN_BAN":
            assert f["ho_ten_nguoi_ghi"] == "Lê E" and f["ho_ten_chu_tri"] == "Nguyễn Văn H"
        else:
            assert (f["quyen_han"], f["quyen_han_cua"], f["chuc_vu"]) == ("T/M", "ĐẢNG ỦY", "BÍ THƯ")
        if t["id"] in ("CONG_VAN", "TO_TRINH"):
            assert f["kinh_gui"] == ["Ban Thường vụ"]
        assert f["trich_yeu"] == "về việc thử nghiệm"


import pytest  # noqa: E402


@pytest.mark.parametrize("type_id", ["NGHI_QUYET", "CONG_VAN", "TO_TRINH", "BIEN_BAN", "QUY_DINH"])
def test_composed_party_document_passes_party_checker(type_id, tmp_path):
    from pathlib import Path
    from nd30fmt.pipeline import process
    from nd30fmt.spec import load_spec
    root = Path(__file__).resolve().parents[2]
    src = tmp_path / "d.docx"
    d = _party(type_id, trich_yeu="về việc thử nghiệm", kinh_gui=["Ban Thường vụ"], ho_ten_nguoi_ghi="Lê E",
               ho_ten_chu_tri="Nguyễn Văn H",
               noi_dung=[{"type": "la_ma", "html": "Tình hình"}, {"type": "p", "html": "Năm 2025, Đảng bộ hoàn thành nhiệm vụ."},
                         {"type": "dieu", "html": "Giao các chi bộ thực hiện"}, {"type": "khoan", "html": "Khoản một;"},
                         {"type": "diem", "html": "điểm a."}])
    src.write_bytes(docx_writer.build_docx(layout.build_layout(d)))
    r = process(str(src), load_spec(str(root / "config" / "dang_spec.yaml")), str(tmp_path), standard="dang")
    assert r["violations"] == [], [(v["role"], v["field"], v["actual"], v["target"]) for v in r["violations"]]
