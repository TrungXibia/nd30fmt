"""So sánh định dạng thực tế với quy chuẩn -> danh sách lỗi (violation)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import ExtractedDoc, ParaInfo
from .roles import RE, RoleDecision
from .spec import Spec

LABEL_ROLES = {"phan_chuong_label", "muc_label", "phu_luc_label"}
LABEL_KW = re.compile(r"^(PHẦN|CHƯƠNG|TIỂU\s+MỤC|MỤC|PHỤ\s+LỤC)\b")
SEV_LABEL ={"loi": "Lỗi (NĐ 30)", "loi_can_doi_chieu": "Lỗi (NĐ 30 – cần đối chiếu)", "canh_bao": "Cảnh báo (quy ước)"}
ALIGN_VI = {"center": "canh giữa", "justify": "canh đều hai lề", "left": "canh trái", "right": "canh phải"}


@dataclass
class Violation:
    scope: str            # page | paragraph
    target: str           # pid hoặc "section 1"
    role: str
    field: str            # font | color | size | bold | italic | caps | align | indent | spacing | line_spacing | margin | paper | page_number
    expected: str
    actual: str
    severity: str
    source: str
    fixable: bool = True
    excerpt: str = ""
    fixed: bool = False
    ignored: bool = False     # người dùng bấm "Bỏ qua" (phát hiện nhầm): không tính, không tự sửa
    key: str = ""             # khoá để bỏ qua: "mục tiêu|trường" (lề trang: theo từng cạnh)

    def __post_init__(self):
        if not self.key:
            self.key = f"{self.target}|{self.field}"

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        d.pop("source", None)       # căn cứ/nguồn quy chuẩn không đưa ra giao diện, báo cáo
        return d


def _fmt_range(r) -> str:
    if not r:
        return "-"
    return f"{r[0]:g}" if r[0] == r[1] else f"{r[0]:g}–{r[1]:g}"


def _excerpt(t: str, n: int = 70) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n] + "…"


# ---------------------------------------------------------------------------
def check_page(ex: ExtractedDoc, spec: Spec) -> list[Violation]:
    out = []
    pg = spec.page
    tol = pg["paper"].get("tolerance_mm", 1.5)
    msrc = pg["margins_mm"]["source"]
    for s in ex.sections:
        tgt = f"Section {s.idx + 1}"
        w, h = sorted([s.width_mm, s.height_mm])
        if abs(w - pg["paper"]["width_mm"]) > tol or abs(h - pg["paper"]["height_mm"]) > tol:
            out.append(Violation("page", tgt, "page", "paper", "A4 210 × 297 mm",
                                 f"{s.width_mm:.0f} × {s.height_mm:.0f} mm", "loi", pg["paper"]["source"]))
        if s.orientation == "landscape":
            allow = pg["orientation"].get("allow_landscape_for_tables") and s.has_tables
            if not allow:
                out.append(Violation("page", tgt, "page", "orientation", "khổ dọc (portrait)", "khổ ngang",
                                     "loi", pg["orientation"]["source"], fixable=False))
        mt = pg["margins_mm"].get("tolerance_mm", 0.3)
        vals = {"top": s.top_mm, "bottom": s.bottom_mm, "left": s.left_mm, "right": s.right_mm}
        vi ={"top": "trên", "bottom": "dưới", "left": "trái", "right": "phải"}
        for side, v in vals.items():
            lo, hi = pg["margins_mm"][side]["range"]
            if v < lo - mt or v > hi + mt:
                out.append(Violation("page", tgt, "page", "margin", f"lề {vi[side]} {_fmt_range([lo, hi])} mm",
                                     f"{v:.1f} mm", "loi", msrc, key=f"{tgt}|margin_{side}"))
    # số trang: kiểm tra section đầu (các section sau thường liên kết header)
    pn = pg.get("page_number", {})
    if pn.get("required") and ex.sections:
        s0 = ex.sections[0]
        if pn.get("any_section"):
            # luận văn: bìa/phần đầu có thể không đánh số -> lấy section đầu tiên có số trang để xét
            s0 = next((s for s in ex.sections if s.has_page_field_header or s.has_page_field_footer), s0)
        if not s0.has_page_field_header:
            where = " (đang đặt ở chân trang)" if s0.has_page_field_footer else ""
            out.append(Violation("page", "Section 1", "page", "page_number",
                                 "có số trang, canh giữa trong lề trên", "không có số trang ở lề trên" + where,
                                 "loi", pn["source"]))
        else:
            if s0.page_field_align and s0.page_field_align != "center":
                out.append(Violation("page", "Section 1", "page", "page_number", "số trang canh giữa",
                                     ALIGN_VI.get(s0.page_field_align, s0.page_field_align), "loi", pn["source"]))
            if s0.page_field_size and pn.get("size") and not (pn["size"][0] <= s0.page_field_size <= pn["size"][1]):
                out.append(Violation("page", "Section 1", "page", "page_number",
                                     f"cỡ chữ số trang {_fmt_range(pn['size'])}", f"{s0.page_field_size:g}",
                                     "loi", pn["source"]))
        if pn.get("hide_first_page") and not ex.sections[0].title_pg and not (
                pn.get("any_section") and not (ex.sections[0].has_page_field_header or ex.sections[0].has_page_field_footer)):
            out.append(Violation("page", "Section 1", "page", "page_number", "không hiển thị số trang thứ nhất",
                                 "trang đầu vẫn dùng header chung (chưa bật 'Different First Page')",
                                 "loi", pn["source"]))
    return out


# ---------------------------------------------------------------------------
def _dieu_prefix_len(text: str) -> int:
    m = RE["dieu"].match(text.strip())
    if not m:
        return 0
    return len(text) - len(text.lstrip()) + m.end()


def _prefix_bold_ok(p: ParaInfo, nchars: int) -> bool:
    seen = 0
    for r in p.runs:
        for ch in r.text:
            if seen >= nchars:
                return True
            if not ch.isspace() and not r.bold:
                return False
            seen += 1
    return True


def check_paragraph(p: ParaInfo, d: RoleDecision, spec: Spec) -> list[Violation]:
    if d is None or d.role in ("empty",) or not p.text.strip():
        return []
    rule = spec.roles.get(d.role) or spec.roles["other"]
    sev = rule.severity
    src = rule.source
    out = []
    ex = _excerpt(p.text)

    def add(field, expected, actual, severity=None, fixable=True, source=None):
        out.append(Violation("paragraph", p.pid, d.role, field, expected, actual, severity or sev,
                             source or src, fixable, ex))

    # 1. phông chữ + màu (áp dụng cho mọi đoạn)
    target_font = spec.font_name
    bad_fonts = [f for f in p.fonts() if (f or "").lower() != target_font.lower()]
    if bad_fonts:
        add("font", target_font, ", ".join(str(f) for f in bad_fonts), "loi", source=spec.page["font"]["source"])
    bad_colors = [c for c in p.colors() if c.lower() not in ("auto", "000000")]
    if bad_colors:
        add("color", "màu đen", ", ".join(bad_colors), "loi", source=spec.page["font"]["source"])

    if spec.body.get("normal_char_spacing"):
        odd = [r for r in p.runs if r.text.strip() and (abs(r.char_spacing) > 0.05 or abs(r.char_scale - 100) > 0.5)]
        if odd:
            r0 = odd[0]
            what = []
            if abs(r0.char_spacing) > 0.05:
                what.append(("giãn" if r0.char_spacing > 0 else "nén") + f" {abs(r0.char_spacing):g}pt")
            if abs(r0.char_scale - 100) > 0.5:
                what.append(f"độ rộng chữ {r0.char_scale:g}%")
            add("char_spacing", "mật độ chữ bình thường (không nén/kéo dãn)", ", ".join(what), "loi",
                source=spec.body["source"])

    low_conf = d.confidence < float(spec.fix.get("min_role_confidence", 0.5))
    if d.role == "other":
        return out

    # 2. cỡ chữ
    if rule.size:
        lo, hi = rule.size
        sizes = [s for s in p.sizes() if s is not None]
        bad = [s for s in sizes if s < lo - 0.01 or s > hi + 0.01]
        if bad:
            add("size", f"cỡ {_fmt_range(rule.size)}", ", ".join(f"{s:g}" for s in sizes), fixable=not low_conf)

    # 3. đậm / nghiêng
    body_like = rule.body_like
    if d.role == "dieu":
        n = _dieu_prefix_len(p.text)
        if n and not _prefix_bold_ok(p, n):
            add("bold", "cụm 'Điều …' in đậm", "không đậm", fixable=not low_conf)
    elif rule.bold in (True, False) and "bold" not in d.skip_fields:
        r = p.ratio("bold")
        if rule.bold is True and r < (0.8 if body_like else 0.95):
            add("bold", "in đậm", f"đậm {r:.0%} ký tự", fixable=not low_conf)
        if rule.bold is False and r > (0.8 if body_like else 0.5):
            add("bold", "không in đậm", f"đậm {r:.0%} ký tự", fixable=not low_conf)
    if rule.italic in (True, False) and "italic" not in d.skip_fields:
        r = p.ratio("italic")
        if d.role == "dang_kinh_gui" and rule.italic is True:
            # HD05: chỉ cụm từ “Kính gửi”/“Kính trình” in nghiêng; tên nơi nhận cùng dòng chữ đứng
            chars = [(rr, ch) for rr, ch in p._chars()]
            head = "".join(ch for _, ch in chars[:10]).lower()
            n = 8 if head.startswith("kínhgửi") else 10 if head.startswith("kínhtrình") else 0
            if n:
                r = sum(1 for rr, _ in chars[:n] if rr.italic) / n
        if rule.italic is True and r < (0.8 if body_like else 0.95):
            add("italic", "in nghiêng", f"nghiêng {r:.0%} ký tự", fixable=not low_conf)
        if rule.italic is False and r > (0.8 if body_like else 0.5):
            add("italic", "chữ đứng (không nghiêng)", f"nghiêng {r:.0%} ký tự", fixable=not low_conf)
    if rule.underline is True and "underline" not in d.skip_fields and p.ratio("underline") < 0.95:
        add("underline", "gạch chân", "chưa gạch chân đủ", fixable=not low_conf)

    # 4. in hoa
    if rule.caps in (True, False) and "caps" not in d.skip_fields:
        cr = p.caps_ratio()
        if rule.caps is True and cr < 0.95:
            add("caps", "CHỮ IN HOA", f"in hoa {cr:.0%} chữ cái",
                fixable=not low_conf and bool(spec.fix.get("caps_text", True)))
        if rule.caps is False and cr >= 0.98 and sum(1 for c in p.text if c.isalpha()) > 5:
            # Chỉ tự sửa được từ khóa nhãn (CHƯƠNG -> Chương, PHỤ LỤC -> Phụ lục...), không đổi tên riêng
            fixable_kw = d.role in LABEL_ROLES and bool(LABEL_KW.match(p.text.strip()))
            add("caps", "chữ in thường", "toàn bộ in hoa", fixable=fixable_kw and not low_conf)

    # 5. căn lề
    if rule.align != "any":
        # “góc trái/góc phải” là vị trí trên trang: trong bảng đầu trang/bảng chữ ký, cột đã bảo đảm vị trí,
        # chữ canh giữa trong cột vẫn đúng (cách trình bày của mẫu văn bản 2 cột)
        in_layout_cell = p.where == "table" and p.zone_hint in ("header_table", "signature_table") \
            and rule.align in ("left", "right") and p.align == "center"
        if p.align != rule.align and not in_layout_cell:
            add("align", ALIGN_VI.get(rule.align, rule.align), ALIGN_VI.get(p.align, p.align), fixable=not low_conf)

    # 6. thụt đầu dòng (chỉ đoạn nằm ngoài bảng)
    if rule.first_line_indent_cm and p.where == "body":
        lo, hi = rule.first_line_indent_cm
        tol = float(spec.body.get("first_line_indent_tolerance_cm", 0.05))
        fl = p.first_line_cm
        if not (lo - tol <= fl <= hi + tol):
            add("indent", f"lùi đầu dòng {lo:g} cm hoặc {hi:g} cm", f"{fl:.2f} cm", fixable=not low_conf,
                source=spec.body["source"] if body_like else src)

    # 6b. giãn dòng riêng của vai trò (vd tên chương, tên bảng/hình: 1,5 line)
    if rule.line_spacing and not body_like:
        lo, hi = rule.line_spacing
        if p.line_rule != "auto" or not (lo - 0.01 <= p.line_value <= hi + 0.01):
            desc = (f"{p.line_value:.2f} dòng" if p.line_rule == "auto" else
                    f"{'chính xác (Exactly)' if p.line_rule == 'exact' else 'tối thiểu (At least)'} {p.line_value:g}pt")
            add("line_spacing", f"giãn dòng {_fmt_range(rule.line_spacing)} lines", desc, fixable=not low_conf)

    # 7. khoảng cách đoạn + giãn dòng (đoạn nội dung ngoài bảng)
    if body_like and p.where == "body":
        b = spec.body
        gap = p.before_pt + p.after_pt
        if gap + 0.01 < b["paragraph_spacing_min_pt"]:
            add("spacing", f"khoảng cách đoạn ≥ {b['paragraph_spacing_min_pt']}pt",
                f"trước {p.before_pt:g}pt, sau {p.after_pt:g}pt", fixable=not low_conf or _all_body_like(d, spec),
                source=b["source"])
        ok, desc = _line_ok(p, b)
        if not ok:
            if b.get("line_spacing_mode") == "exact_pt":
                lo_pt, hi_pt = b["line_spacing_pt"]
                exp = f"giãn dòng chính xác (Exactly) {lo_pt:g}–{hi_pt:g}pt"
            else:
                exp = f"giãn dòng từ {b['line_spacing_min']:g} đến {b['line_spacing_max']:g} lines"
            # giãn dòng/khoảng cách đoạn giống nhau cho MỌI vai trò nội dung: nếu các vai trò có thể có
            # của đoạn đều là vai trò nội dung thì sửa được dù chưa chắc đoạn là vai trò nào
            add("line_spacing", exp, desc, fixable=not low_conf or _all_body_like(d, spec), source=b["source"])
    return out


def _all_body_like(d: RoleDecision, spec: Spec) -> bool:
    cands = [c for c in (d.candidates or [d.role])]
    return bool(cands) and all(spec.roles.get(c) is not None and spec.roles[c].body_like for c in cands)


def _line_ok(p: ParaInfo, b: dict) -> tuple[bool, str]:
    if b.get("line_spacing_mode") == "exact_pt":
        lo, hi = float(b["line_spacing_pt"][0]), float(b["line_spacing_pt"][1])
        tol = float(b.get("line_spacing_pt_tolerance", 0.5))
        v = p.line_value
        if p.line_rule == "exact":
            return (lo - tol <= v <= hi + tol), f"chính xác (Exactly) {v:g}pt"
        if p.line_rule == "atLeast":
            return False, f"tối thiểu (At least) {v:g}pt"
        return False, f"bội số (Multiple) {v:.2f} dòng" if v and abs(v - 1) > 0.01 else "đơn (Single)"
    lo, hi = float(b["line_spacing_min"]), float(b["line_spacing_max"])
    if p.line_rule == "auto":
        v = p.line_value
        return (lo - 0.01 <= v <= hi + 0.01), f"{v:.2f} lines"
    size = max([s for s in p.sizes() if s] or [14.0])
    single = size * 1.15            # chiều cao dòng đơn xấp xỉ của Times New Roman
    v = p.line_value
    if p.line_rule == "exact":
        return (single * lo - 1.2 <= v <= single * hi + 0.6), f"chính xác {v:g}pt (≈ {v / single:.2f} lines)"
    # atLeast
    return (v <= single * hi + 0.6), f"tối thiểu {v:g}pt (≈ {v / single:.2f} lines)"


def check_document(ex: ExtractedDoc, decisions: list[RoleDecision], spec: Spec) -> list[Violation]:
    out = check_page(ex, spec)
    for p, d in zip(ex.paragraphs, decisions):
        out.extend(check_paragraph(p, d, spec))
    out.extend(check_structure(ex, decisions, spec))
    return out


def check_structure(ex: ExtractedDoc, decisions: list[RoleDecision], spec: Spec) -> list[Violation]:
    """Kiểm tra cấu trúc (chỉ báo, không tự sửa): vị trí tên bảng/hình, số cấp và số tiểu mục trong
    nhóm, trang 1 bắt đầu từ MỞ ĐẦU. Chỉ chạy khi quy chuẩn có khai báo các mục tương ứng."""
    out: list[Violation] = []
    paras = ex.paragraphs
    roles = [d.role if d else "empty" for d in decisions]

    def add(i, field, expected, actual, source, sev="loi"):
        p = paras[i]
        out.append(Violation("paragraph", p.pid, roles[i], field, expected, actual, sev, source, False,
                             _excerpt(p.text)))

    cap = spec.raw.get("captions") or {}
    if cap.get("check_position"):
        def near(i, step):
            j = i + step
            while 0 <= j < len(paras) and roles[j] == "empty" and not paras[j].has_drawing:
                j += step
            return j if 0 <= j < len(paras) else None
        for i, r in enumerate(roles):
            if r.endswith("caption_table"):
                p = paras[i]
                nxt = near(i, 1)
                ok = p.next_is_table or (nxt is not None and paras[nxt].where == "table" and paras[nxt].row == 0
                                         and (paras[i].where == "body"))
                if not ok and p.where == "body":
                    add(i, "position", "tên bảng đặt phía trên bảng", "không có bảng ngay bên dưới", cap["source"])
            elif r.endswith("caption_figure"):
                prv = near(i, -1)
                if prv is None or not (paras[prv].has_drawing or paras[i].has_drawing):
                    add(i, "position", "tên hình đặt phía dưới hình", "không có hình ngay bên trên", cap["source"])

    hd = spec.raw.get("headings") or {}
    if hd:
        from .roles import dean_heading_level
        nums = []
        for i, r in enumerate(roles):
            if r.startswith("dean_muc_"):
                t = paras[i].text.strip()
                if paras[i].num_label and paras[i].num_label != "-":
                    t = f"{paras[i].num_label} {t}"
                lvl = dean_heading_level(t)
                if lvl is None:
                    continue
                num = t.split()[0].rstrip(".")
                nums.append((i, num, lvl))
                if lvl > int(hd.get("max_levels", 4)):
                    add(i, "numbering", f"tiểu mục tối đa {hd.get('max_levels', 4)} chữ số", f"{num} ({lvl} chữ số)",
                        hd["source"])
        need = int(hd.get("min_siblings", 0))
        if need > 1:
            groups: dict[str, list[int]] = {}
            for i, num, lvl in nums:
                groups.setdefault(num.rsplit(".", 1)[0], []).append(i)
            for parent, idxs in groups.items():
                if len(idxs) < need:
                    add(idxs[0], "numbering", f"mỗi nhóm tiểu mục có ít nhất {need} tiểu mục",
                        f"nhóm {parent}.x chỉ có {len(idxs)} tiểu mục", hd["source"], "canh_bao")

    pn = spec.page.get("page_number", {})
    if pn.get("start_at_mo_dau"):
        mo = next((i for i, r in enumerate(roles) if r.endswith("tieu_de_phan")
                   and paras[i].text.strip().upper().rstrip(":") in ("MỞ ĐẦU", "PHẦN MỞ ĐẦU", "LỜI MỞ ĐẦU")), None)
        if mo is not None:
            si = paras[mo].section_idx
            sec = ex.sections[si] if si < len(ex.sections) else None
            first_in_sec = all(paras[j].section_idx != si or not paras[j].text.strip() for j in range(mo))
            if sec is None or si == 0 or sec.pg_start != 1 or not first_in_sec:
                add(mo, "page_start", "trang 1 là trang đầu tiên của Phần mở đầu (ngắt Section trước MỞ ĐẦU, "
                    "đánh số bắt đầu từ 1)", "chưa tách section/đánh số lại từ MỞ ĐẦU", pn["source"])
    return out


def mark_ignored(violations: list[Violation], ignored) -> None:
    ig = set(ignored or ())
    for v in violations:
        v.ignored = v.key in ig


def summarize(violations: list[Violation]) -> dict:
    by_sev, by_field = {}, {}
    n_ig = sum(1 for v in violations if getattr(v, "ignored", False))
    violations = [v for v in violations if not getattr(v, "ignored", False)]
    for v in violations:
        by_sev[v.severity] = by_sev.get(v.severity, 0) + 1
        by_field[v.field] = by_field.get(v.field, 0) + 1
    return {"total": len(violations), "ignored": n_ig, "by_severity": by_sev, "by_field": by_field,
            "paragraphs_with_errors": len({v.target for v in violations if v.scope == "paragraph"})}


_ = re
