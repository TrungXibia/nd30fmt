"""Markdown -> bản thảo cho tab Soạn thảo (schema NĐ30 / văn bản Đảng).

Thông tin thể thức (số, ký hiệu, địa danh, ngày, tên loại, trích yếu, nơi nhận) nhận diện bằng
md_to_docx_nd30.auto_extract_fields; phần thân chia thành khối Điều/khoản/điểm/gạch đầu dòng theo cùng
quy tắc với chức năng Nhập Word. Người dùng kiểm tra lại trong form trước khi xuất Word.
"""
from __future__ import annotations

import html
import re
import unicodedata

from ..composer import schema
from ..composer.importer import classify_rule
from . import md_to_docx_nd30 as mdx


MAX_BLOCKS = 600   # trình soạn thảo trên trình duyệt chậm khi quá nhiều khối


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").upper().replace("Đ", "D"))
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _inline_html(text: str) -> str:
    """**đậm**, *nghiêng* trong Markdown -> HTML của trình soạn khối."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", out)
    out = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    return out


def _plain(text: str) -> str:
    return re.sub(r"[*_`]+", "", text).strip()


_DATE = re.compile(r"ngày\s+(\d{1,2})\s+th[aá]ng\s+(\d{1,2})\s+n[aă]m\s+(\d{4})", re.I)   # chịu được lỗi OCR mất dấu


def _header_table(text: str) -> dict:
    """Bảng đầu trang (2 cột) trong Markdown: ô trái = cơ quan, số, V/v; ô phải = quốc hiệu/tiêu đề, ngày."""
    rows = []
    for line in text.split("\n")[:20]:
        s = line.strip()
        if s.startswith("|"):
            if not re.fullmatch(r"\|?[\s:\-|]+\|?", s):
                rows.append([c.strip() for c in s.strip("|").split("|")])
        elif rows:
            break
    if not rows or not re.search(r"CỘNG\s+H[OÒ][AÀ]|ĐẢNG CỘNG SẢN", " ".join(" ".join(r) for r in rows), re.I):
        return {}
    out: dict = {}
    names = []
    in_vv = False
    for r in rows:
        left = [_plain(x) for x in re.split(r"<br>", r[0]) if _plain(x)] if r else []
        right = [_plain(x) for x in re.split(r"<br>", r[-1]) if _plain(x)] if len(r) > 1 else []
        for x in left:
            if set(x) <= set("_-–*. "):
                continue
            sm = re.match(r"^Số\s*:?\s*(.+)$", x, re.I)
            if sm:
                out["so_ky_hieu"] = sm.group(1).strip().rstrip(".")
                in_vv = False
                continue
            vm = re.match(r"^V/v\s+(.+)$", x, re.I)
            if vm:
                out["trich_yeu_cv"] = vm.group(1).strip()
                in_vv = True
                continue
            if in_vv:
                out["trich_yeu_cv"] += " " + x
                continue
            if "so_ky_hieu" not in out:
                names.append(x)
        for x in right:
            dm = re.match(r"^([^,]{2,40}),\s*(ngày.+)$", x, re.I)
            if dm:
                out["dia_danh"], out["ngay_thang"] = dm.group(1).strip(), dm.group(2).strip()
    if names:
        out["co_quan_ban_hanh"] = names[-1]
        if len(names) > 1:
            out["co_quan_chu_quan"] = "\n".join(names[:-1])
    return out


_QH = re.compile(r"CỘNG\s+H[OÒ][AÀ]\s+XÃ\s+HỘI|CONG\s+HOA\s+XA\s+HOI", re.I)
_TN = re.compile(r"Độc\s+lập\s*[-–]\s*Tự\s+do", re.I)


def _upper_run(tokens: list[str], from_end: bool = False) -> list[str]:
    """Chuỗi từ VIẾT HOA liền nhau ở đầu (hoặc cuối) danh sách từ."""
    seq = list(reversed(tokens)) if from_end else tokens
    out = []
    for t in seq:
        w = t.strip(",;:.")
        if w and w.isupper() and any(c.isalpha() for c in w):
            out.append(t.strip(",;:"))
        else:
            break
    return list(reversed(out)) if from_end else out


def _plain_header(text: str) -> dict:
    """Văn bản không có bảng đầu trang (PDF quét qua OCR, văn bản dán): tách cơ quan, số/ký hiệu từ các dòng đầu.
    OCR thường gộp hai cột trên cùng một dòng, VD "BỘ TÀI CHÍNH CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM"."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()][:25]
    out: dict = {}
    orgs = []
    for ln in lines:
        p = _plain(ln)
        m = _QH.search(p) or _TN.search(p)
        if m:
            left = p[:m.start()].strip(" _-–")
            if left and left.isupper():
                orgs.append(left)
            if _TN.search(p):
                break
        elif p.isupper() and len(p) <= 80 and not re.match(r"^(SỐ|V/V)\b", p):
            orgs.append(p.strip(" _-–"))
        if re.match(r"^Số\b", p, re.I):
            break
    orgs = [o for o in orgs if o and not set(o) <= set("_-–*. ")]
    if orgs:
        out["co_quan_ban_hanh"] = orgs[-1]
        if len(orgs) >= 2:
            out["co_quan_chu_quan"] = orgs[-2]
    joined = "\n".join(_plain(x) for x in lines)
    m = re.search(r"Số\s*[:;.]?\s*(\S*?)\s*/\s*([0-9A-ZĐ][\wĐđ\-]*)", joined)
    if m:
        # số viết tay thường bị OCR đọc sai: chỉ lấy khi toàn chữ số, ký hiệu vẫn lấy
        out["so_ky_hieu"] = f"{m.group(1) if m.group(1).isdigit() else ''}/{m.group(2)}"
    d = re.search(r"(?<![\wĐđ])((?:[A-ZĐÀ-Ỹ][a-zà-ỹđ]*\s+){0,3}[A-ZĐÀ-Ỹ][a-zà-ỹđ]*),\s*(ngày\s+\d{1,2}\s+th[aá]ng\s+\d{1,2}\s+n[aă]m\s+\d{4})", joined)
    if d:
        out["dia_danh"], out["ngay_thang"] = d.group(1).strip(), d.group(2)
    return out


def _vv_lines(text: str) -> str:
    """Trích yếu công văn "V/v …" có thể xuống 2–3 dòng (bản quét)."""
    lines = [_plain(x) for x in text.split("\n")]
    for i, ln in enumerate(lines):
        m = re.match(r"^V/v\s+(.+)$", ln, re.I)
        if not m:
            continue
        parts = [m.group(1).strip()]
        for nxt in lines[i + 1:i + 4]:
            if (not nxt or len(nxt) > 60 or re.match(r"^(Kính|Số|\d+[.)]|[-–]|Căn cứ|Thực hiện)", nxt, re.I)
                    or nxt.isupper() or _DATE.search(nxt)):
                break
            parts.append(nxt)
        return " ".join(parts)
    return ""


def _plain_signer(text: str) -> dict:
    """Khối chữ ký khi không có bảng: "KT. BỘ TRƯỞNG / THỨ TRƯỞNG / Nguyễn Văn A" (có thể lẫn cột Nơi nhận)."""
    lines = [_plain(x) for x in text.split("\n") if x.strip()]
    start = next((i for i, x in enumerate(lines) if re.search(r"N[oơ]i\s+nh[aậ]n", x, re.I)), max(0, len(lines) - 20))
    tail = lines[start:start + 25]
    out: dict = {}
    for i, ln in enumerate(tail):
        toks = ln.split()
        k = next((j for j, t in enumerate(toks) if re.fullmatch(r"(KT|TM|TL|TUQ|Q)\.", t)), None)
        if k is None:
            continue
        cua = _upper_run(toks[k + 1:])
        if not cua:
            continue
        out["quyen_han"], out["quyen_han_cua"] = toks[k], " ".join(cua)
        rest = tail[i + 1:]
        for nxt in rest:
            if re.match(r"^[-–•]", nxt):          # dòng của cột Nơi nhận
                continue
            run = _upper_run(nxt.split(), from_end=True)
            if run and not (len(run) == 1 and len(run[0]) < 4):
                out["chuc_vu"] = " ".join(run)
                break
        for cand in reversed(rest):            # họ tên: dòng cuối có 2–5 từ viết hoa chữ đầu
            if re.match(r"^[-–•]", cand):
                continue
            tail_words = []
            for w in reversed(cand.split()):
                if w[:1].isupper() and len(w) > 1 and w[1:].islower():
                    tail_words.append(w)
                else:
                    break
            if 2 <= len(tail_words) <= 5:
                out["ho_ten"] = " ".join(reversed(tail_words))
            break
        break
    return out


def _plain_noi_nhan(text: str) -> tuple[list[str], str]:
    """Nơi nhận khi không có bảng ký (bản quét): các dòng "- …" sau "Nơi nhận:"; dòng "- Lưu: …" -> ô Lưu."""
    lines = [_plain(x) for x in text.split("\n")]
    i = next((k for k, x in enumerate(lines) if re.match(r"^N[oơ]i\s+nh[aậ]n\b", x, re.I)), None)
    if i is None:
        return [], ""
    items, luu = [], ""
    for x in lines[i + 1:i + 40]:
        if not x:
            continue
        m = re.match(r"^[-–•]\s*(.+)$", x)
        if not m:
            if items and len(x) < 40 and not x[:1].isupper():   # dòng nối của mục trước
                items[-1] += " " + x
                continue
            break
        item = m.group(1).strip()
        lm = re.match(r"^L[ưu]u\s*:?\s*(?:VT\s*,?\s*)?(.*)$", item, re.I)
        if lm:
            luu = lm.group(1).strip(" .")
            break
        items.append(item)
    return [x.rstrip(";.,` \\").strip() for x in items], luu


_NEW_BLOCK = re.compile(r"^(#{1,6}\s|\||[-–+•*]\s|\*\*|\(?\d{1,3}[.)]|[a-zđ]\)|[IVXLC]+\.\s|Điều\s+\d|Chương\s|Mục\s+\d|"
                        r"Phần\s|Kính\s+(gửi|trình)|Căn\s+cứ|Theo\s+đề\s+nghị|N[oơ]i\s+nh[aậ]n|QUYẾT)", re.I)


def _reflow(body: str) -> str:
    """Markdown: các dòng liền nhau là một đoạn (văn bản quét/OCR ngắt dòng theo bề ngang trang).
    Giữ dòng riêng khi là tiêu đề, bảng, gạch đầu dòng, đánh số, Điều/Chương/Mục, Kính gửi, Căn cứ…"""
    out: list[str] = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        if out and out[-1] and not _NEW_BLOCK.match(line) and not out[-1].startswith(("#", "|")):
            prev = out[-1]
            out[-1] = (prev[:-1] + line) if prev.endswith("-") and prev[-2:-1].isalpha() else prev + " " + line
        else:
            out.append(line)
    return "\n".join(out)


def _tables(text: str) -> list[list[list[str]]]:
    out, cur = [], []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("|"):
            if not re.fullmatch(r"\|?[\s:\-|]+\|?", st):
                cur.append([c.strip() for c in st.strip("|").split("|")])
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _cell_lines(cell: str) -> list[str]:
    return [_plain(x) for x in re.split(r"<br>", cell) if _plain(x) and not set(_plain(x)) <= set("_-–. ")]


def _sign_table(tables) -> dict:
    """Bảng cuối có “Nơi nhận”: ô trái = nơi nhận, ô phải = quyền hạn, chức vụ, họ tên."""
    out: dict = {}
    for t in tables:
        for row in t:
            if not row or not re.match(r"^\**\s*Nơi nhận", _plain(row[0]), re.I):
                continue
            items = [re.sub(r"^[-–+•]\s*", "", x) for x in _cell_lines(row[0])[1:]]
            luu = [x for x in items if re.match(r"^Lưu\b", x, re.I)]
            out["noi_nhan"] = [x.rstrip(";.,") for x in items if not re.match(r"^Lưu\b", x, re.I)]
            if luu:
                out["luu"] = re.sub(r"^Lưu\s*:?\s*(VT\s*,?\s*)?", "", luu[-1], flags=re.I).rstrip(" .")
            if len(row) > 1:
                lines = [x for x in _cell_lines(row[-1]) if not x.startswith("(")]
                if lines and lines[-1] != lines[-1].upper():
                    out["ho_ten"] = lines.pop()
                if lines:
                    m = re.match(r"^(TM\.|Q\.|KT\.|TL\.|TUQ\.|T/M|K/T|T/L)\s*(.*)$", lines[0])
                    if m:
                        out["quyen_han"] = m.group(1)
                        if m.group(1) == "Q.":
                            out["chuc_vu"] = m.group(2)
                        else:
                            out["quyen_han_cua"] = m.group(2)
                            out["chuc_vu"] = "\n".join(lines[1:])
                    else:
                        out["chuc_vu"] = "\n".join(lines)
            out["_table"] = id(t)
            return out
    return out


def markdown_to_draft(markdown: str, standard: str = "nd30") -> dict:
    if standard not in ("nd30", "hd05"):
        raise ValueError("Chuẩn không hợp lệ")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown or "")       # bỏ ảnh
    warnings: list[str] = []
    # Tệp gộp nhiều văn bản (VD công văn kèm danh mục, phụ lục, văn bản liên quan): chỉ lấy văn bản đầu tiên.
    # Ranh giới: trang chứa "./." + "Nơi nhận" đầu tiên (hết văn bản chính); nếu không thấy thì trước quốc hiệu thứ hai.
    cut = None
    end = re.search(r"\./\.", text)
    nn = re.search(r"N[oơ]i\s+nh[aậ]n", text[end.end():end.end() + 1500], re.I) if end else None
    if nn:
        nxt = text.find("--- Trang", end.end() + nn.end())
        cut = nxt if nxt > 0 else None
    if cut is None:
        heads = [m.start() for m in re.finditer(
            r"CỘNG\s+H[OÒ][AÀ]\s+X[AÃ]\s+H[OỘ]I\s+CH[UỦ]\s+NGH[IĨ]A|ĐẢNG\s+CỘNG\s+SẢN\s+VIỆT\s+NAM", text, re.I)]
        if len(heads) >= 2 and heads[1] - heads[0] > 300:
            c = text.rfind("--- Trang", 0, heads[1])
            cut = c if c > heads[0] else heads[1]
    if cut is not None and text[cut:].strip():
        pages = len(re.findall(r"(?m)^--- Trang \d+ ---", text[:cut]))
        total = len(re.findall(r"(?m)^--- Trang \d+ ---", text))
        warnings.append("Tài liệu gồm nhiều phần; chỉ đưa văn bản chính"
                        + (f" (trang 1–{pages}/{total})" if pages else "") + " vào trình soạn thảo.")
        text = text[:cut]

    # dấu trang và dòng chữ ký số do chuyển từ PDF sinh ra: không thuộc nội dung văn bản
    # dấu trang PDF (+ số trang in ở đầu trang): bỏ; nếu câu cuối trang trước chưa kết thúc thì nối sang trang sau
    text = re.sub(r"\n*^--- Trang \d+ ---[ \t]*\n+(?:[ \t]*\d{1,3}[ \t]*\n)?",
                  lambda m: "\n" if m.start() and not re.search(r"[.:;!?\"”)]\s*$", text[:m.start()]) else "\n\n",
                  text, flags=re.M)
    text = re.sub(r"(?m)^\s*(?:>\s*)?(?:\*\*)?(?:Chữ ký số:\s*)?(?:\*\*)?Ký bởi:.*Thời gian ký:.*$", "", text)
    text = re.sub(r"(?m)^\s*>\s*\[Chỉ chuyển .*$", "", text)
    meta_fm, text = mdx.split_frontmatter(text)
    if re.search(r"ĐẢNG\s+CỘNG\s+SẢN\s+VIỆT\s+NAM", text[:1500], re.I):
        standard = "hd05"
    auto = {}
    try:
        auto = mdx.auto_extract_fields(text)
    except Exception:  # noqa: BLE001
        auto = {}
    for k in ("so_ky_hieu", "loai_van_ban", "trich_yeu", "dia_danh", "ngay_thang", "noi_nhan"):
        if meta_fm.get(k) and not auto.get(k):
            auto[k] = str(meta_fm[k])
    header = _header_table(text) or _plain_header(text)
    for k, v in header.items():
        if k in ("so_ky_hieu", "trich_yeu_cv", "dia_danh", "ngay_thang") and v and not auto.get(k):
            auto[k] = v

    # loại văn bản
    cat = schema.catalog(standard)["types"]
    by_title = {_norm(t["ten_loai"]): t for t in cat if t.get("ten_loai") and t["template_status"] == "supported"}
    loai = _norm(auto.get("loai_van_ban", ""))
    info = by_title.get(loai)
    if loai == "QUYET DINH" and standard == "nd30":
        info = next(t for t in cat if t["id"] == "QUYET_DINH_TRUC_TIEP")
        if re.match(r"^(Ban hành|Phê duyệt)", auto.get("trich_yeu", ""), re.I):
            info = next(t for t in cat if t["id"] == "QUYET_DINH_GIAN_TIEP")
    if info is None:
        if re.search(r"^\s*(\*\*)?\s*V/v\b", text, re.I | re.M) or re.search(r"Kính\s+gửi", text[:1500], re.I):
            info = next(t for t in cat if t["id"] == "CONG_VAN")
        else:
            info = next(t for t in cat if t["id"] == "BAO_CAO")
            warnings.append("Chưa nhận diện được tên loại; đã chọn tạm Báo cáo – hãy chọn lại loại văn bản.")
    type_id = info["id"]
    fields: dict = {}

    # số, ký hiệu
    sk = auto.get("so_ky_hieu", "")
    m = re.match(r"(\d*)\s*/\s*([^\s]+)", sk)
    if standard == "nd30" and m:
        if m.group(1):
            fields["so"] = m.group(1)
        codes = m.group(2).split("-")
        if type_id == "CONG_VAN" and len(codes) >= 2:
            fields["ma_co_quan"], fields["ma_don_vi"] = codes[0], "-".join(codes[1:])
        elif len(codes) >= 2:
            fields["ma_co_quan"] = "-".join(codes[1:])
    pm = re.search(r"Số\s*(\d+)\s*-\s*[A-Za-zĐđ]+\s*/\s*([\wĐđ\-]+)", text[:800])
    if standard == "hd05" and pm:
        fields["so"], fields["ma_co_quan"] = pm.group(1), pm.group(2)
    if auto.get("dia_danh"):
        fields["dia_danh"] = _plain(auto["dia_danh"])
    dm = _DATE.search(auto.get("ngay_thang", ""))
    if dm:
        fields["ngay"] = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
    if auto.get("trich_yeu") and type_id != "CONG_VAN":
        fields["trich_yeu"] = _plain(auto["trich_yeu"])
    vv = _vv_lines(text)
    if vv:
        fields["trich_yeu"] = vv
    elif header.get("trich_yeu_cv") and type_id == "CONG_VAN":
        fields["trich_yeu"] = header["trich_yeu_cv"]
    for k in ("co_quan_chu_quan", "co_quan_ban_hanh"):
        if header.get(k):
            fields[k] = header[k]
    if auto.get("noi_nhan"):
        items = [_plain(x) for x in auto["noi_nhan"].split("\n") if x.strip()]
        luu = [x for x in items if re.match(r"^Lưu\b", x, re.I)]
        fields["noi_nhan"] = [x.rstrip(";.,") for x in items if not re.match(r"^Lưu\b", x, re.I)]
        if luu:
            fields["luu"] = re.sub(r"^Lưu\s*:?\s*(VT\s*,?\s*)?", "", luu[-1], flags=re.I).rstrip(" .")

    if not fields.get("noi_nhan"):
        nn_items, nn_luu = _plain_noi_nhan(text)
        if nn_items:
            fields["noi_nhan"] = nn_items
        if nn_luu and not fields.get("luu"):
            fields["luu"] = nn_luu

    # thân văn bản
    body_md = mdx.strip_trailing_noinhan(mdx.strip_leading_boilerplate(text, auto))
    nn_at = re.search(r"(?m)^[^\n|]*N[oơ]i\s+nh[aậ]n\s*:", body_md, re.I)   # bản quét: cắt khối nơi nhận/chữ ký
    if nn_at:
        body_md = body_md[:nn_at.start()]
    body_md = _reflow(body_md)
    template = schema.template_for(standard, type_id)
    body_comp = next((c for c in template["layout"] if c["kind"] == "body"), None)
    allowed = set(body_comp.get("allowed_blocks", [])) if body_comp else {"p"}
    field_ids = {f["id"] for f in template["fields"]}
    blocks, can_cu, kinh_gui = [], [], []
    in_kg = False
    tables = 0
    for raw in body_md.split("\n"):
        line = raw.strip()
        if not line or set(line) <= set("-_*=| :"):
            continue
        if line.startswith("|"):
            tables += 1
            continue
        plain = _plain(line)
        if re.fullmatch(r"(CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM|Độc lập - Tự do - Hạnh phúc|ĐẢNG CỘNG SẢN VIỆT NAM|\*)",
                        plain, re.I):
            continue
        if re.match(r"^(QUYẾT ĐỊNH|QUYẾT NGHỊ)\s*:$", plain, re.I):
            continue
        kg = re.match(r"^Kính\s+(?:gửi|trình)\s*:?\s*(.*)$", plain, re.I)
        if kg and not kinh_gui:
            blocks = []          # phần trước "Kính gửi" là đầu văn bản (bản quét: dòng chữ ký số, quốc hiệu…)
            if kg.group(1).strip():
                kinh_gui.append(kg.group(1).strip().rstrip(";."))
            in_kg = True
            continue
        if in_kg and re.match(r"^[-–+•]\s*\S", plain) and len(plain) < 200:
            kinh_gui.append(re.sub(r"^[-–+•]\s*", "", plain).rstrip(";."))
            continue
        in_kg = False
        if "can_cu" in field_ids and re.match(r"^[-–]?\s*Căn cứ\b", plain, re.I) and not blocks:
            can_cu.append(re.sub(r"^[-–]\s*", "", plain))
            continue
        if "de_nghi" in field_ids and re.match(r"^Theo đề nghị\b", plain, re.I) and not blocks:
            fields["de_nghi"] = re.sub(r"^Theo đề nghị của\s*", "", plain, flags=re.I).rstrip(" .;")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        content = heading.group(2).strip() if heading else re.sub(r"^[*+]\s+", "- ", line)
        hit = classify_rule(_plain(content))
        if hit:
            kind, skip, num = hit
            # bỏ tiền tố số (trình soạn thảo tự đánh số) – tính trên chuỗi đã bỏ dấu Markdown
            stripped = _plain(content)[skip:]
            kind = kind if kind in allowed else "p"
            html_text = _inline_html(stripped if kind != "p" else _plain(content))
            if kind in ("chuong", "muc", "phan"):
                blocks.append({"type": kind, "html": ""})
                continue
            blocks.append({"type": kind, "html": html_text})
        elif heading:
            kind = "la_ma" if "la_ma" in allowed and len(heading.group(1)) == 1 else "p"
            blocks.append({"type": kind, "html": _inline_html(content) if kind == "la_ma" else
                           f"<strong>{_inline_html(_plain(content))}</strong>"})
        else:
            if blocks and blocks[-1]["type"] in ("chuong", "muc", "phan") and not blocks[-1]["html"]:
                blocks[-1]["html"] = _inline_html(_plain(content))
                continue
            blocks.append({"type": "p", "html": _inline_html(content)})
    if len(blocks) > MAX_BLOCKS:
        warnings.append(f"Nội dung dài ({len(blocks)} đoạn); chỉ đưa {MAX_BLOCKS} đoạn đầu vào trình soạn thảo.")
        blocks = blocks[:MAX_BLOCKS]
    if blocks:
        blocks[-1]["html"] = re.sub(r"\.?/\.\s*$", ".", blocks[-1]["html"])
    if body_comp:
        fields[body_comp["field"]] = blocks or [{"type": "p", "html": ""}]
    if can_cu:
        fields["can_cu"] = can_cu
    if kinh_gui and "kinh_gui" in field_ids:
        fields["kinh_gui"] = kinh_gui
    all_tables = _tables(text)
    sign = _sign_table(all_tables) or _plain_signer(text)
    for k, v in sign.items():
        if not k.startswith("_") and v and (k not in fields or not fields[k]):
            fields[k] = v
    content_tables = [t for t in all_tables if id(t) != sign.get("_table") and not re.search(
        r"CỘNG\s+H[OÒ][AÀ]|ĐẢNG\s+CỘNG\s+SẢN", " ".join(" ".join(r) for r in t), re.I)]
    if content_tables:
        warnings.append(f"Có {len(content_tables)} bảng trong nội dung: bảng chưa đưa vào trình soạn thảo, "
                        "hãy nhập lại nếu cần.")
    if info["template_status"] == "supported" and not body_comp:
        warnings.append("Mẫu này không có khối nội dung tự do; nội dung Markdown chưa được đưa vào các dòng cố định.")
    return {"draft": {"standard": standard, "type_id": type_id, "fields": fields},
            "detected": {"standard": standard, "type_id": type_id, "label": info["label"]}, "warnings": warnings}
