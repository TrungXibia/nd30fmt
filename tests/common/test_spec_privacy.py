"""Quy chuẩn được mã hoá trong kho và không lộ nguồn/căn cứ ra giao diện, API, báo cáo."""
import base64
import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
H = {"X-App-Token": "t0k-very-secret-token"}
HIDDEN = {"source", "sources", "url", "verified", "note", "note_align"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_TOKEN", H["X-App-Token"])
    import nd30fmt.jobs as jobs
    import nd30fmt.web as web
    importlib.reload(jobs)
    importlib.reload(web)
    return TestClient(web.app)


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def test_repo_has_no_plaintext_spec():
    assert not list((ROOT / "config").glob("*_spec.yaml")), "tệp quy chuẩn rõ không được nằm trong kho"
    for name in ("nd30", "dang", "dean"):
        blob = (ROOT / "config" / f"{name}_spec.yaml.enc").read_bytes()
        assert blob.startswith(b"ND30ENC1") and b"roles" not in blob and "Phụ lục".encode() not in blob


def test_wrong_key_errors_missing_key_uses_sample(monkeypatch):
    from nd30fmt import spec
    monkeypatch.setenv("ND30_SPEC_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    with pytest.raises(spec.SpecKeyError, match="Sai khoá"):          # khoá sai: không lặng lẽ chuyển sang bản mẫu
        spec.load_raw()
    monkeypatch.delenv("ND30_SPEC_KEY", raising=False)
    monkeypatch.delenv("ND30_SPEC_KEY_FILE", raising=False)
    assert spec.spec_source() == "sample"
    raw = spec.load_raw()
    assert raw["meta"]["sample"] is True and raw["page"]["margins_mm"]["left"]["fix"]
    for std, p in spec.SPEC_PATHS.items():
        assert spec.spec_source(p) == "sample" and spec.load_spec(p).roles


def test_sample_specs_are_open_and_clean():
    from nd30fmt.spec import SPEC_PATHS
    for std, p in SPEC_PATHS.items():
        text = (ROOT / "config" / "sample" / p.name).read_text(encoding="utf-8")
        assert "http" not in text and "verified" not in text and "note_" not in text and "\nnote:" not in text


def test_wrong_key_gives_clear_503(client, monkeypatch):
    monkeypatch.setenv("ND30_SPEC_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    r = client.get("/api/spec", headers=H)
    assert r.status_code == 503 and "ND30_SPEC_KEY" in r.json()["detail"]


def test_healthz_reports_spec_source(client, monkeypatch):
    if os.getenv("ND30_SPEC_KEY"):
        assert client.get("/healthz").json()["spec"] == "encrypted"
    monkeypatch.delenv("ND30_SPEC_KEY", raising=False)
    assert client.get("/healthz").json()["spec"] == "sample"
    assert client.get("/api/spec", headers=H).json()["raw"]["meta"]["sample"] is True


def test_spec_api_hides_sources(client):
    assert client.get("/spec").status_code == 404                       # trước đây tải được .yaml không cần mã
    for std in ("nd30", "dang", "dean"):
        raw = client.get(f"/api/spec?standard={std}", headers=H).json()["raw"]
        assert not (_keys(raw) & HIDDEN), _keys(raw) & HIDDEN
        assert raw["page"]["margins_mm"]["left"]["fix"]                # thông số vẫn chỉnh được


def test_save_default_restores_hidden_fields(client):
    raw = client.get("/api/spec", headers=H).json()["raw"]
    raw["body"]["fix_size"] = 13
    r = client.put("/api/spec", headers=H, json=raw)
    assert r.status_code == 200, r.text
    from nd30fmt import jobs
    stored = jobs.default_raw("nd30")
    assert stored["body"]["fix_size"] == 13 and stored["meta"]["sources"]     # nguồn vẫn còn ở máy chủ
    assert not (_keys(client.get("/api/spec", headers=H).json()["raw"]) & HIDDEN)


def test_job_payload_report_and_downloads_hide_sources(client):
    with open(SAMPLES / "bao_cao_sai.docx", "rb") as f:
        r = client.post("/api/jobs", headers=H, files=[("files", ("a.docx", f.read(), "application/octet-stream"))],
                        data={"wait": "true", "spell": "false"})
    jid = r.json()["jobs"][0]["id"]
    p = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert p["violations"] and not (_keys(p["violations"]) & HIDDEN)
    assert not (_keys(p["spec_raw"]) & HIDDEN) and "spec_name" not in p
    # áp dụng lại với bộ thông số đã ẩn nguồn vẫn chạy được
    r = client.post(f"/api/jobs/{jid}/apply", headers=H, json={"raw": p["spec_raw"]})
    assert r.status_code == 200, r.text
    html = client.get(f"/api/jobs/{jid}/download/report", headers=H).text
    assert "Căn cứ" not in html and "ND30_PL1" not in html and "Quy chuẩn:" not in html
    rep = json.loads(client.get(f"/api/jobs/{jid}/download/json", headers=H).text)
    assert not (_keys(rep.get("violations")) & HIDDEN)
    assert client.get(f"/api/jobs/{jid}/download/spec", headers=H).status_code == 404


def test_composer_hides_sources(client):
    t = client.get("/api/compose/templates", headers=H).json()
    assert not (_keys(t) & HIDDEN), _keys(t) & HIDDEN
    assert "ND30_PL1" not in client.get("/soan-thao").text
    ui = (ROOT / "nd30fmt" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'href="spec"' not in ui and "Tải .yaml" not in ui and "Căn cứ: ${" not in ui
