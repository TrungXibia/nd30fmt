"""Giải mã âm tiết gõ Telex chưa chuyển thành chữ có dấu (Vieejt -> Việt, dduowcj -> được). Dùng chung cho bộ sửa chính tả
(vspell.py) và bộ nhận diện chữ Anh (langid.py: chữ Telex sót là chữ Việt, không phải tiếng Anh)."""
from __future__ import annotations

import re
import unicodedata

from . import vphon

_TELEX_TONE = {"s": "́", "f": "̀", "r": "̉", "x": "̃", "j": "̣"}
_TELEX_RE = re.compile(r"^[a-zA-Z]+$")


def _telex_core(s: str):
    out, i, signals = "", 0, 0
    while i < len(s):
        c = s[i]
        n = s[i + 1] if i + 1 < len(s) else ""
        if c == "d" and n == "d":
            out += "đ"; i += 2; signals += 1; continue
        if c in "aeo" and n == c:
            out += {"a": "â", "e": "ê", "o": "ô"}[c]; i += 2; signals += 1; continue
        if c in "aou" and n == "w":
            out += {"a": "ă", "o": "ơ", "u": "ư"}[c]; i += 2; signals += 1; continue
        if c in "wfjz":
            return None
        out += c
        i += 1
    return out, signals


_CODAS = ("", "c", "ch", "m", "n", "ng", "nh", "p", "t")


def telex_decode(w: str) -> tuple[str, int] | None:
    """Giải mã một âm tiết gõ Telex chưa chuyển (Vieejt -> Việt, dduowcj -> được). Trả về (chữ, số dấu hiệu) hoặc None."""
    if not _TELEX_RE.match(w):
        return None
    s = w.lower()
    cands = []
    for p, ch in enumerate(s):
        if ch in _TELEX_TONE and p > 0 and s[p - 1] in "aeiouyw" and s[p + 1:] in _CODAS:
            cands.append((s[:p] + s[p + 1:], _TELEX_TONE[ch], 1))
    cands.append((s, "", 0))
    for body, tone, bonus in cands:
        r = _telex_core(body)
        if r is None:
            continue
        out, sig = r
        sig += bonus
        if sig == 0:
            continue
        base = unicodedata.normalize("NFC", out)
        if tone:
            base = vphon.place_tone(base, vphon._TONES[tone])
        if vphon.valid_syllable(base):
            return base, sig
    return None
