"""Kiểm thử bộ kiểm tra văn bản Đảng (HD05)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from nd30fmt.pipeline import process
from nd30fmt.spec import load_spec

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
NAMES = ["bao_cao_sai", "quyet_dinh_sai", "chuyen_de_dai"]


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not all((SAMPLES / f"{n}.docx").exists() for n in NAMES):
        import runpy
        runpy.run_path(str(ROOT / "tests" / "make_samples.py"), run_name="__main__")



def test_party_article_bold_and_noi_nhan(tmp_path):
    from docx import Document
    from nd30fmt.extract import extract
    from nd30fmt.roles import propose_roles_dang
    from nd30fmt.check import check_document

    d = Document()
    d.add_paragraph("ĐẢNG CỘNG SẢN VIỆT NAM")
    d.add_paragraph("Số 01-QĐ/TW")
    d.add_paragraph("QUYẾT ĐỊNH")
    p = d.add_paragraph()
    p.add_run("Điều 1. ").bold = True
    p.add_run("Nội dung giải thích dài không cần in đậm toàn bộ.")
    d.add_paragraph("Nơi nhận:")
    source = tmp_path / "dang.docx"
    d.save(source)
    ex = extract(str(source))
    roles = propose_roles_dang(ex)
    assert any(x.role == "dang_dieu" for x in roles)
    viols = check_document(ex, roles, load_spec(ROOT / "config" / "dang_spec.yaml"))
    assert any(v.role == "dang_dieu" and v.field == "bold" for v in viols)
    assert any(v.role == "dang_noi_nhan_label" and v.field == "underline" for v in viols)


def test_dang_line_spacing_always_becomes_exactly(tmp_path):
    """Đảng: giãn dòng At least / Multiple / Exactly sai cỡ (kể cả do style Normal) đều phải thành Exactly 20pt.
    Lỗi cũ: python-docx giữ lineRule="atLeast" khi gán Pt(), nên sửa xong vẫn là "At least 20pt"."""
    from docx import Document
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt
    from nd30fmt.extract import extract
    from nd30fmt.spec import DANG_SPEC_PATH
    d = Document(str(SAMPLES / "dang_quyet_dinh_sai.docx"))
    modes = [(WD_LINE_SPACING.AT_LEAST, Pt(11.7)), (WD_LINE_SPACING.MULTIPLE, 1.5),
             (WD_LINE_SPACING.EXACTLY, Pt(14)), (WD_LINE_SPACING.SINGLE, None)]
    for i, p in enumerate([p for p in d.paragraphs if len(p.text) > 40]):
        rule, val = modes[i % 4]
        p.paragraph_format.line_spacing_rule = rule
        if val is not None:
            p.paragraph_format.line_spacing = val
    st = d.styles["Normal"].paragraph_format
    st.line_spacing_rule, st.line_spacing = WD_LINE_SPACING.AT_LEAST, Pt(11.7)
    src = tmp_path / "dang.docx"
    d.save(src)
    for mode in ("violations", "normalize"):
        spec = load_spec(str(DANG_SPEC_PATH))
        spec.fix["mode"] = mode
        r = process(str(src), spec, str(tmp_path / mode), standard="dang")
        assert any(v["field"] == "line_spacing" for v in r["violations"])
        assert not [v for v in r["violations_after"] if v["field"] == "line_spacing"], mode
        roles = {x["pid"]: x["role"] for x in r["roles"]}
        ex = extract(str(tmp_path / mode / r["fixed_file"]))
        for p in ex.paragraphs:
            if p.where == "body" and roles.get(p.pid) in ("dang_body", "dang_can_cu", "dang_dieu", "dang_list_item"):
                assert (p.line_rule, round(p.line_value, 1)) == ("exact", 20.0), (p.pid, p.line_rule, p.line_value)
