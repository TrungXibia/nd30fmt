"""Đọc một bản thảo Word để điền vào form soạn thảo (không sửa file gốc)."""
from __future__ import annotations

import io
import re
import unicodedata
from html import escape

from docx import Document


TYPES = {
    "BIEN BAN HOP": "BIEN_BAN_HOP", "GIAY GIOI THIEU": "GIAY_GIOI_THIEU",
    "NGHI QUYET": "NGHI_QUYET", "QUYET DINH": "QUYET_DINH",
    "THONG BAO": "THONG_BAO", "CONG VAN": "CONG_VAN", "TO TRINH": "TO_TRINH",
    "BAO CAO": "BAO_CAO", "KE HOACH": "KE_HOACH", "HUONG DAN": "HUONG_DAN",
    "QUY CHE": "QUY_CHE", "QUY DINH": "QUY_DINH", "BIEN BAN": "BIEN_BAN",
    "GIAY MOI": "GIAY_MOI", "PHU LUC": "PHU_LUC",
}
NUMBER_CODES = {"TB": "THONG_BAO", "QD": "QUYET_DINH", "CV": "CONG_VAN", "TTR": "TO_TRINH",
                "BC": "BAO_CAO", "KH": "KE_HOACH", "HD": "HUONG_DAN", "QC": "QUY_CHE",
                "QDI": "QUY_DINH", "BB": "BIEN_BAN", "GM": "GIAY_MOI", "NQ": "NGHI_QUYET"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.upper().replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _rich(paragraph, skip: int = 0) -> str:
    """HTML đậm/nghiêng/gạch chân của đoạn; skip = số ký tự đầu bỏ đi (vd. số mục "1.1. " vì
    trình soạn thảo tự đánh số)."""
    parts = []
    for run in paragraph.runs:
        text = run.text
        if skip:
            cut = min(skip, len(text))
            text, skip = text[cut:], skip - cut
            if not text:
                continue
        content = escape(text).replace("\n", "<br>")
        if run.underline:
            content = f"<u>{content}</u>"
        if run.italic:
            content = f"<em>{content}</em>"
        if run.bold:
            content = f"<strong>{content}</strong>"
        parts.append(content)
    html = "".join(parts)
    return html.lstrip() if html.strip() else escape(paragraph.text[skip:] if skip else paragraph.text)


# Đề mục có số gõ tay -> cấp đề mục của trình soạn thảo (số được tự đánh lại nên bỏ phần số khỏi nội dung)
_HEAD_RE = [
    ("h1", re.compile(r"^\s*([IVXLC]+)\s*[.)]\s+(?=\S)")),
    ("h4", re.compile(r"^\s*\d+\.\d+\.\d+\.?\s+(?=\S)")),
    ("h3", re.compile(r"^\s*\d+\.\d+\.?\s+(?=\S)")),
    ("h2", re.compile(r"^\s*\d+\s*[.)]\s+(?=\S)")),
    ("h5", re.compile(r"^\s*[a-zđ]\s*\)\s+(?=\S)")),
]


def _heading(paragraph, text: str):
    """(loại, số ký tự tiền tố cần bỏ) nếu đoạn là đề mục; None nếu là nội dung."""
    style = (paragraph.style.name or "").lower() if paragraph.style else ""
    m = re.match(r"heading\s*([1-5])$", style)
    if len(text) > 200 or text.rstrip().endswith(";"):
        return None
    runs = [r for r in paragraph.runs if r.text.strip()]
    bold = bool(runs) and sum(len(r.text) for r in runs if r.bold) >= 0.6 * sum(len(r.text) for r in runs)
    for kind, rx in _HEAD_RE:
        hit = rx.match(text)
        if not hit:
            continue
        short = len(text) <= 160 and not text.rstrip().endswith(".")
        if kind == "h1" or bold or (m and short) or (kind in ("h3", "h4") and short):
            return kind, hit.end()
        return None
    if m:
        return f"h{m.group(1)}", 0
    return None


def _entries(paragraph) -> list[dict]:
    """Dòng `... như sau:- Thời gian` vẫn có dấu tách sau dấu hai chấm."""
    plain = paragraph.text.replace("\xa0", " ")
    if not plain.strip():
        return []
    chunks = re.split(r"(?<=:)[ \t]*?(?=[-–][ \t]*[A-Za-zÀ-ỹ])", plain)
    if len(chunks) == 1:
        chunks = plain.split("\n")
    else:
        chunks = [part for chunk in chunks for part in chunk.split("\n")]
    result = []
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        bullet = re.match(r"^[-–•]\s*", text)
        numbered = paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None
        style = (paragraph.style.name or "").lower() if paragraph.style else ""
        is_bullet = bool(bullet or (numbered or "list bullet" in style) and not re.match(r"^Điều\s+\d+", text, re.I))
        clean = text[bullet.end():] if bullet else text
        single = len(chunks) == 1 and not bullet
        lead = len(plain) - len(plain.lstrip())
        article = re.match(r"^Điều\s+\d+[a-zđ]?\s*[.:]\s*", clean, re.I)
        if article:        # "Điều n." được trình soạn thảo tự đánh số
            html = _rich(paragraph, lead + article.end()) if single else escape(clean[article.end():])
            result.append({"type": "dieu", "html": html, "align": "justify"})
            continue
        if re.fullmatch(r"QUYẾT\s+ĐỊNH\s*:?", clean, re.I):
            result.append({"type": "qd", "html": "QUYẾT ĐỊNH:", "align": "center"})
            continue
        if re.match(r"^(Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị)\s", clean, re.I):
            result.append({"type": "cancu", "html": _rich(paragraph) if single else escape(clean), "align": "justify"})
            continue
        # dòng thẩm quyền ban hành của quyết định ("VIỆN TRƯỞNG VIỆN ..."): in hoa, đậm, căn giữa
        if single and not is_bullet and len(clean) <= 160 and clean == clean.upper() and re.search(r"[A-ZĐÀ-Ỹ]", clean) \
                and paragraph.runs and all(r.bold for r in paragraph.runs if r.text.strip()) \
                and re.match(r"^(BỘ TRƯỞNG|THỨ TRƯỞNG|CHỦ TỊCH|VIỆN TRƯỞNG|GIÁM ĐỐC|TỔNG GIÁM ĐỐC|HIỆU TRƯỞNG|CỤC TRƯỞNG|"
                             r"VỤ TRƯỞNG|CHÁNH|TRƯỞNG|THỦ TRƯỞNG|ỦY BAN|UỶ BAN|HỘI ĐỒNG|BAN )", clean):
            result.append({"type": "qd", "html": escape(clean), "align": "center"})
            continue
        head = None if is_bullet or not single else _heading(paragraph, clean)
        if head:
            kind, skip = head
            result.append({"type": kind, "html": _rich(paragraph, lead + skip) if skip else _rich(paragraph), "align": "left"})
            continue
        html = _rich(paragraph) if single else escape(clean)
        result.append({"type": "bullet" if is_bullet else "p", "html": html, "align": "left" if is_bullet else "justify"})
    return result


def parse_draft_bytes(data: bytes) -> dict:
    doc = Document(io.BytesIO(data))
    paragraphs = [p for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("File Word không có đoạn văn có thể nhập vào trình soạn thảo")

    head = [p.text.strip() for p in paragraphs[:30]]
    table_left = []
    if doc.tables and len(doc.tables[0].columns) >= 2:
        t = doc.tables[0]
        if any("CONG HOA" in _norm(c.text) or "DANG CONG SAN" in _norm(c.text)
               for row in t.rows[:2] for c in row.cells):
            table_left = [line.strip() for p in t.cell(0, 0).paragraphs
                          for line in p.text.splitlines() if line.strip()]
            head = [c.text.strip() for row in t.rows[:2] for c in row.cells] + head
    for section in doc.sections[:1]:
        head += [p.text.strip() for p in section.header.paragraphs if p.text.strip()]
    leading = "\n".join(head[:35]); norm_head = _norm(leading)
    if "DANG CONG SAN VIET NAM" in norm_head:
        form = "PARTY"
    elif "DOAN TNCS HO CHI MINH" in norm_head:
        form = "UNION"
    elif "MAT TRAN TO QUOC" in norm_head:
        form = "FATHERLAND"
    else:
        form = "ADMINISTRATIVE"

    title_idx, doc_type, contract_type = None, None, None
    for idx, p in enumerate(paragraphs[:35]):
        normalized = _norm(p.text.strip(" :.-\t"))
        if normalized.startswith("HOP DONG"):
            form = "CONTRACT"; title_idx = idx
            contract_type = ("HD_LAO_DONG" if "LAO DONG" in normalized else
                             "HD_THU_VIEC" if "THU VIEC" in normalized else
                             "HD_DICH_VU" if "DICH VU" in normalized else "HD_KHAC")
            break
        if normalized in TYPES:
            title_idx = idx; doc_type = TYPES[normalized]; break

    fields = {"hinhThuc": form, "loaiVanBan": doc_type, "loaiHopDong": contract_type}
    number = re.search(r"\bSố\s*[:.]?\s*(\d+)[^\n]*", leading, re.I)
    if number:
        fields["soVanBan"] = number[1]
        fields["soKyHieu"] = number[0].strip()
        if doc_type is None and form != "CONTRACT":
            code = re.search(r"\bSố\s*[:.]?\s*\d+\s*[/\-]\s*([A-Za-zÀ-ỹ]{2,4})", number[0], re.I)
            if code:
                doc_type = NUMBER_CODES.get(_norm(code[1]))
                fields["loaiVanBan"] = doc_type
        unit = re.search(r"-([A-ZÀ-Ỹ][A-ZÀ-Ỹ0-9]{1,24})\s*$", number[0])
        if unit:
            fields["maDonVi"] = unit[1]
    date = re.search(r"([^\n,]{2,50}),\s*ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", leading, re.I)
    if date:
        fields["diaDanh"] = date[1].strip()
        fields["ngayBanHanh"] = f"{date[4]}-{int(date[3]):02d}-{int(date[2]):02d}"
    agency = [s for s in table_left if not re.match(r"^Số\b", s, re.I)]
    if agency:
        fields["cqBanHanh"] = agency[-1]
        if len(agency) > 1:
            fields["cqChuQuan"] = agency[-2]

    start = (title_idx + 1) if title_idx is not None else next((i for i,p in enumerate(paragraphs)
        if re.match(r"^(Kính gửi\b|Căn cứ\b|Điều\s+\d+[.:]|V/v\b)", p.text.strip(), re.I)), 0)
    if title_idx is not None and form != "CONTRACT" and start < len(paragraphs):
        text = paragraphs[start].text.strip()
        if (len(text) <= 180 and not re.match(r"^(Điều\s+\d+[.:]|Căn cứ\b|Kính gửi\b|Nơi nhận\b|VIỆN TRƯỞNG\b|GIÁM ĐỐC\b|BỘ TRƯỞNG\b|CHỦ TỊCH\b)", text, re.I)
                and not re.fullmatch(r"[\W\s]*", text)):
            fields["trichYeu"] = text
            start += 1

    body, kinh_gui, in_kg = [], [], False
    for p in paragraphs[start:]:
        text = p.text.strip()
        if re.match(r"^Nơi nhận\s*:", text, re.I):
            break
        vv = re.match(r"^V/v\s+(.+)", text, re.I)
        if vv and not fields.get("trichYeu") and not body:
            fields["trichYeu"] = vv[1].strip()
            continue
        kg = re.match(r"^Kính\s+gửi\s*:?\s*(.*)$", text, re.I)
        if kg and not body:
            rest = kg[1].strip()
            if rest:
                kinh_gui.append(re.sub(r"^[-–•]\s*", "", rest))
            in_kg = True
            continue
        if in_kg and re.match(r"^[-–•]\s*\S", text) and len(text) <= 160:
            kinh_gui.append(re.sub(r"^[-–•]\s*", "", text))
            continue
        in_kg = False
        body.extend(_entries(p))
    if kinh_gui:
        fields["kinhGui"] = "\n".join(kinh_gui)
    if not body:
        body = [{"type": "p", "html": "", "align": "justify"}]
    warnings = []
    if title_idx is None:
        warnings.append("Không thấy dòng tên loại riêng; đã dựa vào ký hiệu nếu có. Hãy kiểm tra lại loại trong form.")
    if doc_type is None and form != "CONTRACT":
        warnings.append("Chưa nhận diện được loại văn bản; lựa chọn hiện tại được giữ lại.")
    if len(doc.tables) > (1 if table_left else 0) or doc.inline_shapes:
        warnings.append("Bảng/hình trong file chưa chuyển sang form; kiểm tra bản gốc trước khi xuất lại.")
    if form == "CONTRACT":
        warnings.append("Thông tin Bên A/B cần được kiểm tra và điền trong form.")
    return {"fields": fields, "blocks": body, "warnings": warnings,
            "detected": {"form": form, "doc_type": doc_type, "contract_type": contract_type}}
