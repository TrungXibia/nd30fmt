"""Nhiều mã truy cập: quản trị viên cấp mã; mỗi mã chỉ thấy tài liệu của chính mình."""
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
ADM = {"X-App-Token": "admin-secret"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "admin-secret")
    import nd30fmt.jobs as jobs
    import nd30fmt.users as users
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(users)
    importlib.reload(web)
    return TestClient(web.app)


def _upload(client, headers):
    data = (ROOT / "samples" / "bao_cao_sai.docx").read_bytes()
    r = client.post("/api/jobs", headers=headers, files=[("files", ("a.docx", data, "x"))],
                    data={"wait": "true"})
    assert r.status_code == 200, r.text
    return r.json()["jobs"][0]["id"]


def _mk(client, name):
    r = client.post("/api/admin/users", headers=ADM, json={"name": name})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["token"].startswith("vb-") and "token_hash" not in u
    return u, {"X-App-Token": u["token"]}


def test_isolation_between_tokens(client):
    a, ha = _mk(client, "Người A")
    b, hb = _mk(client, "Người B")
    ja = _upload(client, ha)
    assert client.get("/api/me", headers=ha).json() == {"role": "user", "name": "Người A"}
    assert [j["id"] for j in client.get("/api/jobs", headers=ha).json()["jobs"]] == [ja]
    assert client.get("/api/jobs", headers=hb).json()["jobs"] == []
    assert client.get("/api/jobs", headers=ADM).json()["jobs"] == []
    for url in (f"/api/jobs/{ja}", f"/api/jobs/{ja}/status", f"/api/jobs/{ja}/file/fixed", f"/api/jobs/{ja}/file/original"):
        assert client.get(url, headers=hb).status_code == 404, url
        assert client.get(url, headers=ha).status_code == 200, url
    assert client.post(f"/api/jobs/{ja}/toc", headers=hb).status_code == 404
    assert client.delete(f"/api/jobs/{ja}", headers=hb).status_code == 404
    assert client.get(f"/api/jobs/{ja}", headers=ha).status_code == 200
    # người dùng không được quản trị, không đổi quy chuẩn mặc định dùng chung
    assert client.get("/api/admin/users", headers=ha).status_code == 403
    raw = client.get("/api/spec", headers=ha).json()["raw"]
    assert client.put("/api/spec", headers=ha, json=raw).status_code == 403
    users = client.get("/api/admin/users", headers=ADM).json()["users"]
    assert {u["name"]: u["jobs"] for u in users} == {"Người A": 1, "Người B": 0}
    import nd30fmt.jobs as jobs
    stored = json.loads((jobs.DATA_DIR / "users.json").read_text(encoding="utf-8"))
    assert all(a["token"] not in json.dumps(u) for u in stored)   # chỉ lưu băm


def test_lock_reset_delete(client):
    a, ha = _mk(client, "Người A")
    ja = _upload(client, ha)
    assert client.patch(f"/api/admin/users/{a['id']}", headers=ADM, json={"active": False}).status_code == 200
    assert client.get("/api/jobs", headers=ha).status_code == 401
    client.patch(f"/api/admin/users/{a['id']}", headers=ADM, json={"active": True})
    new = client.post(f"/api/admin/users/{a['id']}/reset", headers=ADM).json()["token"]
    assert client.get("/api/jobs", headers=ha).status_code == 401
    hn = {"X-App-Token": new}
    assert [j["id"] for j in client.get("/api/jobs", headers=hn).json()["jobs"]] == [ja]   # tài liệu giữ nguyên
    assert client.post("/api/admin/users", headers=ADM, json={"name": "người a"}).status_code == 400   # trùng tên
    r = client.delete(f"/api/admin/users/{a['id']}?purge=false", headers=ADM)
    assert r.json()["jobs"] == 1
    assert client.get("/api/jobs", headers=hn).status_code == 401
    assert [j["id"] for j in client.get("/api/jobs", headers=ADM).json()["jobs"]] == [ja]   # chuyển cho quản trị viên
    b, hb = _mk(client, "Người B")
    jb = _upload(client, hb)
    client.delete(f"/api/admin/users/{b['id']}?purge=true", headers=ADM)
    assert client.get(f"/api/jobs/{jb}", headers=ADM).status_code == 404


def test_legacy_jobs_belong_to_admin(client):
    ja = _upload(client, ADM)
    import nd30fmt.jobs as jobs
    meta_p = jobs.JOBS_DIR / ja / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta.pop("owner")
    meta_p.write_text(json.dumps(meta), encoding="utf-8")
    assert [j["id"] for j in client.get("/api/jobs", headers=ADM).json()["jobs"]] == [ja]
    _, ha = _mk(client, "Người A")
    assert client.get(f"/api/jobs/{ja}", headers=ha).status_code == 404
