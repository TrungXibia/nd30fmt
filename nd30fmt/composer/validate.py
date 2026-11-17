"""Kiểm tra bản thảo theo schema của mẫu (trường bắt buộc, số/ký hiệu, dấu câu...)."""
from __future__ import annotations

import re

from . import schema
from .text import clean_list, clean_text, parse_rich, runs_text

PL1 = "NĐ 30/2020/NĐ-CP, Phụ lục I"


def _visible(field: dict, type_id: str, fields: dict) -> bool:
    if "only_types" in field and type_id not in field["only_types"]:
        return False
    if type_id in field.get("skip_types", []):
        return False
    cond = field.get("show_if")
    if cond:
        for k, allowed in cond.items():
            if clean_text(fields.get(k)) not in allowed:
                return False
    return True


def _empty(field: dict, value) -> bool:
    kind = field.get("type")
    if kind in ("list", "lines"):
        return not clean_list(value)
    if kind == "blocks":
        return not any(runs_text(parse_rich((b or {}).get("html"))).strip() for b in (value or []) if isinstance(b, dict))
    if kind == "checkbox":
        return False
    return not clean_text(value)


def validate_draft(draft: dict) -> list[dict]:
    out: list[dict] = []
    standard, type_id = draft.get("standard"), draft.get("type_id")
    fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    try:
        info = schema.type_info(standard, type_id)
    except schema.SchemaError as e:
        return [{"level": "error", "field": "type_id", "message": str(e), "source": ""}]
    if info["template_status"] != "supported":
        return [{"level": "error", "field": "type_id", "message": f"{info['label']}: {info.get('status_note')}",
                 "source": "NĐ 30/2020/NĐ-CP Phụ lục III"}]
    t = schema.template_for(standard, type_id)
    rules = set(t.get("validation", []))

    def add(level, field, message, source=""):
        out.append({"level": level, "field": field, "message": message, "source": source})

    for f in t["fields"]:
        if f.get("required") and _visible(f, type_id, fields) and _empty(f, fields.get(f["id"])):
            if f.get("default_from") or f.get("default"):
                pass
            add("error", f["id"], f"Chưa nhập: {f['label']}", t["source"].get("template", "") if isinstance(t["source"], dict) else "")

    so = clean_text(fields.get("so"))
    HD = "Hướng dẫn 05-HD/VPTW"
    if "party_number" in rules and so.isdigit() and len(so) == 1:
        add("info", "so", f"Số {so} < 10: tự ghi thêm số 0 phía trước ({so.zfill(2)}).", f"{HD}, mục 3.2.2")
    if "party_punctuation" in rules:
        items = clean_list(fields.get("noi_nhan"))
        if type_id in ("CONG_VAN", "TO_TRINH") and items and not re.match(r"^Như trên", items[0], re.I):
            add("warn", "noi_nhan", "Công văn, tờ trình: dòng đầu phần “Nơi nhận” có thêm từ “Như trên”.",
                f"{HD}, mục 9.2.3–9.2.4")
        if clean_list(fields.get("can_cu")):
            add("info", "can_cu", "Mỗi căn cứ: trước có “-”, sau có “;”, căn cứ cuối có “.” – tự chỉnh khi trình bày.",
                f"{HD}, mục 6.2.3")
        qh = clean_text(fields.get("quyen_han"))
        if qh in ("T/M", "K/T", "T/L") and not clean_text(fields.get("quyen_han_cua")):
            add("error", "quyen_han_cua", f"Ghi rõ “{qh} …” (tên tập thể hoặc chức vụ cấp trưởng).", f"{HD}, mục 7.1.1")
    if "number_padding" in rules and so.isdigit() and len(so) == 1:
        add("info", "so", f"Số {so} < 10: tự ghi thêm số 0 phía trước ({so.zfill(2)}).", f"{PL1} Mục II.3.c")
    if so and not so.isdigit():
        add("warn", "so", "Số văn bản ghi bằng chữ số Ả Rập.", f"{PL1} Mục II.3.a")
    for key in ("ma_co_quan", "ma_don_vi"):
        v = clean_text(fields.get(key))
        if v and re.search(r"\s", v):
            add("warn", key, "Chữ viết tắt trong ký hiệu không có khoảng trắng.", f"{PL1} Mục II.3.c")
    custom = clean_text(fields.get("ky_hieu_tuy_chinh"))
    if custom and standard == "nd30" and re.search(r"/\s|\s/|\s-|-\s", custom):
        add("warn", "ky_hieu_tuy_chinh", "Giữa số và ký hiệu có “/”, giữa các nhóm chữ viết tắt có “-”, không cách chữ.",
            f"{PL1} Mục II.3.c")
    has_date = any(c.get("kind") == "header" and "dia_danh_ngay" in c.get("right", []) for c in t["layout"]) \
        or standard == "hd05"
    if has_date and not clean_text(fields.get("ngay")):
        add("warn", "ngay", "Chưa có ngày ban hành: bản xem trước ghi “ngày … tháng … năm …”.", f"{PL1} Mục II.4")
    if "can_cu_punctuation" in rules:
        lines = clean_list(fields.get("can_cu"))
        bad = [x for x in lines[:-1] if not x.rstrip().endswith(";")]
        if bad:
            add("info", "can_cu", "Mỗi căn cứ kết thúc bằng “;”, căn cứ cuối bằng “.” – đã tự chỉnh khi trình bày.",
                f"{PL1} Mục II.6.a")
    if "no_ten_loai" in rules and re.match(r"^\s*CÔNG VĂN\b", clean_text(fields.get("trich_yeu")), re.I):
        add("warn", "trich_yeu", "Công văn không ghi tên loại; trích yếu bắt đầu sau “V/v”.", f"{PL1} Mục II.5.b")
    if "kinh_gui_punctuation" in rules:
        items = clean_list(fields.get("kinh_gui"))
        if len(items) > 1 and any(not x.endswith((";", ".")) for x in items):
            add("info", "kinh_gui", "Nhiều nơi nhận: mỗi dòng “-” … “;”, dòng cuối “.” – đã tự chỉnh khi trình bày.",
                f"{PL1} Mục II.9.d")
    if "noi_nhan_punctuation" in rules:
        items = clean_list(fields.get("noi_nhan"))
        if any(re.match(r"^Lưu\b", x, re.I) for x in items):
            add("info", "noi_nhan", "Dòng “Lưu: VT, …” được tạo tự động từ ô Lưu; dòng Lưu nhập tay đã bỏ qua.",
                f"{PL1} Mục II.9.d")
    if type_id == "CONG_VAN" and standard == "nd30" and clean_list(fields.get("noi_nhan")) and \
            not re.match(r"^Như trên", clean_list(fields.get("noi_nhan"))[0], re.I):
        add("warn", "noi_nhan", "Nơi nhận của công văn: phía dưới là “Như trên”, tiếp theo là các nơi liên quan.",
            f"{PL1} Mục II.9.b")
    return out
