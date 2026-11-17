"""Kiểm thử bảo mật: chèn mã qua liên kết, tệp nén bom, dò mã truy cập, tiêu đề bảo mật, link chia sẻ, SSRF."""
import http.server
import importlib
import io
import shutil
import threading
import time
import zipfile

import pytest
from docx import Document
from fastapi.testclient import TestClient

H = {"X-App-Token": "t0k-very-secret-token"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", H["X-App-Token"])
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


def _docx_bytes(paragraphs=("Nội dung",)) -> bytes:
    d = Document()
    for t in paragraphs:
        d.add_paragraph(t)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _bomb(mb: int = 300) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(_docx_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            data = src.read(n)
            if n == "word/document.xml":
                data = data.replace(b"<w:body>", b"<w:body><w:p><w:r><w:t>" + b"A" * (mb * 2**20) + b"</w:t></w:r></w:p>")
            z.writestr(n, data)
    return out.getvalue()


# ------------------------------------------------------------------ liên kết trong Markdown
@pytest.mark.parametrize("url", ["javascript:alert(1)", "\x01javascript:alert(1)", "java\tscript:alert(1)",
                                 " JAVASCRIPT:alert(1)", "vbscript:x", "data:text/html,<script>x</script>",
                                 "java\nscript:alert(1)", "&#x6A;avascript:alert(1)"])
def test_dangerous_link_schemes_blocked(url):
    from nd30fmt.mdlib.store import render_html, safe_url
    assert safe_url(url) == "#"
    out = render_html(f"[bấm]({url})\n\n![ảnh]({url})")
    assert "javascript" not in out.lower().replace("&amp;", "&").replace("\t", "").replace("\n", "") or 'href="#"' in out
    assert "vbscript" not in out.lower() and "data:text" not in out.lower()


@pytest.mark.parametrize("url", ["https://vbpl.vn/a", "http://x.vn", "mailto:a@b.vn", "../../pimg/a/b/c.png",
                                 "#muc-1", "anh/1.png"])
def test_safe_links_kept(url):
    from nd30fmt.mdlib.store import safe_url
    assert safe_url(url) == url


def test_public_share_page_is_sandboxed(client):
    md = "# T\n\n[bấm](\x01javascript:alert(1))\n\n<img src=x onerror=alert(1)>"
    doc = client.post("/api/md/text", headers=H, json={"name": "x", "markdown": md}).json()
    did = (doc.get("doc") or doc)["id"]
    url = client.post(f"/api/md/docs/{did}/share", headers=H, json={"on": True}).json()["share_url"]
    r = client.get("/" + url)
    assert r.status_code == 200
    assert "javascript" not in r.text.lower() and "<img src=x" not in r.text
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp and "script-src" not in csp
    assert r.headers["referrer-policy"] == "no-referrer"


def test_share_link_expires(client, monkeypatch):
    from nd30fmt.mdlib import store
    doc = client.post("/api/md/text", headers=H, json={"name": "x", "markdown": "nội dung"}).json()
    did = (doc.get("doc") or doc)["id"]
    url = client.post(f"/api/md/docs/{did}/share", headers=H, json={"on": True}).json()["share_url"]
    assert client.get("/" + url).status_code == 200
    real = time.time
    monkeypatch.setattr(store.time, "time", lambda: real() + 31 * 86400)
    assert client.get("/" + url).status_code == 404
    monkeypatch.setattr(store, "SHARE_TTL_DAYS", 0.0)         # 0 = không hết hạn
    assert client.get("/" + url).status_code == 200


# ------------------------------------------------------------------ tệp nén bom
def test_zip_bomb_rejected_before_parsing(client):
    from nd30fmt import jobs
    data = _bomb()
    assert len(data) < 2 * 2**20
    assert "quá lớn" in jobs.check_docx_bytes(data)
    r = client.post("/api/jobs", headers=H, files=[("files", ("b.docx", data, "application/octet-stream"))],
                    data={"wait": "true"})
    j = r.json()["jobs"][0]
    assert not j["ok"] and "quá lớn" in j["message"]
    r = client.post("/api/md/docs", headers=H, files=[("files", ("b.docx", data, "application/octet-stream"))])
    res = r.json()["results"][0]
    assert not res["ok"] and "quá lớn" in res["message"]


# ------------------------------------------------------------------ mã truy cập
def test_non_ascii_token_is_401(client):
    r = client.get("/api/me", headers={"X-App-Token": "é".encode("latin-1")})
    assert r.status_code == 401


def test_bruteforce_blocked(client, monkeypatch):
    import nd30fmt.web as web
    monkeypatch.setattr(web, "AUTH_MAX_FAILS", 5)
    codes = [client.get("/api/me", headers={"X-App-Token": f"sai-{i}"}).status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    assert client.get("/api/me", headers=H).status_code == 429       # đang bị chặn: cả mã đúng cũng phải chờ
    web._fails.clear()
    assert client.get("/api/me", headers=H).status_code == 200


def test_open_mode_cannot_change_shared_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("APP_TOKEN", raising=False)
    monkeypatch.delenv("OPEN_ADMIN", raising=False)
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    c = TestClient(web.app)
    raw = c.get("/api/spec").json()["raw"]
    assert c.put("/api/spec", json=raw).status_code == 403
    monkeypatch.setattr(web, "OPEN_ADMIN", True)
    assert c.put("/api/spec", json=raw).status_code == 200


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]


def test_login_link_uses_fragment():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "nd30fmt" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'location.hash' in html and 'hs.get("token")' in html


# ------------------------------------------------------------------ SSRF qua LibreOffice
def _docx_with_remote_refs(url: str) -> bytes:
    """Ảnh liên kết ngoài kiểu DrawingML (LibreOffice 24.2 TẢI thật khi dựng PDF – đã kiểm), kiểu VML và trường
    INCLUDEPICTURE, kèm một siêu liên kết thường phải được giữ."""
    from PIL import Image
    from docx.shared import Pt
    d = Document()
    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, "PNG")
    png.seek(0)
    d.add_picture(png, width=Pt(20))
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    blip = d.element.body.xpath(".//a:blip")[0]
    blip.set(rel_ns + "link", d.part.relate_to(
        url + "/blip.png", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", is_external=True))
    del blip.attrib[rel_ns + "embed"]
    p = d.add_paragraph("Có ảnh liên kết ngoài: ")
    rid = d.part.relate_to(url + "/rel.png", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                           is_external=True)
    p.add_run().element.append(__import__("docx.oxml", fromlist=["parse_xml"]).parse_xml(
        '<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<v:shape style="width:10pt;height:10pt"><v:imagedata r:id="{rid}"/></v:shape></w:pict>'))
    r = d.add_paragraph().add_run()
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for kind, txt in (("begin", None), ("instr", f' INCLUDEPICTURE "{url}/field.png" \\d '), ("end", None)):
        if kind == "instr":
            e = OxmlElement("w:instrText")
            e.set(qn("xml:space"), "preserve")
            e.text = txt
        else:
            e = OxmlElement("w:fldChar")
            e.set(qn("w:fldCharType"), kind)
        r._r.append(e)
    link = d.part.relate_to("https://vbpl.vn", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                            is_external=True)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue(), link


def test_strip_external_refs(tmp_path):
    from nd30fmt.jobs import strip_external_refs
    data, link_rid = _docx_with_remote_refs("http://127.0.0.1:9")
    p = tmp_path / "a.docx"
    p.write_bytes(data)
    assert strip_external_refs(p) == 3
    with zipfile.ZipFile(p) as z:
        allxml = b"".join(z.read(n) for n in z.namelist() if n.endswith((".xml", ".rels")))
        assert b"127.0.0.1" not in allxml
        assert b"https://vbpl.vn" in z.read("word/_rels/document.xml.rels")     # siêu liên kết thường được giữ
    Document(str(p))                                                             # tệp vẫn mở được


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("pdftoppm")), reason="cần LibreOffice")
def test_print_preview_does_not_fetch_remote(client):
    hits = []

    class H_(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H_)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        data, _ = _docx_with_remote_refs(f"http://127.0.0.1:{srv.server_port}")
        r = client.post("/api/jobs", headers=H, files=[("files", ("a.docx", data, "application/octet-stream"))],
                        data={"wait": "true", "spell": "false"})
        jid = r.json()["jobs"][0]["id"]
        assert client.get(f"/api/jobs/{jid}/pages/original", headers=H).status_code == 200
        time.sleep(0.5)
        assert hits == []
    finally:
        srv.shutdown()
