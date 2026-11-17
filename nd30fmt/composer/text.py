"""Tiện ích văn bản: đo độ dài chữ Times New Roman, tách rich-text (b/i/u), đánh số."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from html.parser import HTMLParser

from .schema import TEMPLATE_DIR


@lru_cache(maxsize=1)
def _metrics() -> dict:
    return json.loads((TEMPLATE_DIR / "font_metrics_tnr.json").read_text(encoding="utf-8"))["fonts"]


def text_width_pt(text: str, size: float, bold: bool = False, italic: bool = False) -> float:
    """Độ dài dòng chữ (pt) theo bảng độ rộng ký tự Liberation Serif (tương thích số đo Times New Roman)."""
    style = ("bold" if bold else "") + ("italic" if italic else "") or "regular"
    font = _metrics()[style]
    widths, default = font["widths"], font["default"]
    total = 0
    for ch in text:
        w = widths.get(ch)
        if w is None:
            import unicodedata
            base = unicodedata.normalize("NFD", ch)[:1]
            w = widths.get(base, default)
        total += w
    return total * size / 1000.0


def wrap_width_pt(text: str, size: float, bold: bool, italic: bool, max_width: float) -> tuple[float, int]:
    """(độ dài dòng dài nhất, số dòng) khi ngắt theo từ trong độ rộng max_width."""
    longest, lines = 0.0, 0
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            lines += 1
            continue
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cur and text_width_pt(cand, size, bold, italic) > max_width:
                longest = max(longest, text_width_pt(cur, size, bold, italic))
                lines += 1
                cur = w
            else:
                cur = cand
        longest = max(longest, text_width_pt(cur, size, bold, italic))
        lines += 1
    return min(longest, max_width), max(lines, 1)


# ------------------------------------------------------------------------------------ rich text
class _Rich(HTMLParser):
    TAGS = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.runs: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.runs.append({"br": True})
        elif tag in self.TAGS:
            self.stack.append(self.TAGS[tag])
        elif tag in ("div", "p") and self.runs:
            self.runs.append({"br": True})

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.runs.append({"br": True})

    def handle_endtag(self, tag):
        if tag in self.TAGS and self.TAGS[tag] in self.stack:
            idx = len(self.stack) - 1 - self.stack[::-1].index(self.TAGS[tag])
            self.stack.pop(idx)

    def handle_data(self, data):
        if not data:
            return
        data = data.replace("\xa0", " ")
        self.runs.append({"t": data, "b": "b" in self.stack, "i": "i" in self.stack, "u": "u" in self.stack})


def parse_rich(html: str | None) -> list[dict]:
    """HTML đơn giản (b/strong, i/em, u, br) -> danh sách run; bỏ mọi thẻ khác (an toàn XSS)."""
    if not html:
        return []
    p = _Rich()
    p.feed(str(html))
    p.close()
    runs = []
    for r in p.runs:
        if "t" in r and runs and "t" in runs[-1] and all(runs[-1][k] == r[k] for k in ("b", "i", "u")):
            runs[-1]["t"] += r["t"]
        else:
            runs.append(r)
    return runs


def split_lines(runs: list[dict]) -> list[list[dict]]:
    """Tách run theo <br> thành các dòng (mỗi dòng = một đoạn Word riêng)."""
    lines: list[list[dict]] = [[]]
    for r in runs:
        if r.get("br"):
            lines.append([])
        else:
            lines[-1].append(r)
    return lines


def runs_text(runs: list[dict]) -> str:
    return "".join(r.get("t", "") for r in runs if not r.get("br"))


def strip_runs(runs: list[dict]) -> list[dict]:
    """Bỏ khoảng trắng thừa ở đầu/cuối đoạn và gộp khoảng trắng liên tiếp."""
    out = [dict(r) for r in runs if r.get("t")]
    for r in out:
        r["t"] = re.sub(r"[ \t]+", " ", r["t"])
    while out and not out[0]["t"].strip():
        out.pop(0)
    while out and not out[-1]["t"].strip():
        out.pop()
    if out:
        out[0]["t"] = out[0]["t"].lstrip()
        out[-1]["t"] = out[-1]["t"].rstrip()
    return out


def clean_text(value) -> str:
    """Chuẩn hoá trường text: bỏ khoảng trắng đầu/cuối, gộp khoảng trắng; giữ xuống dòng."""
    if value is None:
        return ""
    lines = [re.sub(r"[ \t\xa0]+", " ", x).strip() for x in str(value).replace("\r", "").split("\n")]
    return "\n".join(lines).strip("\n")


def clean_list(value) -> list[str]:
    if isinstance(value, str):
        value = value.split("\n")
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        s = clean_text(v)
        s = re.sub(r"^[-–•]\s*", "", s)
        if s:
            out.append(s)
    return out


def roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


VN_LETTERS = "abcdđeghiklmnopqrstuvxy"


def letter(n: int) -> str:
    """Điểm theo bảng chữ cái tiếng Việt (PL I Mục II.6.đ): a, b, c, d, đ, e, g, h, i, k, l, m, n, ..."""
    if n <= len(VN_LETTERS):
        return VN_LETTERS[n - 1]
    return VN_LETTERS[(n - 1) // len(VN_LETTERS) - 1] + VN_LETTERS[(n - 1) % len(VN_LETTERS)]


def pad_number(value: str, pad: int = 2) -> str:
    v = str(value or "").strip()
    return v.zfill(pad) if v.isdigit() and len(v) < pad else v


def upper_vn(text: str) -> str:
    return text.upper()
