"""File không có style tên/ID "Normal" (WPS, LibreOffice, phần mềm văn thư...): trước đây báo
Lỗi xử lý: "no style with name 'Normal'"."""
import io
import warnings

from docx import Document
from docx.oxml.ns import qn

from nd30fmt.fix import normal_style
from nd30fmt.pipeline import process
from nd30fmt.spec import DEFAULT_SPEC_PATH, build_spec, load_raw


def test_pipeline_without_normal_style(tmp_path):
    d = Document()
    for t in ("BÁO CÁO", "I. MỤC ĐÍCH", "1. Nội dung", "Đoạn văn nội dung dài, kết thúc bằng dấu chấm."):
        d.add_paragraph(t)
    for s in d.styles.element.findall(qn("w:style")):
        if s.get(qn("w:styleId")) == "Normal":
            s.set(qn("w:styleId"), "a")
            s.find(qn("w:name")).set(qn("w:val"), "Default Paragraph")
    for el in d.styles.element.iter(qn("w:basedOn")):
        if el.get(qn("w:val")) == "Normal":
            el.set(qn("w:val"), "a")
    src = tmp_path / "x.docx"
    d.save(src)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert normal_style(Document(str(src))).style_id == "a"
    out = process(str(src), build_spec(load_raw(DEFAULT_SPEC_PATH)), str(tmp_path / "out"))
    assert out["fixed_file"]
