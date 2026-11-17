"""Giao diện điện thoại (giả lập iPhone 13, Chromium): không tràn ngang, hàng tab dính mép trên, khung Soạn thảo/
Markdown vừa màn hình, thanh Xuất Word nằm trong màn hình. Bỏ qua nếu không có Playwright/Chromium."""
import pytest

pw = pytest.importorskip("playwright.sync_api")
from tests.common.test_ui_composer import server  # noqa: E402,F401  (dùng chung máy chủ thử)

NO_OVERFLOW = "()=>document.documentElement.scrollWidth<=innerWidth"


def _open(p, server, device="iPhone 13"):  # noqa: F811
    try:
        browser = p.chromium.launch()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"không mở được Chromium: {e}")
    ctx = browser.new_context(**p.devices[device])
    ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(server + "/")
    pg.evaluate("localStorage.setItem('nd30_token','t0k')")
    pg.reload()
    pg.wait_for_selector("#workspaceTabs:not([hidden])")
    pg.wait_for_timeout(300)
    return browser, pg


def test_phone_tabs_fit_and_stick(server):  # noqa: F811
    with pw.sync_playwright() as p:
        browser, pg = _open(p, server)
        assert pg.evaluate(NO_OVERFLOW)
        for tid in ("tabStandardize", "tabCompose", "tabMarkdown", "tabAudio"):
            box = pg.locator("#" + tid).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["height"] >= 32
            assert pg.evaluate("id=>{const b=document.getElementById(id);return b.scrollWidth<=b.clientWidth}", tid), tid  # tên tab không bị cắt
        assert pg.locator("#tabMarkdown").inner_text().strip().endswith("Markdown")
        pg.evaluate("scrollTo(0, 2000)")
        pg.wait_for_timeout(200)
        top = pg.locator("#workspaceTabs").bounding_box()["y"]
        assert 0 <= top <= 8                                                  # hàng tab vẫn ở mép trên khi cuộn
        for tab, panel in (("tabCompose", "composerPanel"), ("tabMarkdown", "markdownPanel"), ("tabAudio", "audioPanel")):
            pg.locator("#" + tab).tap()
            pg.wait_for_timeout(500)
            tabs = pg.locator("#workspaceTabs").bounding_box()
            box = pg.locator("#" + panel).bounding_box()
            assert abs(box["y"] - (tabs["y"] + tabs["height"])) <= 12           # khung nằm ngay dưới hàng tab
            assert box["y"] + box["height"] <= 844 + 2                          # và vừa màn hình
            assert pg.evaluate(NO_OVERFLOW)
        assert not pg.errors, pg.errors
        browser.close()


def test_phone_composer_actions_visible(server):  # noqa: F811
    with pw.sync_playwright() as p:
        browser, pg = _open(p, server)
        pg.locator("#tabCompose").tap()
        frame = None
        for _ in range(100):
            frame = next((f for f in pg.frames if "soan-thao" in f.url), None)
            if frame:
                break
            pg.wait_for_timeout(100)
        frame.wait_for_selector("#btnWord")
        panel = pg.locator("#composerPanel").bounding_box()
        word = frame.locator("#btnWord").bounding_box()                       # toạ độ theo trang chính
        assert panel["y"] <= word["y"] and word["y"] + word["height"] <= min(844, panel["y"] + panel["height"]) + 1
        assert frame.evaluate(NO_OVERFLOW)
        frame.locator("#btnTogglePreview").tap()
        frame.wait_for_selector(".preview-pane .page")
        assert frame.locator("#btnWord").is_visible()                         # xem văn bản vẫn xuất Word được
        page_box = frame.locator(".preview-pane .page").first.bounding_box()
        assert page_box["width"] <= 390                                        # trang A4 thu vừa bề ngang
        assert not pg.errors, pg.errors
        browser.close()


def test_tablet_and_laptop_bar_not_clipped(server):  # noqa: F811
    with pw.sync_playwright() as p:
        for vp in ({"width": 820, "height": 1180}, {"width": 1024, "height": 768}, {"width": 1440, "height": 900}):
            try:
                browser = p.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"không mở được Chromium: {e}")
            pg = browser.new_page(viewport=vp)
            pg.goto(server + "/")
            pg.evaluate("localStorage.setItem('nd30_token','t0k')")
            pg.reload()
            pg.wait_for_selector("#workspaceTabs:not([hidden])")
            assert pg.evaluate(NO_OVERFLOW)
            for sel in ("#tabMarkdown", "#logoutBtn"):
                if pg.locator(sel).is_visible():
                    b = pg.locator(sel).bounding_box()
                    assert b["x"] + b["width"] <= vp["width"], (vp, sel)
            browser.close()


def test_audio_tab_loads_page_and_is_hidden_on_desktop_build(server):  # noqa: F811
    import json
    with pw.sync_playwright() as p:
        browser, pg = _open(p, server)
        pg.locator("#tabAudio").tap()
        fr = pg.frame_locator("#audioFrame")
        fr.locator("#stateTxt").wait_for()
        pg.wait_for_function("()=>!document.getElementById('audioFrame').contentDocument.getElementById('stateTxt').textContent.includes('Đang kiểm tra')")
        assert "Chưa cấu hình" in fr.locator("#stateTxt").inner_text()          # máy thử không có GROQ_API_KEY
        assert pg.locator("#tabAudio").get_attribute("aria-selected") == "true"
        assert pg.evaluate("()=>{const d=document.getElementById('audioFrame').contentDocument.documentElement;return d.scrollWidth<=d.clientWidth}")
        assert not pg.errors, pg.errors
        # bản cài trên máy tính: /api/config trả audio=false -> không có tab thứ tư, ba tab còn lại chia đều hàng
        cfg = pg.evaluate("()=>fetch('api/config').then(r=>r.json())")
        cfg["audio"] = False
        pg.route("**/api/config", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(cfg)))
        pg.reload()
        pg.wait_for_selector("#workspaceTabs:not([hidden])")
        assert not pg.locator("#tabAudio").is_visible()
        w = [pg.locator("#" + t).bounding_box()["width"] for t in ("tabStandardize", "tabCompose", "tabMarkdown")]
        assert min(w) > 110 and max(w) - min(w) < 4
        assert not pg.errors, pg.errors
        browser.close()
