"""Sửa chính tả tiếng Việt cho Word: âm vị, bộ sửa, ghi vào .docx (đổi màu), API web."""
import importlib
import io
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

from nd30fmt import vphon, vspell
from nd30fmt.extract import extract
from nd30fmt.spellword import process_document, validate_opts

pytestmark = pytest.mark.skipif(not vspell.available(), reason="chưa có mô hình ngôn ngữ")


# ------------------------------------------------------------------ âm vị
@pytest.mark.parametrize("w", ["nghĩa", "được", "kết", "nhiều", "quyết", "thuỷ", "thủy", "gì", "giữa", "khuya", "ngoài",
                               "xuất", "uống", "người", "yêu", "quốc", "chiến", "hoà", "toà"])
def test_valid_syllables(w):
    assert vphon.valid_syllable(w)


@pytest.mark.parametrize("w", ["đươc", "kêt", "nghoa", "cê", "kan", "ngi", "chat", "bac", "dip", "iran", "ưc"])
def test_invalid_syllables(w):
    assert not vphon.valid_syllable(w)


def test_tone_placement():
    assert vphon.tone_style("nghiã") == "bad"
    assert vphon.tone_style("hòa") == "old" and vphon.tone_style("hoà") == "new"
    assert vphon.tone_style("nghĩa") == "both"


# ------------------------------------------------------------------ bộ sửa
def fixed(text, style="old"):
    r = vspell.analyze(text, style=style)
    return vspell.apply(text, r.fixes, only_sure=True), r


@pytest.mark.parametrize("bad,good", [
    ("Các đơn vị cần đươc bổ sung kêt quả.", "Các đơn vị cần được bổ sung kết quả."),
    ("Nghiã vụ của các bên.", "Nghĩa vụ của các bên."),
    ("Vieejt Nam đang phát triển.", "Việt Nam đang phát triển."),
    ("Xử lý số liệu của của Viện.", "Xử lý số liệu của Viện."),
    ("Công tác sử lý hồ sơ.", "Công tác xử lý hồ sơ."),
    ("Phát triễn kinh tế số.", "Phát triển kinh tế số."),
    ("Doanh nghiệp  gặp khó khăn , cần hỗ trợ.", "Doanh nghiệp gặp khó khăn, cần hỗ trợ."),
])
def test_fixes(bad, good):
    assert fixed(bad)[0] == good


CLEAN = [
    "Viện Nghiên cứu Y báo cáo kết quả thực hiện nhiệm vụ năm 2025.",
    "Căn cứ Nghị định số 30/2020/NĐ-CP ngày 05 tháng 3 năm 2020 của Chính phủ về công tác văn thư.",
    "Kính gửi: Bộ trưởng Bộ X; Chánh Văn phòng Bộ; Vụ Kế hoạch - Tài chính.",
    "Đề nghị các đơn vị khẩn trương hoàn thành, bảo đảm đúng tiến độ và chất lượng.",
    "Theo số liệu của Tổng cục Thống kê, GDP quý III tăng 7,4% so với cùng kỳ năm trước.",
    "Công ty Samsung Electronics Vietnam và tập đoàn Toyota mở rộng đầu tư tại Thái Nguyên.",
    "Liên hệ qua email vanthu@example.gov.vn hoặc truy cập https://example.gov.vn/tin-tuc.",
    "Tổ chức hội nghị trực tuyến với các tỉnh, thành phố trực thuộc Trung ương vào sáng thứ Hai.",
    "Chính sách phát triển công nghiệp hỗ trợ cần gắn với chuyển đổi xanh và chuyển đổi số.",
    "Ông Nguyễn Văn An, Phó Viện trưởng, chủ trì cuộc họp cùng đại diện UBND tỉnh Quảng Ninh.",
    "Kinh tế tuần hoàn, năng lượng tái tạo và hydrogen xanh là những hướng ưu tiên.",
    "Việc thực hiện còn một số tồn tại, hạn chế, nguyên nhân chủ yếu là thiếu nguồn lực.",
]


@pytest.mark.parametrize("s", CLEAN)
def test_clean_text_untouched(s):
    out, r = fixed(s)
    assert out == s, [(f.kind, f.old, f.new) for f in r.fixes if f.tier == 2]


# ------------------------------------------------------------------ chữ tiếng Anh không bị "sửa" thành chữ Việt
@pytest.fixture(params=["rust", "python"])
def engine(request):
    from nd30fmt import core
    if request.param == "rust" and core.speller() is None:
        pytest.skip("không có lõi Rust")
    core.FORCE_PY = request.param == "python"
    yield request.param
    core.FORCE_PY = False


ENGLISH_MIXED = [
    "Hệ thống must được cập nhật và that is the reason của việc này.",
    "Chúng tôi dùng docker, kubernetes và gitlab để triển khai ứng dụng.",
    "Gửi email cho khách hàng qua website, chat trực tuyến và hotline.",
    "Báo cáo về machine learning, big data và blockchain trong quản lý nhà nước.",
    "Phiên bản mới của Microsoft Excel và PowerPoint hỗ trợ cloud backup.",
    "Công ty có six văn phòng, mỗi văn phòng có beef chef và cow chăn nuôi.",
    "Đề tài nghiên cứu bao gồm survey, interview và focus group với doanh nghiệp.",
]
ENGLISH_PURE = [
    "Thank you for your that kind of chat with them about the new policy.",
    "This document must be updated before the committee meets again next week.",
    "Please send the report by email and keep a backup of the original files.",
    "Docker and Kubernetes are used to deploy the web server in the cloud.",
]


@pytest.mark.parametrize("s", ENGLISH_MIXED + ENGLISH_PURE)
def test_english_words_untouched(engine, s):
    """Không được sửa dấu, đoán Telex hay báo nghi sai trên chữ tiếng Anh (kể cả khi trùng chữ Việt bỏ dấu)."""
    out, r = fixed(s)
    assert out == s, [(f.kind, f.old, f.new) for f in r.fixes if f.tier == 2]
    assert not [f for f in r.fixes if f.kind != "space"], [(f.kind, f.old, f.new, f.tier) for f in r.fixes]
    assert not r.suspects


def test_english_next_to_real_typos(engine):
    out, _ = fixed("Hệ thống must đươc cập nhật, that chat kêt quả của của email.")
    assert out == "Hệ thống must được cập nhật, that chat kết quả của email."


def test_english_acronyms_not_telex(engine):
    s = "Định dạng BIF và hệ điều hành DOS theo tiêu chuẩn ISO của Bộ."
    assert fixed(s)[0] == s


def test_telex_still_fixed_beside_english(engine):
    out, _ = fixed("Vieejt Nam dùng email và docker.")
    assert out == "Việt Nam dùng email và docker."


def test_unaccented_vietnamese_paragraph_still_fixed(engine):
    """Đoạn gõ hoàn toàn không dấu: các chữ Việt không bị nhận nhầm là tiếng Anh."""
    r = vspell.analyze("Ban hanh quyet dinh ve viec nay")
    assert {f.old for f in r.fixes} >= {"quyet", "viec"}


def test_langid_flags():
    from nd30fmt import langid
    assert langid.english_flags(["Chúng", "tôi", "dùng", "docker", "và", "email"]) == [False, False, False, True, False, True]
    assert langid.english_flags(["Ban", "hanh", "quyet", "dinh"]) == [False] * 4
    assert langid.english_flags(["This", "must", "be", "done"]) == [True] * 4
    assert langid.english_flags([]) == []


def test_protected_tokens():
    s = "Xem tệp kêt_qua.pdf, Điều 5đươc, NĐ-CP, vietnam@gmail.com, www.dươc.vn, 30/2020/kêt"
    assert fixed(s)[0] == s


def test_new_style_keeps_placement():
    out, _ = fixed("Hoà bình và thuỷ lợi, nghiã vụ", style="new")
    assert out == "Hoà bình và thuỷ lợi, nghĩa vụ"


def test_style_consistency():
    fx = vspell.style_fixes(["Kỹ thuật tiên tiến, kỹ năng tốt.", "Kĩ sư tham gia."])
    assert [f.new for f in fx[1]] == ["Kỹ"] and fx[0] == []


# ------------------------------------------------------------------ Word
def _fld(p, instr, shown):
    for t, txt in (("begin", None), ("instr", instr), ("separate", None), ("text", shown), ("end", None)):
        r = p.add_run()
        if t == "instr":
            i = OxmlElement("w:instrText")
            i.text = txt
            r._r.append(i)
        elif t == "text":
            r.text = txt
        else:
            f = OxmlElement("w:fldChar")
            f.set(qn("w:fldCharType"), t)
            r._r.append(f)


def _make(path):
    d = Document()
    p = d.add_paragraph("Các đơn vị cần đươc bổ sung ")
    r = p.add_run("kêt quả"); r.bold = True
    p.add_run(" thực hiện, gặp khó khăn  về sử lý số liệu.")
    p = d.add_paragraph()
    for part in ("Kinh nghiêm ", "chính", " xát", " và hoàn thành."):
        p.add_run(part)
    p = d.add_paragraph("Trang ")
    _fld(p, " PAGE ", "đươc")
    p = d.add_paragraph("Mã: ")
    r = p.add_run("kêt_qua đươc")
    r._r.get_or_add_rPr().append(OxmlElement("w:noProof"))
    t = d.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "Phát triễn kinh tế số"
    d.save(path)


def _runs(doc):
    out = []
    for p in doc.paragraphs:
        for r in p.runs:
            col = r._r.find(qn("w:rPr") + "/" + qn("w:color"))
            out.append((r.text, col.get(qn("w:val")) if col is not None else None, r.bold))
    return out


def test_word_marks_only_changed_text(tmp_path):
    src = tmp_path / "a.docx"
    _make(src)
    ex = extract(str(src))
    rep = process_document(ex, {"on": True})
    out = tmp_path / "b.docx"
    ex.doc.save(out)
    d = Document(out)
    runs = _runs(d)
    red = [t for t, c, _ in runs if c == "FF0000"]
    assert "được" in red and "kết quả" not in red and "kết" in red and "xử lý" in red and "chính xác" in red
    txt = "\n".join(p.text for p in d.paragraphs)
    assert "đươc" not in txt.replace("Trang đươc", "") or "Trang " in txt
    assert "khó khăn về xử lý số liệu." in txt          # dấu cách đôi gộp lại, không đổi màu
    assert "Kinh nghiêm chính xác và hoàn thành." in txt
    # định dạng đậm của run gốc được giữ cho phần chữ sửa trong run đậm
    assert any(t == "kết" and b for t, c, b in runs)
    # trường tự động, noProof: nguyên vẹn
    assert "Trang đươc" in txt and "kêt_qua đươc" in txt
    assert d.tables[0].cell(0, 0).text == "Phát triển kinh tế số"
    assert rep["applied"] == 6 and rep["applied_by"].get("space") == 1


def test_word_clean_variant_has_no_color(tmp_path):
    src = tmp_path / "a.docx"
    _make(src)
    ex = extract(str(src))
    process_document(ex, {"on": True}, mark=False)
    out = tmp_path / "c.docx"
    ex.doc.save(out)
    assert all(c is None for _, c, _ in _runs(Document(out)))
    assert "được" in Document(out).paragraphs[0].text


def test_word_options(tmp_path):
    src = tmp_path / "a.docx"
    _make(src)

    def run(**o):
        ex = extract(str(src))
        rep = process_document(ex, {"on": True, **o})
        return rep, "\n".join(p.text for p in ex.doc.paragraphs)

    rep, txt = run()
    key = next(i["key"] for i in rep["items"] if i["old"] == "sử lý")
    _, txt2 = run(force_off=[key])
    assert "sử lý" in txt2 and "xử lý" in txt
    _, txt3 = run(off_kinds=["pair"])
    assert "sử lý" in txt3 and "chính xát" in txt3 and "được" in txt3
    _, txt4 = run(ignore_words=["đươc"])
    assert "đươc" in txt4.split("\n")[0]
    # chạy lại trên kết quả: không còn gì để sửa (ổn định)
    ex = extract(str(src))
    process_document(ex, {"on": True})
    p2 = tmp_path / "b.docx"
    ex.doc.save(p2)
    rep2 = process_document(extract(str(p2)), {"on": True})
    assert rep2["applied"] == 0


def test_validate_opts():
    assert validate_opts({"on": True, "level": "wide", "color": "#00aa00"})["color"] == "00AA00"
    for bad in ({"level": "x"}, {"color": "red"}, {"force_on": "a"}, {"off_kinds": ["zzz"]}, []):
        with pytest.raises(ValueError):
            validate_opts(bad)


# ------------------------------------------------------------------ web
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "t0k")
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


H = {"X-App-Token": "t0k"}


def _up(client, tmp_path, **data):
    src = tmp_path / "t.docx"
    _make(src)
    r = client.post("/api/jobs", headers=H, files=[("files", ("t.docx", src.read_bytes(), "application/octet-stream"))],
                    data={"wait": "true", **data})
    assert r.status_code == 200, r.text
    return r.json()["jobs"][0]["id"]


def test_web_spell_flow(client, tmp_path):
    jid = _up(client, tmp_path)
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["spell"]["applied"] == 6 and p["spell"]["clean_file"].endswith("_da_sua_khong_mau.docx")
    fixed = Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/fixed", headers=H).content))
    assert any(c == "FF0000" for _, c, _ in _runs(fixed))
    clean = Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/fixed_clean", headers=H).content))
    assert all(c is None for _, c, _ in _runs(clean))
    # màu chữ sửa không bị tính là lỗi định dạng "màu chữ"
    assert not [v for v in p["violations_after"] if v["field"] == "color"]
    # tắt cả nhóm "pair" rồi sửa lại
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spell": {"on": True, "off_kinds": ["pair"]}})
    assert r.status_code == 200, r.text
    txt = "\n".join(x.text for x in Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/fixed", headers=H).content)).paragraphs)
    assert "sử lý" in txt and "được" in txt
    # tắt hẳn
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spell": {"on": False}})
    assert "spell" not in r.json()
    assert client.get(f"/api/jobs/{jid}/file/fixed_clean", headers=H).status_code == 404
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spell": {"level": "zzz"}}).status_code == 400


def test_web_upload_without_spell(client, tmp_path):
    jid = _up(client, tmp_path, spell="false")
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert "spell" not in p
    txt = "\n".join(x.text for x in Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/fixed", headers=H).content)).paragraphs)
    assert "đươc" in txt
    assert client.post("/api/jobs", headers=H, files=[("files", ("t.docx", b"x"))],
                       data={"spell_level": "zz"}).status_code == 400
