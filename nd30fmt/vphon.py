"""Quy tắc âm vị chính tả tiếng Việt: một âm tiết có "hợp lệ" hay không, đặt dấu thanh đúng chưa.

Không dùng dữ liệu thống kê: chỉ là bảng phụ âm đầu, vần (rime) và quy tắc đi kèm. Dùng cho bộ sửa chính tả Word
(vspell.py) để phân biệt chữ Việt gõ sai ("nghiã", "đươc", "kêt") với tên riêng/chữ nước ngoài (không đụng tới).
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache

_TONES = {"́": 1, "̀": 2, "̉": 3, "̃": 4, "̣": 5}   # sắc, huyền, hỏi, ngã, nặng
VOWELS = set("aăâeêioôơuưy")
VI_LETTERS = set("abcdđeghiklmnopqrstuvxy") | set("ăâêôơư")     # không có f j w z

# phụ âm đầu (tách theo thứ tự dài trước); "gi" và "qu" xử lý riêng
ONSETS = ("ngh", "ng", "nh", "ph", "th", "tr", "ch", "gh", "kh", "b", "c", "d", "đ", "g", "h", "k", "l", "m", "n",
          "p", "r", "s", "t", "v", "x")

_RIMES_TXT = """
a ac ach ai am an ang anh ao ap at au ay
ăc ăm ăn ăng ăp ăt
âc âm ân âng âp ât âu ây
e ec em en eng eo ep et
ê êch êm ên ênh êp êt êu
i ia ich im in inh ip it iu
iêc iêm iên iêng iêp iêt iêu
yêm yên yêng yêt yêu
o oc oi om on ong op ot
oa oac oach oai oam oan oang oanh oao oap oat oay
oăc oăm oăn oăng oăt
oe oen oeo oet
ô ôc ôi ôm ôn ông ôp ôt
ơ ơi ơm ơn ơp ơt
u uc ui um un ung up ut
ua uôc uôi uôm uôn uông uôt
uâ uân uât uâng uây
uê uêch uênh uêu
uy uya uych uyn uynh uyp uyt uyu uyên uyêt uyêu
uơ
ư ưa ưc ưi ưm ưng ưt ưu
ươc ươi ươm ươn ương ươp ươt ươu
y
"""
RIMES = frozenset(_RIMES_TXT.split())
# vần có "iê/uô/ươ" viết thành ia/ua/ưa khi không có âm cuối; ia/ua/ưa đã nằm trong RIMES
STOP_CODAS = ("c", "ch", "p", "t")     # vần kết thúc bằng p t c ch chỉ mang thanh sắc hoặc nặng


@lru_cache(maxsize=200000)
def split_tone(s: str) -> tuple[str, int]:
    """'hoà' -> ('hoa', 2): phần chữ (giữ dấu mũ/móc/trăng) và thanh (0 = không dấu)."""
    tone = 0
    out = []
    for c in unicodedata.normalize("NFD", s):
        if c in _TONES:
            tone = _TONES[c]
        else:
            out.append(c)
    return unicodedata.normalize("NFC", "".join(out)), tone


def parse(base: str):
    """Tách (âm đầu, vần) từ phần chữ đã bỏ thanh; None nếu không tách được."""
    if not base:
        return None
    if base.startswith("qu") and len(base) > 2 and base[2] in VOWELS:
        return "qu", base[2:]
    if base.startswith("gi") and len(base) > 2 and base[2] in VOWELS:
        return "gi", base[2:]
    for o in ONSETS:
        if base.startswith(o):
            rest = base[len(o):]
            if rest and rest[0] in VOWELS:
                return o, rest
    if base[0] in VOWELS:
        return "", base
    return None


def _onset_vowel_ok(onset: str, rime: str) -> bool:
    """c/k, g/gh, ng/ngh phụ thuộc nguyên âm đứng sau (i, e, ê, y là 'nguyên âm trước')."""
    front = rime[0] in "ieêy"
    if onset in ("k", "gh", "ngh"):
        return front
    if onset == "g":                       # g + i = "gi" (gì, gìn); g + e/ê/y phải viết gh
        return not (rime[0] in "eêy")
    if onset in ("c", "ng"):
        return not front
    return True


@lru_cache(maxsize=200000)
def valid_syllable(word: str) -> bool:
    """Âm tiết (chữ thường, NFC, có hoặc không dấu thanh) có hợp quy tắc chính tả tiếng Việt không."""
    base, tone = split_tone(word.lower())
    p = parse(base)
    if p is None:
        return False
    onset, rime = p
    if rime not in RIMES:
        return False
    if not _onset_vowel_ok(onset, rime):
        return False
    if rime.endswith(STOP_CODAS) and tone not in (1, 5):
        return False
    # "gi" + i hoặc "qu" + u/o đã bị loại ở parse (không có vần 'ii', 'quu')
    return True


@lru_cache(maxsize=200000)
def looks_vietnamese(word: str) -> bool:
    """Toàn chữ cái tiếng Việt (không có f j w z, không lẫn số/ký hiệu)."""
    base, _ = split_tone(word.lower())
    return bool(base) and all(c in VI_LETTERS for c in base)


def tone_positions(word: str) -> list[int]:
    nf = unicodedata.normalize("NFC", word)
    pos = []
    for i, c in enumerate(nf):
        if any(m in _TONES for m in unicodedata.normalize("NFD", c)):
            pos.append(i)
    return pos


def _nucleus_indices(base: str) -> list[int]:
    idx = [i for i, c in enumerate(base) if c in VOWELS]
    if base.startswith("qu") and len(idx) > 1 and idx[0] == 1:
        idx = idx[1:]
    if base.startswith("gi") and len(idx) > 1 and idx[0] == 1:
        idx = idx[1:]
    return idx


@lru_cache(maxsize=200000)
def correct_tone_index(base: str, style: str = "old") -> int:
    """Vị trí đặt dấu thanh. style 'old': hòa, thủy; 'new': hoà, thuỷ (chỉ khác nhau ở vần oa, oe, uy không có âm cuối)."""
    idx = _nucleus_indices(base)
    if not idx:
        return -1
    for i in reversed(idx):
        if base[i] in "êơâăô":
            return i
    for i in idx:
        if base[i] == "ư":
            return i
    closed = idx[-1] < len(base) - 1
    if closed or len(idx) == 1:
        return idx[-1]
    if style == "new" and len(idx) == 2 and base[idx[0]] in "ou" and base[idx[1]] in "aey" and (
            base[idx[0]] + base[idx[1]] in ("oa", "oe", "uy")):
        return idx[1]
    return idx[1] if len(idx) >= 3 else idx[0]


@lru_cache(maxsize=200000)
def place_tone(base: str, tone: int, style: str = "old") -> str:
    if not tone:
        return base
    i = correct_tone_index(base, style)
    if i < 0:
        return base
    mark = {v: k for k, v in _TONES.items()}[tone]
    return unicodedata.normalize("NFC", base[:i + 1] + mark + base[i + 1:])


@lru_cache(maxsize=200000)
def tone_style(word: str) -> str | None:
    """'old' | 'new' | 'both' (hai kiểu trùng nhau) | 'bad' (dấu đặt sai chỗ) | None (không có dấu thanh)."""
    base, tone = split_tone(word.lower())
    if not tone:
        return None
    pos = tone_positions(word)
    if len(pos) != 1:
        return "bad"
    old = correct_tone_index(base, "old")
    new = correct_tone_index(base, "new")
    # vị trí trong chuỗi có dấu = vị trí trong chuỗi bỏ dấu (mỗi ký tự NFC là một ô)
    here = pos[0]
    if old == new:
        return "both" if here == old else "bad"
    if here == old:
        return "old"
    if here == new:
        return "new"
    return "bad"
