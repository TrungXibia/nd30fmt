"""Hàng đợi chuyển đổi chạy nền cho tab Chuyển Markdown.

Lý do: PDF quét nhiều trang cần nhận dạng chữ (OCR) có thể mất vài phút; nếu xử lý ngay trong một yêu cầu HTTP thì
nginx/trình duyệt cắt kết nối (504) và người dùng không biết đang tới đâu. Ở đây yêu cầu tải lên trả về mã việc
ngay, một luồng nền xử lý lần lượt từng việc (tránh nhiều việc OCR tranh CPU làm chậm cả máy chủ), giao diện hỏi
tiến độ (file, trang x/y) cho tới khi xong. Trạng thái giữ trong bộ nhớ: khởi động lại máy chủ thì việc đang chạy
mất (giao diện báo cần tải lại); tài liệu đã chuyển xong vẫn còn trong thư viện.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid

from . import doc_to_md, store

KEEP_SECONDS = 3600          # giữ kết quả việc đã xong 1 giờ để giao diện kịp lấy
_jobs: dict[str, dict] = {}
_q: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _public(job: dict) -> dict:
    with _lock:
        ahead = 0
        if job["state"] == "queued":
            ahead = sum(1 for j in _jobs.values() if j["state"] in ("queued", "running") and j["created"] < job["created"])
        return {"id": job["id"], "state": job["state"], "ahead": ahead,
                "files": [{k: f[k] for k in ("filename", "state", "page", "pages", "message")} for f in job["files"]],
                "results": list(job["results"]) if job["state"] == "done" else []}


def _cleanup() -> None:
    now = time.time()
    with _lock:
        for jid in [k for k, j in _jobs.items() if j["state"] == "done" and now - j["finished"] > KEEP_SECONDS]:
            _jobs.pop(jid, None)


def _run(job: dict, label_fn) -> None:
    for f, data in zip(job["files"], job.pop("_data")):
        if f["state"] == "error":                                    # đã bị loại khi nhận (quá dung lượng…)
            job["results"].append({"ok": False, "filename": f["filename"], "message": f["message"]})
            continue
        f["state"] = "running"

        def progress(done, total, f=f):
            f["page"], f["pages"] = done, total
        try:
            doc = store.add_document(job["owner"], f["filename"], data, label_fn, progress)
            f["state"] = "done"
            res = {"ok": True, "filename": f["filename"], "doc": doc}
            if doc.get("truncated"):
                res["warning"] = "Chỉ chuyển một phần số trang (xem dòng đầu tài liệu)."
            job["results"].append(res)
        except store.MdError as e:
            f["state"], f["message"] = "error", str(e)
            job["results"].append({"ok": False, "filename": f["filename"], "message": str(e)})
        except Exception as e:  # noqa: BLE001 - báo lỗi từng file, không dừng cả lô
            f["state"], f["message"] = "error", f"Lỗi chuyển đổi: {e}"
            job["results"].append({"ok": False, "filename": f["filename"], "message": f["message"]})


def _loop() -> None:
    while True:
        jid = _q.get()
        job = _jobs.get(jid)
        if not job:
            continue
        job["state"] = "running"
        try:
            _run(job, job.pop("_label", None))
        finally:
            job["state"], job["finished"] = "done", time.time()
            job.pop("_data", None)


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="md-convert", daemon=True)
            _worker.start()


def submit(owner: str, files: list[tuple[str, bytes | None, str | None]], label_fn=None) -> dict:
    """files: [(tên file, dữ liệu hoặc None, lỗi hoặc None)]. Trả về trạng thái việc."""
    _cleanup()
    jid = uuid.uuid4().hex[:16]
    job = {"id": jid, "owner": owner, "state": "queued", "created": time.time(), "finished": 0.0, "results": [],
           "files": [{"filename": n, "state": "error" if err else "queued", "page": 0, "pages": 0, "message": err or ""}
                     for n, _, err in files],
           "_data": [d for _, d, _ in files], "_label": label_fn}
    with _lock:
        _jobs[jid] = job
    _ensure_worker()
    _q.put(jid)
    return _public(job)


def status(owner: str, jid: str) -> dict | None:
    job = _jobs.get(jid)
    if not job or job["owner"] != owner:
        return None
    return _public(job)


def max_pages() -> int:
    return doc_to_md.MAX_PAGES
