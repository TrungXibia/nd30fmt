"""Định dạng do người dùng chọn cho từng đoạn trên bản Word đã sửa."""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .extract import iter_runs, qn


ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
FIELDS = {"bold", "italic", "underline", "align"}


def validate_manual_format(value: dict | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 10000:
        raise ValueError("manual_format phải là object {mã đoạn: định dạng}")
    for pid, changes in value.items():
        if not isinstance(pid, str) or len(pid) > 40 or not isinstance(changes, dict):
            raise ValueError("Mã đoạn hoặc định dạng chỉnh tay không hợp lệ")
        if not set(changes) <= FIELDS:
            raise ValueError("Chỉ hỗ trợ đậm, nghiêng, gạch chân và căn đoạn")
        if any(changes[k] not in (True, False) or not isinstance(changes[k], bool)
               for k in ("bold", "italic", "underline") if k in changes):
            raise ValueError("B/I/U phải là true hoặc false")
        if "align" in changes and (not isinstance(changes["align"], str) or changes["align"] not in ALIGN):
            raise ValueError("Kiểu căn đoạn không hợp lệ")
    return value


def apply_manual_format(ex, changes: dict) -> list[str]:
    """Áp lên bản đã tự sửa để thao tác tay không bị bộ tự sửa ghi đè."""
    by_pid = {p.pid: p for p in ex.paragraphs}
    notes = []
    for pid, fields in changes.items():
        p = by_pid.get(pid)
        if p is None:
            notes.append(f"{pid}: không tìm thấy đoạn để định dạng")
            continue
        para = Paragraph(p.element, None)
        if "align" in fields:
            para.alignment = ALIGN[fields["align"]]
        for r_el in iter_runs(p.element):
            if not any((t.text or "").strip() for t in r_el.findall(qn("w:t"))):
                continue
            font = Run(r_el, None).font
            for key in ("bold", "italic", "underline"):
                if key in fields:
                    setattr(font, key, fields[key])
    return notes
