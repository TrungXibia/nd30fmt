"""Cỡ chữ trong khoảng cho phép (13 trong 13–14) vẫn phải đưa về giá trị "Sửa về" (14) khi sửa."""
from docx import Document
from docx.shared import Pt

from nd30fmt.extract import extract
from nd30fmt.pipeline import process
from nd30fmt.spec import load_spec


def test_size_13_goes_to_fix_size_14(tmp_path):
    d = Document()
    for t in ["Thực hiện kế hoạch công tác năm 2026, đơn vị báo cáo kết quả như sau.",
              "Các nhiệm vụ trọng tâm đều hoàn thành đúng tiến độ, bảo đảm chất lượng."]:
        r = d.add_paragraph().add_run(t)
        r.font.size = Pt(13)
        r.font.name = "Times New Roman"
    src = tmp_path / "a.docx"
    d.save(src)
    spec = load_spec()
    spec.raw["body"]["fix_size"] = 14
    for k in ("body", "list_item"):
        if k in spec.roles:
            spec.roles[k].fix_size = 14
    r = process(str(src), spec, str(tmp_path / "out"))
    sizes = {run.size for p in extract(str(tmp_path / "out" / r["fixed_file"])).paragraphs for run in p.runs if run.text.strip()}
    assert sizes == {14.0}, sizes
    assert not [v for v in r["violations"] if v["field"] == "size"]     # 13 nằm trong khoảng: không báo lỗi
