"""Kiểm thử API web (phiên xem trước + áp dụng lại thông số)."""
import importlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"


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


def _upload(client, name="bao_cao_sai.docx", standard="nd30"):
    with open(SAMPLES / name, "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", (name, f.read(), "application/octet-stream"))],
                        data={"standard": standard, "wait": "true"})
    assert r.status_code == 200, r.text
    j = r.json()["jobs"][0]
    assert j["ok"], j
    return j["id"]


def test_auth_required(client):
    assert client.get("/api/spec").status_code == 401
    assert client.get("/api/config").json()["token_required"] is True
    assert client.get("/").status_code == 200


def test_branding_pages_public(client):
    cfg = client.get("/api/config").json()
    assert cfg["org"]["name"]
    assert client.get("/huong-dan").status_code == 200
    assert client.get("/static/brand.css").status_code == 200
    r = client.get("/branding/logo")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
    assert cfg["org"]["logo"] == "branding/logo"          # mặc định: biểu tượng dựng sẵn, không gọi link ngoài


def test_composer_tab_and_original_default(client):
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="tabStandardize"' in home.text
    assert 'aria-selected="true" aria-controls="appMain"' in home.text
    assert 'id="tabCompose"' in home.text
    assert 'id="composerPanel"' in home.text
    assert 'id="composerFrame"' in home.text
    composer = client.get("/soan-thao")
    assert composer.status_code == 200
    assert "Xuất Word" in composer.text
    assert "api/compose/templates" in composer.text   # form dựng từ schema, không viết cứng thông số


def test_private_profile_revision_and_auth(client):
    code = "a" * 64
    header = {**H, "X-Draft-Profile": code}
    assert client.get("/api/draft-profile", headers={"X-Draft-Profile": code}).status_code == 401
    assert client.get("/api/draft-profile", headers=header).status_code == 404
    body = {"expected_revision": 0, "draft": {"version": 12}, "settings": {"right": 20}}
    result = client.put("/api/draft-profile", headers=header, json=body)
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert client.get("/api/draft-profile", headers=header).json()["draft"]["version"] == 12
    assert client.put("/api/draft-profile", headers=header, json=body).status_code == 409
    assert client.get("/api/draft-profile", headers={**H, "X-Draft-Profile": "b" * 64}).status_code == 404


def test_import_draft_endpoint_auth(client):
    from docx import Document
    import io
    doc = Document()
    doc.add_paragraph("QUYẾT ĐỊNH")
    doc.add_paragraph("Điều 1. Tổ chức lớp, cụ thể như sau:- Thời gian: ngày 25/9/2026")
    data = io.BytesIO()
    doc.save(data)
    upload = {"file": ("quyet-dinh.docx", data.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    assert client.post("/api/import-draft", files=upload).status_code == 401
    result = client.post("/api/import-draft", headers=H, files=upload)
    assert result.status_code == 200
    assert result.json()["fields"]["loaiVanBan"] == "QUYET_DINH"
    assert [block["type"] for block in result.json()["blocks"]] == ["dieu", "bullet"]   # "Điều n." -> khối Điều tự đánh số


def test_static_behind_proxy_prefix(monkeypatch, tmp_path):
    # nginx cắt /nd30 rồi chuyển tiếp, app chạy với ROOT_PATH=/nd30: file giao diện vẫn phải tải được
    monkeypatch.setenv("ROOT_PATH", "/nd30")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    c = TestClient(web.app)
    r = c.get("/static/brand.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert c.get("/static/index.html").status_code == 404


def test_job_preview_and_apply(client):
    jid = _upload(client)
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["summary"]["total"] > 0 and p["summary_after"]["total"] == 0
    assert set(p["preview"]) == {"original", "fixed"}
    assert p["preview"]["fixed"]["blocks"][0]["t"] == "tbl"
    # đổi thông số: cỡ chữ nội dung sửa về 13, giãn dòng 1.5, chế độ đồng loạt; đổi vai trò 1 đoạn
    spec = p["spec_raw"]
    for r in ("body", "list_item", "can_cu", "dieu"):
        spec["roles"][r]["fix_size"] = 13
    spec["body"]["fix_line_spacing"] = 1.5
    spec["fix"]["mode"] = "normalize"
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spec": spec, "role_overrides": {"P0013": "body"}})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["version"] == p["version"] + 1
    fx = q["preview"]["fixed"]["paras"]
    assert {x["s"] for x in fx["P0017"]["r"]} == {13.0} and fx["P0017"]["lv"] == 1.5
    assert next(d for d in q["roles"] if d["pid"] == "P0013")["method"] == "user"
    # tải file đã sửa
    d = client.get(f"/api/jobs/{jid}/file/fixed", headers=H)
    assert d.status_code == 200 and d.content[:2] == b"PK"


def test_manual_format_applies_to_preview_export_and_subsequent_runs(client):
    import io
    from docx import Document
    jid = _upload(client)
    manual = {"P0017": {"bold": True, "italic": True, "underline": True, "align": "right"}}
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"manual_format": manual})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["manual_format"] == manual
    para = p["preview"]["fixed"]["paras"]["P0017"]
    assert para["a"] == "right"
    assert all(run["b"] and run["i"] and run["u"] for run in para["r"] if run["t"].strip())
    doc = Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/fixed", headers=H).content))
    assert any(x.text and x.alignment is not None and x.alignment.value == 2
               and all(r.bold and r.italic and r.underline for r in x.runs if r.text.strip())
               for x in doc.paragraphs)
    q = client.post(f"/api/jobs/{jid}/apply", headers=H, json={}).json()
    assert q["manual_format"] == manual and q["preview"]["fixed"]["paras"]["P0017"]["a"] == "right"
    reset = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"manual_format": {}}).json()
    assert reset["manual_format"] == {}
    assert reset["preview"]["fixed"]["paras"]["P0017"]["a"] != "right"


def test_list_and_delete_job(client):
    jid = _upload(client)
    lst = client.get("/api/jobs", headers=H).json()["jobs"]
    assert any(j["id"] == jid for j in lst)
    got = next(j for j in lst if j["id"] == jid)
    assert got["errors"] > 0
    assert client.delete(f"/api/jobs/{jid}", headers=H).status_code == 200
    lst2 = client.get("/api/jobs", headers=H).json()["jobs"]
    assert not any(j["id"] == jid for j in lst2)
    assert client.get(f"/api/jobs/{jid}", headers=H).status_code == 404


def test_apply_rejects_bad_values(client):
    jid = _upload(client)
    spec = client.get(f"/api/jobs/{jid}", headers=H).json()["spec_raw"]
    spec["roles"]["body"]["bold"] = "maybe"
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spec": spec})
    assert r.status_code == 400
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"role_overrides": {"P0001": "khong_co"}})
    assert r.status_code == 400
    for bad in ({"P0017": {"bold": "yes"}}, {"P0017": {"align": []}}, {"P0017": {"size": 12}}):
        assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"manual_format": bad}).status_code == 400


def test_range_auto_extend_and_default_spec(client):
    raw = client.get("/api/spec", headers=H).json()["raw"]
    raw["page"]["margins_mm"]["left"]["fix"] = 37
    r = client.put("/api/spec", headers=H, json=raw)
    assert r.status_code == 200 and r.json()["notes"]
    saved = client.get("/api/spec", headers=H).json()
    assert saved["custom"] and saved["raw"]["page"]["margins_mm"]["left"]["range"] == [30, 37]
    assert client.delete("/api/spec", headers=H).status_code == 200
    assert client.get("/api/spec", headers=H).json()["custom"] is False


def test_background_job(client):
    import time
    with open(SAMPLES / "bao_cao_sai.docx", "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", ("a.docx", f.read(), "application/octet-stream"))])
    assert r.status_code == 200, r.text
    body = r.json()
    jid = body["jobs"][0]["id"]
    for _ in range(100):
        st = client.get(f"/api/jobs/{jid}/status", headers=H).json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert st["status"] == "done", st
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["roles"]


def test_doc_and_broken_files_rejected_clearly(client):
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100
    r = client.post("/api/jobs", headers=H, files=[("files", ("cu.doc", ole, "application/msword")),
                                                    ("files", ("hong.docx", b"PK\x03\x04rac", "application/octet-stream"))])
    js = r.json()["jobs"]
    assert not js[0]["ok"] and ".doc" in js[0]["message"]
    assert not js[1]["ok"] and "hỏng" in js[1]["message"]


def test_text_edit_keeps_format_and_rechecks(client):
    jid = _upload(client)
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    body_pid = next(d["pid"] for d in p["roles"] if d["role"] == "body")
    old = next(x["text"] for x in p["paragraphs"] if x["id"] == body_pid)
    new = old.replace("Sở", "Sở Nội vụ tỉnh", 1) if "Sở" in old else old + " (đã bổ sung)"
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"text_edits": {body_pid: new}})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["text_edits"] == {body_pid: new}
    assert next(x["text"] for x in q["paragraphs"] if x["id"] == body_pid) == new
    assert q["summary_after"]["total"] == 0           # vẫn sửa hết lỗi sau khi đổi chữ
    fixed = "".join(t["t"] for t in q["preview"]["fixed"]["paras"][body_pid]["r"])
    assert fixed == new
    # bỏ sửa chữ -> về như file gốc
    q2 = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"text_edits": {}}).json()
    assert next(x["text"] for x in q2["paragraphs"] if x["id"] == body_pid) == old
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"text_edits": ["x"]}).status_code == 400


def test_ignore_violation(client):
    jid = _upload(client)
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    v = next(x for x in p["violations"] if x["scope"] == "paragraph" and x["field"] == "size")
    mg = next(x for x in p["violations"] if x["field"] == "margin")
    total = p["summary"]["total"]
    q = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"ignored": [v["key"], mg["key"]]}).json()
    assert q["ignored"] == sorted([v["key"], mg["key"]])
    assert q["summary"]["total"] == total - 2 and q["summary"]["ignored"] == 2
    got = next(x for x in q["violations"] if x["key"] == v["key"])
    assert got["ignored"] and not got["fixed"]
    # lỗi đã bỏ qua KHÔNG bị tự sửa: cỡ chữ đoạn đó giữ nguyên như file gốc
    orig = {r["s"] for r in q["preview"]["original"]["paras"][v["target"]]["r"]}
    fixed = {r["s"] for r in q["preview"]["fixed"]["paras"][v["target"]]["r"]}
    assert orig == fixed
    side = mg["key"].split("_")[-1]
    s_orig, s_fix = q["preview"]["original"]["sections"][0], q["preview"]["fixed"]["sections"][0]
    assert s_orig[f"{side}_mm"] == s_fix[f"{side}_mm"]      # cạnh lề đã bỏ qua không bị sửa
    assert not any(x.get("key") == v["key"] and not x.get("ignored") for x in q["violations_after"])
    # hoàn tác
    q2 = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"ignored": []}).json()
    assert q2["summary"]["total"] == total and q2["summary_after"]["total"] == 0
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"ignored": "x"}).status_code == 400


def test_bad_standard_rejected(client):
    with open(SAMPLES / "bao_cao_sai.docx", "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", ("x.docx", f.read(), "application/octet-stream"))],
                        data={"standard": "khong_ton_tai"})
    assert r.status_code == 400, r.text


def test_toc_endpoint(client, tmp_path):
    from docx import Document
    from docx.oxml.ns import qn

    path = tmp_path / "co_muc_luc.docx"
    d = Document()
    d.add_paragraph("MỤC LỤC")
    d.add_paragraph("DANH MỤC HÌNH")
    d.add_paragraph("DANH MỤC BẢNG")
    d.add_paragraph("Hình 1. Sơ đồ tổ chức")
    d.add_paragraph("Bảng 1: Số liệu năm 2025")
    d.save(path)
    with open(path, "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", ("co_muc_luc.docx", f.read(), "application/octet-stream"))],
                        data={"wait": "true"})
    jid = r.json()["jobs"][0]["id"]
    assert r.json()["jobs"][0]["ok"]

    r1 = client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": True, "hinh": True, "bang": True})
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["captions"]["converted"] == {"Hinh": 1, "Bang": 1}
    assert body["captions"]["skipped"] == []
    assert body["toc"]["inserted"] == {"toc": True, "hinh": True, "bang": True}

    fixed = client.get(f"/api/jobs/{jid}/file/fixed", headers=H)
    assert fixed.status_code == 200
    out = tmp_path / "fixed1.docx"
    out.write_bytes(fixed.content)
    fd = Document(out)
    instrs = [it.text for p in fd.paragraphs for it in p._p.iter(qn("w:instrText"))]
    assert any("SEQ Hinh" in i for i in instrs)
    assert any("SEQ Bang" in i for i in instrs)
    assert any('TOC \\o "1-3"' in i for i in instrs)
    assert any('TOC \\c "Hinh"' in i for i in instrs)
    assert any('TOC \\c "Bang"' in i for i in instrs)

    # bấm lại lần 2: dựng lại từ file gốc theo lựa chọn nên cho cùng kết quả, không lặp field (idempotent)
    r2 = client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": True, "hinh": True, "bang": True})
    b2 = r2.json()
    assert b2["captions"]["converted"] == {"Hinh": 1, "Bang": 1}
    assert b2["toc"]["inserted"] == {"toc": True, "hinh": True, "bang": True}
    out_b = tmp_path / "fixed_b.docx"
    out_b.write_bytes(client.get(f"/api/jobs/{jid}/file/fixed", headers=H).content)
    instr_b = [it.text for p in Document(out_b).paragraphs for it in p._p.iter(qn("w:instrText"))]
    assert sum('TOC \\o "1-3"' in i for i in instr_b) == 1 and sum("SEQ Hinh" in i for i in instr_b) == 1

    # sửa lại (đổi thông số) không được làm mất mục lục/field đã tạo
    spec = client.get(f"/api/jobs/{jid}", headers=H).json()["spec_raw"]
    r3 = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spec": spec})
    assert r3.status_code == 200, r3.text
    assert r3.json().get("toc_stats") is not None
    fixed2 = client.get(f"/api/jobs/{jid}/file/fixed", headers=H)
    out2 = tmp_path / "fixed2.docx"
    out2.write_bytes(fixed2.content)
    fd2 = Document(out2)
    instrs2 = [it.text for p in fd2.paragraphs for it in p._p.iter(qn("w:instrText"))]
    assert any("SEQ Hinh" in i for i in instrs2) and any('TOC \\o "1-3"' in i for i in instrs2)


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("pdftoppm")), reason="cần LibreOffice")
def test_print_pages(client):
    jid = _upload(client)
    r = client.get(f"/api/jobs/{jid}/pages/fixed", headers=H)
    assert r.status_code == 200 and r.json()["count"] >= 1
    img = client.get(f"/api/jobs/{jid}/page/fixed/1", headers=H)
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"


def test_restandard_without_reupload(client):
    """Đổi chuẩn NĐ 30 -> Đảng -> NĐ 30 trên cùng file, không tải lại file gốc (v39 đã bỏ chuẩn Đề án)."""
    import time
    jid = _upload(client, "bao_cao_sai.docx", "nd30")
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    pid = p["paragraphs"][5]["id"]
    body = {"spec": p["spec_raw"], "role_overrides": {pid: "other"}, "ignored": [f"{pid}|font"],
            "manual_format": {pid: {"bold": True}}}
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json=body).status_code == 200

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

    q = switch("dang")
    assert q["standard"] == "dang" and q["id"] == jid
    assert q["role_overrides"] == {} and q["ignored"] == []
    assert q["manual_format"] == {pid: {"bold": True}}
    assert any(r["role"].startswith("dang_") for r in q["roles"])
    assert client.get(f"/api/jobs/{jid}/file/fixed", headers=H).status_code == 200
    q = switch("nd30")
    assert q["standard"] == "nd30" and not any(r["role"].startswith("dang_") for r in q["roles"])
    assert client.post(f"/api/jobs/{jid}/restandard", headers=H, json={"standard": "xyz"}).status_code == 400


def _toc_doc(tmp_path, with_heads):
    from docx import Document
    d = Document()
    d.add_paragraph("BÁO CÁO TỔNG HỢP")
    if with_heads:
        d.add_paragraph("MỤC LỤC")
    d.add_heading("1. Mở đầu", 1)
    d.add_paragraph("Nội dung.")
    d.add_paragraph("Hình 1. Sơ đồ tổ chức")
    d.add_paragraph("Bảng 1: Số liệu năm 2025")
    d.add_heading("2. Kết quả", 1)
    path = tmp_path / "toc.docx"
    d.save(path)
    return path


def _upload_path(client, path):
    r = client.post("/api/jobs", headers=H, files=[("files", (path.name, path.read_bytes(), "application/octet-stream"))],
                    data={"wait": "true", "spell": "false"})
    return r.json()["jobs"][0]["id"]


def _instrs(client, jid, kind="fixed"):
    import io
    from docx import Document
    from docx.oxml.ns import qn
    d = Document(io.BytesIO(client.get(f"/api/jobs/{jid}/file/{kind}", headers=H).content))
    return [it.text for p in d.paragraphs for it in p._p.iter(qn("w:instrText"))], [p.text for p in d.paragraphs]


def test_toc_default_only_toc_created(client, tmp_path):
    """Mặc định chỉ Mục lục; văn bản chưa có tiêu đề MỤC LỤC thì tạo mới trước đề mục đầu tiên; không đụng chú thích Hình/Bảng."""
    jid = _upload_path(client, _toc_doc(tmp_path, with_heads=False))
    r = client.post(f"/api/jobs/{jid}/toc", headers=H)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["toc"]["inserted"] == {"toc": True, "hinh": False, "bang": False} and b["toc"]["created"]["toc"]
    assert b["captions"]["converted"] == {"Hinh": 0, "Bang": 0}
    ins, texts = _instrs(client, jid)
    assert len(ins) == 1 and 'TOC \\o "1-3"' in ins[0]
    assert texts.index("MỤC LỤC") < texts.index("1. Mở đầu")
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["toc_opts"] == {"on": True, "toc": True, "hinh": False, "bang": False}


def test_toc_pick_lists_creates_headings_and_can_remove(client, tmp_path):
    jid = _upload_path(client, _toc_doc(tmp_path, with_heads=False))
    r = client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": True, "hinh": True, "bang": True})
    assert r.json()["toc"]["created"] == {"toc": True, "hinh": True, "bang": True}
    ins, texts = _instrs(client, jid)
    assert any("SEQ Hinh" in i for i in ins) and any("SEQ Bang" in i for i in ins)
    assert texts.index("MỤC LỤC") < texts.index("DANH MỤC HÌNH") < texts.index("DANH MỤC BẢNG") < texts.index("1. Mở đầu")
    # bỏ tick danh mục bảng rồi tạo lại: danh mục bảng biến mất (dựng lại từ file gốc)
    client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": True, "hinh": True, "bang": False})
    ins, texts = _instrs(client, jid)
    assert "DANH MỤC BẢNG" not in texts and not any("SEQ Bang" in i for i in ins)
    # sửa lại (đổi thông số) vẫn giữ lựa chọn
    spec = client.get(f"/api/jobs/{jid}", headers=H).json()["spec_raw"]
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spec": spec}).json()["toc_opts"]["hinh"] is True
    assert "DANH MỤC HÌNH" in _instrs(client, jid)[1]
    # gỡ mục lục
    p = client.post(f"/api/jobs/{jid}/toc/remove", headers=H).json()
    assert p["toc_opts"]["on"] is False
    ins, texts = _instrs(client, jid)
    assert not ins and "MỤC LỤC" not in texts


def test_toc_existing_headings_refreshed_and_validation(client, tmp_path):
    jid = _upload_path(client, _toc_doc(tmp_path, with_heads=True))
    b = client.post(f"/api/jobs/{jid}/toc", headers=H).json()
    assert b["toc"]["inserted"]["toc"] and not b["toc"]["created"]["toc"]
    assert client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": False, "hinh": False, "bang": False}).status_code == 400
    assert client.post(f"/api/jobs/{jid}/toc", headers=H, json={"toc": "yes"}).status_code == 400
    assert client.post(f"/api/jobs/{jid}/apply", headers=H, json={"toc": []}).status_code == 400


def test_toc_also_in_clean_spell_variant(client, tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("BÁO CÁO")
    d.add_heading("1. Mở đầu", 1)
    d.add_paragraph("Các đơn vị cần đươc bổ sung kêt quả.")
    path = tmp_path / "s.docx"
    d.save(path)
    r = client.post("/api/jobs", headers=H, files=[("files", ("s.docx", path.read_bytes(), "application/octet-stream"))],
                    data={"wait": "true"})
    jid = r.json()["jobs"][0]["id"]
    client.post(f"/api/jobs/{jid}/toc", headers=H)
    for kind in ("fixed", "fixed_clean"):
        ins, texts = _instrs(client, jid, kind)
        assert len(ins) == 1 and "MỤC LỤC" in texts, kind


def _outline_doc(tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("BÁO CÁO TỔNG HỢP")
    for i, t in enumerate(["Mở đầu", "Thực trạng", "Kết quả"], 1):
        d.add_heading(f"{i}. {t}", 1)
        d.add_paragraph("Nội dung của phần này được trình bày ngắn gọn để kiểm tra.")
        d.add_heading(f"{i}.1. Nội dung con {i}", 2)
        d.add_paragraph("Nội dung chi tiết hơn của mục con.")
    path = tmp_path / "outline_api.docx"
    d.save(path)
    return path


def test_toc_candidates_in_payload_and_user_override(client, tmp_path):
    jid = _upload_path(client, _outline_doc(tmp_path))
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    cands = {c["text"]: c for c in p["toc_candidates"]}
    assert set(cands) == {"1. Mở đầu", "1.1. Nội dung con 1", "2. Thực trạng", "2.1. Nội dung con 2",
                          "3. Kết quả", "3.1. Nội dung con 3"}
    assert all(c["reason"] == "" and c["where"] == "body" for c in cands.values())
    # người dùng tích bỏ '2. Thực trạng' -> không vào mục lục (chữ vẫn còn trong văn bản)
    opts = {"toc": True, "hinh": False, "bang": False, "exclude": [cands["2. Thực trạng"]["key"]]}
    b = client.post(f"/api/jobs/{jid}/toc", headers=H, json=opts).json()
    assert b["toc"]["gate_removed"] == ["2. Thực trạng"]
    saved = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert saved["toc_opts"]["exclude"] == opts["exclude"]
    assert "2. Thực trạng" in _instrs(client, jid)[1]
    # áp dụng & sửa lại vẫn giữ lựa chọn; danh sách đề mục không đổi khoá
    again = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"spec": saved["spec_raw"]}).json()
    assert again["toc_opts"]["exclude"] == opts["exclude"]
    assert [c["key"] for c in again["toc_candidates"]] == [c["key"] for c in saved["toc_candidates"]]
    # kiểm tra đầu vào
    assert client.post(f"/api/jobs/{jid}/toc", headers=H, json={"exclude": "x"}).status_code == 400
    assert client.post(f"/api/jobs/{jid}/toc", headers=H, json={"include": [""]}).status_code == 400
