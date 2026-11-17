"""Xác định VAI TRÒ (thành phần thể thức) của từng đoạn.

Nguyên tắc:
  1. Code xử lý những gì chắc chắn: regex (Quốc hiệu, "Số:", "V/v", "Nơi nhận:", "Điều 1."...)
     và ngữ cảnh cấu trúc (bảng tiêu đề, bảng chữ ký, dòng ngay sau "Chương I"...).
  2. Những đoạn MƠ HỒ (vd "1. ..." là đề mục hay khoản nội dung? dòng in hoa là tên cơ quan
     chủ quản hay cơ quan ban hành?) được gán vai trò mặc định theo heuristic (độ tin cậy thấp hơn) để người dùng xem lại.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .core import alpha_caps
from .extract import ExtractedDoc, ParaInfo

DOC_TYPES = {
    "BÁO CÁO", "QUYẾT ĐỊNH", "TỜ TRÌNH", "KẾ HOẠCH", "THÔNG BÁO", "CHỈ THỊ", "QUY CHẾ", "QUY ĐỊNH",
    "HƯỚNG DẪN", "CHƯƠNG TRÌNH", "PHƯƠNG ÁN", "ĐỀ ÁN", "DỰ ÁN", "BIÊN BẢN", "HỢP ĐỒNG", "GIẤY MỜI",
    "GIẤY GIỚI THIỆU", "NGHỊ QUYẾT", "CÔNG ĐIỆN", "BẢN GHI NHỚ", "BẢN THỎA THUẬN", "BẢN THOẢ THUẬN",
    "GIẤY ỦY QUYỀN", "GIẤY UỶ QUYỀN", "GIẤY NGHỈ PHÉP", "PHIẾU GỬI", "PHIẾU CHUYỂN", "PHIẾU BÁO",
    "THƯ CÔNG", "CÔNG VĂN", "CHUYÊN ĐỀ", "ĐỀ CƯƠNG", "BÁO CÁO TÓM TẮT", "BÁO CÁO TỔNG HỢP",
    "BÁO CÁO CHUYÊN ĐỀ", "BÁO CÁO KẾT QUẢ", "BÁO CÁO TỔNG KẾT", "THUYẾT MINH", "DỰ THẢO",
}

RE = {
    "quoc_hieu": re.compile(r"^C[ỘO]NG\s+H[OÒ]À?\s*A?\s*X[ÃA]\s+H[ỘO]I\s+CH[ỦU]\s+NGH[ĨI]A\s+VI[ỆE]T\s+NAM$", re.I),
    "tieu_ngu": re.compile(r"^Độc\s+lập\s*[-–—]\s*Tự\s+do\s*[-–—]\s*Hạnh\s+phúc$", re.I),
    "so_ky_hieu": re.compile(r"^Số\s*[:：]", re.I),
    "trich_yeu_cong_van": re.compile(r"^V/v\b", re.I),
    "dia_danh_thoi_gian": re.compile(r"^[^\n]{2,60},\s*ngày\s+(\d{1,2}|[.…]{2,}|\s+)\s*tháng\s+.{0,8}\s*năm\s+(\d{4}|[.…]{2,})", re.I),
    "kinh_gui": re.compile(r"^Kính\s+gửi\s*[:：]?", re.I),
    "noi_nhan_label": re.compile(r"^Nơi\s+nhận\s*[:：]?\s*$", re.I),
    "noi_nhan_item": re.compile(r"^([-–+]\s*\S|Lưu\s*[:：])", re.I),
    "phan_chuong_label": re.compile(r"^(Phần|Chương)\s+([IVXLCDM]+|\d+|thứ\s+\S+)\s*\.?$", re.I),
    "phan_chuong_inline": re.compile(r"^(Phần|Chương)\s+([IVXLCDM]+|\d+)\s*[.:\-–]\s*\S", re.I),
    "muc_label": re.compile(r"^(Tiểu\s+mục|Mục)\s+(\d+|[IVXLC]+)\s*\.?$", re.I),
    "dieu": re.compile(r"^Điều\s+\d+[a-zđ]?\s*\.", re.I),
    "phu_luc_label": re.compile(r"^Phụ\s+lục(\s+[IVXLC\d]+[a-z]?)?\s*\.?$", re.I),
    # tên bảng/hình: sau số hiệu PHẢI có dấu (. : - – —) hoặc hết dòng; "Bảng 3.1 cho thấy..." là câu văn
    "caption_table": re.compile(r"^Bảng\s+\d+(?:\.\d+)*\s*(?:[.:\-–—](?!\d)|$)", re.I),
    "caption_figure": re.compile(r"^(Hình|Biểu\s+đồ|Sơ\s+đồ|Đồ\s+thị)\s+\d+(?:\.\d+)*\s*(?:[.:\-–—](?!\d)|$)", re.I),
    # ghi chú nguồn / đơn vị tính của bảng ("Đơn vị tính: triệu đồng", "ĐVT: tỷ đồng") – không phải đề mục
    "source_note": re.compile(r"^\(?\s*(?:(?:Nguồn|Ghi\s+chú|Đơn\s+vị\s+tính|ĐVT)\s*[:：]|Đơn\s+vị\s*[:：]\s*(?:triệu|tỷ|tỉ|nghìn|ngàn|đồng|%|người|tấn|USD|VNĐ|VND|kWh|MWh|GWh|MW|ha\b|km|m2|m³))", re.I),
    "can_cu": re.compile(r"^(Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị|Thực\s+hiện)\b", re.I),
    "dong_quyet_dinh": re.compile(r"^(QUYẾT\s+ĐỊNH|QUYẾT\s+NGHỊ|NGHỊ\s+QUYẾT)\s*[:：]\s*$"),
    "sig_prefix": re.compile(r"^(TM|KT|TL|TUQ|Q|T/M|K/T|T/L)\.?\s+\S", re.I),
    "roman": re.compile(r"^[IVXLC]+\s*[.)]\s+\S"),
    "num1": re.compile(r"^\d+\s*[.)]\s+(?!\d)\S"),
    "num2": re.compile(r"^\d+\.\d+(\.\d+)*\.?\s+\S"),
    "letter": re.compile(r"^[a-zđ]\s*[).]\s+\S"),
    "bullet": re.compile(r"^[-–+•*▪●○■□◦]\s*\S"),
    "separator": re.compile(r"^[\s_\-–—=.*~]+$"),
    "sig_note": re.compile(r"^\((đã\s+ký|ký|ký\s+tên|ký,\s*đóng\s+dấu|ký,\s*ghi\s+rõ).*\)$", re.I),
}


DOC_TYPES_DANG = DOC_TYPES | {"KẾT LUẬN", "THÔNG TRI"}

RE_DANG = {
    "tieu_de": re.compile(r"^ĐẢNG\s+CỘNG\s+S[ẢA]N\s+VI[ỆE]T\s+NAM$", re.I),
    # "Số 127-QĐ/TW", "Số 05-HD/VPTW" – không có dấu hai chấm như NĐ 30
    "so_ky_hieu": re.compile(r"^Số\s+\d+[a-zđ]?\s*-\s*\S+/", re.I),
    "kinh_gui": re.compile(r"^Kính\s+(gửi|trình)\s*[:：]?", re.I),
    # DANG_05 mục 6.2.3: mỗi căn cứ trước có dấu gạch ngang (-)
    "can_cu": re.compile(r"^([-–]\s*)?(Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị|Thực\s+hiện)\b", re.I),
    "dau_khan": re.compile(r"^(KHẨN|THƯỢNG\s+KHẨN|H[ỎO]A\s+TỐC)\s*!?\s*$", re.I),
    "pham_vi_luu_hanh": re.compile(
        r"^(LƯU\s+HÀNH\s+NỘI\s+BỘ|TÀI\s+LIỆU\s+HỘI\s+NGHỊ|PHỔ\s+BIẾN\s+HẠN\s+CHẾ)\s*$", re.I),
    "du_thao": re.compile(r"^Dự\s+thảo(\s+lần(\s+thứ)?\s+\d+)?\s*\.?\s*$", re.I),
    "thong_tin_lien_he": re.compile(r"(điện\s+thoại|email|fax|website)\s*[:：]", re.I),
}


@dataclass
class RoleDecision:
    pid: str
    role: str
    confidence: float
    method: str                      # regex | context | heuristic | skip
    candidates: list[str] = field(default_factory=list)
    default: str | None = None
    scores: dict = field(default_factory=dict)
    skip_fields: list[str] = field(default_factory=list)
    note: str = ""

    def to_json(self) -> dict:
        return {"pid": self.pid, "role": self.role, "confidence": round(self.confidence, 3),
                "method": self.method, "candidates": self.candidates, "default": self.default,
                "scores": {k: round(v, 3) for k, v in self.scores.items()}, "note": self.note,
                "skip_fields": self.skip_fields}

    @classmethod
    def from_json(cls, d: dict) -> "RoleDecision":
        return cls(pid=d["pid"], role=d["role"], confidence=float(d.get("confidence", 1.0)),
                   method=d.get("method", "regex"), candidates=list(d.get("candidates") or []),
                   default=d.get("default"), scores=dict(d.get("scores") or {}),
                   skip_fields=list(d.get("skip_fields") or []), note=d.get("note", ""))


def full_text(p: ParaInfo) -> str:
    t = p.text.strip()
    if p.num_label and p.num_label != "-":
        return f"{p.num_label} {t}".strip()
    if p.num_label == "-":
        return f"- {t}"
    return t


def _letters(s: str) -> int:
    return alpha_caps(s)[0]


def _is_caps(s: str) -> bool:
    n, up = alpha_caps(s)
    return n >= 3 and up / n >= 0.9


def _name_like(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 45 or re.search(r"[\d:;,.()/]", s):
        return False
    words = s.split()
    return 2 <= len(words) <= 6 and all(w[0].isupper() for w in words if w) and not _is_caps(s)


def _terminated(s: str) -> bool:
    return s.rstrip().endswith((".", ";", ":", ",", "?", "!", "…"))


# ---------------------------------------------------------------------------
def mark_zones(ex: ExtractedDoc) -> None:
    """Gắn nhãn vùng cho đoạn trong bảng: bảng tiêu đề / bảng chữ ký / bảng số liệu."""
    paras = ex.paragraphs
    # tổng tích luỹ số đoạn nội dung (ngoài bảng): tra O(1) thay vì đếm lại cho từng bảng (O(n²) với văn bản dài)
    prefix = [0]
    for p in paras:
        prefix.append(prefix[-1] + (1 if p.where == "body" and _letters(p.text) > 3 else 0))
    for t in ex.tables_meta:
        cell_paras = paras[t["first_para"]: t["last_para"] + 1]
        texts = [full_text(p) for p in cell_paras]
        # số đoạn nội dung (ngoài bảng) đứng trước bảng
        before_content = prefix[t["first_para"]]
        is_header = before_content <= 2 and t["ncols"] <= 3 and any(
            RE["quoc_hieu"].match(x) or RE["tieu_ngu"].match(x) or RE["so_ky_hieu"].match(x)
            or RE_DANG["tieu_de"].match(x) or RE_DANG["so_ky_hieu"].match(x)
            for x in texts)
        is_sig = (not is_header) and t["ncols"] <= 3 and any(
            RE["noi_nhan_label"].match(x) or RE["sig_prefix"].match(x)
            or re.match(r"^(NGƯỜI GHI BIÊN BẢN|CHỦ TRÌ HỘI NGHỊ|THƯ KÝ|CHỦ TỌA)\b", x) for x in texts)
        if not is_sig and not is_header and t["ncols"] <= 2 and t["nrows"] <= 3:
            # bảng chữ ký không có "Nơi nhận"/tiền tố: có dòng in hoa + dòng tên người
            has_caps = any(_is_caps(x) and len(x) < 60 for x in texts)
            has_name = any(_name_like(x) for x in texts)
            after = prefix[-1] - prefix[t["last_para"] + 1]
            is_sig = has_caps and has_name and after <= 3
        zone = "header_table" if is_header else ("signature_table" if is_sig else "data_table")
        for p in cell_paras:
            p.zone_hint = zone
        t["zone"] = zone


def position_text(p: ParaInfo) -> str:
    side = ""
    if p.col is not None and p.ncols and p.ncols >= 2:
        side = ", left column" if p.col == 0 else (", right column" if p.col == p.ncols - 1 else ", middle column")
    return {
        "header_table": "top header block (table)" + side,
        "signature_table": "signature block at the end (table)" + side,
        "data_table": "inside a data table",
    }.get(p.zone_hint, "document body")


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# VÙNG MỤC LỤC / DANH MỤC / TÀI LIỆU THAM KHẢO (dùng chung cho luồng NĐ30 và Đảng)
# ---------------------------------------------------------------------------
_TOC_HEAD_RE = re.compile(
    r"^(MỤC\s+LỤC|DANH\s+MỤC\s+(?!TÀI\s+LIỆU|CÔNG\s+TRÌNH)(CÁC\s+)?"
    r"(TỪ|CHỮ|KÝ\s+HIỆU|BẢNG|HÌNH|BIỂU|SƠ\s+ĐỒ|ĐỒ\s+THỊ|HỘP)\b.*)$")
_REF_HEAD_RE = re.compile(r"^(DANH\s+MỤC\s+)?TÀI\s+LIỆU\s+THAM\s+KHẢO$")
# dòng mục lục: kết thúc bằng [tab | dấu dẫn ... | khoảng trắng] + số trang (Ả Rập hoặc La Mã thường)
_TOC_LINE_RE = re.compile(r"((\t|\.{3,}|…+|\s)\s*(\d{1,4}|[ivxlc]{1,6})|(?<=[.)])\d{1,4})\s*$", re.I)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# tiêu đề nhóm trong danh mục tài liệu tham khảo: "A. Tài liệu tiếng Việt", "II. VĂN BẢN PHÁP LUẬT"...
_REF_GROUP_RE = re.compile(
    r"^(([A-ZĐ]|[IVX]+)\s*[.)]\s*)?(TÀI\s+LIỆU|TIẾNG|VĂN\s+BẢN|SÁCH|BÁO|TẠP\s+CHÍ|WEBSITE|TRANG\s+(WEB|THÔNG)|"
    r"LUẬN\s+(VĂN|ÁN)|ĐỀ\s+TÀI|CÔNG\s+TRÌNH|NGUỒN)\b")


_LABEL_ONLY_RE = re.compile(r"^(CHƯƠNG|PHẦN|PHỤ\s+LỤC|MỤC|TIỂU\s+MỤC)\s+([IVXLC]+|\d+)\s*[.:]?$", re.I)


def is_label_only(t: str) -> bool:
    """'CHƯƠNG 1', 'Phần II' đứng riêng: số ở cuối là số thứ tự, KHÔNG phải số trang mục lục."""
    return bool(_LABEL_ONLY_RE.match(unicodedata.normalize("NFC", t or "").strip()))


def _norm_head(t: str) -> str:
    return unicodedata.normalize("NFC", t or "").strip().rstrip(":.").strip().upper()


def is_toc_heading(t: str) -> bool:
    h = _norm_head(t)
    return len(h) <= 90 and bool(_TOC_HEAD_RE.match(h))


def is_ref_heading(t: str) -> bool:
    h = _norm_head(t)
    return len(h) <= 60 and bool(_REF_HEAD_RE.match(h))


def _toc_line(p: ParaInfo, t: str) -> bool:
    if (p.style_name or "").lower().startswith("toc"):
        return True
    if is_label_only(t):
        return False
    if _TOC_LINE_RE.search(t) and len(t) < 300:
        return True
    # danh mục chữ viết tắt: "UBND<tab>Ủy ban nhân dân"
    return "\t" in t and len(t) < 160


def ref_like(t: str) -> bool:
    """Dòng có dáng một mục tài liệu tham khảo (APA/TCVN 7115/cách ghi phổ biến ở VN)."""
    s = t.strip()
    if re.match(r"^\[\s*\d+\s*\]", s):
        return True
    if re.search(r"https?://|www\.|doi\.org|\bdoi\s*:", s, re.I):
        return True
    return bool(_YEAR_RE.search(s)) and len(s) >= 25 and ("," in s or "." in s)


def _ref_region_ends(p: ParaInfo, t: str) -> bool:
    """Tín hiệu kết thúc vùng tài liệu tham khảo: gặp PHỤ LỤC, chương/phần mới, hoặc một tiêu đề
    thật (style Heading / in hoa đậm ngắn) mà không phải tiêu đề nhóm tài liệu."""
    h = _norm_head(t)
    if RE["phu_luc_label"].match(t.strip()) or h.startswith("PHỤ LỤC"):
        return True
    if RE["phan_chuong_label"].match(t.strip()) or RE["phan_chuong_inline"].match(t.strip()):
        return True
    if ref_like(t) or _REF_GROUP_RE.match(h):
        return False
    if p.heading_level is not None and p.heading_level <= 2:
        return True
    return _is_caps(t) and len(t) <= 100 and p.ratio("bold") >= 0.5


def front_matter_regions(paras: list[ParaInfo], texts: list[str]) -> dict[int, str]:
    """Đánh dấu trước các đoạn thuộc mục lục/danh mục gõ tay và danh mục tài liệu tham khảo:
    toc_head | toc | ref_head | ref | ref_group. Dòng mục lục bị lọt ra ngoài vùng này sẽ bị
    nhận nhầm thành đề mục (vd. "I. ĐÁNH GIÁ...<tab>5" -> đề mục cấp 1) và kéo lệch cả mục lục."""
    out: dict[int, str] = {}
    region = None
    for i, p in enumerate(paras):
        t = texts[i]
        if p.where != "body" or not any(c.isalnum() for c in t):
            continue
        if is_ref_heading(t):
            region = "ref"
            out[i] = "ref_head"
            continue
        if is_toc_heading(t):
            region = "toc"
            out[i] = "toc_head"
            continue
        if region == "toc":
            if _toc_line(p, t):
                out[i] = "toc"
                continue
            region = None
        elif region == "ref":
            if _ref_region_ends(p, t):
                region = None
            else:
                out[i] = "ref" if (ref_like(t) or len(t) > 60) else "ref_group"
                continue
    return out


def _sentence_like(t: str) -> bool:
    """Dáng câu văn: rất dài, hoặc dài và kết thúc bằng dấu câu. Dòng gõ IN HOA TOÀN BỘ (tên chương
    dài, vd '... TRONG BỐI CẢNH TOÀN CẦU.') không bị coi là câu văn trừ khi quá dài."""
    s = t.strip()
    if _is_caps(s):
        return len(s) > 250
    if len(s) > 200:
        return True
    words = len(s.split())
    if s.endswith((".", ";", "!", "?")):
        return (len(s) > 80 and words >= 14) or (words >= 8 and "," in s)
    return False


_BULLET_START = re.compile(r"^\s*[-–+•*▪●○■□◦]\s*\S")


def content_signal(t: str) -> bool:
    """Dấu hiệu CHẮC CHẮN là nội dung, không phải đề mục (dù style có gắn cấp đề mục): dòng gạch
    đầu dòng, dòng liệt kê kết thúc bằng ';', hoặc có dáng câu văn."""
    s = (t or "").strip()
    return bool(_BULLET_START.match(s)) or s.endswith(";") or _sentence_like(s)


def numbered_role(p: ParaInfo, t: str, kind: str, prev_text: str, prev_is_list: bool,
                  seen_dieu: bool, pre: str = "") -> tuple[list[str], str, float]:
    """Phân biệt ĐỀ MỤC có số với KHOẢN/ĐIỂM LIỆT KÊ trong nội dung.
    Tín hiệu liệt kê: câu trước kết thúc bằng ':'; dòng kết thúc bằng ';' hoặc ','; đang nằm trong
    một chuỗi liệt kê (đoạn trước cũng là liệt kê) mà không in đậm; dòng dài/kết thúc như câu văn.
    Tín hiệu đề mục: in đậm (hoặc nghiêng với cấp 3), ngắn, không kết thúc bằng dấu câu."""
    h1, h2, h3, li = f"{pre}heading_l1", f"{pre}heading_l2", f"{pre}heading_l3", f"{pre}list_item"
    s = t.rstrip()
    bold = p.ratio("bold") >= 0.5
    italic = p.ratio("italic") >= 0.5
    short = len(s) < 160 and not s.endswith((".", ";", ","))
    item_end = s.endswith((";", ","))
    after_colon = prev_text.rstrip().endswith(":")
    list_ctx = (after_colon or item_end or (prev_is_list and not bold)) and not (bold and short)
    if kind == "num2":
        if list_ctx:
            return [li, h3, h2], li, 0.7
        return [h3, h2, li], (h3 if short else li), (0.7 if short and (bold or italic) else 0.6)
    if kind == "num1":
        if bold and short and not seen_dieu:
            return [h2, h3, li], h2, 0.75
        if list_ctx or not short:
            return [li, h2, h3], li, 0.75 if list_ctx else 0.6
        return [h2, h3, li], (li if seen_dieu else h2), 0.55
    # kind == "letter": a), b), đ)...
    if (bold or italic) and short and len(s) < 100 and not after_colon:
        return [h3, li], h3, 0.7
    if list_ctx or not short:
        return [li, h3], li, 0.75
    return [h3, li], h3, 0.5


def propose_roles(ex: ExtractedDoc) -> list[RoleDecision]:
    mark_zones(ex)
    paras = ex.paragraphs
    n = len(paras)
    out: list[RoleDecision] = [None] * n  # type: ignore

    def definite(i, role, method="regex", **kw):
        out[i] = RoleDecision(paras[i].pid, role, 1.0, method, [role], role, **kw)

    def ambiguous(i, cands, default, note="", conf=0.6):
        # conf < min_role_confidence (0.5) => chỉ sửa phông/màu, không sửa theo vai trò
        cands = list(dict.fromkeys(cands))
        out[i] = RoleDecision(paras[i].pid, default, conf, "heuristic", cands, default, note=note)

    texts = [full_text(p) for p in paras]
    regions = front_matter_regions(paras, texts)

    def prev_text(i: int) -> str:
        for j in range(i - 1, max(-1, i - 4), -1):
            if paras[j].where == paras[i].where and any(c.isalnum() for c in texts[j]):
                return texts[j]
        return ""

    def is_doc_type(i) -> bool:
        return (paras[i].zone_hint not in ("data_table", "signature_table", "header_table")
                and texts[i].rstrip(":").strip().upper() in DOC_TYPES and _is_caps(texts[i])
                and not RE["dong_quyet_dinh"].match(texts[i]))

    # --- tìm tên loại văn bản (văn bản chính) ---
    ten_loai_idx = None
    for i in range(min(40, n)):
        if is_doc_type(i):
            ten_loai_idx = i
            break
    decision_like = False   # văn bản dạng quyết định/nghị quyết -> có dòng thẩm quyền

    # --- vùng chữ ký ngoài bảng: từ dòng có tiền tố TM./KT./... trong 25 đoạn cuối ---
    sig_start = None
    for i in range(max(0, n - 25), n):
        if paras[i].where == "body" and RE["sig_prefix"].match(texts[i]) and _is_caps(texts[i]):
            sig_start = i
            break

    seen_dieu = False
    seen_decision_line = False
    pre_content = True          # vùng trước nội dung chính (tên loại, trích yếu, căn cứ)
    after_title = 0             # số dòng sau tên loại
    prev_role = None
    in_noi_nhan = False
    noi_nhan_cell = None
    in_kinh_gui = False         # các dòng “- …” ngay sau “Kính gửi:” / “… điện:” (PL I ô 9a; Mẫu 1.6)

    for i, p in enumerate(paras):
        t = texts[i]
        if not any(c.isalnum() for c in t) or RE["separator"].match(t):
            out[i] = RoleDecision(p.pid, "empty", 1.0, "skip", [], "empty")
            continue
        if p.where == "body" and re.search(r"trân\s+trọng\s+giới\s+thiệu\s*:\s*$", t, re.I) and len(t) <= 250:
            definite(i, "other", "context", note="Dòng mở đầu Giấy giới thiệu (Mẫu 1.8, canh giữa)")
            prev_role = "other"
            pre_content = False
            continue
        if in_kinh_gui:
            if p.where == "body" and (RE["noi_nhan_item"].match(t) or p.num_label == "-") and len(t) <= 250:
                definite(i, "kinh_gui", "context", note="Dòng nơi nhận sau “Kính gửi:”")
                prev_role = "kinh_gui"
                continue
            in_kinh_gui = False
        if p.where == "body" and re.search(r"\bđiện\s*:\s*$", t) and len(t) <= 250 and pre_content is not None \
                and ten_loai_idx is not None and i > ten_loai_idx and texts[ten_loai_idx].strip().upper() == "CÔNG ĐIỆN":
            definite(i, "kinh_gui", "context", note="Dòng “… điện:” của Công điện (Mẫu 1.6)")
            in_kinh_gui = True
            prev_role = "kinh_gui"
            pre_content = False
            continue

        # ---- mục lục ----
        if p.style_name and p.style_name.lower().startswith("toc"):
            definite(i, "toc_entry", "context")
            prev_role = "toc_entry"
            continue

        # ---- vùng mục lục/danh mục gõ tay, danh mục tài liệu tham khảo ----
        fm = regions.get(i)
        if fm:
            role = {"toc_head": "other", "toc": "toc_entry", "ref_head": "heading_l1",
                    "ref": "tai_lieu_tham_khao", "ref_group": "other"}[fm]
            note = {"toc_head": "Tiêu đề mục lục/danh mục – không đưa vào mục lục",
                    "ref_group": "Tiêu đề nhóm tài liệu tham khảo"}.get(fm, "")
            definite(i, role, "context", note=note)
            prev_role = role
            continue

        # ---- khối nơi nhận ----
        if RE["noi_nhan_label"].match(t):
            definite(i, "noi_nhan_label")
            in_noi_nhan = True
            noi_nhan_cell = (p.table_idx, p.row, p.col)
            prev_role = "noi_nhan_label"
            continue
        if in_noi_nhan:
            same_cell = (p.table_idx, p.row, p.col) == noi_nhan_cell
            if (same_cell or p.where == "body") and (RE["noi_nhan_item"].match(t) or p.num_label == "-"):
                definite(i, "noi_nhan_item", "context")
                continue
            if same_cell:
                definite(i, "noi_nhan_item", "context", note="Dòng tiếp theo trong ô Nơi nhận")
                continue
            in_noi_nhan = False

        # ---- regex chắc chắn, áp dụng mọi vùng ----
        for key in ("quoc_hieu", "tieu_ngu", "so_ky_hieu", "trich_yeu_cong_van", "kinh_gui"):
            if RE[key].match(t):
                definite(i, key)
                break
        if out[i] is not None:
            prev_role = out[i].role
            if prev_role == "kinh_gui":
                pre_content = False
                in_kinh_gui = t.rstrip().endswith(":")
            continue
        if RE["dia_danh_thoi_gian"].match(t) and (i < 20 or p.zone_hint == "header_table") \
                and ":" not in t.split(",")[0] and not re.search(r"\bgiờ\b", t.split(",")[0]):
            # “Thời gian bắt đầu: 8 giờ, ngày …”, “… kết thúc vào 11 giờ, ngày …” không phải địa danh
            definite(i, "dia_danh_thoi_gian")
            prev_role = "dia_danh_thoi_gian"
            continue

        # ---- bảng tiêu đề ----
        if p.zone_hint == "header_table":
            if prev_role == "trich_yeu_cong_van" and not _is_caps(t):
                definite(i, "trich_yeu_cong_van", "context", note="Dòng tiếp của trích yếu V/v")
            elif _is_caps(t) and (p.col == 0 or (p.ncols or 1) == 1):
                left_caps = [j for j, q in enumerate(paras) if q.zone_hint == "header_table"
                             and q.table_idx == p.table_idx and q.col == p.col and _is_caps(texts[j])
                             and not RE["quoc_hieu"].match(texts[j])]
                if len(left_caps) == 1:
                    definite(i, "co_quan_ban_hanh", "context", note="Chỉ có một dòng tên cơ quan")
                else:
                    default = "co_quan_chu_quan" if i == left_caps[0] else "co_quan_ban_hanh"
                    ambiguous(i, ["co_quan_chu_quan", "co_quan_ban_hanh"], default)
            else:
                definite(i, "other", "context")
            prev_role = out[i].role
            continue

        # ---- bảng chữ ký / vùng chữ ký ----
        if p.zone_hint == "signature_table" or (sig_start is not None and i >= sig_start and p.where == "body"):
            if RE["sig_note"].match(t):
                definite(i, "other", "context", note="Ghi chú chữ ký")
            elif RE["sig_prefix"].match(t):
                definite(i, "chuc_vu_nguoi_ky")
            elif _is_caps(t) and len(t) <= 80:
                ambiguous(i, ["chuc_vu_nguoi_ky", "other"], "chuc_vu_nguoi_ky")
            elif _name_like(t):
                ambiguous(i, ["ho_ten_nguoi_ky", "other"], "ho_ten_nguoi_ky")
            else:
                definite(i, "other", "context")
            prev_role = out[i].role
            continue

        # ---- bảng số liệu ----
        if p.zone_hint == "data_table":
            if RE["source_note"].match(t):
                definite(i, "source_note")
            else:
                definite(i, "table_cell", "context")
            prev_role = "table_cell"
            continue

        # ============ PHẦN THÂN VĂN BẢN ============
        # tên cơ quan khi không dùng bảng tiêu đề
        if ten_loai_idx is not None and i < ten_loai_idx and _is_caps(t) and not RE["quoc_hieu"].match(t):
            ambiguous(i, ["co_quan_chu_quan", "co_quan_ban_hanh", "other"], "co_quan_ban_hanh")
            prev_role = out[i].role
            continue
        if i == ten_loai_idx or (ten_loai_idx is not None and i > ten_loai_idx and is_doc_type(i)):
            # tên loại của văn bản chính hoặc văn bản ban hành kèm theo (Quy chế, Quy định...)
            definite(i, "ten_loai", "regex" if i == ten_loai_idx else "context")
            after_title = 0
            pre_content = True
            decision_like = texts[i].rstrip(":").strip().upper() in ("QUYẾT ĐỊNH", "NGHỊ QUYẾT", "CHỈ THỊ")
            prev_role = "ten_loai"
            continue

        # dòng "QUYẾT ĐỊNH:"
        if RE["dong_quyet_dinh"].match(t):
            definite(i, "dong_quyet_dinh")
            seen_decision_line = True
            pre_content = False
            prev_role = "dong_quyet_dinh"
            continue

        # trích yếu / thẩm quyền / căn cứ (vùng đầu văn bản)
        if pre_content and ten_loai_idx is not None and i > ten_loai_idx:
            after_title += 1
            if RE["can_cu"].match(t) and not seen_decision_line:
                strong = re.match(r"^(Căn\s+cứ|Theo\s+đề\s+nghị|Xét\s+đề\s+nghị)\b", t, re.I)
                ambiguous(i, ["can_cu", "body"], "can_cu" if strong else "body")
                prev_role = out[i].role
                continue
            if after_title <= 3 and prev_role in ("ten_loai", "trich_yeu") and len(t) < 250 \
                    and not (RE["roman"].match(t) or RE["num1"].match(t) or RE["dieu"].match(t)
                             or RE["phan_chuong_label"].match(t) or RE["phan_chuong_inline"].match(t)):
                if _is_caps(t) and prev_role == "trich_yeu":
                    if decision_like:
                        ambiguous(i, ["tham_quyen", "trich_yeu", "heading_l1", "other"], "tham_quyen")
                    else:
                        ambiguous(i, ["heading_l1", "trich_yeu", "other"], "heading_l1", conf=0.45)
                elif t.startswith("(") and t.rstrip().endswith(")"):
                    definite(i, "other", "context", note="Dòng chú thích trong ngoặc (vd. 'Ban hành kèm theo...')")
                else:
                    # Mẫu 1.8, 1.10 không có trích yếu; dòng canh đều/thụt đầu dòng nhiều khả năng là nội dung
                    no_trich = texts[ten_loai_idx].strip().upper() in ("GIẤY GIỚI THIỆU", "GIẤY NGHỈ PHÉP")
                    looks_body = p.align in ("justify", "left") and (p.first_line_cm or 0) >= 0.5
                    ambiguous(i, ["trich_yeu", "body", "heading_l1"], "body" if no_trich or looks_body else "trich_yeu")
                prev_role = out[i].role
                continue
            if decision_like and prev_role in ("trich_yeu", "tham_quyen") and _is_caps(t) and len(t) < 120:
                ambiguous(i, ["tham_quyen", "heading_l1", "other"], "tham_quyen")
                prev_role = out[i].role
                continue
            pre_content = False

        # nhãn phần/chương/mục/điều/phụ lục
        if RE["phan_chuong_label"].match(t):
            definite(i, "phan_chuong_label")
            prev_role = "phan_chuong_label"
            continue
        if RE["phan_chuong_inline"].match(t):
            definite(i, "phan_chuong_label", skip_fields=["caps"], note="Nhãn và tiêu đề chương trên cùng một dòng")
            prev_role = "phan_chuong_title"
            continue
        if RE["muc_label"].match(t):
            definite(i, "muc_label")
            prev_role = "muc_label"
            continue
        if RE["dieu"].match(t):
            definite(i, "dieu")
            seen_dieu = True
            prev_role = "dieu"
            continue
        if RE["phu_luc_label"].match(t):
            definite(i, "phu_luc_label")
            prev_role = "phu_luc_label"
            continue
        if prev_role == "phan_chuong_label":
            definite(i, "phan_chuong_title", "context")
            prev_role = "phan_chuong_title"
            continue
        if prev_role == "muc_label":
            definite(i, "muc_title", "context")
            prev_role = "muc_title"
            continue
        if prev_role == "phu_luc_label":
            definite(i, "phu_luc_title", "context")
            prev_role = "phu_luc_title"
            continue

        # chú thích bảng/hình, nguồn
        if RE["source_note"].match(t) and len(t) < 300:
            definite(i, "source_note")
            prev_role = "source_note"
            continue
        if RE["caption_table"].match(t) and len(t) < 220:
            if p.next_is_table:
                definite(i, "caption_table", "context")
            else:
                ambiguous(i, ["caption_table", "body"], "caption_table")
            prev_role = out[i].role
            continue
        if RE["caption_figure"].match(t) and len(t) < 220:
            ambiguous(i, ["caption_figure", "body"], "caption_figure")
            prev_role = out[i].role
            continue

        # đề mục có đánh số
        short = len(t) < 160 and not t.rstrip().endswith((".", ";"))
        if RE["bullet"].match(t) or p.num_label == "-":
            definite(i, "list_item")
        elif RE["roman"].match(t):
            ambiguous(i, ["heading_l1", "list_item"], "heading_l1" if len(t) < 200 else "list_item")
        elif RE["num2"].match(t) or RE["num1"].match(t) or RE["letter"].match(t):
            kind = "num2" if RE["num2"].match(t) else ("num1" if RE["num1"].match(t) else "letter")
            cands, default, conf = numbered_role(p, t, kind, prev_text(i), prev_role == "list_item", seen_dieu)
            ambiguous(i, cands, default, conf=conf)
        elif p.heading_level and _sentence_like(t):
            # style Heading bị gán nhầm cho câu văn (thường do copy từ nguồn khác) -> nội dung,
            # để không lọt vào mục lục
            ambiguous(i, ["body", "heading_l2", "heading_l3"], "body", conf=0.75,
                      note="Mang style Heading nhưng là câu văn – đã coi là đoạn nội dung")
        elif p.heading_level:
            lvl = min(p.heading_level, 3)
            ambiguous(i, ["heading_l1", "heading_l2", "heading_l3", "body"], f"heading_l{lvl}")
        elif _is_caps(t) and len(t) <= 150:
            ambiguous(i, ["heading_l1", "phan_chuong_title", "phu_luc_title", "other"], "heading_l1", conf=0.55)
        elif len(t) < 100 and not _terminated(t) and len(t.split()) <= 15:
            ambiguous(i, ["heading_l2", "heading_l3", "body"], "body", conf=0.4)
        else:
            definite(i, "body", "context")
        prev_role = out[i].role

    return out


# ---------------------------------------------------------------------------
def propose_roles_dang(ex: ExtractedDoc) -> list[RoleDecision]:
    """Xác định vai trò cho văn bản của Đảng (Hướng dẫn 05-HD/VPTW). Cùng cấu trúc
    logic với propose_roles() ở trên (ND30) nhưng theo thể thức của Đảng: tiêu đề
    "ĐẢNG CỘNG SẢN VIỆT NAM" thay quốc hiệu/tiêu ngữ; "Số 127-QĐ/TW" (không dấu
    hai chấm) thay "Số: .../QĐ-..."; dấu sao (*) ngăn cách cơ quan ban hành và số
    ký hiệu; quyền hạn ký (T/M, K/T, T/L, Q.) tách riêng khỏi chức vụ người ký."""
    mark_zones(ex)
    paras = ex.paragraphs
    n = len(paras)
    out: list[RoleDecision] = [None] * n  # type: ignore

    def definite(i, role, method="regex", **kw):
        out[i] = RoleDecision(paras[i].pid, role, 1.0, method, [role], role, **kw)

    def ambiguous(i, cands, default, note="", conf=0.6):
        cands = list(dict.fromkeys(cands))
        out[i] = RoleDecision(paras[i].pid, default, conf, "heuristic", cands, default, note=note)

    texts = [full_text(p) for p in paras]
    regions = front_matter_regions(paras, texts)

    def prev_text(i: int) -> str:
        for j in range(i - 1, max(-1, i - 4), -1):
            if paras[j].where == paras[i].where and any(c.isalnum() for c in texts[j]):
                return texts[j]
        return ""

    def is_doc_type(i) -> bool:
        return (paras[i].zone_hint not in ("data_table", "signature_table", "header_table")
                and texts[i].rstrip(":").strip().upper() in DOC_TYPES_DANG and _is_caps(texts[i])
                and not RE["dong_quyet_dinh"].match(texts[i]))

    ten_loai_idx = None
    for i in range(min(40, n)):
        if is_doc_type(i):
            ten_loai_idx = i
            break

    sig_start = None
    for i in range(max(0, n - 25), n):
        if paras[i].where == "body" and RE["sig_prefix"].match(texts[i]) and _is_caps(texts[i]):
            sig_start = i
            break

    seen_dieu = False
    pre_content = True
    after_title = 0
    prev_role = None
    in_noi_nhan = False
    noi_nhan_cell = None
    noi_nhan_done_at = None

    for i, p in enumerate(paras):
        t = texts[i]
        if not any(c.isalnum() for c in t) or RE["separator"].match(t):
            out[i] = RoleDecision(p.pid, "empty", 1.0, "skip", [], "empty")
            continue

        if p.style_name and p.style_name.lower().startswith("toc"):
            definite(i, "dang_toc_entry", "context")
            prev_role = "dang_toc_entry"
            continue

        fm = regions.get(i)
        if fm:
            role = {"toc_head": "other", "toc": "dang_toc_entry", "ref_head": "dang_heading_l1",
                    "ref": "dang_tai_lieu", "ref_group": "other"}[fm]
            note = {"toc_head": "Tiêu đề mục lục/danh mục – không đưa vào mục lục",
                    "ref_group": "Tiêu đề nhóm tài liệu tham khảo"}.get(fm, "")
            definite(i, role, "context", note=note)
            prev_role = role
            continue

        # ---- khối nơi nhận ----
        if RE["noi_nhan_label"].match(t):
            definite(i, "dang_noi_nhan_label")
            in_noi_nhan = True
            noi_nhan_cell = (p.table_idx, p.row, p.col)
            prev_role = "dang_noi_nhan_label"
            continue
        if in_noi_nhan:
            same_cell = (p.table_idx, p.row, p.col) == noi_nhan_cell
            if (same_cell or p.where == "body") and (RE["noi_nhan_item"].match(t) or p.num_label == "-"):
                definite(i, "dang_noi_nhan_item", "context")
                continue
            if same_cell:
                definite(i, "dang_noi_nhan_item", "context", note="Dòng tiếp theo trong ô Nơi nhận")
                continue
            in_noi_nhan = False
            noi_nhan_done_at = i

        # ---- regex chắc chắn, áp dụng mọi vùng ----
        if RE_DANG["tieu_de"].match(t):
            definite(i, "dang_tieu_de")
            prev_role = "dang_tieu_de"
            continue
        if RE_DANG["so_ky_hieu"].match(t):
            definite(i, "dang_so_ky_hieu")
            prev_role = "dang_so_ky_hieu"
            continue
        if RE_DANG["kinh_gui"].match(t):
            definite(i, "dang_kinh_gui")
            pre_content = False
            prev_role = "dang_kinh_gui"
            continue
        if RE_DANG["dau_khan"].match(t):
            definite(i, "dang_dau_khan")
            prev_role = "dang_dau_khan"
            continue
        if RE_DANG["pham_vi_luu_hanh"].match(t):
            definite(i, "dang_pham_vi_luu_hanh")
            prev_role = "dang_pham_vi_luu_hanh"
            continue
        if RE_DANG["du_thao"].match(t):
            definite(i, "dang_du_thao")
            prev_role = "dang_du_thao"
            continue
        if RE_DANG["thong_tin_lien_he"].search(t):
            definite(i, "dang_thong_tin_lien_he")
            prev_role = "dang_thong_tin_lien_he"
            continue
        if RE["dia_danh_thoi_gian"].match(t) and (i < 20 or p.zone_hint == "header_table"):
            definite(i, "dang_dia_danh_thoi_gian")
            prev_role = "dang_dia_danh_thoi_gian"
            continue

        # ---- bảng tiêu đề (cơ quan cấp trên / cơ quan ban hành) ----
        if p.zone_hint == "header_table":
            if _is_caps(t) and (p.col == 0 or (p.ncols or 1) == 1):
                left_caps = [j for j, q in enumerate(paras) if q.zone_hint == "header_table"
                             and q.table_idx == p.table_idx and q.col == p.col and _is_caps(texts[j])
                             and not RE_DANG["tieu_de"].match(texts[j])]
                if len(left_caps) == 1:
                    definite(i, "dang_co_quan_ban_hanh", "context", note="Chỉ có một dòng tên cơ quan")
                else:
                    default = "dang_co_quan_cap_tren" if i == left_caps[0] else "dang_co_quan_ban_hanh"
                    ambiguous(i, ["dang_co_quan_cap_tren", "dang_co_quan_ban_hanh"], default)
            else:
                definite(i, "other", "context")
            prev_role = out[i].role
            continue

        # ---- trích yếu công văn: dòng ngắn, không in hoa, ngay sau số/địa danh
        # (công văn không có dòng thể loại riêng nên không bắt được bằng regex) ----
        if prev_role in ("dang_so_ky_hieu", "dang_dia_danh_thoi_gian") and i < 15 \
                and not _is_caps(t) and len(t) < 200:
            ambiguous(i, ["dang_trich_yeu_cong_van", "dang_body", "dang_kinh_gui"], "dang_trich_yeu_cong_van")
            prev_role = out[i].role
            continue

        # ---- bảng/khối chữ ký ----
        if p.zone_hint == "signature_table" or (sig_start is not None and i >= sig_start and p.where == "body"):
            if RE["sig_note"].match(t):
                definite(i, "other", "context", note="Ghi chú chữ ký")
            elif RE["sig_prefix"].match(t):
                definite(i, "dang_quyen_han_ky")
            elif _is_caps(t) and len(t) <= 80:
                ambiguous(i, ["dang_chuc_vu_ky", "other"], "dang_chuc_vu_ky")
            elif _name_like(t):
                ambiguous(i, ["dang_ho_ten_ky", "other"], "dang_ho_ten_ky")
            else:
                definite(i, "other", "context")
            prev_role = out[i].role
            continue

        # ---- bảng số liệu ----
        if p.zone_hint == "data_table":
            if RE["source_note"].match(t):
                definite(i, "dang_source_note")
            else:
                definite(i, "dang_table_cell", "context")
            prev_role = "dang_table_cell"
            continue

        # ---- ký hiệu người soạn thảo: dòng ngắn, không dấu cách/rất ít, ngay sau khối Nơi nhận ----
        if noi_nhan_done_at is not None and i == noi_nhan_done_at and len(t) < 30 \
                and not _is_caps(t) and not _name_like(t) and len(t.split()) <= 2:
            ambiguous(i, ["dang_ky_hieu_soan_thao", "other"], "dang_ky_hieu_soan_thao", conf=0.45)
            noi_nhan_done_at = None
            prev_role = out[i].role
            continue
        noi_nhan_done_at = None

        # ============ PHẦN THÂN VĂN BẢN ============
        if ten_loai_idx is not None and i < ten_loai_idx and _is_caps(t) and not RE_DANG["tieu_de"].match(t):
            ambiguous(i, ["dang_co_quan_cap_tren", "dang_co_quan_ban_hanh", "other"], "dang_co_quan_ban_hanh")
            prev_role = out[i].role
            continue
        if i == ten_loai_idx or (ten_loai_idx is not None and i > ten_loai_idx and is_doc_type(i)):
            definite(i, "dang_the_loai", "regex" if i == ten_loai_idx else "context")
            after_title = 0
            pre_content = True
            prev_role = "dang_the_loai"
            continue

        # dòng chuyển tiếp "QUYẾT ĐỊNH:"/"NGHỊ QUYẾT:" trước Điều 1 (không có role riêng, chỉ kiểm tra phông)
        if RE["dong_quyet_dinh"].match(t):
            definite(i, "other", "context", note="Dòng chuyển tiếp trước nội dung quyết định/nghị quyết")
            pre_content = False
            prev_role = "other"
            continue

        # trích yếu / căn cứ (vùng đầu văn bản, sau thể loại)
        if pre_content and ten_loai_idx is not None and i > ten_loai_idx:
            after_title += 1
            if RE_DANG["can_cu"].match(t):
                ambiguous(i, ["dang_can_cu", "dang_body"], "dang_can_cu")
                prev_role = out[i].role
                continue
            if after_title <= 2 and prev_role == "dang_the_loai" and len(t) < 250 \
                    and not (RE["roman"].match(t) or RE["num1"].match(t) or RE["dieu"].match(t)
                             or RE["phan_chuong_label"].match(t) or RE["phan_chuong_inline"].match(t)):
                if t.startswith("(") and t.rstrip().endswith(")"):
                    definite(i, "other", "context", note="Dòng chú thích trong ngoặc")
                else:
                    ambiguous(i, ["dang_trich_yeu", "dang_body", "dang_heading_l1"], "dang_trich_yeu")
                prev_role = out[i].role
                continue
            pre_content = False

        # nhãn phần/chương/mục/điều/phụ lục (regex dùng chung với ND30 – cùng cách viết)
        if RE["phan_chuong_label"].match(t):
            definite(i, "dang_phan_chuong_label")
            prev_role = "dang_phan_chuong_label"
            continue
        if RE["phan_chuong_inline"].match(t):
            definite(i, "dang_phan_chuong_label", skip_fields=["caps"],
                     note="Nhãn và tiêu đề chương trên cùng một dòng")
            prev_role = "dang_phan_chuong_title"
            continue
        if RE["muc_label"].match(t):
            definite(i, "dang_muc_label")
            prev_role = "dang_muc_label"
            continue
        if RE["dieu"].match(t):
            definite(i, "dang_dieu")
            seen_dieu = True
            prev_role = "dang_dieu"
            continue
        if RE["phu_luc_label"].match(t):
            definite(i, "dang_phu_luc_label")
            prev_role = "dang_phu_luc_label"
            continue
        if prev_role == "dang_phan_chuong_label":
            definite(i, "dang_phan_chuong_title", "context")
            prev_role = "dang_phan_chuong_title"
            continue
        if prev_role == "dang_muc_label":
            definite(i, "dang_muc_title", "context")
            prev_role = "dang_muc_title"
            continue
        if prev_role == "dang_phu_luc_label":
            definite(i, "dang_phu_luc_title", "context")
            prev_role = "dang_phu_luc_title"
            continue

        # chú thích bảng/hình, nguồn (quy ước, dùng chung regex với ND30)
        if RE["source_note"].match(t) and len(t) < 300:
            definite(i, "dang_source_note")
            prev_role = "dang_source_note"
            continue
        if RE["caption_table"].match(t) and len(t) < 220:
            if p.next_is_table:
                definite(i, "dang_caption_table", "context")
            else:
                ambiguous(i, ["dang_caption_table", "dang_body"], "dang_caption_table")
            prev_role = out[i].role
            continue
        if RE["caption_figure"].match(t) and len(t) < 220:
            ambiguous(i, ["dang_caption_figure", "dang_body"], "dang_caption_figure")
            prev_role = out[i].role
            continue

        # đề mục có đánh số / khoản, điểm, gạch đầu dòng
        short = len(t) < 160 and not t.rstrip().endswith((".", ";"))
        if RE["bullet"].match(t) or p.num_label == "-":
            definite(i, "dang_list_item")
        elif RE["roman"].match(t):
            ambiguous(i, ["dang_heading_l1", "dang_list_item"], "dang_heading_l1" if len(t) < 200 else "dang_list_item")
        elif RE["num2"].match(t) or RE["num1"].match(t) or RE["letter"].match(t):
            kind = "num2" if RE["num2"].match(t) else ("num1" if RE["num1"].match(t) else "letter")
            cands, default, conf = numbered_role(p, t, kind, prev_text(i), prev_role == "dang_list_item",
                                                 seen_dieu, pre="dang_")
            ambiguous(i, cands, default, conf=conf)
        elif p.heading_level and _sentence_like(t):
            # style Heading bị gán nhầm cho câu văn (thường do copy từ nguồn khác) -> nội dung,
            # để không lọt vào mục lục
            ambiguous(i, ["dang_body", "dang_heading_l2", "dang_heading_l3"], "dang_body", conf=0.75,
                      note="Mang style Heading nhưng là câu văn – đã coi là đoạn nội dung")
        elif p.heading_level:
            lvl = min(p.heading_level, 3)
            ambiguous(i, ["dang_heading_l1", "dang_heading_l2", "dang_heading_l3", "dang_body"], f"dang_heading_l{lvl}")
        elif _is_caps(t) and len(t) <= 150:
            ambiguous(i, ["dang_heading_l1", "dang_phan_chuong_title", "dang_phu_luc_title", "other"],
                      "dang_heading_l1", conf=0.55)
        elif len(t) < 100 and not _terminated(t) and len(t.split()) <= 15:
            ambiguous(i, ["dang_heading_l2", "dang_heading_l3", "dang_body"], "dang_body", conf=0.4)
        else:
            definite(i, "dang_body", "context")
        prev_role = out[i].role

    return out


# ---------------------------------------------------------------------------
# LUẬN VĂN / ĐỀ ÁN THẠC SĨ (Phụ lục 4.1)
# ---------------------------------------------------------------------------
_DEAN_TITLES_EXACT = {
    "LỜI CAM ĐOAN", "LỜI CẢM ƠN", "MỤC LỤC", "MỞ ĐẦU", "PHẦN MỞ ĐẦU", "NỘI DUNG", "KẾT LUẬN",
    "KẾT LUẬN VÀ KIẾN NGHỊ", "KẾT LUẬN VÀ KHUYẾN NGHỊ", "KIẾN NGHỊ", "TÀI LIỆU THAM KHẢO",
    "DANH MỤC TÀI LIỆU THAM KHẢO", "PHỤ LỤC", "TÓM TẮT", "LỜI MỞ ĐẦU",
}
# vùng nội dung ngay sau tiêu đề phần
_DEAN_LIST_PREFIX = ("MỤC LỤC", "DANH MỤC CÁC KÝ HIỆU", "DANH MỤC KÝ HIỆU", "DANH MỤC CÁC CHỮ", "DANH MỤC CHỮ",
                     "DANH MỤC CÁC TỪ", "DANH MỤC TỪ", "DANH MỤC CÁC BẢNG", "DANH MỤC BẢNG", "DANH MỤC CÁC HÌNH",
                     "DANH MỤC HÌNH", "DANH MỤC CÁC BIỂU", "DANH MỤC BIỂU", "DANH MỤC CÁC SƠ ĐỒ", "DANH MỤC SƠ ĐỒ")
_DEAN_REF_PREFIX = ("TÀI LIỆU THAM KHẢO", "DANH MỤC TÀI LIỆU THAM KHẢO", "DANH MỤC CÔNG TRÌNH")
_DEAN_APPX_PREFIX = ("PHỤ LỤC", "QUYẾT ĐỊNH GIAO ĐỀ TÀI")
_DEAN_OTHER_PREFIX = ("DANH MỤC", "KẾT LUẬN")

RE_DEAN = {
    "chuong": re.compile(r"^CHƯƠNG\s+(\d+|[IVXLC]+)\b", re.I),
    "muc": re.compile(r"^(\d+)((?:\.\d+){1,5})\.?\s+\S"),
    "caption_table": re.compile(r"^(Bảng|Biểu)\s+\d+(?:\.\d+)*\s*(?:[.:\-–—](?!\d)|$)", re.I),
    "caption_figure": re.compile(r"^(Hình|Biểu\s+đồ|Sơ\s+đồ|Đồ\s+thị|Ảnh)\s+\d+(?:\.\d+)*\s*(?:[.:\-–—](?!\d)|$)", re.I),
    "nguon": re.compile(r"^\(?\s*(?:(?:Nguồn|Ghi\s+chú|Đơn\s+vị\s+tính|ĐVT)\s*[:：]|Đơn\s+vị\s*[:：]\s*(?:triệu|tỷ|tỉ|nghìn|ngàn|đồng|%|người|tấn|USD|VNĐ|VND|kWh|MWh|GWh|MW|ha\b|km|m2|m³))", re.I),
}


def dean_heading_level(text: str) -> int | None:
    """'1.1. Abc' -> 2, '1.1.1 Abc' -> 3 ... (số chữ số trong nhóm). None nếu không phải dạng này."""
    m = RE_DEAN["muc"].match(text.strip())
    if not m:
        return None
    return 1 + m.group(2).count(".")


def _dean_title_kind(t: str, caps_ok: bool) -> str | None:
    """Phân loại tiêu đề phần: list | ref | appx | text. None nếu không phải tiêu đề phần."""
    u = t.strip().rstrip(".:").strip().upper()
    if len(u) > 120:
        return None
    exact = u in _DEAN_TITLES_EXACT
    if not exact and not caps_ok:
        return None
    if u.startswith(_DEAN_LIST_PREFIX):
        return "list"
    if u.startswith(_DEAN_REF_PREFIX):
        return "ref"
    if u.startswith(_DEAN_APPX_PREFIX):
        return "appx"
    if exact or u.startswith(_DEAN_OTHER_PREFIX):
        return "text"
    return None


_COVER_BREAK_RE = re.compile(r"^(\d+(\.\d+)*\s*[.)]\s*\S|[a-zđ]\s*[.)]\s+\S|[-–+•]\s*\S)")


_COVER_PERSON_RE = re.compile(r"^\d+\s*[.)]\s*(GS|PGS|TS|ThS|TSKH|NGƯT|NGND|Th\.S)\b", re.I)


def _dean_cover_breaker(t: str) -> bool:
    """Dòng không thể thuộc trang bìa/phụ bìa: đề mục đánh số, mục a)/b), gạch đầu dòng, câu văn dài."""
    t = (t or "").strip()
    if not t:
        return False
    if _COVER_PERSON_RE.match(t):   # "1. PGS.TS. Nguyễn Văn A" – người hướng dẫn trên phụ bìa
        return False
    return bool(_COVER_BREAK_RE.match(t)) or len(t) > 160


_THESIS_MARK_RE = re.compile(r"(LUẬN\s+VĂN|LUẬN\s+ÁN|ĐỀ\s+ÁN\s+(TỐT\s+NGHIỆP\s+)?THẠC\s+SĨ|KHÓA\s+LUẬN|KHOÁ\s+LUẬN)",
                             re.I)
_THESIS_CORE = ("MỞ ĐẦU", "PHẦN MỞ ĐẦU", "LỜI MỞ ĐẦU", "KẾT LUẬN", "TÀI LIỆU THAM KHẢO",
                "DANH MỤC TÀI LIỆU THAM KHẢO", "LỜI CAM ĐOAN")


def detect_dean_fit(ex: ExtractedDoc) -> dict:
    """Văn bản có cấu trúc luận văn/đề án thạc sĩ (Phụ lục 4.1) hay không. Dùng để CẢNH BÁO khi người
    dùng chọn chuẩn "Đề án" cho văn bản khác loại (tờ trình, thuyết minh nhiệm vụ, báo cáo...)."""
    head, core, marker = "", set(), ""
    for p in ex.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        if not head and p.where == "body" and len(t) >= 15 and _is_caps(t):
            head = t
        if not marker and _THESIS_MARK_RE.search(t) and len(t) <= 120:
            marker = t
        u = t.rstrip(".:").strip().upper()
        if p.where == "body" and u in _THESIS_CORE:
            core.add(u)
    fits = bool(marker) or len(core) >= 2
    return {"fits": fits, "evidence": (marker or head or "")[:160], "core_titles": sorted(core)}


def propose_roles_dean(ex: ExtractedDoc) -> list[RoleDecision]:
    """Vai trò đoạn cho luận văn/đề án thạc sĩ: bìa -> các phần đầu (lời cam đoan, mục lục, danh mục)
    -> MỞ ĐẦU -> các chương (tên chương, tiểu mục 1.1/1.1.1/1.1.1.1, tên bảng/hình, nội dung)
    -> KẾT LUẬN -> TÀI LIỆU THAM KHẢO -> PHỤ LỤC. Dòng trong mục lục/danh mục không bị nhận nhầm
    là tên bảng/hình hay tiểu mục vì được xét theo VÙNG (sau tiêu đề nào)."""
    mark_zones(ex)
    paras = ex.paragraphs
    n = len(paras)
    out: list[RoleDecision] = [None] * n  # type: ignore
    texts = [full_text(p) for p in paras]

    def definite(i, role, method="regex", conf=1.0, note=""):
        out[i] = RoleDecision(paras[i].pid, role, conf, method, [role], role, note=note)

    def ambiguous(i, cands, default, note="", conf=0.6):
        cands = list(dict.fromkeys(cands))
        out[i] = RoleDecision(paras[i].pid, default, conf, "heuristic", cands, default, note=note)

    def title_kind(i):
        p = paras[i]
        if p.where != "body" or p.zone_hint == "data_table":
            return None
        real_heading_style = (p.heading_level or 9) <= 3 or (p.style_name or "").lower().startswith("heading")
        caps_ok = _is_caps(texts[i]) and (p.ratio("bold") >= 0.5 or (p.heading_level or 9) <= 2)
        return _dean_title_kind(texts[i], caps_ok or real_heading_style)

    kinds = [title_kind(i) for i in range(n)]
    first_title = next((i for i in range(n) if kinds[i] or RE_DEAN["chuong"].match(texts[i])), None)
    # Trang bìa/phụ bìa chỉ gồm các dòng ngắn (tên trường, tên tác giả, "LUẬN VĂN THẠC SĨ", "Mã số:",
    # "HÀ NỘI - 2026"...). Gặp dòng có dấu hiệu nội dung (đề mục đánh số "7.1.", gạch đầu dòng, câu
    # văn dài) trước tiêu đề phần đầu tiên thì vùng bìa KẾT THÚC tại đó – nếu không, cả văn bản không
    # có cấu trúc luận văn (vd. thuyết minh nhiệm vụ có "CHƯƠNG 1" nằm trong mục "Nội dung nghiên cứu")
    # sẽ bị coi là trang bìa và không được kiểm tra.
    cover_end = first_title
    if first_title is not None:
        for i in range(first_title):
            if paras[i].where == "body" and _dean_cover_breaker(texts[i]):
                cover_end = i
                break

    region = "text"
    chapter_title_next = False
    front_matter_streak = 0  # số đoạn liên tiếp trong vùng list/ref/appx KHÔNG giống dòng mục lục/danh mục thật
    for i, p in enumerate(paras):
        t = texts[i]
        if not t.strip():
            definite(i, "empty")
            continue
        if cover_end is not None and i < cover_end:
            definite(i, "dean_bia", "context", note="Trước tiêu đề phần đầu tiên – coi là trang bìa/phụ bìa")
            continue
        k = kinds[i]
        if k:
            definite(i, "dean_tieu_de_phan")
            region = k
            chapter_title_next = False
            front_matter_streak = 0
            continue
        toc_like = bool(re.search(r"((\t|\.{3,}|…+|\s)\s*\d+|(?<=[.)])\d{1,4})\s*$", t)) and region in ("list", "ref", "appx") \
            and not is_label_only(t)
        if RE_DEAN["chuong"].match(t) and p.where == "body" and not toc_like:
            definite(i, "dean_chuong")
            region = "text"
            front_matter_streak = 0
            # "CHƯƠNG 1" đứng riêng một dòng -> dòng kế tiếp là tên chương
            chapter_title_next = len(t.strip()) <= 14
            continue
        if chapter_title_next:
            chapter_title_next = False
            if p.where == "body" and len(t) <= 200 and not t.rstrip().endswith("."):
                definite(i, "dean_chuong", "context", note="Dòng ngay sau 'CHƯƠNG n' – tên chương")
                continue
        if region == "ref" and p.where == "body" and _ref_region_ends(p, t) \
                and not RE_DEAN["chuong"].match(t):
            region = "text"            # vd. tiêu đề in hoa đậm/Heading sau danh mục tài liệu
        if region == "ref":
            # mục tài liệu tham khảo thường dài, kết thúc bằng dấu chấm -> KHÔNG dùng lưới an toàn
            # "giống câu văn thì thoát vùng" như mục lục; chỉ thoát khi gặp tiêu đề thật (ở trên).
            if p.where == "body" and not ref_like(t) and len(t) <= 60 and _REF_GROUP_RE.match(_norm_head(t)):
                definite(i, "other", "context", note="Tiêu đề nhóm tài liệu tham khảo")
            else:
                definite(i, "dean_tai_lieu" if p.where == "body" else "dean_table_cell", "context")
            continue
        if region == "appx":
            definite(i, "dean_phu_luc", "context")
            continue
        if region == "list":
            looks_like_front_matter_line = toc_like or len(t) <= 12 or p.where != "body"
            strong_content_signal = p.where == "body" and not toc_like and (
                dean_heading_level(t) is not None
                or (p.heading_level or 9) <= 4
                or len(t) > 200
                or (len(t) > 90 and t.rstrip().endswith((".", ";")))
            )
            if not looks_like_front_matter_line:
                front_matter_streak += 1
            else:
                front_matter_streak = 0
            # Thoát vùng ngay khi có tín hiệu chắc chắn (đề mục có số, style Heading, câu văn dài),
            # hoặc khi đã có 2 đoạn liên tiếp không còn giống dòng mục lục/danh mục/tài liệu –
            # tránh trường hợp không tìm được tiêu đề kế tiếp khiến cả phần nội dung bị lây nhãn.
            if strong_content_signal or front_matter_streak >= 2:
                region = "text"
                front_matter_streak = 0
                # rơi tiếp xuống các nhánh xử lý nội dung phía dưới, KHÔNG continue ở đây
            else:
                definite(i, "dean_toc_entry", "context")
                continue
        # ---- vùng nội dung ----
        if RE_DEAN["caption_figure"].match(t) and len(t) <= 300:
            definite(i, "dean_caption_figure")
            continue
        if RE_DEAN["caption_table"].match(t) and len(t) <= 300:
            definite(i, "dean_caption_table")
            continue
        if RE_DEAN["nguon"].match(t):
            definite(i, "dean_nguon")
            continue
        if p.where != "body" or p.zone_hint in ("data_table", "header_table", "signature_table"):
            definite(i, "dean_table_cell", "context")
            continue
        lvl = dean_heading_level(t)
        if lvl is None and p.heading_level and content_signal(t):
            # style (thường do file chuyển đổi/ABBYY) gắn cấp đề mục cho dòng liệt kê/câu văn
            definite(i, "dean_body", "context", conf=0.9,
                     note="Dòng liệt kê/câu văn mang cấp đề mục – đã coi là nội dung, không đưa vào mục lục")
            continue
        if lvl is None and p.heading_level and 2 <= p.heading_level <= 4:
            lvl = p.heading_level          # đề mục dùng style Heading 2–4 nhưng không gõ số
        if lvl is not None:
            role = f"dean_muc_{min(lvl, 4)}"
            sentence_like = len(t) > 200 or (t.rstrip().endswith((".", ";")) and len(t) > 90) \
                or (dean_heading_level(t) is None and _sentence_like(t))
            if sentence_like:
                ambiguous(i, [role, "dean_body"], "dean_body", "Giống câu văn nên coi là nội dung – cần kiểm tra",
                          conf=0.75)
            else:
                definite(i, role, "regex" if dean_heading_level(t) else "context")
            continue
        if p.heading_level == 1:
            # Outline level 1 đến từ STYLE (file chuyển đổi bằng ABBYY/PDF, template tự tạo hay gắn
            # outline level cho cả style nội dung) -> không tin tuyệt đối: câu văn vẫn là nội dung.
            if _sentence_like(t):
                definite(i, "dean_body", "context", conf=0.9,
                         note="Mang cấp đề mục 1 nhưng là câu văn – đã coi là đoạn nội dung")
            elif _is_caps(t) or RE_DEAN["chuong"].match(t) or (len(t) <= 120 and not _terminated(t)):
                definite(i, "dean_chuong", "context", note="Style Heading 1")
            else:
                ambiguous(i, ["dean_body", "dean_chuong"], "dean_body", conf=0.7,
                          note="Mang cấp đề mục 1 nhưng không giống tên chương – đã coi là nội dung")
            continue
        definite(i, "dean_body", "context", conf=0.9)
    return out


# ---------------------------------------------------------------------------
# Gợi ý chuẩn thể thức (NĐ 30 hay Đảng) dựa vào các đoạn ĐẦU văn bản, độc lập với
# chuẩn người dùng đang chọn — để cảnh báo khi có thể đã chọn nhầm nút "NĐ 30 / Đảng".
_PARTY_ORG_PHRASES = ("ĐẢNG ỦY", "ĐẢNG UỶ", "CHI BỘ", "TỈNH ỦY", "TỈNH UỶ", "THÀNH ỦY", "THÀNH UỶ",
                      "QUẬN ỦY", "QUẬN UỶ", "HUYỆN ỦY", "HUYỆN UỶ", "ĐẢNG BỘ",
                      "BAN CHẤP HÀNH TRUNG ƯƠNG", "BAN THƯỜNG VỤ", "BAN BÍ THƯ", "BỘ CHÍNH TRỊ")
_STD_HINT_SCAN_LIMIT = 15


def detect_standard_hint(ex: ExtractedDoc) -> dict:
    """Đoán văn bản có phải của Đảng hay không, chỉ dựa vào ~15 đoạn ĐẦU văn bản (quốc hiệu/tiêu đề
    Đảng, tên cơ quan, số ký hiệu) — KHÔNG đọc toàn văn, để tránh nhầm khi nội dung chỉ nhắc đến
    từ "Đảng" mà không phải văn bản do cấp ủy/tổ chức đảng ban hành. Trả về {"suggested": "dang"|
    "nd30"|None, "evidence": trích đoạn, "matched": dấu hiệu khớp}. Dùng để CẢNH BÁO, không tự
    đổi chuẩn — người dùng luôn là người quyết định cuối cùng."""
    n = 0
    for p in ex.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        n += 1
        if n > _STD_HINT_SCAN_LIMIT:
            break
        if RE_DANG["tieu_de"].match(t):
            return {"suggested": "dang", "evidence": t[:160], "matched": "ĐẢNG CỘNG SẢN VIỆT NAM"}
        if RE["quoc_hieu"].match(t):
            return {"suggested": "nd30", "evidence": t[:160], "matched": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"}
        up = t.upper()
        for phrase in _PARTY_ORG_PHRASES:
            if phrase in up:
                return {"suggested": "dang", "evidence": t[:160], "matched": phrase}
        if RE_DANG["so_ky_hieu"].match(t):
            return {"suggested": "dang", "evidence": t[:160], "matched": "Số ...-.../..."}
        if RE["so_ky_hieu"].match(t):
            return {"suggested": "nd30", "evidence": t[:160], "matched": "Số:"}
    return {"suggested": None, "evidence": "", "matched": ""}
