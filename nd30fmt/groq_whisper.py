"""Phiên âm bằng Groq Whisper API (chỉ dùng thư viện chuẩn + ffmpeg).

ffmpeg nén tệp về mono 16 kHz (opus), cắt đoạn 20 phút để mỗi tệp gửi đi nhỏ hơn nhiều giới hạn 25 MB
của Groq; kết quả từng đoạn được ghép lại, mốc thời gian cộng dồn theo độ dài thật của từng đoạn.

Tệp nguồn được đọc từ đĩa (không nạp cả tệp vào bộ nhớ). Khi Groq báo quá hạn mức (HTTP 429) hoặc lỗi tạm thời
(5xx, rớt mạng), đoạn đang gửi được thử lại vài lần thay vì bỏ cả tệp.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CHUNK_SECONDS = 1200
TMP_PREFIX = "nd30audio"
MAX_TRIES = 4            # số lần gửi tối đa cho mỗi đoạn
MAX_WAIT = 90.0          # chỉ chờ rồi thử lại khi Groq yêu cầu chờ không quá ngần này giây
_RETRY_5XX = (500, 502, 503, 504)

_active: set[str] = set()            # thư mục tạm đang dùng: sweep_stale không được xóa
_active_lock = threading.Lock()


class GroqError(Exception):
    """Lỗi có thông điệp tiếng Việt, hiển thị được cho người dùng."""


class Cancelled(Exception):
    """Người dùng đã huỷ việc trong lúc đang chạy."""


def new_workdir() -> str:
    """Thư mục tạm cho một việc (tệp nguồn + các đoạn đã nén). Gọi release_workdir khi xong."""
    d = tempfile.mkdtemp(prefix=TMP_PREFIX)
    with _active_lock:
        _active.add(d)
    return d


def release_workdir(d: str) -> None:
    shutil.rmtree(d, ignore_errors=True)
    with _active_lock:
        _active.discard(d)


def sweep_stale(max_age: float = 3600.0) -> int:
    """Xóa thư mục tạm nd30audio* bị bỏ sót (ví dụ container bị tắt giữa chừng). Trả về số thư mục đã xóa.

    Thư mục của việc đang chờ hoặc đang chạy trong tiến trình này không bị đụng tới, dù đã cũ.
    """
    n = 0
    with _active_lock:
        busy = set(_active)
    for d in glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")):
        if d in busy:
            continue
        try:
            if time.time() - os.path.getmtime(d) > max_age:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def _multipart(fields: dict, fname: str, fbytes: bytes):
    boundary = "----nd" + os.urandom(8).hex()
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n").encode())
    parts.append(fbytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    try:
        return max(0.0, float(e.headers.get("retry-after")))
    except (TypeError, ValueError):
        return None


def _post(api_key: str, body: bytes, ctype: str) -> dict:
    req = urllib.request.Request(GROQ_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + api_key, "Content-Type": ctype,
        "User-Agent": "nd30fmt/1.0"})  # UA mặc định của urllib bị Cloudflare chặn
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _one(api_key: str, model: str, fbytes: bytes, fname: str, sleep: Callable[[float], None] = time.sleep) -> dict:
    body, ctype = _multipart({"model": model, "language": "vi", "temperature": "0",
                              "response_format": "verbose_json"}, fname, fbytes)
    for attempt in range(1, MAX_TRIES + 1):
        last = attempt == MAX_TRIES
        try:
            return _post(api_key, body, ctype)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise GroqError("GROQ_API_KEY trên máy chủ sai hoặc đã bị thu hồi.") from e
            if e.code == 413:
                raise GroqError("Đoạn âm thanh vượt giới hạn dung lượng của Groq.") from e
            if e.code == 429:
                wait = _retry_after(e)
                if not last and wait is not None and wait <= MAX_WAIT:
                    sleep(wait + 1.0)
                    continue
                when = f"{int(wait) + 1} giây" if wait is not None else "ít phút"
                raise GroqError(f"Groq báo hết hạn mức, thử lại sau {when}.") from e
            if e.code in _RETRY_5XX and not last:
                sleep(3.0 * attempt)
                continue
            raise GroqError(f"Groq báo lỗi HTTP {e.code}.") from e
        except (OSError, ValueError) as e:      # rớt mạng, hết thời gian chờ, trả về không phải JSON
            if not last:
                sleep(3.0 * attempt)
                continue
            raise GroqError("Không kết nối được tới Groq.") from e
    raise GroqError("Không kết nối được tới Groq.")     # không tới được đây; để trình kiểm tra kiểu yên tâm


def transcribe_file(src: str, api_key: str, model: str = "whisper-large-v3",
                    progress: Callable[[int, int], None] | None = None, workdir: str | None = None) -> dict:
    """Phiên âm tệp `src`. `progress(đã_xong, tổng_số_đoạn)` được gọi trước mỗi đoạn và khi xong;
    hàm này có thể ném Cancelled để dừng giữa chừng. Các đoạn nén được ghi vào `workdir` (mặc định: thư mục tạm riêng).
    """
    if not available():
        raise GroqError("Máy chủ chưa cài ffmpeg.")
    own = workdir is None
    tmp = new_workdir() if own else workdir
    try:
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "libopus", "-b:a", "24k", "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
               "-reset_timestamps", "1", os.path.join(tmp, "part%03d.ogg")]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=900)
        except subprocess.TimeoutExpired as e:
            raise GroqError("Nén âm thanh quá lâu, tệp có thể lỗi.") from e
        files = sorted(glob.glob(os.path.join(tmp, "part*.ogg")))
        if p.returncode != 0 or not files:
            raise GroqError("Không đọc được tệp này (định dạng không hỗ trợ hoặc tệp hỏng).")
        segments: list[dict] = []
        texts: list[str] = []
        offset = 0.0
        for i, fp in enumerate(files):
            if progress:
                progress(i, len(files))
            with open(fp, "rb") as f:
                res = _one(api_key, model, f.read(), os.path.basename(fp))
            for sg in res.get("segments") or []:
                t = (sg.get("text") or "").strip()
                if t:
                    segments.append({"start": round(offset + float(sg["start"]), 1),
                                     "end": round(offset + float(sg["end"]), 1), "text": t})
            texts.append((res.get("text") or "").strip())
            offset += float(res.get("duration") or CHUNK_SECONDS)
        if progress:
            progress(len(files), len(files))
        text = " ".join(s["text"] for s in segments) if segments else " ".join(t for t in texts if t)
        return {"text": text, "segments": segments, "duration": round(offset, 1)}
    finally:
        if own:
            release_workdir(tmp)


def transcribe(data: bytes, api_key: str, model: str = "whisper-large-v3") -> dict:
    """Như transcribe_file nhưng nhận dữ liệu trong bộ nhớ (giữ để tương thích)."""
    tmp = new_workdir()
    try:
        src = os.path.join(tmp, "in.bin")
        with open(src, "wb") as f:
            f.write(data)
        return transcribe_file(src, api_key, model, workdir=tmp)
    finally:
        release_workdir(tmp)
