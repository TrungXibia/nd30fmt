"""Đọc file Word (.docx) -> bản thảo theo schema (chuẩn, loại, mẫu, các trường, khối nội dung).

Không sửa file gốc. Nhận diện dựa trên cấu trúc (bảng đầu trang, số/ký hiệu, tên loại, nhãn cố định
của mẫu); dòng nội dung không có dấu hiệu rõ ràng được giữ là đoạn thường
(xem classify.py).
"""
from __future__ import annotations

import io
import re
import unicodedata

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..import_draft import _rich
from . import schema
from .layout import BLOCK_TYPES


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").upper().replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _iter_body(doc):
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _bold(p) -> bool:
    runs = [r for r in p.runs if r.text.strip()]
    if not runs:
        return False
    total = sum(len(r.text) for r in runs)
    style_bold = bool(p.style is not None and p.style.font is not None and p.style.font.bold)
    return sum(len(r.text) for r in runs if r.bold or (r.bold is None and style_bold)) >= 0.6 * total


def _cell_lines(cell):
    out = []
    for p in cell.paragraphs:
        for i, line in enumerate(p.text.replace("\xa0", " ").split("\n")):
            if line.strip():
                out.append((line.strip(), _bold(p), p))
    return out


DATE_RE = re.compile(r"^(?P<place>[^,\n]{1,60}),\s*ngày\s*(?P<d>\d{1,2})\s*tháng\s*(?P<m>\d{1,2})\s*năm\s*(?P<y>\d{4})", re.I)
DATE_ANY = re.compile(r"ngày\s*(?:…|\.+)?\s*tháng", re.I)


def _template_regex(template: str) -> tuple[re.Pattern, list[str]]:
    names = re.findall(r"\{(\w+)\}", template)
    pattern = ""
    pos = 0
    for m in re.finditer(r"\{(\w+)\}", template):
        pattern += re.escape(template[pos:m.start()]).replace(r"\ ", r"\s*") + f"(?P<{m[1]}>.*?)"
        pos = m.end()
    tail = template[pos:].rstrip("/.").rstrip()
    pattern += re.escape(tail).replace(r"\ ", r"\s*") + r"\s*(?:\./\.|/\.|\.)?\s*$"
    return re.compile("^" + pattern, re.I), names


def _parse_number(text: str, standard: str) -> dict:
    out = {}
    if standard == "hd05":
        m = re.search(r"Số\s*:?\s*(\d*)\s*-\s*([A-Za-zÀ-ỹĐđ]+)\s*/\s*([\wÀ-ỹĐđ\-]+)", text)
        if m:
            out.update(so=m[1], ma_loai=m[2], ma_co_quan=m[3])
        return out
    m = re.search(r"Số\s*:?\s*(\d*)\s*/\s*([^\s]+)", text)
    if m:
        out["so"] = m[1]
        parts = m[2].split("-")
        out["codes"] = parts
    return out


def parse_docx(data: bytes) -> dict:
    doc = Document(io.BytesIO(data))
    items = list(_iter_body(doc))
    if not any((isinstance(x, Paragraph) and x.text.strip()) or isinstance(x, Table) for x in items):
        raise ValueError("File Word không có nội dung")
    warnings: list[str] = []
    fields: dict = {}

    # ---------- chuẩn
    head_text = " ".join((x.text if isinstance(x, Paragraph) else " ".join(c.text for r in x.rows for c in r.cells))
                         for x in items[:6])
    standard = "hd05" if "DANG CONG SAN VIET NAM" in _norm(head_text) else "nd30"

    # ---------- đầu trang
    idx = 0
    header_found = False
    for i, x in enumerate(items[:4]):
        if isinstance(x, Table) and len(x.columns) >= 2:
            txt = _norm(" ".join(c.text for r in x.rows for c in r.cells))
            if "CONG HOA" in txt or "DANG CONG SAN" in txt:
                left, right = [], []
                for r in x.rows:
                    cells = r.cells
                    left += _cell_lines(cells[0])
                    right += _cell_lines(cells[-1])
                _read_header(left, right, standard, fields)
                idx = i + 1
                header_found = True
                break
    if not header_found:
        # văn bản không dùng bảng: đọc các đoạn đầu
        heads = []
        for i, x in enumerate(items[:12]):
            if isinstance(x, Paragraph) and x.text.strip():
                heads.append((x.text.strip(), _bold(x), x))
                if DATE_RE.search(x.text) or re.match(r"^Số\b", x.text.strip()):
                    idx = i + 1
        _read_header(heads, heads, standard, fields)
        warnings.append("Không thấy bảng đầu trang 2 cột; thông tin cơ quan, số, ngày đọc từ các đoạn đầu – hãy kiểm tra lại.")

    number = _parse_number(fields.pop("_so_text", ""), standard)

    # ---------- tên loại
    catalog = schema.catalog(standard)["types"]
    by_title = {}
    for t in catalog:
        if t.get("ten_loai"):
            by_title.setdefault(_norm(t["ten_loai"]), []).append(t)
    paras = [(i, x) for i, x in enumerate(items) if i >= idx and isinstance(x, Paragraph)]
    type_id = None
    title_pos = None
    for i, p in paras[:8]:
        n = _norm(p.text.strip(" :.\t"))
        if n in by_title:
            cands = by_title[n]
            type_id = cands[0]["id"]
            title_pos = i
            break
    detected_by = "tên loại"
    codes = number.get("codes", [])
    if type_id is None:
        if fields.get("trich_yeu"):
            type_id, detected_by = "CONG_VAN", "V/v dưới số, ký hiệu"
        elif standard == "hd05" and number.get("ma_loai"):
            type_id = next((t["id"] for t in catalog if t.get("ma_loai") == number["ma_loai"]), None)
            detected_by = "ký hiệu"
        elif codes:
            type_id = next((t["id"] for t in catalog if t.get("ma_loai") and t["ma_loai"] == codes[0]), None)
            detected_by = "ký hiệu"
    if type_id is None:
        type_id = "CONG_VAN" if standard == "nd30" else "THONG_BAO"
        detected_by = "mặc định"
        warnings.append("Chưa nhận diện được loại văn bản; đã chọn tạm – hãy chọn lại loại trong form.")

    # số / ký hiệu
    if number.get("so"):
        fields["so"] = number["so"]
    if standard == "nd30" and codes:
        if type_id == "CONG_VAN" and len(codes) >= 2:
            fields["ma_co_quan"], fields["ma_don_vi"] = codes[0], "-".join(codes[1:])
        elif len(codes) >= 2:
            fields["ma_co_quan"] = "-".join(codes[1:])
        else:
            fields["ma_co_quan"] = codes[0]
    if standard == "hd05" and number.get("ma_co_quan"):
        fields["ma_co_quan"] = number["ma_co_quan"]

    rest = [x for i, x in enumerate(items) if i > (title_pos if title_pos is not None else idx - 1)]
    # trích yếu ngay dưới tên loại
    if title_pos is not None and _has_trich(standard, type_id):
        while rest and isinstance(rest[0], Paragraph) and not rest[0].text.strip():
            rest.pop(0)
        if rest and isinstance(rest[0], Paragraph):
            t0 = rest[0].text.strip()
            plain_title = len(t0) <= 200 and not t0.endswith((".", ":", ";")) and not classify_rule(t0)
            if t0 and len(t0) <= 250 and not re.match(r"^(Căn cứ|Kính gửi|Kính trình|Điều\s+\d|Thời gian|Xét|Ông|\-)", t0, re.I) \
                    and _norm(t0) not in ("-----",) and (_bold(rest[0]) or rest[0].alignment == 1 or plain_title):
                fields["trich_yeu"] = t0
                rest.pop(0)

    # quyết định 1.2 hay 1.3
    if type_id in ("QUYET_DINH_TRUC_TIEP", "QUYET_DINH_GIAN_TIEP", "QUYET_DINH") and standard == "nd30":
        body_text = " ".join(x.text for x in rest[:40] if isinstance(x, Paragraph))
        indirect = re.match(r"^\s*(Ban hành|Phê duyệt)", fields.get("trich_yeu", ""), re.I) or \
            re.search(r"Điều\s+1\s*\.\s*(Ban hành|Phê duyệt)\s.*kèm theo Quyết định này", body_text, re.I)
        type_id = "QUYET_DINH_GIAN_TIEP" if indirect else "QUYET_DINH_TRUC_TIEP"
    info = schema.type_info(standard, type_id)
    if info["template_status"] != "supported":
        return {"draft": {"standard": standard, "type_id": type_id, "fields": fields},
                "detected": {"standard": standard, "type_id": type_id, "template": None, "by": detected_by},
                "warnings": warnings + [info.get("status_note", "Chưa có mẫu chuẩn")], "unsupported": True}
    template = schema.template_for(standard, type_id)

    # ---------- nội dung + khu vực ký
    body_end = len(rest)
    sign_tables = []
    for k, x in enumerate(rest):
        if isinstance(x, Table):
            txt = _norm(" ".join(c.text for r in x.rows for c in r.cells))
            if "NOI NHAN" in txt or "THU KY" in txt or "CHU TOA" in txt or "HO VA TEN" in txt \
                    or "NGUOI GHI BIEN BAN" in txt or k >= len(rest) - 3:
                body_end = min(body_end, k)
                sign_tables.append(x)
        elif isinstance(x, Paragraph) and re.match(r"^Nơi nhận\s*:", x.text.strip(), re.I):
            body_end = min(body_end, k)
    body_items = rest[:body_end]
    tail_items = rest[body_end:]
    _read_content(body_items, template, fields, warnings, standard)
    _read_sign(sign_tables, [x for x in tail_items if isinstance(x, Paragraph)], template, fields)
    # địa chỉ liên hệ ở chân trang đầu (công văn)
    if any(c.get("kind") == "lien_he" for c in template["layout"]):
        sec = doc.sections[0]
        try:
            txt = "\n".join(p.text.strip() for p in sec.first_page_footer.paragraphs if p.text.strip())
        except Exception:  # noqa: BLE001
            txt = ""
        if txt:
            fields["lien_he"] = txt
    if len(doc.inline_shapes):
        warnings.append("File có hình ảnh: hình chưa được đưa vào trình soạn thảo.")
    extra_tables = [x for x in body_items if isinstance(x, Table)]
    if extra_tables:
        warnings.append(f"Có {len(extra_tables)} bảng trong phần nội dung: chưa chuyển sang trình soạn thảo, "
                        "hãy kiểm tra bản gốc.")
    return {"draft": {"standard": standard, "type_id": type_id, "fields": fields},
            "detected": {"standard": standard, "type_id": type_id, "template": template["id"],
                         "template_name": template["name"], "by": detected_by},
            "warnings": warnings}


def _has_trich(standard, type_id):
    try:
        t = schema.template_for(standard, type_id)
    except schema.SchemaError:
        return True
    return any(c["kind"] == "trich_yeu" for c in t["layout"])


def _read_header(left, right, standard, fields):
    names = []
    in_vv = False
    in_so = False
    for text, bold, p in left:
        if set(text) <= set("_-–—. *"):
            continue
        if re.match(r"^Số\b", text, re.I):
            fields["_so_text"] = text
            in_so = True
            continue
        if standard == "hd05" and in_so:
            # dưới số, ký hiệu (HD05): trích yếu công văn, dấu khẩn, chỉ dẫn dự thảo
            if _norm(text) in ("KHAN", "THUONG KHAN", "HOA TOC"):
                fields["do_khan"] = text.upper()
            elif re.match(r"^Dự\s+thảo\b", text, re.I):
                fields["du_thao"] = text
            elif text != text.upper():
                fields["trich_yeu"] = (fields.get("trich_yeu", "") + " " + text).strip()
            continue
        if re.match(r"^V/v\b", text, re.I):
            fields["trich_yeu"] = re.sub(r"^V/v\s*", "", text, flags=re.I)
            in_vv = True
            continue
        if in_vv:   # trích yếu công văn nhiều dòng
            fields["trich_yeu"] += " " + text
            continue
        n = _norm(text)
        if text.strip() in ("*", "-----") or "CONG HOA" in n or "DOC LAP" in n or "DANG CONG SAN" in n \
                or DATE_ANY.search(text) or DATE_RE.search(text):
            continue
        names.append((text, bold))
    if standard == "hd05" and not fields.get("trich_yeu"):
        pass
    bold_idx = [i for i, (_, b) in enumerate(names) if b]
    if bold_idx:
        first = bold_idx[0]
        fields["co_quan_chu_quan"] = "\n".join(t for t, _ in names[:first])
        fields["co_quan_ban_hanh"] = "\n".join(t for t, _ in names[first:])
    elif names:
        fields["co_quan_ban_hanh"] = names[-1][0]
        if len(names) > 1:
            fields["co_quan_chu_quan"] = "\n".join(t for t, _ in names[:-1])
    for text, _, _ in right:
        m = DATE_RE.search(text)
        if m:
            fields["dia_danh"] = m["place"].strip()
            fields["ngay"] = f"{m['y']}-{int(m['m']):02d}-{int(m['d']):02d}"
            break
    if not fields.get("co_quan_chu_quan"):
        fields.pop("co_quan_chu_quan", None)


_BLOCK_RULES = [
    ("dieu", re.compile(r"^Điều\s+(\d+[a-zđ]?)\s*[.:]\s*", re.I)),
    ("chuong", re.compile(r"^Chương\s+([IVXLC]+|\d+)\s*[.:]?\s*$", re.I)),
    ("muc", re.compile(r"^Mục\s+(\d+)\s*[.:]?\s*$", re.I)),
    ("phan", re.compile(r"^Phần\s+([IVXLC]+|\d+|thứ\s+\w+)\s*[.:]?\s*$", re.I)),
    ("la_ma", re.compile(r"^([IVXLC]+)\s*\.\s+(?=\S)")),
    ("khoan", re.compile(r"^(\d+)\s*\.\s+(?=\S)")),
    ("diem", re.compile(r"^([a-zđ])\s*\)\s+(?=\S)")),
    ("bullet", re.compile(r"^[-–•+]\s*(?=\S)")),
]


def classify_rule(text: str):
    """(loại, số ký tự tiền tố cần bỏ, số gõ tay) theo dấu hiệu rõ ràng; None nếu không có."""
    for kind, rx in _BLOCK_RULES:
        m = rx.match(text)
        if m:
            num = m.group(1) if m.groups() else ""
            return kind, m.end(), num
    return None


def _read_content(body_items, template, fields, warnings, standard):
    comps = template["layout"]
    kinds = {c["kind"] for c in comps}
    field_ids = {f["id"] for f in template["fields"]}
    line_rx = [(_template_regex(c["template"] if c["kind"] == "text_line"
                                else f"Điều {c['number']}. " + c["template"]), c)
               for c in comps if c["kind"] in ("text_line", "dieu_co_dinh")]
    body_field = next((c["field"] for c in comps if c["kind"] == "body"), None)
    blocks: list[dict] = []
    can_cu: list[str] = []
    kinh_gui: list[str] = []
    dien_nhan: list[str] = []
    mode = None
    pending_heading = None
    for x in body_items:
        if not isinstance(x, Paragraph):
            continue
        text = x.text.replace("\xa0", " ").strip()
        if not text or set(text) <= set("-_–. "):
            continue
        if re.fullmatch(r"(QUYẾT\s+NGHỊ|QUYẾT\s+ĐỊNH)\s*:", text, re.I):
            mode = "body"
            continue
        if "tham_quyen" in kinds and not can_cu and not blocks and "tham_quyen" not in fields \
                and text == text.upper() and re.search(r"[A-ZĐÀ-Ỹ]", text) and _bold(x) and len(text) < 200:
            fields["tham_quyen"] = text
            continue
        if "can_cu" in field_ids and re.match(r"^[-–]?\s*(Căn cứ)\b", text, re.I) and mode != "body" and not blocks:
            can_cu.append(re.sub(r"^[-–]\s*", "", text))
            continue
        if ("de_nghi" in field_ids or "can_cu" in field_ids) and re.match(r"^(Theo|Xét)\s+đề nghị\b", text, re.I) \
                and mode != "body" and not blocks:
            if "de_nghi" in field_ids:
                fields["de_nghi"] = re.sub(r"^Theo đề nghị của\s*", "", text, flags=re.I).rstrip(" .;")
            else:
                can_cu.append(text)
            continue
        kg = re.match(r"^Kính\s+(?:gửi|trình)\s*:?\s*(.*)$", text, re.I)
        if kg and not blocks:
            if kg[1].strip():
                kinh_gui.append(kg[1].strip())
            mode = "kinh_gui"
            continue
        if mode == "kinh_gui" and (re.match(r"^[-–•]\s*\S", text) or (standard == "hd05" and text.endswith(";")))\
                and len(text) <= 200:
            kinh_gui.append(re.sub(r"^[-–•]\s*", "", text))
            continue
        cd = re.match(r"^(.+?)\s+điện\s*:\s*$", text, re.I)
        if cd and "cong_dien_gui" in kinds and not blocks:
            fields["nguoi_dien"] = cd[1].strip()
            mode = "dien"
            continue
        if mode == "dien" and re.match(r"^[-–•]\s*\S", text) and len(text) <= 250:
            dien_nhan.append(re.sub(r"^[-–•]\s*", "", text))
            continue
        matched = False
        for (rx, names), comp in line_rx:
            m = rx.match(text)
            if m and names:
                for name in names:
                    v = (m.group(name) or "").strip().rstrip(";")
                    if v and v not in ("…", "..."):
                        fields[name] = v
                matched = True
                mode = "body" if comp["kind"] == "dieu_co_dinh" else "lines"
                break
            if m and not names:
                matched = True
                break
        if matched:
            continue
        if mode in ("kinh_gui", "dien"):
            mode = "body"
        # khối nội dung
        hit = classify_rule(text)
        align = {1: "center", 2: "right", 3: "justify"}.get(x.alignment, None)
        if pending_heading is not None:
            pending_heading["html"] = _rich(x)
            pending_heading = None
            continue
        if hit:
            kind, skip, num = hit
            lead = len(x.text) - len(x.text.lstrip())
            if kind in ("chuong", "muc", "phan"):
                blk = {"type": kind, "html": "", "number": "" if kind != "phan" else "", "source": "rule"}
                blocks.append(blk)
                pending_heading = blk
                continue
            html = _rich(x, lead + skip)
            blk = {"type": kind, "html": html, "source": "rule"}
            whole = re.fullmatch(r"<strong>(.*)</strong>", html, re.S)
            if whole and "<strong>" not in whole[1] and kind in ("dieu", "khoan", "la_ma"):
                blk["html"] = whole[1]
                if kind != "la_ma":
                    blk["tieu_de"] = True
            blocks.append(blk)
        else:
            blk = {"type": "p", "html": _rich(x), "source": "default"}
            if align in ("center", "right"):
                blk["align"] = align
            blocks.append(blk)
    if blocks:
        last = blocks[-1]
        last["html"] = re.sub(r"\.?/\.\s*$", ".", last["html"]).rstrip()
        if last["html"].endswith("..") and not last["html"].endswith("..."):
            last["html"] = last["html"][:-1]
    # Điều 1 cố định của mẫu 1.3 đã tách thành trường -> các Điều còn lại bắt đầu từ 2
    if body_field:
        fields[body_field] = [{k: v for k, v in b.items() if k != "source"} | {"src": b.get("source", "")}
                              for b in blocks if b["type"] in BLOCK_TYPES]
    elif blocks:
        warnings.append("Mẫu này không có khối nội dung tự do; các đoạn không khớp dòng cố định của mẫu đã bỏ qua.")
    if can_cu:
        fields["can_cu"] = can_cu
    if kinh_gui:
        fields["kinh_gui"] = [x.rstrip(";.") for x in kinh_gui]
    if dien_nhan:
        fields["noi_nhan_dien"] = [x.rstrip(";.") for x in dien_nhan]


def _split_signer(lines: list[str], fields: dict, standard: str):
    lines = [x for x in lines if x.strip() and not x.strip().startswith("(")]
    if not lines:
        return
    name = lines[-1] if lines[-1] != lines[-1].upper() else ""
    heads = lines[:-1] if name else lines
    if name:
        fields["ho_ten"] = name
    if not heads:
        return
    m = re.match(r"^(TM\.|T/M|Q\.|KT\.|K/T|TL\.|T/L|TUQ\.)\s*(.*)$", heads[0])
    if standard == "hd05":
        pm = re.match(r"^(T/M|K/T|T/L|Q\.)\s*(.*)$", heads[0])
        if pm and pm[1] == "Q.":
            fields["quyen_han"], fields["chuc_vu"] = "Q.", pm[2]
        elif pm:
            fields["quyen_han"], fields["quyen_han_cua"] = pm[1], pm[2]
            fields["chuc_vu"] = "\n".join(heads[1:])
        else:
            fields["chuc_vu"] = "\n".join(heads)
        return
    if m and m[1] == "Q.":
        fields["quyen_han"] = "Q."
        fields["chuc_vu"] = m[2]
    elif m:
        fields["quyen_han"] = m[1]
        fields["quyen_han_cua"] = m[2]
        fields["chuc_vu"] = " ".join(heads[1:])
    else:
        fields["chuc_vu"] = " ".join(heads)


def _noi_nhan(lines: list[str], fields: dict):
    items = []
    for x in lines:
        x = x.strip()
        if not x or re.match(r"^Nơi nhận\s*:?$", x, re.I):
            continue
        x = re.sub(r"^[-–•]\s*", "", x)
        lm = re.match(r"^Lưu\s*:?\s*(?:VT\s*,?\s*)?(.*)$", x, re.I)
        if lm:
            fields["luu"] = lm[1].rstrip(" .")
            continue
        items.append(x.rstrip(" ;,."))
    if items:
        fields["noi_nhan"] = items


def _read_sign(tables, paras, template, fields):
    standard = template["standard"]
    kinds = {c["kind"] for c in template["layout"]}
    for t in tables:
        for row in t.rows:
            cells = row.cells
            texts = [[ln for ln, _, _ in _cell_lines(c)] for c in cells]
            for col, lines in enumerate(texts):
                joined = _norm(" ".join(lines))
                if not lines:
                    continue
                if joined.startswith("NOI NHAN"):
                    _noi_nhan(lines, fields)
                elif joined.startswith("THU KY") and "bien_ban_sign" in kinds:
                    rest = [x for x in lines[1:] if not x.startswith("(")]
                    if rest:
                        fields["ho_ten_thu_ky"] = rest[-1]
                elif joined.startswith("CHU TOA") and "bien_ban_sign" in kinds:
                    rest = [x for x in lines[1:] if not x.startswith("(")]
                    if rest:
                        fields["ho_ten_chu_toa"] = rest[-1]
                        if len(rest) > 1:
                            fields["chuc_vu_chinh_quyen"] = rest[0]
                elif joined.startswith("NGUOI GHI BIEN BAN") and "party_bien_ban_sign" in kinds:
                    rest = [x for x in lines[1:] if not x.startswith("(")]
                    if rest:
                        fields["ho_ten_nguoi_ghi"] = rest[-1]
                elif joined.startswith("CHU TRI HOI NGHI") and "party_bien_ban_sign" in kinds:
                    rest = [x for x in lines[1:] if not x.startswith("(")]
                    if rest:
                        fields["ho_ten_chu_tri"] = rest[-1]
                elif joined.startswith("XAC NHAN"):
                    fields["hien_xac_nhan"] = True
                elif col == len(cells) - 1:
                    _split_signer(lines, fields, standard)
    if paras:
        lines = [p.text for p in paras]
        if any(re.match(r"^Nơi nhận", x.strip(), re.I) for x in lines):
            start = next(i for i, x in enumerate(lines) if re.match(r"^Nơi nhận", x.strip(), re.I))
            nn = []
            for x in lines[start:]:
                if x.strip() and not re.match(r"^[-–•]|^Nơi nhận", x.strip(), re.I):
                    break
                nn.append(x)
            _noi_nhan(nn, fields)
