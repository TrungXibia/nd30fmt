"""Tab Chuyển đổi Âm thanh: cắt đoạn + ghép kết quả, thử lại khi Groq quá hạn mức, hàng đợi, quyền xem việc,
giới hạn dung lượng, dọn tệp tạm, và bản máy tính (không có tab này). Không gọi Groq thật: _post được thay thế."""
import glob
import importlib
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

from nd30fmt import groq_whisper as gw

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="không có ffmpeg")
ADM = {"X-App-Token": "admin-secret"}


def _tone(path, seconds=5):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-ar", "16000", "-ac", "1", str(path)], check=True)
    return path


def _http_error(code, retry_after=None):
    hdrs = {"retry-after": str(retry_after)} if retry_after is not None else {}
    import email.message
    m = email.message.Message()
    for k, v in hdrs.items():
        m[k] = v
    return urllib.error.HTTPError(gw.GROQ_URL, code, "x", m, io.BytesIO(b"{}"))


def _leftover():
    return glob.glob(os.path.join(tempfile.gettempdir(), gw.TMP_PREFIX + "*"))


@pytest.fixture(autouse=True)
def _clean_tmp():
    before = set(_leftover())
    yield
    for d in set(_leftover()) - before:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- groq_whisper
@needs_ffmpeg
def test_segments_are_joined_with_running_offset(tmp_path, monkeypatch):
    src = _tone(tmp_path / "a.wav", 5)
    monkeypatch.setattr(gw, "CHUNK_SECONDS", 2)
    calls = []

    def fake_post(key, body, ctype):
        calls.append(len(body))
        n = len(calls)
        return {"text": f"đoạn {n}", "duration": 2.0, "segments": [{"start": 0.5, "end": 1.5, "text": f" đoạn {n} "}]}

    monkeypatch.setattr(gw, "_post", fake_post)
    seen = []
    before = set(_leftover())
    res = gw.transcribe_file(str(src), "k", progress=lambda d, t: seen.append((d, t)))
    assert len(calls) == 3
    assert [s["start"] for s in res["segments"]] == [0.5, 2.5, 4.5]
    assert res["text"] == "đoạn 1 đoạn 2 đoạn 3" and res["duration"] == 6.0
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert set(_leftover()) == before                       # thư mục tạm đã được dọn
    assert src.exists()                                     # không xóa tệp nguồn của người gọi


@needs_ffmpeg
def test_bytes_wrapper_and_bad_file(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "_post", lambda *a: {"text": "xin chào", "duration": 1.0})
    data = _tone(tmp_path / "b.wav", 1).read_bytes()
    assert gw.transcribe(data, "k")["text"] == "xin chào"
    with pytest.raises(gw.GroqError, match="Không đọc được tệp"):
        gw.transcribe(b"day khong phai am thanh", "k")
    assert not [d for d in _leftover() if os.path.exists(os.path.join(d, "in.bin"))]


def test_retry_on_rate_limit_then_ok(monkeypatch):
    seq = [_http_error(429, 2), _http_error(503), {"text": "ok"}]
    slept = []

    def fake_post(*a):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    monkeypatch.setattr(gw, "_post", fake_post)
    assert gw._one("k", "m", b"x", "p.ogg", sleep=slept.append) == {"text": "ok"}
    assert slept[0] == 3.0 and len(slept) == 2              # chờ đúng retry-after + 1 giây, rồi thử lại lỗi 503


def test_rate_limit_too_long_gives_readable_message(monkeypatch):
    monkeypatch.setattr(gw, "_post", lambda *a: (_ for _ in ()).throw(_http_error(429, 600)))
    slept = []
    with pytest.raises(gw.GroqError) as e:
        gw._one("k", "m", b"x", "p.ogg", sleep=slept.append)
    assert "601 giây" in str(e.value) and not slept          # không ngồi chờ 10 phút
    monkeypatch.setattr(gw, "_post", lambda *a: (_ for _ in ()).throw(_http_error(429)))
    with pytest.raises(gw.GroqError, match="ít phút"):
        gw._one("k", "m", b"x", "p.ogg", sleep=slept.append)


def test_no_retry_on_bad_key_and_gives_up_on_network(monkeypatch):
    n = {"c": 0}

    def bad_key(*a):
        n["c"] += 1
        raise _http_error(401)

    monkeypatch.setattr(gw, "_post", bad_key)
    with pytest.raises(gw.GroqError, match="GROQ_API_KEY"):
        gw._one("k", "m", b"x", "p.ogg", sleep=lambda s: None)
    assert n["c"] == 1

    def offline(*a):
        n["c"] += 1
        raise OSError("down")

    n["c"] = 0
    monkeypatch.setattr(gw, "_post", offline)
    with pytest.raises(gw.GroqError, match="Không kết nối"):
        gw._one("k", "m", b"x", "p.ogg", sleep=lambda s: None)
    assert n["c"] == gw.MAX_TRIES


def test_real_http_request_shape_and_retry_after_header(monkeypatch):
    """Gửi thật qua HTTP tới một máy chủ giả: kiểm tra tiêu đề, phần thân multipart và việc đọc Retry-After."""
    import http.server
    import json
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((dict(self.headers), body))
            if len(seen) == 1:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.end_headers()
                return
            out = json.dumps({"text": "xin chào", "duration": 1.5}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(gw, "GROQ_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1/audio/transcriptions")
        slept = []
        assert gw._one("gsk_k", "whisper-large-v3", b"OggS-data", "part000.ogg", sleep=slept.append)["text"] == "xin chào"
    finally:
        srv.shutdown()
    assert slept == [2.0] and len(seen) == 2
    hdr, body = seen[1]
    assert hdr["Authorization"] == "Bearer gsk_k" and hdr["User-Agent"] == "nd30fmt/1.0"
    assert hdr["Content-Type"].startswith("multipart/form-data; boundary=")
    for part in (b'name="model"\r\n\r\nwhisper-large-v3', b'name="language"\r\n\r\nvi', b'name="response_format"\r\n\r\nverbose_json',
                 b'name="file"; filename="part000.ogg"', b"OggS-data"):
        assert part in body


def test_sweep_keeps_active_workdir():
    busy = gw.new_workdir()
    stale = tempfile.mkdtemp(prefix=gw.TMP_PREFIX)
    old = time.time() - 7200
    os.utime(busy, (old, old))
    os.utime(stale, (old, old))
    try:
        assert gw.sweep_stale() >= 1
        assert os.path.isdir(busy) and not os.path.exists(stale)
    finally:
        gw.release_workdir(busy)
    assert not os.path.exists(busy)


# ---------------------------------------------------------------- API web
@pytest.fixture()
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "admin-secret")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WHISPER_TOKEN", raising=False)
    monkeypatch.delenv("ND30_DESKTOP", raising=False)
    import nd30fmt.jobs as jobs
    import nd30fmt.users as users
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(users)
    importlib.reload(web)
    web.client = TestClient(web.app)
    yield web
    web._groq_pool.shutdown(wait=True)


def _wait(web, pid, headers=ADM, want=("done", "error"), timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = web.client.get(f"/api/audio/jobs/{pid}", headers=headers)
        assert r.status_code == 200, r.text
        if r.json()["status"] in want:
            return r.json()
        time.sleep(0.05)
    raise AssertionError("việc không xong")


def _send(web, data, headers=ADM, name="hop.m4a"):
    return web.client.post("/api/audio/jobs", headers=headers, files={"file": (name, data, "audio/mp4")})


@needs_ffmpeg
def test_api_job_flow_progress_and_cleanup(web, tmp_path, monkeypatch):
    assert web.client.get("/api/audio/status").status_code == 401
    st = web.client.get("/api/audio/status", headers=ADM).json()
    assert st == {"configured": True, "alive": True, "max_mb": 90.0, "backend": "groq"}
    assert web.client.get("/healthz").json()["audio"] is True
    assert web.client.get("/api/config").json()["audio"] is True
    assert "Chuyển đổi Âm thanh" in web.client.get("/chuyen-am-thanh").text

    monkeypatch.setattr(gw, "CHUNK_SECONDS", 2)
    gate, entered = threading.Event(), threading.Event()

    def fake_post(key, body, ctype):
        assert key == "gsk_test"
        entered.set()
        assert gate.wait(10)
        return {"text": "kính gửi", "duration": 2.0, "segments": [{"start": 0.0, "end": 1.0, "text": "kính gửi"}]}

    monkeypatch.setattr(gw, "_post", fake_post)
    before = set(_leftover())
    pid = _send(web, _tone(tmp_path / "a.wav", 5).read_bytes()).json()["id"]
    assert entered.wait(10)
    running = web.client.get(f"/api/audio/jobs/{pid}", headers=ADM).json()
    assert running == {"status": "running", "part": 1, "parts": 3}
    pid2 = _send(web, _tone(tmp_path / "b.wav", 1).read_bytes()).json()["id"]
    assert web.client.get(f"/api/audio/jobs/{pid2}", headers=ADM).json() == {"status": "queued", "ahead": 1}
    gate.set()
    done = _wait(web, pid)
    assert done["status"] == "done" and done["result"]["text"] == "kính gửi kính gửi kính gửi"
    assert [s["start"] for s in done["result"]["segments"]] == [0.0, 2.0, 4.0]
    assert "seconds" in done["result"]
    assert _wait(web, pid2)["status"] == "done"
    web._groq_pool.submit(lambda: None).result()             # chờ luồng xử lý dọn xong thư mục của việc thứ hai
    assert set(_leftover()) == before                        # không giữ âm thanh trên máy chủ
    assert web.client.delete(f"/api/audio/jobs/{pid}", headers=ADM).json() == {"ok": True}
    assert web.client.get(f"/api/audio/jobs/{pid}", headers=ADM).status_code == 404


@needs_ffmpeg
def test_api_job_is_private_to_its_owner(web, tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "_post", lambda *a: {"text": "mật", "duration": 1.0})
    tok = web.client.post("/api/admin/users", headers=ADM, json={"name": "Người B"}).json()["token"]
    hb = {"X-App-Token": tok}
    pid = _send(web, _tone(tmp_path / "a.wav", 1).read_bytes()).json()["id"]
    assert _wait(web, pid)["result"]["text"] == "mật"
    assert web.client.get(f"/api/audio/jobs/{pid}", headers=hb).status_code == 404
    assert web.client.delete(f"/api/audio/jobs/{pid}", headers=hb).json() == {"ok": True}    # không xóa được việc của người khác
    assert web.client.get(f"/api/audio/jobs/{pid}", headers=ADM).json()["status"] == "done"
    assert web.client.get("/api/audio/jobs/khong-hop-le", headers=ADM).status_code == 404


def test_api_limits_and_errors(web, monkeypatch):
    before = set(_leftover())
    assert _send(web, b"").status_code == 400
    monkeypatch.setattr(web, "AUDIO_MAX_MB", 0.001)
    r = _send(web, b"x" * 5000)
    assert r.status_code == 413 and "vượt quá" in r.json()["detail"]
    assert set(_leftover()) == before                        # tệp bị từ chối không để lại gì trên đĩa
    monkeypatch.setattr(web, "AUDIO_MAX_MB", 90.0)
    monkeypatch.setattr(gw, "_post", lambda *a: (_ for _ in ()).throw(AssertionError("không được gọi Groq")))
    pid = _send(web, b"khong phai am thanh").json()["id"]
    out = _wait(web, pid)
    if shutil.which("ffmpeg"):
        assert out == {"status": "error", "error": "Không đọc được tệp này (định dạng không hỗ trợ hoặc tệp hỏng)."}
    else:
        assert out["status"] == "error" and "ffmpeg" in out["error"]
    web._groq_pool.submit(lambda: None).result()
    assert set(_leftover()) == before


@needs_ffmpeg
def test_api_queue_limit_and_cancel_while_running(web, tmp_path, monkeypatch):
    monkeypatch.setattr(web, "AUDIO_MAX_QUEUE", 2)
    monkeypatch.setattr(gw, "CHUNK_SECONDS", 2)
    gate, entered, calls = threading.Event(), threading.Event(), []

    def fake_post(*a):
        calls.append(1)
        entered.set()
        assert gate.wait(10)
        return {"text": "a", "duration": 2.0}

    monkeypatch.setattr(gw, "_post", fake_post)
    data = _tone(tmp_path / "a.wav", 5).read_bytes()
    first = _send(web, data).json()["id"]
    assert entered.wait(10)
    second = _send(web, data).json()["id"]
    r = _send(web, data)
    assert r.status_code == 429 and "quá nhiều việc" in r.json()["detail"]
    # huỷ cả hai: việc đang chạy dừng sau đoạn hiện tại, việc đang chờ không chạy nữa
    web.client.delete(f"/api/audio/jobs/{first}", headers=ADM)
    web.client.delete(f"/api/audio/jobs/{second}", headers=ADM)
    gate.set()
    web._groq_pool.submit(lambda: None).result()
    assert len(calls) == 1
    assert _send(web, data).status_code == 200               # hàng đợi đã trống trở lại


def test_not_configured_and_desktop_build(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("APP_TOKEN", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("WHISPER_TOKEN", raising=False)
    monkeypatch.delenv("ND30_DESKTOP", raising=False)
    import nd30fmt.web as web
    importlib.reload(web)
    c = TestClient(web.app)
    assert c.get("/api/audio/status").json() == {"configured": False, "alive": False, "max_mb": 90.0}
    assert c.get("/healthz").json()["audio"] is False
    assert c.get("/api/config").json()["audio"] is True      # tab vẫn hiện, trang báo "chưa cấu hình"
    # bản cài trên máy tính: không có tab Âm thanh, kể cả khi máy có sẵn khoá
    monkeypatch.setenv("ND30_DESKTOP", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    importlib.reload(web)
    c = TestClient(web.app)
    assert c.get("/api/config").json()["audio"] is False
    assert c.get("/chuyen-am-thanh").status_code == 404
    assert c.get("/api/audio/status").json()["configured"] is False
    assert c.post("/api/audio/jobs", files={"file": ("a.mp3", b"x", "audio/mpeg")}).status_code == 404
    assert c.get("/healthz").json()["audio"] is False
    monkeypatch.delenv("ND30_DESKTOP")
    importlib.reload(web)
