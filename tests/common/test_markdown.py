"""Tab Chuyển Markdown: chuyển đổi, thư viện riêng theo mã, tìm kiếm, tải về, chia sẻ, chuyển sang Soạn thảo."""
import importlib
import io
import shutil
import zipfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "nd30" / "fixtures"
H = {"X-App-Token": "t0k"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "t0k")
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


def _up(client, name, data, headers=H):
    r = client.post("/api/md/docs", headers=headers, files=[("files", (name, data, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def _docx_with_image(tmp_path):
    from PIL import Image
    img = tmp_path / "a.png"
    Image.new("RGB", (40, 20), (200, 30, 30)).save(img)
    d = Document()
    d.add_heading("Báo cáo thử nghiệm", 1)
    p = d.add_paragraph()
    p.add_run("Đoạn có ").bold = False
    p.add_run("chữ đậm").bold = True
    d.add_picture(str(img))
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Năm", "Sản lượng", "2025", "12|3"
    d.add_paragraph("Đoạn sau bảng.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_page_and_auth(client):
    html = client.get("/chuyen-md").text
    assert "Chuyển tài liệu sang Markdown" in html and "api/md/docs" in html
    assert client.get("/api/md/docs").status_code == 401
    home = client.get("/").text
    assert 'id="tabMarkdown"' in home and 'id="markdownFrame"' in home


def test_docx_to_markdown_order_images_and_table(client, tmp_path):
    res = _up(client, "bao cao.docx", _docx_with_image(tmp_path))
    assert res["ok"], res
    doc_id = res["doc"]["id"]
    r = client.get(f"/api/md/docs/{doc_id}", headers=H).json()
    md = r["markdown"]
    assert md.index("# Báo cáo thử nghiệm") < md.index("**chữ đậm**") < md.index("![") < md.index("| Năm |") \
        < md.index("Đoạn sau bảng.")                                         # đúng thứ tự trong văn bản
    assert "12\\|3" in md                                                     # ký tự | trong ô được thoát
    assert "<table>" in r["html"] and "<strong>chữ đậm</strong>" in r["html"]
    img = r["html"].split('src="')[1].split('"')[0]
    assert img.startswith(f"api/md/img/{doc_id}/")
    assert client.get("/" + img).status_code == 200                           # ảnh dùng khoá riêng, không cần header
    assert client.get(img.rsplit("/", 2)[0].replace(img.split("/")[4], "sai") + "/" + img.rsplit("/", 1)[1]).status_code == 404


def test_html_is_escaped(client):
    d = client.post("/api/md/text", headers=H, json={"name": "xss", "markdown": "<script>alert(1)</script>\n\n[x](javascript:alert(1))"}).json()
    html = client.get(f"/api/md/docs/{d['id']}", headers=H).json()["html"]
    assert "<script>" not in html and "javascript:" not in html


def test_search_without_diacritics_update_rename_delete(client):
    a = client.post("/api/md/text", headers=H, json={"name": "kế hoạch", "markdown": "Lưu trữ hồ sơ điện tử năm 2026"}).json()
    client.post("/api/md/text", headers=H, json={"name": "khác", "markdown": "Nội dung không liên quan"})
    found = client.get("/api/md/docs", headers=H, params={"q": "luu tru"}).json()["docs"]
    assert [d["id"] for d in found] == [a["id"]] and "<mark>" in found[0]["snippet"]
    client.put(f"/api/md/docs/{a['id']}", headers=H, json={"markdown": "Năng lượng tái tạo theo Nghị định đường dây"})
    hit = client.get("/api/md/docs", headers=H, params={"q": "nghi dinh duong"}).json()["docs"]   # "d" khớp "đ"
    assert [d["id"] for d in hit] == [a["id"]]
    assert "<mark>Nghị</mark> <mark>định</mark> <mark>đường</mark>" in hit[0]["snippet"]          # trích giữ chữ "đ"
    assert client.get("/api/md/docs", headers=H, params={"q": "định"}).json()["docs"][0]["id"] == a["id"]
    assert client.get("/api/md/docs", headers=H, params={"q": "nang luong"}).json()["docs"][0]["id"] == a["id"]
    assert not client.get("/api/md/docs", headers=H, params={"q": "luu tru"}).json()["docs"]
    assert client.put(f"/api/md/docs/{a['id']}", headers=H, json={"filename": "ten moi.md"}).json()["filename"] == "ten moi.md"
    assert client.delete(f"/api/md/docs/{a['id']}", headers=H).status_code == 200
    assert client.get(f"/api/md/docs/{a['id']}", headers=H).status_code == 404


def test_downloads(client, tmp_path):
    res = _up(client, "bao cao.docx", _docx_with_image(tmp_path))
    i = res["doc"]["id"]
    md = client.get(f"/api/md/docs/{i}/download/md", headers=H)
    assert md.status_code == 200 and "{IMGBASE}" not in md.text and ".md" in md.headers["content-disposition"]
    orig = client.get(f"/api/md/docs/{i}/download/original", headers=H)
    assert orig.content[:2] == b"PK"
    dx = client.get(f"/api/md/docs/{i}/download/docx", headers=H)
    assert dx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dx.content)) as z:
        assert z.testzip() is None
    assert any("chữ đậm" in p.text for p in Document(io.BytesIO(dx.content)).paragraphs)


def test_owner_isolation_and_user_deletion(client):
    u = client.post("/api/admin/users", headers=H, json={"name": "Người A"}).json()
    hu = {"X-App-Token": u["token"]}
    mine = client.post("/api/md/text", headers=hu, json={"name": "riêng", "markdown": "bí mật"}).json()
    assert client.get("/api/md/docs", headers=H).json()["docs"] == []                       # quản trị không thấy
    assert client.get(f"/api/md/docs/{mine['id']}", headers=H).status_code == 404
    assert [d["id"] for d in client.get("/api/md/docs", headers=hu).json()["docs"]] == [mine["id"]]
    client.delete(f"/api/admin/users/{u['id']}", headers=H)                                # chuyển cho quản trị
    assert [d["id"] for d in client.get("/api/md/docs", headers=H).json()["docs"]] == [mine["id"]]


def test_share_public_link_and_revoke(client, tmp_path):
    res = _up(client, "bao cao.docx", _docx_with_image(tmp_path))
    i = res["doc"]["id"]
    url = client.post(f"/api/md/docs/{i}/share", headers=H, json={"on": True}).json()["share_url"]
    page = client.get("/" + url)
    assert page.status_code == 200 and "Báo cáo thử nghiệm" in page.text and 'name="robots" content="noindex"' in page.text
    img = page.text.split('src="')[1].split('"')[0]
    assert img.startswith("../../pimg/")
    assert client.get("/md/" + img[len("../../"):]).status_code == 200
    client.post(f"/api/md/docs/{i}/share", headers=H, json={"on": False})
    assert client.get("/" + url).status_code == 404


def test_unsupported_and_empty(client):
    r = _up(client, "a.exe", b"MZ")
    assert not r["ok"] and "chưa hỗ trợ" in r["message"]
    r = _up(client, "rong.txt", b"   ")
    assert not r["ok"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="không có tesseract")
def test_image_ocr(client, tmp_path):
    import subprocess
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    if "vie" not in langs:
        pytest.skip("thiếu dữ liệu tiếng Việt cho tesseract")
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 120), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", 44)
    ImageDraw.Draw(img).text((20, 30), "Công văn số 191", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    res = _up(client, "anh.png", buf.getvalue())
    assert res["ok"], res
    md = client.get(f"/api/md/docs/{res['doc']['id']}", headers=H).json()["markdown"]
    assert "191" in md


def test_pdf_conversion(client):
    pytest.importorskip("pymupdf")
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Bao cao nang luong 2026 " * 3, fontsize=12)
    res = _up(client, "a.pdf", pdf.tobytes())
    assert res["ok"], res
    md = client.get(f"/api/md/docs/{res['doc']['id']}", headers=H).json()["markdown"]
    assert "--- Trang 1 ---" in md and "nang luong 2026" in md


def test_markdown_to_compose_draft(client):
    from nd30fmt.mdlib import doc_to_md
    from nd30fmt.composer import layout
    md = doc_to_md.convert(FIX / "cv236.docx")
    d = client.post("/api/md/text", headers=H, json={"name": "cv236", "markdown": md}).json()
    r = client.get(f"/api/md/docs/{d['id']}/compose", headers=H, params={"standard": "nd30"}).json()
    f = r["draft"]["fields"]
    assert r["draft"]["type_id"] == "CONG_VAN"
    assert (f["so"], f["ma_co_quan"], f["ma_don_vi"], f["ngay"]) == ("236", "CT", "VP", "2020-03-23")
    assert f["co_quan_ban_hanh"] == "CỤC THUẾ TỈNH SÓC TRĂNG" and f["trich_yeu"].startswith("thực hiện Nghị định")
    assert (f["quyen_han"], f["quyen_han_cua"], f["chuc_vu"], f["ho_ten"]) == ("KT.", "CỤC TRƯỞNG", "PHÓ CỤC TRƯỞNG", "Tôn Bạch")
    assert any(b["type"] == "la_ma" for b in f["noi_dung"]) and any(b["type"] == "khoan" for b in f["noi_dung"])
    layout.build_layout(r["draft"])                                            # dựng được bố cục từ bản thảo
    q = client.post("/api/md/compose", headers=H, json={"markdown": "# QUYẾT ĐỊNH VỀ VIỆC THÀNH LẬP TỔ\n"
                                                                    "**Điều 1.** Thành lập.\n1. Ông A;\na) việc một"}).json()
    assert q["draft"]["type_id"] == "QUYET_DINH_TRUC_TIEP"
    assert [b["type"] for b in q["draft"]["fields"]["noi_dung"]] == ["dieu", "khoan", "diem"]
    p = client.post("/api/md/compose", headers=H, json={"markdown": "ĐẢNG CỘNG SẢN VIỆT NAM\nNGHỊ QUYẾT\nNội dung."}).json()
    assert p["draft"]["standard"] == "hd05"


def _scan_pdf(pages, text="Bao cao nang luong tai tao 2026"):
    import pymupdf
    src = pymupdf.open()
    for i in range(pages):
        pg = src.new_page()
        pg.insert_text((72, 90), f"Trang {i + 1}: {text}", fontsize=16)
    out = pymupdf.open()
    for pg in src:                                    # chỉ còn ảnh, không còn lớp chữ -> phải OCR
        pix = pg.get_pixmap(dpi=150)
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    return out.tobytes()


def _wait_job(client, jid, headers=H, timeout=120):
    import time
    seen = []
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/md/jobs/{jid}", headers=headers).json()
        seen.append(st)
        if st["state"] == "done":
            return st, seen
        time.sleep(0.2)
    raise AssertionError("việc chuyển đổi không xong")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="không có tesseract")
def test_background_job_scanned_pdf_progress_and_owner(client):
    pytest.importorskip("pymupdf")
    r = client.post("/api/md/jobs", headers=H, files=[("files", ("scan.pdf", _scan_pdf(3), "application/pdf")),
                                                       ("files", ("x.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 200
    job = r.json()
    assert job["state"] in ("queued", "running", "done") and len(job["files"]) == 2
    u = client.post("/api/admin/users", headers=H, json={"name": "B"}).json()
    assert client.get(f"/api/md/jobs/{job['id']}", headers={"X-App-Token": u["token"]}).status_code == 404  # mã khác
    st, _ = _wait_job(client, job["id"])
    ok = [x for x in st["results"] if x["ok"]]
    bad = [x for x in st["results"] if not x["ok"]]
    assert len(ok) == 1 and bad[0]["filename"] == "x.exe" and "chưa hỗ trợ" in bad[0]["message"]
    f = st["files"][0]
    assert (f["page"], f["pages"], f["state"]) == (3, 3, "done")
    md = client.get(f"/api/md/docs/{ok[0]['doc']['id']}", headers=H).json()["markdown"]
    assert md.count("--- Trang") == 3 and "năng lượng tái tạo" in md and "![" not in md   # không chèn ảnh quét;
    # chữ OCR không dấu "nang luong tai tao" đã được tự sửa dấu
    assert client.get("/api/md/jobs/khongco", headers=H).status_code == 404


def test_pdf_page_limit_is_reported_not_silent(client, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    from nd30fmt.mdlib import doc_to_md
    monkeypatch.setattr(doc_to_md, "MAX_PAGES", 2)
    pdf = pymupdf.open()
    for i in range(4):
        pdf.new_page().insert_text((72, 72), f"Trang so {i + 1} " * 8, fontsize=12)
    job = client.post("/api/md/jobs", headers=H, files=[("files", ("dai.pdf", pdf.tobytes(), "application/pdf"))]).json()
    st, _ = _wait_job(client, job["id"])
    res = st["results"][0]
    assert res["ok"] and "warning" in res
    md = client.get(f"/api/md/docs/{res['doc']['id']}", headers=H).json()["markdown"]
    assert md.startswith("> [Chỉ chuyển 2/4 trang đầu") and md.count("--- Trang") == 2


def test_ocr_runs_single_threaded(monkeypatch, tmp_path):
    """tesseract chạy 1 luồng/tiến trình (tránh tranh CPU làm chậm ~4 lần trên VPS ít nhân)."""
    import subprocess
    from nd30fmt.mdlib import doc_to_md
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert doc_to_md._tesseract(tmp_path / "a.png") == "ok"
    assert seen["env"].get("OMP_THREAD_LIMIT") == "1"


def test_frontmatter_not_confused_with_pdf_page_marker():
    from nd30fmt.mdlib import md_to_docx_nd30 as mdx
    md = "--- Trang 1 ---\n\nKý bởi: X\n\n--- Trang 2 ---\n\nNội dung"
    assert mdx.split_frontmatter(md) == ({}, md)                       # trước đây mất trang 1 và gây lỗi 500
    meta, body = mdx.split_frontmatter("---\nloai_van_ban: Công văn\n---\nThân")
    assert meta == {"loai_van_ban": "Công văn"} and body == "Thân"


def _signed_scan_pdf():
    """Mô phỏng công văn quét có lớp chữ ký số (dạng file gửi VPCP): ảnh cả trang + dòng chữ "Ký bởi …"."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont
    font = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
    pages = [
        ["BỘ TÀI CHÍNH          CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM", "Độc lập - Tự do - Hạnh phúc", "",
         "Số: 15651/BTC-TĐĐT          Hà Nội, ngày 03 tháng 10 năm 2026", "V/v hồ sơ đề nghị chấp thuận chủ",
         "trương đầu tư các dự án", "", "Kính gửi: Thủ tướng Chính phủ", "",
         "Tại văn bản số 9608/VPCP-CN, Phó Thủ tướng giao các Bộ nghiên cứu các nội dung",
         "kiến nghị của doanh nghiệp và báo cáo kết quả trước ngày 05 tháng 10 năm 2026.", "",
         "Bộ Tài chính kính báo cáo Thủ tướng Chính phủ xem xét./.", "",
         "Nơi nhận:                                   KT. BỘ TRƯỞNG", "- Như trên;                                  THỨ TRƯỞNG",
         "- Văn phòng Chính phủ;", "- Lưu: VT, TĐĐT.", "", "                                             Trần Quốc Phương"],
        ["CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM", "Độc lập - Tự do - Hạnh phúc", "", "PHỤ LỤC KÈM THEO", "Nội dung phụ lục."],
    ]
    doc = pymupdf.open()
    for lines in pages:
        im = Image.new("L", (1240, 1754), 255)
        d = ImageDraw.Draw(im)
        for k, t in enumerate(lines):
            d.text((110, 140 + k * 52), t, fill=0, font=ImageFont.truetype(font, 30))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        pg = doc.new_page()
        pg.insert_image(pg.rect, stream=buf.getvalue())
        pg.insert_font(fontname="lib", fontfile=font)
        pg.insert_text((20, 20), "Ký bởi: BỘ TÀI CHÍNH Cơ quan: 28 Trần Hưng Đạo Thời gian ký: 04/10/2026 16:28:05",
                       fontname="lib", fontsize=7)
    return doc.tobytes()


@pytest.mark.skipif(not shutil.which("tesseract"), reason="không có tesseract")
def test_signed_scan_pdf_is_ocred_and_composes(client):
    pytest.importorskip("pymupdf")
    job = client.post("/api/md/jobs", headers=H, files=[("files", ("Gui VPCP.pdf", _signed_scan_pdf(), "application/pdf"))]).json()
    st, _ = _wait_job(client, job["id"])
    doc_id = st["results"][0]["doc"]["id"]
    md = client.get(f"/api/md/docs/{doc_id}", headers=H).json()["markdown"]
    assert "Chữ ký số: Ký bởi: BỘ TÀI CHÍNH" in md                    # giữ thông tin chữ ký số
    assert "Thủ tướng Chính phủ" in md and "![" not in md               # trang quét đã được nhận dạng chữ
    r = client.get(f"/api/md/docs/{doc_id}/compose", headers=H, params={"standard": "nd30"})
    assert r.status_code == 200, r.text                                 # trước đây: HTTP 500
    d = r.json()
    f = d["draft"]["fields"]
    assert d["draft"]["type_id"] == "CONG_VAN"
    assert (f.get("ma_co_quan"), f.get("ma_don_vi"), f.get("ngay")) == ("BTC", "TĐĐT", "2026-10-03")
    assert f["trich_yeu"].startswith("hồ sơ đề nghị chấp thuận chủ trương")   # trích yếu 2 dòng được nối
    assert f["kinh_gui"] == ["Thủ tướng Chính phủ"]
    assert f.get("quyen_han") == "KT." and f.get("noi_nhan") and f.get("luu", "").startswith("TĐĐT")
    texts = [b["html"] for b in f["noi_dung"]]
    assert texts[0].startswith("Tại văn bản số 9608") and "kiến nghị của doanh nghiệp" in texts[0]   # dòng OCR nối thành đoạn
    assert not any("Ký bởi" in t or "PHỤ LỤC" in t for t in texts)      # bỏ chữ ký số, chỉ lấy văn bản chính
    assert any("chỉ đưa văn bản chính" in w for w in d["warnings"])


def test_compose_limits_blocks():
    from nd30fmt.mdlib import compose
    md = "V/v thử\n\nKính gửi: A\n\n" + "\n\n".join(f"Đoạn {i}." for i in range(compose.MAX_BLOCKS + 50))
    r = compose.markdown_to_draft(md, "nd30")
    assert len(r["draft"]["fields"]["noi_dung"]) == compose.MAX_BLOCKS and any("chỉ đưa" in w for w in r["warnings"])


def test_ocr_diacritic_autofix_and_undo(client, monkeypatch):
    """OCR sai dấu -> tự sửa theo ngữ cảnh, tô màu, hoàn tác từng nhóm hoặc khôi phục toàn bộ bản nhận dạng."""
    pytest.importorskip("pymupdf")
    from nd30fmt.mdlib import doc_to_md, vnfix
    if not vnfix.available():
        pytest.skip("thiếu dữ liệu mô hình")
    ocr = ("Bộ Tài chính xin báo cáo Thủ tướng Chính phủ xem xét theo thâm quyên, bảo dam đúng quy định "
           "pháp luật; dé nghị các Bộ phối hợp xử lý hồ sơ dự án điện gió ngoài khơi. Nghị định số 30/2020/NĐ-CP.")
    monkeypatch.setattr(doc_to_md, "_tesseract", lambda *a, **k: ocr)
    job = client.post("/api/md/jobs", headers=H, files=[("files", ("q.pdf", _scan_pdf(1), "application/pdf"))]).json()
    st, _ = _wait_job(client, job["id"])
    doc_id = st["results"][0]["doc"]["id"]
    r = client.get(f"/api/md/docs/{doc_id}", headers=H).json()
    md = r["markdown"]
    assert "theo thẩm quyền, bảo đảm đúng quy định" in md and "đề nghị các Bộ" in md
    assert "30/2020/NĐ-CP" in md and "\ue010" not in md and "\ue011" not in md          # ký hiệu, số giữ nguyên
    pairs = {(g["from"], g["to"]) for g in r["ocr"]["groups"]}
    assert {("thâm", "thẩm"), ("quyên", "quyền"), ("dam", "đảm"), ("dé", "đề")} <= pairs
    assert r["ocr"]["fixed"] >= 4 and not r["ocr"]["edited"]
    assert 'class="ocrfix" title="Đã sửa từ bản nhận dạng: thâm">thẩm</mark>' in r["html"]
    # hoàn tác một nhóm
    r = client.post(f"/api/md/docs/{doc_id}/ocrfix", headers=H, json={"disabled": [["dam", "đảm"]]}).json()
    assert "bảo dam đúng" in r["markdown"] and "thẩm quyền" in r["markdown"]
    assert [g["on"] for g in r["ocr"]["groups"] if g["from"] == "dam"] == [False]
    # khôi phục bản nhận dạng gốc, rồi áp dụng lại
    r = client.post(f"/api/md/docs/{doc_id}/ocrfix", headers=H, json={"mode": "raw"}).json()
    assert ocr in r["markdown"] and r["ocr"]["fixed"] == 0
    assert client.get("/api/md/docs", headers=H, params={"q": "tham quyen"}).json()["docs"]      # tìm kiếm cập nhật
    r = client.post(f"/api/md/docs/{doc_id}/ocrfix", headers=H, json={"mode": "all"}).json()
    assert "thẩm quyền" in r["markdown"]
    # sửa tay -> báo đã sửa tay, không tô màu
    client.put(f"/api/md/docs/{doc_id}", headers=H, json={"markdown": r["markdown"] + "\nThêm dòng."})
    r = client.get(f"/api/md/docs/{doc_id}", headers=H).json()
    assert r["ocr"]["edited"] and "ocrfix" not in r["html"]
    # tài liệu Word không qua OCR: không có phần sửa dấu, không cho gọi
    w = client.post("/api/md/text", headers=H, json={"name": "w", "markdown": "thâm quyên"}).json()
    assert client.get(f"/api/md/docs/{w['id']}", headers=H).json()["ocr"] is None
    assert client.post(f"/api/md/docs/{w['id']}/ocrfix", headers=H, json={"mode": "raw"}).status_code == 400


def test_vnfix_does_not_touch_clean_or_special_text():
    from nd30fmt.mdlib import vnfix
    if not vnfix.available():
        pytest.skip("thiếu dữ liệu mô hình")
    clean = ("Căn cứ Nghị định số 30/2020/NĐ-CP ngày 05 tháng 3 năm 2020 của Chính phủ về công tác văn thư; "
             "theo đề nghị của Chánh Văn phòng, Bộ trưởng Bộ X quyết định. Ví dụ: Mát-xcơ-va, (.doc), "
             "Số 06-CT/TU, mục o) và a) giữ nguyên. Ông Nguyễn Văn A, bà Trần Thị Hoà; thủy lợi, hòa bình, hoá chất.")
    out, fx = vnfix.correct_text(clean)
    assert out == clean and fx == []
