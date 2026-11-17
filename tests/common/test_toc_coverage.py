"""Mục lục & danh mục hình/bảng: các cách trình bày chú thích và tiêu đề danh mục phổ biến."""
import io
import re
import zipfile

from docx import Document
from docx.oxml import parse_xml

from nd30fmt.toc import build_toc

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _word_caption(doc, label, rest):
    p = doc.add_paragraph()
    p.add_run(label + " ")
    for x in ('<w:r %s><w:fldChar w:fldCharType="begin"/></w:r>' % W,
              '<w:r %s><w:instrText xml:space="preserve"> SEQ %s \\* ARABIC </w:instrText></w:r>' % (W, label),
              '<w:r %s><w:fldChar w:fldCharType="separate"/></w:r>' % W, '<w:r %s><w:t>1</w:t></w:r>' % W,
              '<w:r %s><w:fldChar w:fldCharType="end"/></w:r>' % W):
        p._p.append(parse_xml(x))
    p.add_run(". " + rest)


def _run(tmp_path, heads, caps):
    d = Document()
    for h in heads:
        d.add_paragraph(h)
    for c in caps:
        if isinstance(c, tuple):
            _word_caption(d, *c)
        else:
            d.add_paragraph(c)
    src = tmp_path / "in.docx"
    d.save(src)
    out = tmp_path / "out.docx"
    stats = build_toc(str(src), str(out))
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    instr = [i.strip() for i in re.findall(r"<w:instrText[^>]*>([^<]*)</w:instrText>", xml)]
    return stats, instr


def test_word_insert_caption_labels_join_lists(tmp_path):
    stats, instr = _run(tmp_path, ["DANH MỤC HÌNH", "DANH MỤC BẢNG"],
                        [("Hình", "Sơ đồ"), ("Figure", "Biểu đồ"), ("Table", "Số liệu")])
    assert stats["captions"]["word_captions"] == {"Hinh": 2, "Bang": 1}
    assert instr.count("SEQ Hinh \\* ARABIC") == 2 and "SEQ Bang \\* ARABIC" in instr


def test_heading_variants_and_combined_list(tmp_path):
    stats, instr = _run(tmp_path, ["Mục lục", "DANH MỤC HÌNH VÀ BẢNG"], ["Hình 1. A", "Bảng 1. B"])
    assert stats["toc"]["inserted"] == {"toc": True, "hinh": True, "bang": True}
    stats, _ = _run(tmp_path, ["DANH MỤC BIỂU ĐỒ", "DANH MỤC CÁC BẢNG BIỂU SỐ LIỆU"], ["Biểu đồ 1. A"])
    assert stats["toc"]["inserted"] == {"toc": False, "hinh": True, "bang": True}
    stats, _ = _run(tmp_path, ["DANH MỤC CHỮ VIẾT TẮT"], ["Hình 1. A"])
    assert stats["toc"]["inserted"] == {"toc": False, "hinh": False, "bang": False}


def test_bieu_is_table_and_hidden_seq_is_vanished(tmp_path):
    stats, instr = _run(tmp_path, ["DANH MỤC BẢNG"], ["Biểu 2.1. Chi phí"])
    assert stats["captions"]["tagged"]["Bang"] == 1
    xml = zipfile.ZipFile(tmp_path / "out.docx").read("word/document.xml").decode()
    assert re.search(r"<w:vanish/></w:rPr><w:instrText[^>]*> SEQ Bang \\c \\h ", xml)
