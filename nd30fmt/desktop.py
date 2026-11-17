"""Trình chạy bản máy tính (Windows) – "Công cụ văn bản NĐ30".

- Chạy máy chủ nội bộ trên 127.0.0.1 (chỉ máy này truy cập), không cần mã đăng nhập.
- Mở giao diện trong cửa sổ ứng dụng của Microsoft Edge/Chrome (chế độ --app); không có thì mở trình duyệt mặc định.
- Đóng cửa sổ là tắt máy chủ; chạy lại khi đang mở thì chỉ mở thêm cửa sổ.
- Dữ liệu (thư viện Markdown, bản nháp, cài đặt) lưu ở %LOCALAPPDATA%\\CongCuVanBanND30\\data.
- Công cụ đi kèm: Tesseract (nhận dạng chữ tiếng Việt) trong thư mục tesseract cạnh ứng dụng.
  LibreOffice (bản in, file .doc) dùng nếu máy đã cài.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

APP_NAME = "Công cụ văn bản NĐ30"
APP_DIR = Path(__file__).resolve().parents[1]                 # thư mục chứa nd30fmt/, config/
INSTALL_DIR = APP_DIR.parent if APP_DIR.name == "app" else APP_DIR
HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CongCuVanBanND30"
DATA = HOME / "data"
LOG = HOME / "app.log"
IDLE_EXIT = 90           # giây không còn trang nào mở -> tắt


def _msg(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)


def _no_console_windows() -> None:
    """pythonw gọi chương trình dòng lệnh (tesseract, soffice) sẽ bật cửa sổ đen: ẩn đi."""
    if os.name != "nt":
        return
    flag = 0x08000000   # CREATE_NO_WINDOW
    orig = subprocess.Popen.__init__

    def init(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | flag
        return orig(self, *a, **kw)
    subprocess.Popen.__init__ = init


def _setup_env() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(DATA)
    os.environ["ND30_DESKTOP"] = "1"
    os.environ["APP_NAME"] = APP_NAME
    os.environ.pop("APP_TOKEN", None)                  # một người dùng, không cần mã
    paths = []
    tess = INSTALL_DIR / "tesseract"
    if (tess / "tesseract.exe").exists():
        paths.append(str(tess))
        os.environ["TESSDATA_PREFIX"] = str(tess / "tessdata")
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        lo = Path(base) / "LibreOffice" / "program"
        if (lo / "soffice.exe").exists():
            paths.append(str(lo))
            break
    os.environ["PATH"] = os.pathsep.join(paths + [os.environ.get("PATH", "")])
    settings = HOME / "settings.json"          # tuỳ chọn: {"GROQ_API_KEY": "..."} – biến môi trường bổ sung
    if settings.exists():
        try:
            for k, v in json.loads(settings.read_text(encoding="utf-8-sig")).items():
                if isinstance(v, str) and k.isupper():
                    os.environ.setdefault(k, v)
        except Exception:  # noqa: BLE001
            pass


def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _free_port() -> int:
    for port in range(18730, 18760):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _browser() -> str | None:
    cands = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    return next((str(c) for c in cands if c.exists()), None)


def open_window(url: str):
    exe = _browser()
    if exe:
        prof = HOME / "window"
        return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={prof}", "--no-first-run",
                                 "--no-default-browser-check", "--window-size=1400,900", "--lang=vi"])
    import webbrowser
    webbrowser.open(url)
    return None


def main() -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    lock = HOME / "instance.json"
    if lock.exists():                     # đang chạy: chỉ mở thêm cửa sổ
        try:
            port = json.loads(lock.read_text())["port"]
            if _alive(port):
                open_window(f"http://127.0.0.1:{port}/")
                return 0
        except Exception:  # noqa: BLE001
            pass
    _setup_env()
    _no_console_windows()
    sys.path.insert(0, str(APP_DIR))
    import logging
    logging.basicConfig(filename=str(LOG), level=logging.WARNING, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn
    from nd30fmt import web
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_config=None,
                                           log_level="warning", access_log=False))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(300):
        if server.started:
            break
        if not th.is_alive():
            _msg("Không khởi động được. Xem nhật ký: " + str(LOG))
            return 1
        time.sleep(0.05)
    lock.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    url = f"http://127.0.0.1:{port}/"
    proc = open_window(url)
    started = time.time()
    try:
        while True:
            time.sleep(2)
            now, last = time.time(), web._last_ping["t"]
            window_closed = proc is None or proc.poll() is not None
            # trang mở báo "còn dùng" 15 giây/lần (trình duyệt có thể giãn tới 1 phút/lần khi thu nhỏ cửa sổ)
            if last and window_closed and now - last > IDLE_EXIT * 1.7:
                break
            if not last and window_closed and now - started > 180:
                break
    finally:
        server.should_exit = True
        th.join(timeout=5)
        try:
            lock.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        HOME.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        _msg("Có lỗi khi chạy ứng dụng. Xem nhật ký: " + str(LOG))
        sys.exit(1)
