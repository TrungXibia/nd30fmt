"""Kiểm thử API web cho chuẩn Đảng (HD05)."""
import importlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", "t0k")
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


H = {"X-App-Token": "t0k"}


def _upload(client, name="bao_cao_sai.docx", standard="nd30"):
    with open(SAMPLES / name, "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", (name, f.read(), "application/octet-stream"))],
                        data={"standard": standard, "wait": "true"})
    assert r.status_code == 200, r.text
    j = r.json()["jobs"][0]
    assert j["ok"], j
    return j["id"]


def test_composer_party_settings_share_checker_source(client):
    from nd30fmt.composer_spec import party_composer_spec
    from nd30fmt import jobs
    projection=party_composer_spec()
    source=jobs.default_raw("dang")
    assert projection["margins_mm"]["right"] == source["page"]["margins_mm"]["right"]["fix"] == 15
    assert projection["roles"]["title"]["fix_size"] == source["roles"]["dang_tieu_de"]["fix_size"] == 15
    assert projection["roles"]["letter_summary"]["fix_size"] == 12
    assert projection["body"]["line_spacing_pt"] == 20
    assert projection["page_number"] == {"size":14.0,"distance_from_top_mm":10.0,"hide_first_page":True}
    hd05 = client.get("/api/compose/templates", headers=H).json()["hd05"]["format"]
    assert hd05["roles"]["tieu_de"]["default"] == 15 and hd05["margins_mm"]["right"]["default"] == 15


def test_composer_party_picks_saved_checker_spec(client):
    import json
    from nd30fmt import jobs
    raw=jobs.default_raw("dang")
    raw["roles"]["dang_trich_yeu"]["fix_size"]=14
    jobs.save_default(raw,"dang")
    fmt = client.get("/api/compose/templates", headers=H).json()["hd05"]["format"]
    assert fmt["roles"]["trich_yeu"]["default"] == 14   # trình soạn thảo đọc cùng quy chuẩn Đảng đã lưu


def test_dang_standard(client):
    jid = _upload(client, "dang_quyet_dinh_sai.docx", standard="dang")
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["standard"] == "dang"
    assert p["summary"]["total"] > 0 and p["summary_after"]["total"] == 0
    # vai trò xác định phải dùng bộ role_keys của Đảng, không lẫn với ND30
    keys = {r["key"] for r in p["role_keys"]}
    assert "dang_the_loai" in keys and "ten_loai" not in keys
    roles = {d["pid"]: d["role"] for d in p["roles"]}
    assert roles.get("P0007") == "dang_the_loai"  # dòng "QUYẾT ĐỊNH"
    # danh sách phiên phải ghi đúng chuẩn đã dùng
    lst = client.get("/api/jobs", headers=H).json()["jobs"]
    assert next(j for j in lst if j["id"] == jid)["standard"] == "dang"
    # quy chuẩn mặc định/tuỳ chỉnh của Đảng tách riêng khỏi ND30
    raw = client.get("/api/spec", headers=H, params={"standard": "dang"}).json()["raw"]
    assert "dang_tieu_de" in raw["roles"]
    raw["roles"]["dang_body"]["fix_size"] = 15
    assert client.put("/api/spec", headers=H, json=raw, params={"standard": "dang"}).status_code == 200
    nd30_raw = client.get("/api/spec", headers=H, params={"standard": "nd30"}).json()
    assert nd30_raw["custom"] is False and "dang_tieu_de" not in nd30_raw["raw"]["roles"]
    assert client.delete("/api/spec", headers=H, params={"standard": "dang"}).status_code == 200
