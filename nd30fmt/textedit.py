"""Sửa CHỮ của đoạn văn (người dùng gõ trực tiếp trên bản xem trước) mà vẫn giữ định dạng từng run.

Cách làm: so khớp ký tự cũ/mới (difflib); ký tự giữ nguyên ở lại run cũ, ký tự gõ thêm gắn vào run
của ký tự đứng ngay trước (như khi gõ tiếp trong Word), ký tự xoá thì bỏ. Tab/ngắt dòng có sẵn được
giữ nếu còn trong chữ mới; tab/ngắt dòng gõ thêm được đổi thành khoảng trắng. Không thêm/bớt đoạn
(giữ nguyên số đoạn để vai trò đã xác định vẫn khớp).
"""
from __future__ import annotations

from difflib import SequenceMatcher

from docx.oxml import OxmlElement

from .extract import iter_runs, qn

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
MAX_CHARS = 20000


class EditError(ValueError):
    pass


def paragraph_editable(p_el) -> bool:
    """Không cho sửa đoạn có trường tự động (số trang, SEQ, mục lục...) để không phá cấu trúc field."""
    return not any(True for _ in p_el.iter(qn("w:fldChar"))) and not any(True for _ in p_el.iter(qn("w:fldSimple")))


def set_paragraph_text(p_el, new: str) -> bool:
    """Ghi chữ mới cho đoạn. Trả về True nếu có thay đổi."""
    if not paragraph_editable(p_el):
        raise EditError("Đoạn có trường tự động (số trang, mục lục, số hình/bảng) – không sửa trực tiếp được")
    new = (new or "").replace("\r", "")
    if len(new) > MAX_CHARS:
        raise EditError("Đoạn quá dài")
    # các "ô" chữ theo thứ tự: w:t (sửa được) và w:tab / w:br (cố định, 1 ký tự)
    cells = []           # (node, kind) kind: t | tab | br
    for r in iter_runs(p_el):
        for node in r:
            if node.tag == qn("w:t"):
                cells.append((node, "t"))
            elif node.tag == qn("w:tab"):
                cells.append((node, "tab"))
            elif node.tag in (qn("w:br"), qn("w:cr")) and node.get(qn("w:type")) in (None, "textWrapping"):
                cells.append((node, "br"))
    old_parts, owners = [], []
    for k, (node, kind) in enumerate(cells):
        s = (node.text or "") if kind == "t" else ("\t" if kind == "tab" else "\n")
        old_parts.append(s)
        owners.extend([k] * len(s))
    old = "".join(old_parts)
    if old == new:
        return False
    t_cells = [k for k, (_, kind) in enumerate(cells) if kind == "t"]
    if not t_cells:                       # đoạn chưa có chữ: tạo 1 run mới
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = new.replace("\t", " ").replace("\n", " ")
        t.set(XML_SPACE, "preserve")
        r.append(t)
        p_el.append(r)
        return True

    def text_owner(i_old: int) -> int:
        """run chữ gần nhất đứng trước vị trí i_old (không tính tab/br); không có thì run chữ đầu tiên."""
        for i in range(min(i_old, len(owners)) - 1, -1, -1):
            if cells[owners[i]][1] == "t":
                return owners[i]
        return t_cells[0]

    buf = {k: [] for k in t_cells}
    keep = set()                          # tab/br còn giữ
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                k = owners[i]
                if cells[k][1] == "t":
                    buf[k].append(new[j])
                else:
                    keep.add(k)
        elif tag in ("replace", "insert"):
            if tag == "replace" and cells[owners[i1]][1] == "t":
                k = owners[i1]            # thay chữ: giữ định dạng của chữ bị thay
            else:
                k = text_owner(i1)        # gõ thêm: theo định dạng chữ đứng ngay trước
            buf[k].append(new[j1:j2].replace("\t", " ").replace("\n", " "))
        # delete: bỏ
    for k, (node, kind) in enumerate(cells):
        if kind == "t":
            node.text = "".join(buf[k])
            node.set(XML_SPACE, "preserve")
        elif k not in keep:
            node.getparent().remove(node)
    return True


def apply_text_edits(ex, edits: dict[str, str]) -> list[str]:
    """Áp các sửa chữ {pid: chữ mới} vào ExtractedDoc (sửa trực tiếp XML). Trả về ghi chú lỗi (nếu có)."""
    notes = []
    by_pid = {p.pid: p for p in ex.paragraphs}
    for pid, txt in edits.items():
        p = by_pid.get(pid)
        if p is None:
            notes.append(f"{pid}: không tìm thấy đoạn")
            continue
        try:
            set_paragraph_text(p.element, txt)
        except EditError as e:
            notes.append(f"{pid}: {e}")
    return notes
