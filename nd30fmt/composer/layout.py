"""Dựng MÔ HÌNH BỐ CỤC (layout model) từ bản thảo + schema.

Đây là nguồn duy nhất cho cả bản xem trước (giao diện vẽ từ JSON này) và file Word
(docx_writer đọc cùng JSON này), nên xem trước và Word luôn khớp nhau.

Đơn vị: pt (1 mm = 72/25,4 pt). Mô hình:
    {"page": {...}, "items": [para | table], "header": {...}, "first_footer": [para], "meta": {...},
     "notices": [...]}
    para  = {"t": "p", "runs": [{"t", "b", "i", "u", "size"}], "align", "ind": {"left","right","first"},
             "sp": {"before","after","line": {"rule": "multiple"|"exact", "value"}},
             "border": {"bottom"|"top": {"w": 0.75}}, "role", "keep_next", "size"}
    table = {"t": "table", "cols": [pt,...], "rows": [[{"items": [para...]}]], "role"}
"""
from __future__ import annotations

import datetime as _dt
import re

from . import schema
from .text import (clean_list, clean_text, letter, pad_number, parse_rich, roman, runs_text, split_lines,
                   strip_runs, text_width_pt, wrap_width_pt)

MM = 72 / 25.4
PAGE_W, PAGE_H = 210 * MM, 297 * MM
SINGLE = {"rule": "multiple", "value": 1.0}


class LayoutError(ValueError):
    pass


# ------------------------------------------------------------------------------------ settings
def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float(default)
    return min(max(v, lo), hi)


def resolve_settings(standard: str, raw: dict | None) -> tuple[dict, list[str]]:
    """Thiết lập của người dùng -> giá trị hợp lệ theo chuẩn (ngoài khoảng: kéo về biên + cảnh báo)."""
    raw = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    def take(name, lo, hi, default, label):
        if name in raw and raw[name] not in (None, ""):
            v = _clamp(raw[name], lo, hi, default)
            try:
                if abs(float(raw[name]) - v) > 1e-6:
                    notes.append(f"{label} {raw[name]} ngoài khoảng cho phép [{lo}–{hi}] – đã dùng {v:g}.")
            except (TypeError, ValueError):
                notes.append(f"{label} không hợp lệ – đã dùng {v:g}.")
            return v
        return float(default)

    margins_raw = raw.get("margins") if isinstance(raw.get("margins"), dict) else {}
    if standard == "nd30":
        fmt = schema.nd30_format()
        mar = {}
        for side, spec in fmt["page"]["margins_mm"].items():
            lo, hi = spec["range"]
            sub = {"v": margins_raw.get(side)} if side in margins_raw else {}
            mar[side] = take_side(sub, lo, hi, spec["default"], f"Lề {_SIDE[side]} (mm)", notes)
        body = fmt["body"]
        size = int(round(take("body_size", *body["size"]["range"], body["size"]["default"], "Cỡ chữ nội dung")))
        profile = dict(fmt["size_profiles"][str(size)])
        sizes_raw = raw.get("sizes") if isinstance(raw.get("sizes"), dict) else {}
        for role, v in sizes_raw.items():
            r = fmt["roles"].get(role)
            if role in profile and r and "size" in r:
                lo, hi = r["size"]
                nv = _clamp(v, lo, hi, profile[role])
                if nv != _clamp(v, -1e9, 1e9, nv):
                    notes.append(f"Cỡ chữ {role} {v} ngoài khoảng [{lo}–{hi}] của PL I – đã dùng {nv:g}.")
                profile[role] = nv
        indent = take("indent_cm", 1.0, 1.27, body["first_line_indent_cm"]["default"], "Thụt đầu dòng (cm)")
        indent = min(body["first_line_indent_cm"]["allowed"], key=lambda a: abs(a - indent))
        s = {
            "standard": "nd30", "margins_mm": mar, "sizes": profile, "body_size": size,
            "line": {"rule": "multiple", "value": take("line_spacing", *body["line_spacing"]["range"],
                                                       body["line_spacing"]["default"], "Giãn dòng")},
            "indent_pt": indent / 2.54 * 72, "indent_cm": indent,
            "before": take("space_before_pt", *body["space_before_pt"]["range"], body["space_before_pt"]["default"],
                           "Khoảng cách đoạn (pt)"),
            "sign_blank_lines": int(take("sign_blank_lines", 1, 8, fmt["signature"]["blank_lines"], "Dòng trống chữ ký")),
            "ratio_co_quan": take("line_ratio_co_quan", *fmt["lines"]["co_quan"]["range"], fmt["lines"]["co_quan"]["default"],
                                  "Tỉ lệ đường kẻ dưới tên cơ quan"),
            "ratio_trich_yeu": take("line_ratio_trich_yeu", *fmt["lines"]["trich_yeu"]["range"],
                                    fmt["lines"]["trich_yeu"]["default"], "Tỉ lệ đường kẻ dưới trích yếu"),
            "header_distance_pt": fmt["page"]["header_distance_mm"] * MM,
            "page_number_size": profile["so_trang"],
            "hide_first_page_number": fmt["page"]["page_number"]["hide_first_page"],
        }
        return s, notes
    if standard == "hd05":
        pf = schema.party_format()
        mar = {}
        for side, spec in pf["margins_mm"].items():
            lo, hi = spec["range"]
            sub = {"v": margins_raw.get(side)} if side in margins_raw else {}
            mar[side] = take_side(sub, lo, hi, spec["default"], f"Lề {_SIDE[side]} (mm)", notes)
        b = pf["body"]
        size = take("body_size", *b["size"]["range"], b["size"]["default"], "Cỡ chữ nội dung")
        sizes = {k: v["default"] for k, v in pf["roles"].items()}
        for k in ("body", "can_cu", "dieu", "phan_label", "phan_title", "muc_label", "muc_title"):
            if k in sizes:
                lo, hi = pf["roles"][k]["size"]
                sizes[k] = min(max(size, lo), hi)
        sizes_raw = raw.get("sizes") if isinstance(raw.get("sizes"), dict) else {}
        for role, v in sizes_raw.items():
            if role in pf["roles"]:
                lo, hi = pf["roles"][role]["size"]
                sizes[role] = _clamp(v, lo, hi, sizes[role])
        s = {
            "standard": "hd05", "margins_mm": mar, "sizes": sizes, "body_size": size,
            "line": {"rule": "exact", "value": take("line_spacing_pt", *b["line_spacing_pt"]["range"],
                                                    b["line_spacing_pt"]["default"], "Giãn dòng (pt, Exactly)")},
            "indent_cm": take("indent_cm", *b["first_line_indent_cm"]["range"], b["first_line_indent_cm"]["default"],
                              "Thụt đầu dòng (cm)"),
            "before": take("space_before_pt", *b["space_before_pt"]["range"], b["space_before_pt"]["default"],
                           "Khoảng cách đoạn (pt)"),
            "sign_blank_lines": int(take("sign_blank_lines", 1, 8, 4, "Dòng trống chữ ký")),
            "header_distance_pt": pf["page_number"]["distance_from_top_mm"] * MM,
            "page_number_size": pf["page_number"]["size"],
            "hide_first_page_number": pf["page_number"]["hide_first_page"],
            # HD05 Phần II mục IV.4.2: in hai mặt – mặt sau lề trái 15, lề phải 30 mm (lề đối xứng)
            "mirror": raw.get("in_hai_mat") in (True, "true", 1, "1", "on"),
        }
        s["indent_pt"] = s["indent_cm"] / 2.54 * 72
        return s, notes
    raise LayoutError("Chuẩn không hợp lệ (chỉ nd30 hoặc hd05)")


_SIDE = {"top": "trên", "bottom": "dưới", "left": "trái", "right": "phải"}


def take_side(sub, lo, hi, default, label, notes):
    if "v" in sub and sub["v"] not in (None, ""):
        v = _clamp(sub["v"], lo, hi, default)
        try:
            if abs(float(sub["v"]) - v) > 1e-6:
                notes.append(f"{label} {sub['v']} ngoài khoảng [{lo}–{hi}] – đã dùng {v:g}.")
        except (TypeError, ValueError):
            notes.append(f"{label} không hợp lệ – đã dùng {v:g}.")
        return v
    return float(default)


# ------------------------------------------------------------------------------------ helpers
def P(text_or_runs, size, *, bold=False, italic=False, underline=False, caps=False, align="left", first=0.0,
      left=0.0, right=0.0, before=0.0, after=0.0, line=None, border=None, role=None, keep_next=False, endable=False):
    if isinstance(text_or_runs, str):
        runs = [{"t": text_or_runs}] if text_or_runs else []
    else:
        runs = [dict(r) for r in text_or_runs]
    for r in runs:
        r["b"] = bool(r.get("b")) or bold
        r["i"] = bool(r.get("i")) or italic
        r["u"] = bool(r.get("u")) or underline
        r.setdefault("size", size)
        if caps:
            r["t"] = r["t"].upper()
    p = {"t": "p", "runs": runs, "align": align, "size": size,
         "ind": {"left": round(left, 2), "right": round(right, 2), "first": round(first, 2)},
         "sp": {"before": before, "after": after, "line": line or SINGLE}, "role": role}
    if border:
        p["border"] = border
    if keep_next:
        p["keep_next"] = True
    if endable:
        p["endable"] = True
    return p


def rule_para(width, avail, size=1.0, align="center", role="line"):
    """Đoạn rỗng có viền dưới dài đúng `width` (đường kẻ theo PL I, không dùng ký tự '-')."""
    width = min(width, avail)
    if align == "center":
        left = right = (avail - width) / 2
    elif align == "right":
        left, right = avail - width, 0.0
    else:
        left, right = 0.0, avail - width
    p = P("", size, align="left", left=left, right=right, line={"rule": "exact", "value": 1.0},
          border={"bottom": {"w": 0.75, "len": round(width, 2)}}, role=role)
    return p


def _value(fields: dict, key: str) -> str:
    return clean_text(fields.get(key))


def _fmt_date(iso: str, place: str) -> str:
    place = place or "…"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", iso or "")
    if not m:
        return f"{place}, ngày … tháng … năm …"
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    try:
        _dt.date(y, mo, d)
    except ValueError:
        return f"{place}, ngày … tháng … năm …"
    # PL I Mục II.4.b: ngày < 10 và tháng 1, 2 thêm số 0
    dd = f"{d:02d}"
    mm = f"{mo:02d}" if mo in (1, 2) else str(mo)
    return f"{place}, ngày {dd} tháng {mm} năm {y}"


def _fill(template: str, fields: dict, placeholder="…") -> str:
    def rep(m):
        v = _value(fields, m[1])
        return v if v else placeholder
    return re.sub(r"\{(\w+)\}", rep, template)


def _content_width(s) -> float:
    m = s["margins_mm"]
    return PAGE_W - (m["left"] + m["right"]) * MM


def _cols(widths, total):
    k = total / sum(widths)
    out = [w * k for w in widths]
    out[-1] = total - sum(out[:-1])
    return out


# ------------------------------------------------------------------------------------ số, ký hiệu
def number_text(standard: str, type_id: str, fields: dict, template: dict) -> str:
    custom = _value(fields, "ky_hieu_tuy_chinh")
    if custom:
        return custom
    so = pad_number(_value(fields, "so"))
    info = schema.type_info(standard, type_id)
    ma_cq = _value(fields, "ma_co_quan").upper() or "…"
    if standard == "nd30":
        code = template["number"]["ky_hieu"].format(
            ma_co_quan=ma_cq, ma_loai=info.get("ma_loai") or "…",
            ma_don_vi=_value(fields, "ma_don_vi").upper() or "…")
        return f"Số: {so or '     '}/{code}" if so else f"Số:      /{code}"
    code = "CV" if type_id == "CONG_VAN" else (info.get("ma_loai") or "…")
    return f"Số {so or '   '}-{code}/{ma_cq}"


# ------------------------------------------------------------------------------------ nội dung (block)
BLOCK_TYPES = ("p", "bullet", "dieu", "khoan", "diem", "la_ma", "phan", "chuong", "muc")


def number_blocks(blocks: list[dict], start_dieu: int = 1) -> list[str]:
    """Nhãn số tự động cho từng khối (dùng chung cho form, xem trước và Word)."""
    c = {"phan": 0, "chuong": 0, "muc": 0, "dieu": start_dieu - 1, "la_ma": 0, "khoan": 0, "diem": 0}
    labels = []
    for b in blocks:
        t = b.get("type")
        manual = str(b.get("number") or "").strip()
        if t == "phan":
            c["phan"] = _manual_int(manual, c["phan"] + 1)
            labels.append(f"Phần {manual or roman(c['phan'])}")
        elif t == "chuong":
            c["chuong"] = _manual_int(manual, c["chuong"] + 1)
            c["muc"] = 0
            labels.append(f"Chương {manual or roman(c['chuong'])}")
        elif t == "muc":
            c["muc"] = _manual_int(manual, c["muc"] + 1)
            labels.append(f"Mục {manual or c['muc']}")
        elif t == "dieu":
            c["dieu"] = _manual_int(manual, c["dieu"] + 1)
            c["khoan"] = c["diem"] = 0
            labels.append(f"Điều {manual or c['dieu']}.")
        elif t == "la_ma":
            c["la_ma"] = _manual_roman(manual, c["la_ma"] + 1)
            c["khoan"] = c["diem"] = 0
            labels.append(f"{manual or roman(c['la_ma'])}.")
        elif t == "khoan":
            c["khoan"] = _manual_int(manual, c["khoan"] + 1)
            c["diem"] = 0
            labels.append(f"{manual or c['khoan']}.")
        elif t == "diem":
            c["diem"] += 1
            labels.append(f"{manual or letter(c['diem'])})")
        elif t == "bullet":
            labels.append("-")
        else:
            labels.append("")
    return labels


def _manual_int(manual: str, default: int) -> int:
    return int(manual) if manual.isdigit() else default


def _manual_roman(manual: str, default: int) -> int:
    vals = {roman(i): i for i in range(1, 100)}
    return vals.get(manual.upper(), default)


def _clean_blocks(blocks) -> list[dict]:
    out = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict):
            continue
        t = b.get("type") if b.get("type") in BLOCK_TYPES else "p"
        out.append({"type": t, "html": str(b.get("html") or ""), "align": b.get("align"),
                    "number": str(b.get("number") or "").strip()[:8], "tieu_de": bool(b.get("tieu_de"))})
    return out


# ------------------------------------------------------------------------------------ dựng bố cục
class _Ctx:
    def __init__(self, standard, type_id, fields, settings, template):
        self.standard, self.type_id, self.f, self.s, self.t = standard, type_id, fields, settings, template
        self.W = _content_width(settings)
        self.items: list[dict] = []
        self.first_footer: list[dict] = []
        self.first_header: list[dict] = []
        self.notices: list[str] = []
        self.party = standard == "hd05"
        self.info = schema.type_info(standard, type_id)
        self.block_labels: dict[str, list[str]] = {}

    def size(self, role):
        sz = self.s["sizes"]
        if role in sz:
            return sz[role]
        return self.s["sizes"].get("body", self.s["body_size"])

    # đoạn nội dung chuẩn
    def body_para(self, runs, *, bold=False, italic=False, align="justify", first=None, before=None, role="body",
                  caps=False, endable=True, left=0.0):
        return P(runs, self.size("body"), bold=bold, italic=italic, caps=caps, align=align,
                 first=self.s["indent_pt"] if first is None else first, left=left,
                 before=self.s["before"] if before is None else before, line=self.s["line"], role=role,
                 endable=endable)


def build_layout(draft: dict) -> dict:
    if not isinstance(draft, dict):
        raise LayoutError("Bản thảo không hợp lệ")
    standard = draft.get("standard") if draft.get("standard") in schema.STANDARDS else None
    if not standard:
        raise LayoutError("Chọn chuẩn: nd30 (NĐ 30/2020) hoặc hd05 (văn bản Đảng)")
    type_id = str(draft.get("type_id") or "")
    try:
        template = schema.template_for(standard, type_id)
    except schema.SchemaError as e:
        raise LayoutError(str(e)) from e
    fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    settings, notes = resolve_settings(standard, draft.get("settings"))
    ctx = _Ctx(standard, type_id, fields, settings, template)
    ctx.notices.extend(notes)
    for comp in template["layout"]:
        if ctx.type_id in comp.get("skip_types", []):
            continue
        if "only_types" in comp and ctx.type_id not in comp["only_types"]:
            continue
        getattr(_Builders, comp["kind"])(ctx, comp)
    _apply_end_mark(ctx)
    for it in ctx.items:
        it.pop("endable", None)
    m = settings["margins_mm"]
    return {
        "version": 40,
        "page": {"w": round(PAGE_W, 2), "h": round(PAGE_H, 2),
                 "margins": {k: round(v * MM, 2) for k, v in m.items()}, "margins_mm": m,
                 "header_distance": round(settings["header_distance_pt"], 2),
                 "content_width": round(ctx.W, 2), "mirror": bool(settings.get("mirror"))},
        "header": {"page_number": {"size": settings["page_number_size"], "align": "center",
                                   "hide_first_page": settings["hide_first_page_number"]}},
        "items": ctx.items,
        "first_footer": ctx.first_footer,
        "first_header": ctx.first_header,
        "meta": {"standard": standard, "type_id": type_id, "template": template["id"],
                 "template_name": template["name"], "template_file": template.get("file"),
                 "number_text": number_text(standard, type_id, fields, template),
                 "block_labels": ctx.block_labels,
                 "settings": {k: v for k, v in settings.items() if k != "line"} | {"line": settings["line"]}},
        "notices": ctx.notices,
    }


def _apply_end_mark(ctx: _Ctx):
    """Mẫu 1.1–1.10: nội dung kết thúc bằng “/.” – thêm vào đoạn nội dung cuối nếu người soạn chưa ghi."""
    paras = [it for it in ctx.items if it.get("t") == "p" and it.get("endable") and runs_text(it["runs"]).strip()]
    if not paras:
        return
    if ctx.party:
        # HD05 mục 6.2.2: kết thúc nội dung văn bản có dấu chấm
        tail = paras[-1]["runs"][-1]
        text = tail["t"].rstrip()
        if text and text[-1] not in ".!?…":
            tail["t"] = re.sub(r"[;,:]+$", "", text) + "."
        return
    allp = [it for it in ctx.items if it.get("t") == "p"]
    if any(runs_text(p["runs"]).rstrip().endswith("/.") for p in allp):
        return
    last = paras[-1]
    runs = last["runs"]
    tail = runs[-1]
    text = tail["t"].rstrip()
    tail["t"] = text + ("/." if text.endswith(".") else "./.")


def _punct(text: str, end: str) -> str:
    text = text.rstrip()
    text = re.sub(r"[;,.:]+$", "", text).rstrip()
    return text + end if text else text


class _Builders:
    # ------------------------------------------------------------------ đầu trang NĐ30
    @staticmethod
    def header(ctx: _Ctx, comp):
        s, f = ctx.s, ctx.f
        W = ctx.W
        cols = _cols(ctx.t["geometry"]["header_cols_pt"], W)
        qh_size, tn_size = ctx.size("quoc_hieu"), ctx.size("tieu_ngu")
        qh = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
        tn = "Độc lập - Tự do - Hạnh phúc"
        need = max(text_width_pt(qh, qh_size, True), text_width_pt(tn, tn_size, True)) + 6
        if cols[1] < need:  # bảo đảm Quốc hiệu nằm trên một dòng
            cols = [W - need, need]
        lw, rw = cols
        left1, left2, right1, right2 = [], [], [], []
        cq_size, cqcq_size = ctx.size("co_quan_ban_hanh"), ctx.size("co_quan_chu_quan")
        chu_quan = _value(f, "co_quan_chu_quan")
        ban_hanh = _value(f, "co_quan_ban_hanh") or "TÊN CƠ QUAN, TỔ CHỨC"
        for line in [x for x in chu_quan.split("\n") if x.strip()]:
            left1.append(P(line, cqcq_size, caps=True, align="center", role="co_quan_chu_quan"))
        for line in [x for x in ban_hanh.split("\n") if x.strip()]:
            left1.append(P(line, cq_size, bold=True, caps=True, align="center", role="co_quan_ban_hanh"))
        longest, _ = wrap_width_pt(ban_hanh.upper(), cq_size, True, False, lw)
        left1.append(rule_para(longest * s["ratio_co_quan"], lw, role="line_co_quan"))
        right1.append(P(qh, qh_size, bold=True, align="center", role="quoc_hieu"))
        tw = text_width_pt(tn, tn_size, True) + 2  # 1 pt dư mỗi bên để chữ không xuống dòng
        pad = max((rw - tw) / 2, 0)
        right1.append(P(tn, tn_size, bold=True, align="center", left=pad, right=pad, role="tieu_ngu",
                        border={"bottom": {"w": 0.75, "len": round(tw, 2)}}))
        left2.append(P(number_text(ctx.standard, ctx.type_id, f, ctx.t), ctx.size("so_ky_hieu"), align="center",
                       before=6, role="so_ky_hieu"))
        if "vv" in comp["left"]:
            ty = _value(f, "trich_yeu")
            ty = re.sub(r"^V/v\s*", "", ty, flags=re.I)
            left2.append(P(f"V/v {ty}" if ty else "V/v …", ctx.size("trich_yeu_cong_van"), align="center",
                           before=6, role="trich_yeu_cong_van"))
        if "dia_danh_ngay" in comp["right"]:
            right2.append(P(_fmt_date(_value(f, "ngay"), _value(f, "dia_danh")), ctx.size("dia_danh_ngay"),
                            italic=True, align="center", before=6, role="dia_danh_ngay"))
        else:
            right2.append(P("", ctx.size("dia_danh_ngay"), before=6, role="empty"))
        ctx.items.append({"t": "table", "role": "header", "cols": [round(lw, 2), round(rw, 2)],
                          "rows": [[{"items": left1}, {"items": right1}], [{"items": left2}, {"items": right2}]]})

    # ------------------------------------------------------------------ đầu trang Đảng
    @staticmethod
    def party_header(ctx: _Ctx, comp):
        """HD05 mục 1–5 và Phụ lục 1: ô 2 (cơ quan, dấu *), ô 3 (số, ký hiệu), ô 5b (trích yếu công văn),
        ô 10/11b (khẩn, dự thảo) bên trái; ô 1 (tiêu đề + đường kẻ), ô 4 (địa danh, ngày) bên phải."""
        f, W = ctx.f, ctx.W
        title = "ĐẢNG CỘNG SẢN VIỆT NAM"
        tsz = ctx.size("tieu_de")
        date = _fmt_date(_value(f, "ngay"), _value(f, "dia_danh"))
        tw = text_width_pt(title, tsz, True)
        dw = text_width_pt(date, ctx.size("dia_danh_ngay"), False, True)
        rw = min(max(tw, dw) + 16, W * 0.55)
        lw = W - rw
        roles = schema.party_format()["roles"]
        left1, right1, left2, right2 = [], [], [], []
        for line in [x for x in _value(f, "co_quan_chu_quan").split("\n") if x.strip()]:
            left1.append(P(line, ctx.size("cap_tren"), caps=True, align="center", role="dang_co_quan_cap_tren"))
        for line in [x for x in (_value(f, "co_quan_ban_hanh") or "TÊN CƠ QUAN BAN HÀNH").split("\n") if x.strip()]:
            left1.append(P(line, ctx.size("ban_hanh"), bold=True, caps=True, align="center",
                           role="dang_co_quan_ban_hanh"))
        left1.append(P("*", ctx.size("ban_hanh"), align="center", role="dang_dau_sao"))
        pad = max((rw - tw - 2) / 2, 0)
        right1.append(P(title, tsz, bold=roles["tieu_de"]["bold"], align="center", left=pad, right=pad,
                        role="dang_tieu_de", border={"bottom": {"w": 0.75, "len": round(tw + 2, 2)}}))
        left2.append(P(number_text(ctx.standard, ctx.type_id, f, ctx.t), ctx.size("so_ky_hieu"), align="center",
                       before=6, role="dang_so_ky_hieu"))
        if ctx.type_id == "CONG_VAN" and _value(f, "trich_yeu"):
            r = roles["trich_yeu_cong_van"]
            for line in _value(f, "trich_yeu").split("\n"):
                left2.append(P(line, ctx.size("trich_yeu_cong_van"), italic=r["italic"], bold=r["bold"],
                               align="center", role="dang_trich_yeu_cong_van"))
        if _value(f, "do_khan"):
            left2.append(P(_value(f, "do_khan"), ctx.size("dau_khan"), bold=True, caps=True, align="center", before=6,
                           role="dang_dau_khan"))
        if _value(f, "du_thao"):
            left2.append(P(_value(f, "du_thao"), ctx.size("du_thao"), italic=roles["du_thao"]["italic"],
                           align="center", before=6, role="dang_du_thao"))
        right2.append(P(date, ctx.size("dia_danh_ngay"), italic=True, align="center", before=6,
                        role="dang_dia_danh_thoi_gian"))
        ctx.items.append({"t": "table", "role": "header", "cols": [round(lw, 2), round(rw, 2)],
                          "rows": [[{"items": left1}, {"items": right1}], [{"items": left2}, {"items": right2}]]})
        pv = _value(f, "pham_vi")
        if pv and not re.search(r"không phổ biến trên phương tiện thông tin đại chúng", pv, re.I):
            # ô 11a: góc phải trang đầu, cách mép trên 10 mm
            ctx.first_header.append(P(pv, ctx.size("pham_vi"), bold=True, caps=True, align="right",
                                      role="dang_pham_vi_luu_hanh"))

    # ------------------------------------------------------------------ tên loại, trích yếu
    @staticmethod
    def ten_loai(ctx: _Ctx, comp):
        text = comp.get("text") or ctx.info.get("ten_loai") or ""
        role = "the_loai" if ctx.party else "ten_loai"
        ctx.items.append(P(text, ctx.size(role), bold=True, caps=True, align="center", before=18, role=role,
                           keep_next=True))

    @staticmethod
    def trich_yeu(ctx: _Ctx, comp):
        ty = _value(ctx.f, comp["field"])
        role = "trich_yeu"
        lines = ty.split("\n") if ty else ["…"]
        for line in lines:
            ctx.items.append(P(line, ctx.size(role), bold=True, align="center", role=role, keep_next=True))

    @staticmethod
    def line_trich_yeu(ctx: _Ctx, comp):
        if comp.get("of") == "ten_loai":
            text, size = ctx.info.get("ten_loai") or "", ctx.size("ten_loai")
            text = next((it for it in reversed(ctx.items) if it.get("role") == "ten_loai"), None)
            text = runs_text(text["runs"]) if text else ""
        else:
            text = _value(ctx.f, "trich_yeu") or "…"
            size = ctx.size("trich_yeu")
        longest, _ = wrap_width_pt(text, size, True, False, ctx.W)
        p = rule_para(max(longest * ctx.s["ratio_trich_yeu"], 30), ctx.W, role="line_trich_yeu")
        p["sp"]["after"] = 6
        ctx.items.append(p)

    @staticmethod
    def party_summary_rule(ctx: _Ctx, comp):
        # HD05 mục 5.2.1: dưới trích yếu có 05 dấu gạch nối (-) ngăn cách với nội dung
        if _value(ctx.f, "trich_yeu"):
            ctx.items.append(P("-----", ctx.size("trich_yeu"), align="center", role="dang_gach_trich_yeu"))

    # ------------------------------------------------------------------ các khối nội dung đầu
    @staticmethod
    def tham_quyen(ctx: _Ctx, comp):
        v = _value(ctx.f, comp["field"]) or "THẨM QUYỀN BAN HÀNH"
        for i, line in enumerate(v.split("\n")):
            ctx.items.append(P(line, ctx.size("body"), bold=True, caps=True, align="center",
                               before=12 if i == 0 else 0, after=6, line=SINGLE, role="tham_quyen"))

    @staticmethod
    def can_cu(ctx: _Ctx, comp):
        lines = clean_list(ctx.f.get(comp["field"]))
        if ctx.party:
            lines = [re.sub(r"^[-–]\s*", "", x) for x in lines]
        de_nghi = _value(ctx.f, comp["then_field"]) if comp.get("then_field") else ""
        out = []
        for x in lines:
            if not re.match(r"^(Căn cứ|Theo|Xét|Thực hiện)\b", x, re.I):
                x = "Căn cứ " + x
            out.append(x)
        if de_nghi:
            out.append(de_nghi if re.match(r"^(Theo|Xét)\b", de_nghi, re.I) else "Theo đề nghị của " + de_nghi)
        changed = False
        for i, x in enumerate(out):
            fixed = _punct(x, "." if i == len(out) - 1 else ";")
            changed |= fixed != x
            if ctx.party:
                fixed = "- " + fixed
            ctx.items.append(ctx.body_para([{"t": fixed}], italic=not ctx.party, role="can_cu", endable=False))
        if changed:
            ctx.notices.append("Đã chuẩn hoá dấu câu cuối các dòng căn cứ (“;” và dòng cuối “.”) theo PL I Mục II.6.a.")

    @staticmethod
    def chuyen_tiep(ctx: _Ctx, comp):
        ctx.items.append(P(comp["text"], ctx.size("body"), bold=True, align="center", before=12, after=6,
                           line=ctx.s["line"], role="chuyen_tiep", keep_next=True))

    @staticmethod
    def kinh_gui(ctx: _Ctx, comp):
        items = clean_list(ctx.f.get(comp["field"]))
        if not items:
            return
        size = ctx.size("kinh_gui")
        label = "Kính gửi:"
        if ctx.party:
            # HD05 mục 9.2.3–9.2.5: công văn “Kính gửi” chính giữa trang đầu; tờ trình “Kính trình” dưới trích yếu;
            # sau mỗi nơi nhận có dấu chấm phẩy
            label = "Kính trình:" if ctx.type_id == "TO_TRINH" else "Kính gửi:"
            lab_w = text_width_pt(label + " ", size, False, True)
            widest = max(text_width_pt(_punct(x, ";"), size) for x in items)
            start = max((ctx.W - lab_w - widest) / 2, 0)
            for i, x in enumerate(items):
                runs = ([{"t": label, "i": True}, {"t": " "}] if i == 0 else []) + [{"t": _punct(x, ";")}]
                ctx.items.append(P(runs, size, align="left", left=start + lab_w, first=-lab_w if i == 0 else 0,
                                   before=12 if i == 0 else 0, after=6 if i == len(items) - 1 else 0,
                                   line=ctx.s["line"], role="dang_kinh_gui"))
            return
        left = 2268 / 20
        lab = [{"t": label}]
        colon = text_width_pt("Kính gửi", size)
        if len(items) == 1:
            full = text_width_pt("Kính gửi: ", size)
            ctx.items.append(P(lab + [{"t": " " + _punct(items[0], ".")}], size, align="left", left=left + full,
                               first=-full, before=12, after=6, line=ctx.s["line"], role="kinh_gui"))
            return
        ctx.items.append(P(lab, size, align="left", left=left, before=12, line=ctx.s["line"], role="kinh_gui"))
        for i, x in enumerate(items):
            end = "." if i == len(items) - 1 else ";"
            dash = text_width_pt("- ", size)
            ctx.items.append(P("- " + _punct(x, end), size, align="left", left=left + colon + dash, first=-dash,
                               after=6 if i == len(items) - 1 else 0, line=ctx.s["line"], role="kinh_gui_item"))

    @staticmethod
    def cong_dien_gui(ctx: _Ctx, comp):
        who = _value(ctx.f, comp["field"]) or "…"
        size = ctx.size("body")
        ctx.items.append(P(f"{who} điện:", size, align="center", before=12, line=ctx.s["line"], role="cong_dien_gui"))
        items = clean_list(ctx.f.get(comp["list_field"])) or ["…"]
        left = 2532 / 20
        dash = text_width_pt("- ", size)
        for i, x in enumerate(items):
            ctx.items.append(P("- " + _punct(x, "." if i == len(items) - 1 else ";"), size, align="left",
                               left=left + dash, first=-dash, line=ctx.s["line"], role="cong_dien_nhan"))

    @staticmethod
    def dieu_co_dinh(ctx: _Ctx, comp):
        text = _fill(comp["template"], ctx.f)
        text = re.sub(r"\s+\.$", ".", text)
        ctx.items.append(ctx.body_para([{"t": f"Điều {comp['number']}.", "b": True}, {"t": " " + text}], role="dieu"))

    @staticmethod
    def text_line(ctx: _Ctx, comp):
        text = _fill(comp["template"], ctx.f)
        lines = text.split("\n")
        center = comp.get("align") == "center"
        for i, line in enumerate(lines):
            ctx.items.append(ctx.body_para([{"t": line}], align="center" if center else "justify",
                                           first=0 if center or comp.get("indent") is False else None,
                                           role="text_line", endable=comp.get("end_mark", True)))

    # ------------------------------------------------------------------ thân văn bản
    @staticmethod
    def body(ctx: _Ctx, comp):
        blocks = _clean_blocks(ctx.f.get(comp["field"]))
        allowed = comp.get("allowed_blocks") or list(BLOCK_TYPES)
        labels = number_blocks(blocks, comp.get("start_dieu", 1))
        ctx.block_labels[comp["field"]] = labels
        endable = comp.get("end_mark", True)
        added = 0
        for b, label in zip(blocks, labels):
            t = b["type"] if b["type"] in allowed else "p"
            runs = parse_rich(b["html"])
            lines = [strip_runs(x) for x in split_lines(runs)]
            if not any(lines):
                continue
            align = b["align"] if b["align"] in ("left", "center", "right", "justify") else None
            if t in ("phan", "chuong", "muc"):
                lrole, trole = ("phan_label", "phan_title") if t != "muc" else ("muc_label", "muc_title")
                if t == "chuong" and not ctx.party:
                    lrole, trole = "chuong_label", "chuong_title"
                ctx.items.append(P(label, ctx.size(lrole if ctx.party else "body"), bold=True, align="center",
                                   before=12, line=ctx.s["line"], role=lrole, keep_next=True))
                for ln in lines:
                    if ln:
                        ctx.items.append(P(ln, ctx.size(trole if ctx.party else "body"), bold=True, caps=True,
                                           align="center", line=ctx.s["line"], role=trole, keep_next=True))
                added += 1
                continue
            first_runs = lines[0] if lines else []
            rest = lines[1:]
            if t == "dieu":
                role = "dieu"
                head = [{"t": label, "b": True}]
                body_runs = [dict(r, b=True) if (b["tieu_de"] or ctx.party) else r for r in first_runs]
                p = ctx.body_para(head + ([{"t": " "}] + body_runs if body_runs else []), align=align or "justify",
                                  role=role, endable=endable)
                if ctx.party:
                    for r in p["runs"]:
                        r["size"] = ctx.size("dieu")
                ctx.items.append(p)
            elif t in ("khoan", "diem", "la_ma", "bullet"):
                prefix = {"t": label + " "}
                if t == "la_ma":
                    first_runs = [dict(r, b=True, t=r["t"].upper()) for r in first_runs]
                    prefix["b"] = True
                if t == "khoan" and b["tieu_de"]:
                    first_runs = [dict(r, b=True) for r in first_runs]
                    prefix["b"] = True
                ctx.items.append(ctx.body_para([prefix] + first_runs, align=align or "justify", role=t,
                                               endable=endable))
            else:
                ctx.items.append(ctx.body_para(first_runs, align=align or "justify",
                                               first=0 if align in ("center", "right") else None, role="body",
                                               endable=endable))
            for ln in rest:
                if ln:
                    ctx.items.append(ctx.body_para(ln, align=align or "justify",
                                                   first=0 if align in ("center", "right") else None, role="body",
                                                   endable=endable))
            added += 1
        if not added and not comp.get("optional"):
            ctx.items.append(ctx.body_para([{"t": "…"}], role="body", endable=False))

    # ------------------------------------------------------------------ nơi nhận, chữ ký
    @staticmethod
    def _noi_nhan(ctx: _Ctx, before=12.0):
        items = clean_list(ctx.f.get("noi_nhan"))
        defaults = ctx.t.get("noi_nhan_default") or (ctx.t.get("noi_nhan_default_types") or {}).get(ctx.type_id)
        if not items and defaults:
            items = [_fill(x, ctx.f) for x in defaults]
        luu = _value(ctx.f, "luu")
        out = []
        if ctx.party:
            r = schema.party_format()["roles"]
            out.append(P("Nơi nhận:", ctx.size("noi_nhan_label"), underline=r["noi_nhan_label"]["underline"],
                         before=before, role="noi_nhan_label"))
            sz = ctx.size("noi_nhan_item")
            for x in items:
                if re.match(r"^Lưu\b", x, re.I):
                    continue
                out.append(P("- " + _punct(x, ";"), sz, role="noi_nhan_item"))
            luu = re.sub(r"^Lưu\s*:?\s*", "", luu, flags=re.I)
            out.append(P("- Lưu " + _punct(luu or "Văn phòng", "."), sz, role="noi_nhan_luu"))
            return out
        out.append(P("Nơi nhận:", 12, bold=True, italic=True, before=before, role="noi_nhan_label"))
        for x in items:
            if re.match(r"^Lưu\s*:", x, re.I):
                continue
            out.append(P("- " + _punct(x, ";"), 11, role="noi_nhan_item"))
        luu = re.sub(r"^(Lưu\s*:\s*)?(VT\s*,?\s*)?", "", luu, flags=re.I).strip()
        out.append(P("- Lưu: VT" + (", " + _punct(luu, ".") if luu else "."), 11, role="noi_nhan_luu"))
        return out

    @staticmethod
    def _signer(ctx: _Ctx, before=12.0):
        f = ctx.f
        out = []
        qh = _value(f, "quyen_han")
        cua = _value(f, "quyen_han_cua")
        cv = _value(f, "chuc_vu") or "CHỨC VỤ NGƯỜI KÝ"
        if ctx.party:
            # HD05 mục 7: T/M, K/T, T/L + tên tập thể/cấp trưởng; Q. + chức vụ; dòng “kiêm” giữ chữ thường
            cv_raw = _value(f, "chuc_vu")
            first = True
            if qh in ("T/M", "K/T", "T/L"):
                out.append(P(f"{qh} {cua or '…'}", ctx.size("quyen_han_ky"), bold=True, caps=True, align="center",
                             before=before, role="dang_quyen_han_ky"))
                first = False
            elif qh == "Q.":
                out.append(P(f"Q. {cv_raw or '…'}", ctx.size("quyen_han_ky"), bold=True, caps=True, align="center",
                             before=before, role="dang_quyen_han_ky"))
                cv_raw, first = "", False
            elif qh:  # giá trị tự do của bản nháp cũ (VD “T/M BAN THƯỜNG VỤ”)
                out.append(P(qh, ctx.size("quyen_han_ky"), bold=True, caps=True, align="center", before=before,
                             role="dang_quyen_han_ky"))
                first = False
            for line in [x for x in cv_raw.split("\n") if x.strip()]:
                low = line.strip().lower() == "kiêm"
                out.append(P(line.strip().lower() if low else line, ctx.size("chuc_vu_ky"), caps=not low,
                             align="center", before=before if first else 0, role="dang_chuc_vu_ky"))
                first = False
        else:
            first = []
            if qh == "Q.":
                first = [f"Q. {cv}"]
            elif qh in ("TM.", "KT.", "TL.", "TUQ."):
                first = [f"{qh} {cua or '…'}", cv]
            else:
                first = [cv]
            for i, line in enumerate(first):
                for j, sub in enumerate(line.split("\n")):
                    out.append(P(sub, ctx.size("quyen_han_ky" if i == 0 else "chuc_vu_ky"), bold=True, caps=True,
                                 align="center", before=before if (i == 0 and j == 0) else 0,
                                 role="quyen_han_ky" if i == 0 else "chuc_vu_ky"))
        for _ in range(ctx.s["sign_blank_lines"]):
            out.append(P("", ctx.size("ho_ten_ky"), role="khoang_ky"))
        out.append(P(_value(f, "ho_ten"), ctx.size("ho_ten_ky"), bold=True, align="center",
                     role="dang_ho_ten_ky" if ctx.party else "ho_ten_ky"))
        return out

    @staticmethod
    def _footer_cols(ctx: _Ctx, left_items):
        """Độ rộng cột theo file mẫu; nới cột Nơi nhận (tối đa 45%) nếu dòng nơi nhận bị ngắt."""
        cols = _cols(ctx.t["geometry"]["footer_cols_pt"], ctx.W)
        need = max((text_width_pt(runs_text(p["runs"]), p["size"], any(r.get("b") for r in p["runs"]),
                                  any(r.get("i") for r in p["runs"])) for p in left_items if p["runs"]), default=0) + 4
        if cols[0] < need:
            left = min(need, ctx.W * 0.45)
            cols = [left, ctx.W - left]
        return [round(c, 2) for c in cols]

    @staticmethod
    def sign_footer(ctx: _Ctx, comp):
        left = _Builders._noi_nhan(ctx)
        ctx.items.append({"t": "table", "role": "sign", "cols": _Builders._footer_cols(ctx, left),
                          "rows": [[{"items": left}, {"items": _Builders._signer(ctx)}]]})

    @staticmethod
    def party_bien_ban_sign(ctx: _Ctx, comp):
        """HD05 mục 7.1.4.e, 7.2.4: chủ trì hội nghị bên phải, người ghi biên bản bên trái."""
        f = ctx.f
        sz = ctx.size("chuc_vu_ky")
        blank = lambda: [P("", sz, role="khoang_ky") for _ in range(ctx.s["sign_blank_lines"])]  # noqa: E731
        left = [P("NGƯỜI GHI BIÊN BẢN", sz, caps=True, align="center", before=12, role="dang_chuc_vu_ky")] + blank() + [
            P(_value(f, "ho_ten_nguoi_ghi"), ctx.size("ho_ten_ky"), bold=True, align="center", role="dang_ho_ten_ky")]
        right = [P("CHỦ TRÌ HỘI NGHỊ", sz, caps=True, align="center", before=12, role="dang_chuc_vu_ky")] + blank() + [
            P(_value(f, "ho_ten_chu_tri"), ctx.size("ho_ten_ky"), bold=True, align="center", role="dang_ho_ten_ky")]
        ctx.items.append({"t": "table", "role": "sign", "cols": [round(ctx.W / 2, 2), round(ctx.W / 2, 2)],
                          "rows": [[{"items": left}, {"items": right}]]})
        for p_ in _Builders._noi_nhan(ctx, before=12):
            ctx.items.append(p_)

    @staticmethod
    def party_extra(ctx: _Ctx, comp):
        """HD05 Phần II mục II.4.1 và II.6: chỉ dẫn “Không phổ biến …” ở trang cuối, chính giữa;
        thông tin liên hệ ở trang cuối dưới đường kẻ nét liền hết chiều ngang."""
        pv = _value(ctx.f, "pham_vi")
        if pv and re.search(r"không phổ biến trên phương tiện thông tin đại chúng", pv, re.I):
            ctx.items.append(P(pv, ctx.size("pham_vi"), bold=True, caps=True, align="center", before=24,
                               role="dang_pham_vi_luu_hanh"))
        v = _value(ctx.f, "lien_he")
        if v:
            for i, line in enumerate(v.split("\n")):
                p_ = P(line, ctx.size("lien_he"), align="left", before=24 if i == 0 else 0, role="dang_thong_tin_lien_he")
                if i == 0:
                    p_["border"] = {"top": {"w": 0.75, "len": round(ctx.W, 2)}}
                ctx.items.append(p_)

    @staticmethod
    def party_sign_footer(ctx: _Ctx, comp):
        cols = [ctx.W * 0.5, ctx.W * 0.5]
        ctx.items.append({"t": "table", "role": "sign", "cols": [round(c, 2) for c in cols],
                          "rows": [[{"items": _Builders._noi_nhan(ctx)}, {"items": _Builders._signer(ctx)}]]})

    @staticmethod
    def bien_ban_sign(ctx: _Ctx, comp):
        f = ctx.f
        cols = _cols(ctx.t["geometry"]["footer_cols_pt"], ctx.W)
        sz = ctx.size("body")
        blank = [P("", sz, role="khoang_ky") for _ in range(ctx.s["sign_blank_lines"])]
        left = [P("THƯ KÝ", sz, bold=True, align="center", before=12, role="thu_ky_label")] + blank + [
            P(_value(f, "ho_ten_thu_ky"), sz, bold=True, align="center", role="ho_ten_thu_ky")]
        right = [P("CHỦ TỌA", sz, bold=True, align="center", before=12, role="chu_toa_label")]
        cq = _value(f, "chuc_vu_chinh_quyen")
        if cq:
            right.append(P(cq, sz, bold=True, caps=True, align="center", role="chuc_vu_chinh_quyen"))
        right += [P("", sz, role="khoang_ky") for _ in range(ctx.s["sign_blank_lines"])]
        right.append(P(_value(f, "ho_ten_chu_toa"), sz, bold=True, align="center", role="ho_ten_chu_toa"))
        ctx.items.append({"t": "table", "role": "bien_ban_sign", "cols": [round(c, 2) for c in cols],
                          "rows": [[{"items": left}, {"items": right}]]})
        for p in _Builders._noi_nhan(ctx, before=12):
            ctx.items.append(p)

    @staticmethod
    def nghi_phep_sign(ctx: _Ctx, comp):
        left = _Builders._noi_nhan(ctx)
        cols = _Builders._footer_cols(ctx, left)
        rows = [[{"items": left}, {"items": _Builders._signer(ctx)}]]
        show = ctx.f.get("hien_xac_nhan")
        if show is None or show is True or str(show).lower() in ("true", "1", "on"):
            sz = ctx.size("body")
            zone = [P("Xác nhận của cơ quan (tổ chức) hoặc chính quyền địa phương nơi nghỉ phép (nếu cần)", sz,
                      italic=True, align="center", before=12, role="xac_nhan")]
            zone += [P("", sz, role="khoang_ky") for _ in range(ctx.s["sign_blank_lines"])]
            rows.append([{"items": zone}, {"items": [P("", sz, role="empty")]}])
        ctx.items.append({"t": "table", "role": "nghi_phep_sign", "cols": cols, "rows": rows})

    @staticmethod
    def lien_he(ctx: _Ctx, comp):
        v = _value(ctx.f, comp["field"])
        if not v:
            return
        sz = 11
        lines = v.split("\n")
        for i, line in enumerate(lines):
            p = P(line, sz, align="left", role="lien_he")
            if i == 0:
                p["border"] = {"top": {"w": 0.75, "len": round(ctx.W, 2)}}
            ctx.first_footer.append(p)
