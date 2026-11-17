"""File Word thật thường có Track Changes (w:rPrChange/w:pPrChange) và phần mở rộng w14:*.
python-docx nối phần tử mới (w:u, w:jc, w:outlineLvl...) vào SAU các phần tử này -> Word báo file hỏng.
Bản đã sửa (kể cả chỉnh tay B/I/U, căn lề và mục lục) phải giữ đúng thứ tự lược đồ."""
import zipfile

from docx import Document
from docx.oxml import parse_xml
from lxml import etree

from nd30fmt.extract import extract
from nd30fmt.manual_format import apply_manual_format
from nd30fmt.ooxml_order import SETTINGS_SEQ, save_docx
from nd30fmt.toc import set_update_fields

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = (f'xmlns:w="{W}" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')


def _word_like(path):
    d = Document()
    for i in range(4):
        p = d.add_paragraph()
        r = p.add_run(f"Đoạn thử {i}")
        r.font.size = None
        rpr = r._r.get_or_add_rPr()
        rpr.append(parse_xml(f'<w:sz {NS} w:val="26"/>'))
        rpr.append(parse_xml(f'<w14:ligatures {NS} w14:val="standard"/>'))
        rpr.append(parse_xml(f'<w:rPrChange {NS} w:id="{i+1}" w:author="A"><w:rPr/></w:rPrChange>'))
        p._p.get_or_add_pPr().append(parse_xml(f'<w:pPrChange {NS} w:id="{i+11}" w:author="A"><w:pPr/></w:pPrChange>'))
    d.save(path)


def _local(el):
    return etree.QName(el).localname


def test_manual_format_keeps_schema_order(tmp_path):
    src = tmp_path / "a.docx"
    _word_like(src)
    ex = extract(str(src))
    fmt = {p.pid: {"bold": True, "italic": True, "underline": True, "align": "center"} for p in ex.paragraphs}
    assert not apply_manual_format(ex, fmt)
    set_update_fields(ex.doc)
    out = tmp_path / "b.docx"
    save_docx(ex.doc, out)
    with zipfile.ZipFile(out) as z:
        doc = etree.fromstring(z.read("word/document.xml"))
        settings = etree.fromstring(z.read("word/settings.xml"))
    for rpr in doc.iter(f"{{{W}}}rPr"):
        if rpr.getparent().tag != f"{{{W}}}r":
            continue
        names = [_local(c) for c in rpr]
        assert names[-1] == "rPrChange", names
        assert names.index("u") < names.index("ligatures") and names.index("b") < names.index("sz"), names
    for ppr in doc.iter(f"{{{W}}}pPr"):
        names = [_local(c) for c in ppr]
        if "pPrChange" in names:
            assert names[-1] == "pPrChange" and "jc" in names, names
    names = [_local(c) for c in settings]
    known = [n for n in names if n in SETTINGS_SEQ]
    assert known == sorted(known, key=SETTINGS_SEQ.index), names
    ex2 = extract(str(out))
    assert all(r.bold and r.italic and r.underline for p in ex2.paragraphs for r in p.runs)
    assert all(p.align == "center" for p in ex2.paragraphs)


def test_outline_level_before_paragraph_mark_rpr(tmp_path):
    """Lỗi thật (TM Giá điện Sinh khối): đề mục có rPr của dấu đoạn -> w:outlineLvl bị append sau w:rPr."""
    from nd30fmt.fix import _set_outline_level, _suppress_style_numbering
    d = Document()
    p = d.add_paragraph("1.1. Tổng quan")
    ppr = p._p.get_or_add_pPr()
    ppr.append(parse_xml(f'<w:keepNext {NS}/>'))
    ppr.append(parse_xml(f'<w:rPr {NS}><w:b/></w:rPr>'))
    _set_outline_level(p._p, 2)
    _suppress_style_numbering(p._p)
    names = [_local(c) for c in p._p.pPr]
    assert names == ["keepNext", "numPr", "outlineLvl", "rPr"], names


def test_unit_line_is_source_note_not_heading():
    from nd30fmt.roles import RE, RE_DEAN
    for t in ("Đơn vị tính: Triệu đồng", "(Đơn vị: tỷ đồng)", "ĐVT: người", "Nguồn: Tổng cục Thống kê"):
        assert RE["source_note"].match(t) and RE_DEAN["nguon"].match(t), t
    for t in ("Đơn vị: Viện Nghiên cứu Y", "Đơn vị chủ trì: Viện X"):
        assert not RE["source_note"].match(t), t

