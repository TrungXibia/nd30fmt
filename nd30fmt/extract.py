"""Trích xuất định dạng HIỆU LỰC (effective) của từng đoạn/run trong file .docx.

Giá trị hiệu lực được tính theo chuỗi kế thừa của Word:
  run rPr -> character style (rStyle, basedOn...) -> paragraph style (pStyle, basedOn...)
  -> default paragraph style -> docDefaults.
Phông theo theme (asciiTheme=minorHAnsi...) được quy đổi theo theme1.xml.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from docx import Document
from docx.oxml.ns import qn as _qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from .core import alpha_caps

EMU_PER_CM = 360000
EMU_PER_MM = 36000
TWIPS_PER_CM = 566.929
TWIPS_PER_PT = 20

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

# qn() được gọi hàng trăm nghìn lần với văn bản dài -> nhớ đệm kết quả
qn = lru_cache(maxsize=None)(_qn)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _on(el) -> bool | None:
    """Giá trị toggle (w:b, w:i, w:caps): phần tử có mặt, val mặc định = true."""
    if el is None:
        return None
    v = el.get(qn("w:val"))
    if v is None:
        return True
    return v.lower() not in ("0", "false", "off", "none")


# ---------------------------------------------------------------------------
@dataclass
class RunInfo:
    text: str
    font_ascii: str | None
    font_hansi: str | None
    size: float | None
    bold: bool
    italic: bool
    caps: bool
    color: str | None
    underline: bool = False
    vert: str | None = None          # superscript | subscript
    char_spacing: float = 0.0        # giãn/nén khoảng cách chữ (pt; âm = nén)
    char_scale: float = 100.0        # co giãn độ rộng chữ (%)


@dataclass
class ParaInfo:
    pid: str
    idx: int
    text: str
    where: str                      # body | table
    table_idx: int | None = None
    row: int | None = None
    col: int | None = None
    ncols: int | None = None
    zone_hint: str = "body"         # header_table | signature_table | data_table | body
    style_id: str | None = None
    style_name: str | None = None
    num_label: str = ""
    align: str = "left"
    first_line_cm: float = 0.0
    left_indent_cm: float = 0.0
    before_pt: float = 0.0
    after_pt: float = 0.0
    line_rule: str = "auto"
    line_value: float = 1.0         # auto: bội số dòng; exact/atLeast: pt
    contextual: bool = False
    heading_level: int | None = None
    runs: list[RunInfo] = field(default_factory=list)
    element: Any = None             # w:p (không serialize)
    section_idx: int = 0
    next_is_table: bool = False
    has_drawing: bool = False
    page_break_before: bool = False

    # -------- thống kê theo ký tự --------
    def _chars(self):
        for r in self.runs:
            for ch in r.text:
                if not ch.isspace():
                    yield r, ch

    def ratio(self, attr: str) -> float:
        # đếm theo từng run (không lặp từng ký tự): số ký tự không phải khoảng trắng của run
        tot = hit = 0
        for r in self.runs:
            n = len(r.text) - sum(map(str.isspace, r.text))
            tot += n
            if getattr(r, attr):
                hit += n
        return hit / tot if tot else 0.0

    def caps_ratio(self) -> float:
        tot = up = 0
        for r in self.runs:
            n, u = alpha_caps(r.text)
            tot += n
            up += n if r.caps else u
        return up / tot if tot else 0.0

    def sizes(self) -> list[float | None]:
        return sorted({r.size for r in self.runs if r.text.strip()}, key=lambda x: (x is None, x or 0))

    def fonts(self) -> list[str | None]:
        out = set()
        for r in self.runs:
            if r.text.strip():
                out.add(r.font_ascii)
                if any(ord(c) > 127 for c in r.text):
                    out.add(r.font_hansi)
        return sorted(out, key=lambda x: (x is None, x or ""))

    def colors(self) -> list[str]:
        return sorted({(r.color or "auto") for r in self.runs if r.text.strip()})

    def to_json(self) -> dict:
        return {
            "id": self.pid, "idx": self.idx, "text": self.text, "where": self.where,
            "zone": self.zone_hint, "table_idx": self.table_idx, "row": self.row, "col": self.col,
            "style": self.style_name, "num_label": self.num_label, "align": self.align,
            "first_line_cm": round(self.first_line_cm, 2), "left_indent_cm": round(self.left_indent_cm, 2),
            "before_pt": self.before_pt, "after_pt": self.after_pt,
            "line_rule": self.line_rule, "line_value": round(self.line_value, 2),
            "sizes": self.sizes(), "fonts": self.fonts(), "colors": self.colors(),
            "bold_ratio": round(self.ratio("bold"), 2), "italic_ratio": round(self.ratio("italic"), 2),
            "caps_ratio": round(self.caps_ratio(), 2), "section": self.section_idx,
        }

    def preview_json(self) -> dict:
        """Dữ liệu đủ để vẽ lại đoạn trên trình duyệt."""
        return {
            "id": self.pid, "a": self.align, "fl": round(self.first_line_cm, 3), "li": round(self.left_indent_cm, 3),
            "sb": self.before_pt, "sa": self.after_pt, "lr": self.line_rule, "lv": round(self.line_value, 3),
            "nl": self.num_label, "img": self.has_drawing, "pb": self.page_break_before,
            "fd": self.element is not None and any(True for _ in self.element.iter(qn("w:fldChar"))),
            "r": [{"t": r.text, "f": r.font_hansi or r.font_ascii, "s": r.size, "b": r.bold, "i": r.italic,
                   "u": r.underline, "c": r.color, "k": r.caps, "v": r.vert} for r in self.runs],
        }


@dataclass
class SectionInfo:
    idx: int
    width_mm: float
    height_mm: float
    orientation: str
    top_mm: float
    bottom_mm: float
    left_mm: float
    right_mm: float
    title_pg: bool
    has_page_field_header: bool
    has_page_field_footer: bool
    page_field_align: str | None
    page_field_size: float | None
    has_tables: bool = False
    pg_start: int | None = None     # "Start at" của đánh số trang trong section (None = nối tiếp)

    def to_json(self) -> dict:
        return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
class StyleResolver:
    def __init__(self, doc):
        self.doc = doc
        self.styles_el = doc.styles.element
        self._by_id = {}
        for s in self.styles_el.findall(qn("w:style")):
            self._by_id[s.get(qn("w:styleId"))] = s
        self.default_para_style = None
        self.default_char_style = None
        for s in self.styles_el.findall(qn("w:style")):
            if s.get(qn("w:default")) in ("1", "true"):
                t = s.get(qn("w:type"))
                if t == "paragraph":
                    self.default_para_style = s.get(qn("w:styleId"))
                elif t == "character":
                    self.default_char_style = s.get(qn("w:styleId"))
        dd = self.styles_el.find(qn("w:docDefaults"))
        self.rpr_default = None
        self.ppr_default = None
        if dd is not None:
            rd = dd.find(qn("w:rPrDefault"))
            if rd is not None:
                self.rpr_default = rd.find(qn("w:rPr"))
            pd = dd.find(qn("w:pPrDefault"))
            if pd is not None:
                self.ppr_default = pd.find(qn("w:pPr"))
        self.theme_fonts = self._theme_fonts()

    def _theme_fonts(self) -> dict:
        fonts = {"minor": None, "major": None}
        try:
            theme_part = self.doc.part.part_related_by(RT.THEME)
            from lxml import etree
            root = etree.fromstring(theme_part.blob)
            for kind, tag in (("minor", "minorFont"), ("major", "majorFont")):
                el = root.find(f".//{{{A_NS}}}{tag}/{{{A_NS}}}latin")
                if el is not None:
                    fonts[kind] = el.get("typeface")
        except Exception:
            pass
        return fonts

    def style_name(self, sid: str | None) -> str | None:
        if not sid or sid not in self._by_id:
            return None
        n = self._by_id[sid].find(qn("w:name"))
        return n.get(qn("w:val")) if n is not None else sid

    def chain(self, sid: str | None) -> list:
        out, seen = [], set()
        while sid and sid in self._by_id and sid not in seen:
            seen.add(sid)
            s = self._by_id[sid]
            out.append(s)
            b = s.find(qn("w:basedOn"))
            sid = b.get(qn("w:val")) if b is not None else None
        return out

    # -- rPr chain cho 1 run --
    def rpr_chain(self, r_el, p_style_id: str | None, tbl_style: str | None = None) -> list:
        chain = []
        rpr = r_el.find(qn("w:rPr"))
        if rpr is not None:
            chain.append(rpr)
            rs = rpr.find(qn("w:rStyle"))
            if rs is not None:
                for s in self.chain(rs.get(qn("w:val"))):
                    x = s.find(qn("w:rPr"))
                    if x is not None:
                        chain.append(x)
        for s in self.chain(p_style_id or self.default_para_style):
            x = s.find(qn("w:rPr"))
            if x is not None:
                chain.append(x)
        for s in self.chain(tbl_style):          # style của bảng: sau style đoạn, trước docDefaults
            x = s.find(qn("w:rPr"))
            if x is not None:
                chain.append(x)
        if self.rpr_default is not None:
            chain.append(self.rpr_default)
        return chain

    def ppr_chain(self, p_el, tbl_style: str | None = None) -> tuple[list, str | None]:
        chain = []
        ppr = p_el.find(qn("w:pPr"))
        sid = None
        if ppr is not None:
            chain.append(ppr)
            ps = ppr.find(qn("w:pStyle"))
            if ps is not None:
                sid = ps.get(qn("w:val"))
        for s in self.chain(sid or self.default_para_style):
            x = s.find(qn("w:pPr"))
            if x is not None:
                chain.append(x)
        for s in self.chain(tbl_style):
            x = s.find(qn("w:pPr"))
            if x is not None:
                chain.append(x)
        if self.ppr_default is not None:
            chain.append(self.ppr_default)
        return chain, sid

    # -- tra cứu thuộc tính --
    @staticmethod
    def first(chain, tag):
        for el in chain:
            x = el.find(qn(tag))
            if x is not None:
                return x
        return None

    def font(self, chain, slot: str) -> str | None:
        for el in chain:
            rf = el.find(qn("w:rFonts"))
            if rf is None:
                continue
            theme = rf.get(qn(f"w:{slot}Theme"))
            if theme:
                return self.theme_fonts["major" if theme.startswith("major") else "minor"] or f"theme:{theme}"
            v = rf.get(qn(f"w:{slot}"))
            if v:
                return v
        return None


# ---------------------------------------------------------------------------
class NumberingRenderer:
    """Dựng lại nhãn số tự động (1., a), I., 1.1.) của danh sách Word."""

    def __init__(self, doc, resolver: StyleResolver):
        self.levels = {}   # (numId, ilvl) -> (fmt, lvlText, start)
        self.counters = {}
        self.resolver = resolver
        try:
            numbering = doc.part.numbering_part.element
        except Exception:
            return
        abstract = {}
        for an in numbering.findall(qn("w:abstractNum")):
            aid = an.get(qn("w:abstractNumId"))
            lv = {}
            for l in an.findall(qn("w:lvl")):
                il = int(l.get(qn("w:ilvl")))
                fmt = l.find(qn("w:numFmt"))
                txt = l.find(qn("w:lvlText"))
                st = l.find(qn("w:start"))
                lv[il] = (
                    fmt.get(qn("w:val")) if fmt is not None else "decimal",
                    txt.get(qn("w:val")) if txt is not None else "",
                    int(st.get(qn("w:val"))) if st is not None else 1,
                )
            abstract[aid] = lv
        for n in numbering.findall(qn("w:num")):
            nid = n.get(qn("w:numId"))
            a = n.find(qn("w:abstractNumId"))
            if a is not None and a.get(qn("w:val")) in abstract:
                for il, v in abstract[a.get(qn("w:val"))].items():
                    self.levels[(nid, il)] = v

    @staticmethod
    def _fmt(n: int, fmt: str) -> str:
        if fmt in ("lowerLetter", "upperLetter"):
            s = ""
            while n > 0:
                n, r = divmod(n - 1, 26)
                s = chr(97 + r) + s
            return s.upper() if fmt == "upperLetter" else s
        if fmt in ("lowerRoman", "upperRoman"):
            vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
            s = ""
            for v, sym in vals:
                while n >= v:
                    s += sym
                    n -= v
            return s.lower() if fmt == "lowerRoman" else s
        if fmt == "bullet":
            return "•"
        return str(n)

    def label(self, ppr_chain) -> tuple[str, int | None]:
        numpr = StyleResolver.first(ppr_chain, "w:numPr")
        if numpr is None:
            return "", None
        nid_el = numpr.find(qn("w:numId"))
        il_el = numpr.find(qn("w:ilvl"))
        if nid_el is None:
            return "", None
        nid = nid_el.get(qn("w:val"))
        il = int(il_el.get(qn("w:val"))) if il_el is not None else 0
        if nid == "0" or (nid, il) not in self.levels:
            return "", None
        fmt, txt, start = self.levels[(nid, il)]
        cnt = self.counters.setdefault(nid, {})
        cnt[il] = cnt.get(il, start - 1) + 1
        for deeper in [k for k in cnt if k > il]:
            del cnt[deeper]
        if fmt == "bullet":
            return "-", il
        out = txt
        for k in range(0, 9):
            if f"%{k + 1}" in out:
                lvl = self.levels.get((nid, k), ("decimal", "", 1))
                out = out.replace(f"%{k + 1}", self._fmt(cnt.get(k, lvl[2]), lvl[0]))
        return out.strip(), il


# ---------------------------------------------------------------------------
_SKIP_ANCESTORS = None


def iter_runs(p_el):
    """Các w:r thuộc đoạn, bỏ qua run nằm trong text box / bản fallback (VML)."""
    global _SKIP_ANCESTORS
    if _SKIP_ANCESTORS is None:
        _SKIP_ANCESTORS = {
            qn("w:txbxContent"),
            "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback",
            qn("w:del"),
        }
    for r in p_el.iter(qn("w:r")):
        a = r.getparent()
        ok = True
        while a is not None and a is not p_el:
            if a.tag in _SKIP_ANCESTORS:
                ok = False
                break
            a = a.getparent()
        if ok:
            yield r


def _para_text(p_el) -> str:
    return nfc("".join(_run_text(r) for r in iter_runs(p_el)))


def _run_text(r_el) -> str:
    parts = []
    for node in r_el:
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag == qn("w:br") and node.get(qn("w:type")) == "page":
            parts.append("\f")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
    return nfc("".join(parts))


def _has_page_field(container_el) -> bool:
    for f in container_el.iter(qn("w:fldSimple")):
        if "PAGE" in (f.get(qn("w:instr")) or "").upper():
            return True
    for t in container_el.iter(qn("w:instrText")):
        if re.search(r"\bPAGE\b", (t.text or "").upper()):
            return True
    return False


def _page_field_props(container_el, resolver: StyleResolver):
    """Căn lề + cỡ chữ của đoạn chứa trường PAGE (nếu có)."""
    for p in container_el.iter(qn("w:p")):
        if _has_page_field(p):
            chain, sid = resolver.ppr_chain(p)
            jc = StyleResolver.first(chain, "w:jc")
            align = _norm_align(jc.get(qn("w:val")) if jc is not None else "left")
            size = None
            for r in p.iter(qn("w:r")):
                rc = resolver.rpr_chain(r, sid)
                sz = StyleResolver.first(rc, "w:sz")
                if sz is not None:
                    size = int(sz.get(qn("w:val"))) / 2
                    break
            return align, size
    return None, None


def _norm_align(v: str | None) -> str:
    v = (v or "left").lower()
    return {"both": "justify", "distribute": "justify", "start": "left", "end": "right",
            "lowkashida": "justify", "mediumkashida": "justify", "highkashida": "justify",
            "thaidistribute": "justify"}.get(v, v)


# ---------------------------------------------------------------------------
class ExtractedDoc:
    def __init__(self, path: str):
        self.path = path
        self.doc = Document(path)
        self.resolver = StyleResolver(self.doc)
        self.numbering = NumberingRenderer(self.doc, self.resolver)
        self.paragraphs: list[ParaInfo] = []
        self.sections: list[SectionInfo] = []
        self.tables_meta: list[dict] = []
        self.blocks: list[dict] = []      # cấu trúc khối cho preview
        self._extract()

    def preview_json(self) -> dict:
        tz = {t["idx"]: t.get("zone", "data_table") for t in self.tables_meta}
        blocks = []
        for b in self.blocks:
            if b["t"] == "tbl":
                b = dict(b, zone=tz.get(b["idx"], "data_table"))
            blocks.append(b)
        return {"sections": [s.to_json() for s in self.sections], "blocks": blocks,
                "paras": {p.pid: p.preview_json() for p in self.paragraphs}}

    # ---- đoạn văn ----
    def _para_info(self, p_el, where: str, section_idx: int, tbl_style: str | None = None, **kw) -> ParaInfo:
        chain, sid = self.resolver.ppr_chain(p_el, tbl_style)
        jc = StyleResolver.first(chain, "w:jc")
        # thụt lề: gộp theo thứ tự ưu tiên từng thuộc tính
        first_line = 0.0
        left = 0.0
        got_fl = got_left = False
        for el in chain:
            x = el.find(qn("w:ind"))
            if x is None:
                continue
            if not got_fl:
                if x.get(qn("w:hanging")) is not None:
                    first_line = -int(x.get(qn("w:hanging"))) / TWIPS_PER_CM
                    got_fl = True
                elif x.get(qn("w:firstLine")) is not None:
                    first_line = int(x.get(qn("w:firstLine"))) / TWIPS_PER_CM
                    got_fl = True
            if not got_left:
                v = x.get(qn("w:left")) or x.get(qn("w:start"))
                if v is not None:
                    left = int(v) / TWIPS_PER_CM
                    got_left = True
        before = after = None
        line_rule, line_val = None, None
        for el in chain:
            sp = el.find(qn("w:spacing"))
            if sp is None:
                continue
            if before is None and sp.get(qn("w:before")) is not None:
                before = int(sp.get(qn("w:before"))) / TWIPS_PER_PT
            if before is None and _on_attr(sp.get(qn("w:beforeAutospacing"))):
                before = 14.0
            if after is None and sp.get(qn("w:after")) is not None:
                after = int(sp.get(qn("w:after"))) / TWIPS_PER_PT
            if after is None and _on_attr(sp.get(qn("w:afterAutospacing"))):
                after = 14.0
            if line_val is None and sp.get(qn("w:line")) is not None:
                line_rule = sp.get(qn("w:lineRule")) or "auto"
                raw = int(sp.get(qn("w:line")))
                line_val = raw / 240 if line_rule == "auto" else raw / TWIPS_PER_PT
        ctx = StyleResolver.first(chain, "w:contextualSpacing")
        outline = StyleResolver.first(chain, "w:outlineLvl")
        label, _lvl = self.numbering.label(chain)
        sname = self.resolver.style_name(sid or self.resolver.default_para_style)
        hl = None
        if sname:
            m = re.match(r"(?i)heading\s*(\d)", sname)
            if m:
                hl = int(m.group(1))
        if hl is None and outline is not None:
            try:
                ol = int(outline.get(qn("w:val")))
                if ol < 9:
                    hl = ol + 1
            except (TypeError, ValueError):
                pass
        runs = []
        for r_el in iter_runs(p_el):
            txt = _run_text(r_el)
            if not txt:
                continue
            rc = self.resolver.rpr_chain(r_el, sid, tbl_style)
            sz = StyleResolver.first(rc, "w:sz")
            col = StyleResolver.first(rc, "w:color")
            u_el = StyleResolver.first(rc, "w:u")
            va = StyleResolver.first(rc, "w:vertAlign")
            csp = StyleResolver.first(rc, "w:spacing")
            csc = StyleResolver.first(rc, "w:w")
            runs.append(RunInfo(
                text=txt,
                font_ascii=self.resolver.font(rc, "ascii"),
                font_hansi=self.resolver.font(rc, "hAnsi"),
                size=(int(sz.get(qn("w:val"))) / 2) if sz is not None else 10.0,
                bold=bool(_on(StyleResolver.first(rc, "w:b"))),
                italic=bool(_on(StyleResolver.first(rc, "w:i"))),
                caps=bool(_on(StyleResolver.first(rc, "w:caps"))),
                color=(col.get(qn("w:val")) if col is not None else None),
                underline=u_el is not None and (u_el.get(qn("w:val")) or "single") != "none",
                vert=(va.get(qn("w:val")) if va is not None and va.get(qn("w:val")) != "baseline" else None),
                char_spacing=_int_attr(csp, 0) / 20,
                char_scale=float(_int_attr(csc, 100)),
            ))
        pbb = StyleResolver.first(chain, "w:pageBreakBefore")
        has_drawing = any(True for _ in p_el.iter(qn("w:drawing"))) or any(True for _ in p_el.iter(qn("w:pict")))
        info = ParaInfo(
            pid=f"P{len(self.paragraphs) + 1:04d}",
            idx=len(self.paragraphs),
            text=_para_text(p_el),
            where=where,
            style_id=sid,
            style_name=sname,
            num_label=label,
            align=_norm_align(jc.get(qn("w:val")) if jc is not None else "left"),
            first_line_cm=first_line,
            left_indent_cm=left,
            before_pt=before or 0.0,
            after_pt=after or 0.0,
            line_rule=line_rule or "auto",
            line_value=line_val if line_val is not None else 1.0,
            contextual=bool(_on(ctx)),
            heading_level=hl,
            runs=runs,
            element=p_el,
            section_idx=section_idx,
            has_drawing=has_drawing,
            page_break_before=bool(_on(pbb)),
            **kw,
        )
        return info

    def _walk_table(self, tbl_el, section_idx: int, table_idx: int, grid_rows=None):
        """Duyệt bảng; trả về (số cột, số dòng, cấu trúc dòng/ô cho preview)."""
        rows = tbl_el.findall(qn("w:tr"))
        ncols = 0
        struct = []
        tpr = tbl_el.find(qn("w:tblPr"))
        ts = tpr.find(qn("w:tblStyle")) if tpr is not None else None
        tbl_style = ts.get(qn("w:val")) if ts is not None else None
        for ri, tr in enumerate(rows):
            cells = tr.findall(qn("w:tc"))
            ncols = max(ncols, len(cells))
            row_s = []
            for ci, tc in enumerate(cells):
                w_cm, span, vmerge = None, 1, None
                tcpr = tc.find(qn("w:tcPr"))
                if tcpr is not None:
                    tcw = tcpr.find(qn("w:tcW"))
                    if tcw is not None and (tcw.get(qn("w:type")) in (None, "dxa")) and tcw.get(qn("w:w")):
                        try:
                            w_cm = round(int(tcw.get(qn("w:w"))) / TWIPS_PER_CM, 2)
                        except ValueError:
                            pass
                    gs = tcpr.find(qn("w:gridSpan"))
                    if gs is not None:
                        span = int(gs.get(qn("w:val")) or 1)
                    vm = tcpr.find(qn("w:vMerge"))
                    if vm is not None:
                        vmerge = vm.get(qn("w:val")) or "continue"
                pids = []
                for child in tc:
                    if child.tag == qn("w:p"):
                        info = self._para_info(child, "table", section_idx, tbl_style, table_idx=table_idx,
                                               row=ri, col=ci, ncols=len(cells))
                        self.paragraphs.append(info)
                        pids.append(info.pid)
                    elif child.tag == qn("w:tbl"):
                        first = len(self.paragraphs)
                        self._walk_table(child, section_idx, table_idx)
                        pids.extend(p.pid for p in self.paragraphs[first:])
                row_s.append({"w": w_cm, "span": span, "vm": vmerge, "pids": pids})
            struct.append(row_s)
        return ncols, len(rows), struct

    @staticmethod
    def _blocks(container):
        """Các khối cấp thân văn bản (w:p, w:tbl), đi xuyên qua content control (w:sdt) và customXml."""
        out = []
        for child in container:
            if child.tag in (qn("w:p"), qn("w:tbl")):
                out.append(child)
            elif child.tag == qn("w:sdt"):
                content = child.find(qn("w:sdtContent"))
                if content is not None:
                    out.extend(ExtractedDoc._blocks(content))
            elif child.tag == qn("w:customXml"):
                out.extend(ExtractedDoc._blocks(child))
        return out

    def _extract(self):
        body = self.doc.element.body
        section_idx = 0
        table_idx = 0
        children = self._blocks(body)
        for i, child in enumerate(children):
            if child.tag == qn("w:p"):
                info = self._para_info(child, "body", section_idx)
                nxt = children[i + 1] if i + 1 < len(children) else None
                info.next_is_table = nxt is not None and nxt.tag == qn("w:tbl")
                self.paragraphs.append(info)
                self.blocks.append({"t": "p", "id": info.pid})
                ppr = child.find(qn("w:pPr"))
                if ppr is not None and ppr.find(qn("w:sectPr")) is not None:
                    section_idx += 1
                    self.blocks.append({"t": "sect", "idx": section_idx})
            elif child.tag == qn("w:tbl"):
                first = len(self.paragraphs)
                ncols, nrows, struct = self._walk_table(child, section_idx, table_idx)
                self.tables_meta.append({"idx": table_idx, "first_para": first,
                                         "last_para": len(self.paragraphs) - 1,
                                         "ncols": ncols, "nrows": nrows, "section": section_idx})
                self.blocks.append({"t": "tbl", "idx": table_idx, "rows": struct})
                table_idx += 1
        # --- section ---
        for si, sec in enumerate(self.doc.sections):
            hdr_el = sec.header._element if not sec.header.is_linked_to_previous else None
            ftr_el = sec.footer._element if not sec.footer.is_linked_to_previous else None
            # nếu liên kết với section trước -> kế thừa kết quả của section trước
            prev = self.sections[-1] if self.sections else None
            has_h = _has_page_field(hdr_el) if hdr_el is not None else (prev.has_page_field_header if prev else False)
            has_f = _has_page_field(ftr_el) if ftr_el is not None else (prev.has_page_field_footer if prev else False)
            align = size = None
            if hdr_el is not None and has_h:
                align, size = _page_field_props(hdr_el, self.resolver)
            elif prev is not None and has_h:
                align, size = prev.page_field_align, prev.page_field_size
            self.sections.append(SectionInfo(
                idx=si,
                width_mm=(sec.page_width or 0) / EMU_PER_MM,
                height_mm=(sec.page_height or 0) / EMU_PER_MM,
                orientation="landscape" if (sec.page_width or 0) > (sec.page_height or 0) else "portrait",
                top_mm=(sec.top_margin or 0) / EMU_PER_MM,
                bottom_mm=(sec.bottom_margin or 0) / EMU_PER_MM,
                left_mm=(sec.left_margin or 0) / EMU_PER_MM,
                right_mm=(sec.right_margin or 0) / EMU_PER_MM,
                title_pg=bool(sec.different_first_page_header_footer),
                has_page_field_header=has_h,
                has_page_field_footer=has_f,
                page_field_align=align,
                page_field_size=size,
                has_tables=any(t["section"] == si for t in self.tables_meta),
                pg_start=_pg_start(sec),
            ))


def _int_attr(el, default: int) -> int:
    if el is None:
        return default
    try:
        return int(float(el.get(qn("w:val"))))
    except (TypeError, ValueError):
        return default


def _pg_start(sec) -> int | None:
    pt = sec._sectPr.find(qn("w:pgNumType"))
    if pt is None or pt.get(qn("w:start")) is None:
        return None
    try:
        return int(pt.get(qn("w:start")))
    except ValueError:
        return None


def _on_attr(v) -> bool:
    return v is not None and v.lower() in ("1", "true", "on")


def extract(path: str) -> ExtractedDoc:
    return ExtractedDoc(path)
