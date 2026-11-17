"""Giao diện tab Chuyển Markdown (Playwright/Chromium): tải file, tìm kiếm, chuyển sang tab Soạn thảo. Bỏ qua nếu không có."""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from tests.common.test_ui_composer import server  # noqa: E402,F401  (dùng chung máy chủ thử)

FIX = Path(__file__).resolve().parents[1] / "nd30" / "fixtures"


def test_markdown_tab_upload_search_and_compose(server):  # noqa: F811
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {e}")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/")
        pg.evaluate("localStorage.clear();localStorage.setItem('nd30_token','t0k')")
        pg.reload()
        pg.click("#tabMarkdown")
        md = pg.frame_locator("#markdownFrame")
        md.locator("#file").set_input_files(str(FIX / "cv236.docx"))
        md.locator("#pickList li").first.wait_for()                  # chọn xong chỉ đưa vào danh sách chờ
        assert md.locator(".item").count() == 0
        md.locator("#btnUpload").click()
        md.locator(".item").first.wait_for(timeout=20000)
        md.locator("#q").fill("nghi dinh")                       # tìm không dấu
        pg.wait_for_timeout(800)
        assert md.locator(".item").count() == 1
        md.locator(".item").first.click()
        md.locator("[data-compose=nd30]").click()
        pg.wait_for_function("document.querySelector('#tabCompose').getAttribute('aria-selected')==='true'", timeout=10000)
        comp = None
        for _ in range(100):
            comp = next((f for f in pg.frames if "soan-thao" in f.url), None)
            if comp:
                break
            pg.wait_for_timeout(100)
        assert comp is not None
        comp.wait_for_function("typeof draft==='function' && draft().type_id==='CONG_VAN' && draft().fields.so==='236'",
                               timeout=15000)
        assert not errors, errors
        browser.close()


def test_markdown_tab_mobile_pick_then_upload(server, tmp_path):  # noqa: F811
    """Điện thoại: chọn file -> hiện danh sách và nút Tải lên; bỏ file chưa hỗ trợ; tải lên thành công."""
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {e}")
        ctx = browser.new_context(**p.devices["iPhone 13"])
        ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/chuyen-md")
        pg.evaluate("localStorage.setItem('nd30_token','t0k')")
        pg.reload()
        bad = tmp_path / "anh.heic"
        bad.write_bytes(b"x")
        pg.set_input_files("#file", [str(FIX / "cv236.docx")])
        pg.set_input_files("#file", [str(bad)])                        # chọn thêm lần 2: không mất file lần 1
        pg.wait_for_function("document.querySelectorAll('#pickList li').length===2")
        assert pg.locator("#btnUpload").is_visible() and pg.locator("#pickList li.bad").count() == 1
        box = pg.locator("#btnUpload").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["height"] >= 32   # nằm gọn, đủ lớn để chạm
        pg.locator("#btnUpload").tap()
        pg.wait_for_function("document.querySelector('#upStatus').textContent.includes('Đã chuyển')", timeout=20000)
        st = pg.locator("#upStatus").inner_text()
        assert "Đã chuyển 1 file" in st and "anh.heic: định dạng chưa hỗ trợ" in st
        assert pg.locator("#pick").is_hidden()
        assert not errors, errors
        browser.close()


def test_upload_error_is_shown_not_reset(server):  # noqa: F811
    """Lỗi từ máy chủ/nginx (VD 504, 413) phải hiện ra, không quay về trạng thái 'Đã chọn' như chưa có gì."""
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {e}")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.route("**/api/md/jobs", lambda r: r.fulfill(status=504, body="<html>504 Gateway Time-out</html>",
                                                        content_type="text/html"))
        pg.goto(server + "/chuyen-md")
        pg.evaluate("localStorage.setItem('nd30_token','t0k')")
        pg.reload()
        pg.set_input_files("#file", [str(FIX / "cv236.docx")])
        pg.wait_for_selector("#pickList li")
        pg.click("#btnUpload")
        pg.wait_for_function("document.querySelector('#upStatus').classList.contains('err')", timeout=10000)
        st = pg.locator("#upStatus").inner_text()
        assert st.startswith("Lỗi:") and "quá lâu" in st
        assert pg.locator("#btnUpload").is_enabled() and pg.locator("#pickList li").count() == 1   # còn file để thử lại
        browser.close()
