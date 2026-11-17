"""Kiểm thử giao diện trình soạn thảo bằng trình duyệt thật (Playwright/Chromium). Bỏ qua nếu máy không có."""
import socket
import threading
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import importlib
    import os
    import uvicorn
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    os.environ["APP_TOKEN"] = "t0k"
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


@pytest.fixture()
def page(server):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {e}")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/soan-thao")
        pg.evaluate("localStorage.clear();localStorage.setItem('nd30_token','t0k')")
        pg.reload()
        pg.wait_for_selector(".page")
        pg.errors = errors
        yield pg
        browser.close()


def _wait_render(pg):
    pg.wait_for_timeout(700)


def test_preview_right_zoom_and_templates(page):
    form = page.locator("#formPane").bounding_box()
    prev = page.locator("#previewPane").bounding_box()
    assert prev["x"] > form["x"] + form["width"] - 1          # xem trước bên phải form
    page.click("[data-zoom='80']")
    assert page.input_value("#zoomRange") == "80"
    page.click("#zoomIn")
    assert page.input_value("#zoomRange") == "90"
    for t in ["NGHI_QUYET", "QUYET_DINH_TRUC_TIEP", "QUYET_DINH_GIAN_TIEP", "KE_HOACH", "CONG_VAN", "CONG_DIEN",
              "GIAY_MOI", "GIAY_GIOI_THIEU", "BIEN_BAN", "GIAY_NGHI_PHEP"]:
        page.select_option("#selType", t)
        _wait_render(page)
        assert page.locator(".page").count() >= 1
        assert page.locator(".tplinfo").inner_text().startswith("Mẫu 1.")
    assert page.locator("#selType option[value='HOP_DONG']").is_disabled()
    assert page.errors == []


def test_block_editor_numbering_paste_and_export(page, tmp_path):
    page.select_option("#selType", "QUYET_DINH_TRUC_TIEP")
    _wait_render(page)
    page.fill("#f_trich_yeu", "Về việc thành lập Tổ công tác")
    ed = page.locator(".blk-ed").first
    ed.click()
    page.keyboard.type("Thành lập Tổ công tác.")
    page.keyboard.press("Enter")
    page.keyboard.type("Giao Văn phòng thực hiện.")
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    page.keyboard.type("Khoản một")
    page.keyboard.press("Control+b")
    page.keyboard.type(" đậm")
    _wait_render(page)
    labels = page.eval_on_selector_all(".blk .blk-num", "e=>e.map(x=>x.textContent.trim())")
    assert labels[:3] == ["Điều 1.", "Điều 2.", "1."]
    page.evaluate("""()=>{const ed=[...document.querySelectorAll('.blk-ed')].at(-1);const dt=new DataTransfer();
      dt.setData('text/plain','a) điểm một\\n- gạch đầu dòng\\nĐiều 9. Điều mới');
      ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));}""")
    _wait_render(page)
    types = page.eval_on_selector_all(".blk select", "e=>e.map(x=>x.value)")
    assert types == ["dieu", "dieu", "khoan", "diem", "bullet", "dieu"]
    text = page.inner_text("#pvPages")
    assert "Điều 3. Điều mới" in text and "a) điểm một" in text
    assert page.locator("#pvPages b, #pvPages [style*='font-weight:700']").count() > 0
    page.on("dialog", lambda d: d.accept())   # còn thiếu trường bắt buộc (thẩm quyền) -> hỏi xác nhận
    with page.expect_download() as dl:
        page.click("#btnWord")
    path = tmp_path / "qd.docx"
    dl.value.save_as(path)
    from docx import Document
    doc = Document(str(path))
    assert any(p.text.startswith("Điều 3. Điều mới") for p in doc.paragraphs)
    assert page.errors == []


def test_new_document_keeps_defaults_and_settings_restore(page):
    page.fill("#f_trich_yeu", "Nội dung tạm")
    page.once("dialog", lambda d: d.accept())
    page.click("#btnNew")
    _wait_render(page)
    assert page.input_value("#f_trich_yeu") == ""
    assert page.input_value("#f_co_quan_ban_hanh") == "VIỆN NGHIÊN CỨU Y"
    page.click("#btnSettings")
    page.fill("[data-key='margins.left']", "33")
    page.click("#saveSettings")
    _wait_render(page)
    assert "33" in page.inner_text("#pvInfo")
    page.click("#resetNd30")
    page.locator("#dlgSettings [data-close]").click()
    _wait_render(page)
    assert "20/20/30/20" in page.inner_text("#pvInfo")
    page.select_option("#selStandard", "hd05")
    _wait_render(page)
    assert "ĐẢNG CỘNG SẢN VIỆT NAM" in page.inner_text("#pvPages")
    assert page.errors == []


def test_import_word_fills_form(page, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from compose_samples import GIAY_NGHI_PHEP
    from nd30fmt.composer import docx_writer, layout
    src = tmp_path / "gnp.docx"
    src.write_bytes(docx_writer.build_docx(layout.build_layout(GIAY_NGHI_PHEP)))
    page.set_input_files("#importFile", str(src))
    page.wait_for_function("document.getElementById('importStatus').textContent.includes('Đã nhập')")
    assert page.input_value("#selType") == "GIAY_NGHI_PHEP"
    assert page.input_value("#f_noi_nghi") == "Nam Định"
    _wait_render(page)
    assert "Xác nhận của cơ quan (tổ chức)" in page.inner_text("#pvPages")
    assert page.errors == []


def test_v39_draft_and_settings_migrate(page):
    import json
    v12 = {"version": 12, "fields": {"hinhThuc": "ADMINISTRATIVE", "loaiVanBan": "QUYET_DINH_TRUC_TIEP",
                                     "trichYeu": "Về việc cũ", "cqBanHanh": "CỤC Y", "maDonVi": "CY",
                                     "soVanBan": "4", "chucVu": "CỤC TRƯỞNG", "signAuth": "KT.", "signAuthOf": "CỤC TRƯỞNG"},
           "contentBlocks": [{"type": "cancu", "html": "Căn cứ A;<br>Căn cứ B."}, {"type": "qd", "html": "QUYẾT ĐỊNH:"},
                             {"type": "dieu", "html": "Nội dung 1"}, {"type": "h2", "html": "khoản"}],
           "recipients": ["Như Điều 3;", "Lưu: VT, VP."]}
    fmt = {"top": 20, "bottom": 20, "left": 32, "right": 20, "body": 14, "line": 1.3, "indent": 1, "before": 6,
           "organization": {"cqChuQuan": "BỘ X", "cqBanHanh": "VIỆN Z", "maDonVi": "VZ", "chucVu": "VIỆN TRƯỞNG", "hoTen": "A"}}
    page.evaluate("([a,b])=>{localStorage.clear();localStorage.setItem('nd30_token','t0k');"
                  "localStorage.setItem('hanhchinh-personal-v12-draft',a);localStorage.setItem('hanhchinh-personal-format-v1',b)}",
                  [json.dumps(v12), json.dumps(fmt)])
    page.reload()
    page.wait_for_selector(".page")
    _wait_render(page)
    assert "bản nháp cũ" in page.inner_text("#saveStatus")
    assert page.input_value("#selType") == "QUYET_DINH_TRUC_TIEP" and page.input_value("#f_ma_co_quan") == "CY"
    assert page.input_value("#f_can_cu") == "Căn cứ A;\nCăn cứ B." and page.input_value("#f_luu") == "VP"
    assert page.eval_on_selector_all(".blk select", "e=>e.map(x=>x.value)") == ["dieu", "khoan"]
    assert "20/20/32/20" in page.inner_text("#pvInfo")
    assert page.errors == []


def test_party_form_fields_and_two_sided(page):
    page.select_option("#selStandard", "hd05")
    _wait_render(page)
    page.select_option("#selType", "CONG_VAN")
    _wait_render(page)
    assert page.locator("#f_kinh_gui").count() == 1 and page.locator("#f_do_khan").count() == 1
    assert page.eval_on_selector_all("#f_quyen_han option", "e=>e.map(x=>x.value)") == ["", "T/M", "K/T", "T/L", "Q."]
    page.select_option("#f_quyen_han", "T/M")
    page.wait_for_selector("#f_quyen_han_cua")
    page.fill("#f_quyen_han_cua", "Ban Thường vụ")
    page.fill("#f_kinh_gui", "Ban Thường vụ Đảng ủy Bộ")
    _wait_render(page)
    text = page.inner_text("#pvPages")
    assert "T/M BAN THƯỜNG VỤ" in text and "Kính gửi:" in text and "Số" in text
    page.select_option("#selType", "BIEN_BAN")
    _wait_render(page)
    assert page.locator("#f_ho_ten_nguoi_ghi").count() == 1 and page.locator("#f_quyen_han").count() == 0
    page.click("#btnSettings")
    page.check("[data-key='in_hai_mat']")
    page.click("#saveSettings")
    page.locator("#dlgSettings [data-close]").click()
    _wait_render(page)
    assert page.errors == []
