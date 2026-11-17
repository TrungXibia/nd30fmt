"""Giao diện chính tả (Playwright/Chromium): tải file, xem nhóm chính tả, bỏ tick một chỗ rồi áp dụng lại. Bỏ qua nếu không có."""
import io

import pytest

pw = pytest.importorskip("playwright.sync_api")
from tests.common.test_spell import _make  # noqa: E402
from tests.common.test_ui_composer import server  # noqa: E402,F401  (dùng chung máy chủ thử)


def test_spell_panel_flow(server, tmp_path):  # noqa: F811
    src = tmp_path / "chinh_ta.docx"
    _make(src)
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
        assert pg.locator("#optSpell").is_checked()
        pg.set_input_files("#fileIn", str(src))
        pg.click("#upBtn")
        pg.wait_for_selector('#tabs [data-t="spell"]', timeout=60000)
        pg.wait_for_function("document.querySelector('#cntSpell') && !document.querySelector('#cntSpell').hidden", timeout=60000)
        assert pg.locator("#spBox").count() == 1 and pg.locator("#tab-errs #spBox").count() == 0   # không còn nằm trong tab Lỗi
        pg.click('#tabs [data-t="spell"]')
        assert "6 chỗ đã sửa" in pg.inner_text("#spBox h3")
        pg.click('[data-spk="pair"] .h')
        box = pg.locator('[data-spk="pair"] [data-spi]')
        assert box.count() == 3                                  # sử lý, chính xát, phát triễn
        box.first.uncheck()
        pg.wait_for_selector("#applybar:not([hidden])")
        assert "chính tả" in pg.inner_text("#dirtyTxt")
        pg.click("#spApply")
        pg.wait_for_function("document.querySelector('#spBox h3').textContent.includes('5 chỗ đã sửa')", timeout=60000)
        assert pg.locator("#dlClean").count() == 1
        assert not errors, errors
        browser.close()


def test_toc_tab_flow(server, tmp_path):  # noqa: F811
    from docx import Document
    d = Document()
    d.add_paragraph("BÁO CÁO TỔNG HỢP")
    d.add_heading("1. Mở đầu", 1)
    d.add_paragraph("Nội dung.")
    d.add_paragraph("Hình 1. Sơ đồ tổ chức")
    d.add_paragraph("Bảng 1: Số liệu năm 2025")
    d.add_heading("2. Kết quả", 1)
    src = tmp_path / "muc_luc.docx"
    d.save(src)
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
        assert pg.locator("#tocBtn").count() == 0                      # nút cũ trên thanh công cụ đã bỏ
        pg.set_input_files("#fileIn", str(src))
        pg.click("#upBtn")
        pg.wait_for_selector('#tabs [data-t="toc"]', timeout=60000)
        pg.wait_for_selector("#tocGo", state="attached", timeout=60000)
        pg.click('#tabs [data-t="toc"]')
        assert pg.locator('[data-toc="toc"]').is_checked()             # mặc định chỉ Mục lục
        assert not pg.locator('[data-toc="hinh"]').is_checked() and not pg.locator('[data-toc="bang"]').is_checked()
        n_rows = pg.locator(".toc-cand").count()
        assert n_rows >= 1                                             # danh sách đề mục có ô tích
        pg.locator(".toc-cand input").first.uncheck()                  # bỏ một đề mục khỏi mục lục
        assert pg.evaluate("S.tocOpts.exclude.length") == 1
        pg.locator(".toc-cand input").first.check()                    # tích lại -> không còn bị bỏ
        assert pg.evaluate("S.tocOpts.exclude.length") == 0
        pg.check('[data-toc="hinh"]')
        pg.click("#tocGo")
        pg.wait_for_selector("#tocOff", timeout=60000)                 # có nút Gỡ sau khi tạo
        res = pg.inner_text("#tab-toc .toc-res")
        assert "Mục lục (mới)" in res and "Danh mục hình (mới)" in res and "Danh mục bảng" not in res
        pg.click("#tocOff")
        pg.wait_for_selector("#tocOff", state="detached", timeout=60000)
        assert pg.locator("#tab-toc .toc-res").count() == 0
        assert not errors, errors
        browser.close()
