"""Sửa lỗi chính tả tiếng Việt cho văn bản gõ tay (Word) – chạy hoàn toàn trên máy chủ, không gửi văn bản ra ngoài.

Khác với vnfix.py (khôi phục dấu cho chữ do OCR sinh ra), văn bản Word thường đã đủ dấu; lỗi là gõ nhầm. Bộ sửa
chia làm các nhóm, mỗi nhóm có mức tin cậy riêng; chỉ nhóm "chắc chắn" được ghi thẳng vào file, phần còn lại chỉ báo:

  nfc        chữ tổ hợp (e + dấu rời) -> chữ dựng sẵn; không nhìn thấy khác biệt, không tô màu
  space      hai dấu cách liền giữa chữ, dấu cách trước dấu câu, thiếu dấu cách sau , ; : . ; không tô màu
  dup        lặp từ chức năng ("của của", "và và")
  placement  dấu thanh đặt sai nguyên âm ("nghiã" -> "nghĩa", "tiễn" không bị đụng vì hợp lệ)
  tone       âm tiết không hợp quy tắc chính tả ("đươc", "kêt", "nghiều") -> âm tiết gần nhất hợp ngữ cảnh
  context    âm tiết hợp lệ nhưng sai theo ngữ cảnh ("chia sẽ" -> "chia sẻ"); ngưỡng cao
  telex      còn sót phím Telex ("Vieejt" -> "Việt")
  pair       danh mục cặp sai–đúng chắc chắn ("sử lý" -> "xử lý", "bổ xung" -> "bổ sung")
  style      cùng văn bản lẫn hai cách viết ("kỹ"/"kĩ", "hòa"/"hoà") -> theo cách dùng nhiều hơn

Không đụng tới: tên riêng không có trong từ vựng, viết tắt, chữ nước ngoài, số hiệu/ký hiệu văn bản (30/2020/NĐ-CP),
đường dẫn/email, chữ dính "-", "/", "_", ".", chữ trong trường tự động của Word (xem spellword.py).
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from functools import lru_cache

from . import core, langid, vphon
from .telex import telex_decode
from .mdlib import vnfix

# ------------------------------------------------------------------ tham số (chỉnh bằng đo trên văn bản chưa từng thấy)
P_TONE_INVALID = 1.5        # đổi dấu/dấu thanh của âm tiết KHÔNG hợp lệ
P_EDIT_INVALID = 4.5        # sửa 1 chữ cái (thiếu/thừa/đảo/nhầm) của âm tiết không hợp lệ
TONE_RATIO = 20             # sửa dấu/thanh chỉ khi dạng đúng phổ biến gấp ngần này lần dạng gõ
EDIT_MAX_ORIG = 12          # sửa chữ cái chỉ khi dạng gõ gần như chưa từng thấy trong kho (gen, top, Iran là chữ thật)
EDIT_MIN_CAND = 300         # và dạng đúng phải phổ biến
RARE_COUNT = 3              # âm tiết hợp lệ nhưng gần như chưa từng thấy: xét như chữ gõ sai
P_EDIT_RARE = 6.5           # sửa 1 chữ cái của âm tiết hợp lệ nhưng hiếm
P_CONTEXT = 9.0             # đổi âm tiết đã hợp lệ sang âm tiết khác cùng khung chữ
INVALID_COST = 5.0          # phạt thêm cho âm tiết không hợp lệ giữ nguyên
THRESH = {"tone": 6.0, "edit": 22.0, "edit_rare": 24.0, "context": 12.0}
WIDE = {"tone": 0.0, "edit": 12.0, "edit_rare": 16.0, "context": 6.0}   # mức "rộng": thêm các chỗ nghi ngờ có gợi ý
ASCII_EXTRA = 6.0           # chữ không dấu hoàn toàn: có thể là tiếng nước ngoài/tên không dấu, đòi chắc chắn hơn
MARGIN_SURE = 3.0           # phần lợi còn lại sau khi trừ phạt để coi là "chắc chắn"
MARGIN_SURE_CONTEXT = 5.0
MIN_CAND_COUNT = 30         # âm tiết trong từ vựng phải xuất hiện ít nhất ngần này lần mới được làm ứng viên
OOV_VALID_LOGP = math.log(15 / 52_000_000)   # âm tiết hợp lệ nhưng chưa có trong từ vựng
UNK_LOGP = math.log(1e-9)
MAX_TOKEN = 7
KEEP_CAPS = True            # tên riêng (viết hoa không ở đầu câu) không có trong từ vựng: giữ nguyên

_TOK = re.compile(r"[^\W\d_]+")
_ALPHABET = "abcdeghiklmnopqrstuvxy"
_SENT_END = re.compile(r"[.!?:;]\s*$|[\n\t\f\v]")

# từ chức năng có thể bị gõ lặp (từ láy hợp lệ như "ngày ngày", "dần dần" không nằm trong danh sách)
_DUP_WORDS = frozenset("""của và các những để với trong được cho có này đó thì mà bởi tại theo về đã sẽ đang
nên cũng hoặc nhưng""".split())

# cặp sai -> đúng chắc chắn (so khớp theo từ/cụm, không phân biệt hoa thường, giữ kiểu viết hoa)
PAIRS = {
    "sử lý": "xử lý", "sử lí": "xử lí", "xử dụng": "sử dụng", "xữ dụng": "sử dụng", "sữ dụng": "sử dụng",
    "sát nhập": "sáp nhập", "thăm quan": "tham quan", "nghành": "ngành", "ngề nghiệp": "nghề nghiệp",
    "bổ xung": "bổ sung", "bỏ sung": "bổ sung", "chính xát": "chính xác", "chặc chẽ": "chặt chẽ",
    "trao dồi": "trau dồi", "xuất xắc": "xuất sắc", "sơ xuất": "sơ suất", "suất xứ": "xuất xứ", "xuất sứ": "xuất xứ",
    "dỏ ràng": "rõ ràng", "rỏ ràng": "rõ ràng", "rỏ": "rõ", "lảng phí": "lãng phí", "ưu thê": "ưu thế",
    "giám xát": "giám sát", "vướn mắc": "vướng mắc", "vướng mắt": "vướng mắc", "thông qua": "thông qua",
    "phương hướng": "phương hướng", "khẩn trương": "khẩn trương", "trương trình": "chương trình",
    "tiến độ": "tiến độ", "dự án": "dự án", "kế hoặc": "kế hoạch", "kế hoạc": "kế hoạch", "quy hoặch": "quy hoạch",
    "triễn khai": "triển khai", "phát triễn": "phát triển", "phát triễn": "phát triển", "đẩy mạnh": "đẩy mạnh",
    "cơ cấu tổ chức": "cơ cấu tổ chức", "kiểm tra giám xát": "kiểm tra giám sát",
    "nâng cao chất lượng": "nâng cao chất lượng", "đảm bảo": "đảm bảo",
}
# bỏ các cặp "x -> x" (chỉ để làm mẫu khi viết) khỏi bảng thật
PAIRS = {k: v for k, v in PAIRS.items() if k != v}

# cặp cách viết tương đương: (a, b); nếu trong cùng văn bản cả hai cùng xuất hiện thì theo cách nhiều hơn
STYLE_PAIRS = [("kỹ", "kĩ"), ("mỹ", "mĩ"), ("lý", "lí"), ("kỳ", "kì"), ("quý", "quí"), ("quy", "qui"),
               ("thủy", "thuỷ"), ("hòa", "hoà"), ("tòa", "toà"), ("hóa", "hoá"), ("thủ", "thủ")]
STYLE_PAIRS = [p for p in STYLE_PAIRS if p[0] != p[1]]


@dataclass
class Fix:
    start: int
    end: int
    old: str
    new: str
    kind: str
    sure: bool = True
    mark: bool = True            # có đổi màu chữ ở chỗ này không (chỉ khi thay đổi nhìn thấy được)
    reason: str = ""
    gain: float = 0.0
    tier: int = 2                # 2 = chắc chắn (ghi thẳng), 1 = nghi ngờ có gợi ý (chỉ ghi ở mức "rộng"), 0 = chỉ báo

    def to_json(self) -> dict:
        return {"from": self.old, "to": self.new, "kind": self.kind, "tier": self.tier, "reason": self.reason}


@dataclass
class Suspect:
    start: int
    end: int
    word: str
    reason: str
    suggest: str = ""


# ------------------------------------------------------------------ mô hình và chỉ mục ứng viên
class _Lex:
    """Từ vựng dùng chung: id -> dạng chuẩn, tần suất, hợp lệ âm vị; chỉ mục ứng viên theo khung chữ."""

    def __init__(self):
        M = vnfix._model()
        self.M = M
        self.words = M["words"]
        self.uni = M["uni"]
        self.wid = M["wid"]
        self.logu = M["logu"]
        self.total = float(sum(self.uni))
        n = len(self.words)
        self.valid = [False] * n
        self.surface = [""] * n          # dạng viết (đặt dấu kiểu cũ)
        by_key: dict[str, list[int]] = {}
        for i, w in enumerate(self.words):
            s = vnfix.realize(w)
            self.surface[i] = s
            if self.uni[i] >= MIN_CAND_COUNT and vphon.looks_vietnamese(s) and vphon.valid_syllable(s):
                self.valid[i] = True
                by_key.setdefault(vnfix.strip_marks(s), []).append(i)
        for k in by_key:
            by_key[k].sort(key=lambda i: -self.uni[i])
        self.by_key = by_key

    def key_of(self, tok: str) -> str:
        return vnfix.strip_marks(tok)

    def edit1_keys(self, key: str):
        """Khung chữ cách `key` một thao tác (xoá, thêm, đổi, đảo hai chữ liền nhau) có trong từ vựng, kèm loại thao tác."""
        seen = {}
        L = len(key)
        for i in range(L):                                   # xoá
            k = key[:i] + key[i + 1:]
            if k in self.by_key:
                seen.setdefault(k, "del")
        for i in range(L + 1):                               # thêm
            for c in _ALPHABET:
                k = key[:i] + c + key[i:]
                if k in self.by_key:
                    seen.setdefault(k, "ins")
        for i in range(L):                                   # đổi
            for c in _ALPHABET:
                if c != key[i]:
                    k = key[:i] + c + key[i + 1:]
                    if k in self.by_key:
                        seen.setdefault(k, "sub")
        for i in range(L - 1):                               # đảo
            if key[i] != key[i + 1]:
                k = key[:i] + key[i + 1] + key[i] + key[i + 2:]
                if k in self.by_key:
                    seen.setdefault(k, "swap")
        seen.pop(key, None)
        return seen


@lru_cache(maxsize=1)
def lexicon() -> _Lex:
    return _Lex()


def available() -> bool:
    return vnfix.available()


# ------------------------------------------------------------------ phân loại âm tiết
def _canon(tok: str) -> str:
    return vnfix.canon(tok.lower())


def _is_cap(tok: str) -> bool:
    return tok[:1].isupper() and not tok.isupper() and tok[1:] == tok[1:].lower()


def _tone_of(tok: str) -> int:
    return vphon.split_tone(tok.lower())[1]


def _apply_case(src: str, dst: str) -> str:
    if len(src) > 1 and src.isupper():
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


@dataclass
class _Tok:
    start: int
    end: int
    text: str
    low: str
    canon: str
    oid: int | None          # id trong từ vựng (None = chưa có)
    valid: bool              # hợp quy tắc chính tả (kể cả đặt dấu)
    placement_bad: bool = False
    skip: bool = False       # giữ nguyên hẳn
    sent_start: bool = False
    en: bool = False         # nhận diện là chữ tiếng Anh (langid.py)
    states: list = field(default_factory=list)


def _tokenize(text: str, lex: _Lex) -> list[_Tok]:
    toks: list[_Tok] = []
    last_end = 0
    for m in _TOK.finditer(text):
        w = m.group()
        s, e = m.start(), m.end()
        before, after = text[max(0, s - 1):s], text[e:e + 1]
        after2 = text[e + 1:e + 2]
        low = w.lower()
        c = vnfix.canon(low)
        skip = False
        if len(w) == 1 or len(w) > MAX_TOKEN:
            skip = True
        elif not vphon.looks_vietnamese(low):
            skip = True
        elif (before and (before.isdigit() or before in "-/_.@#&\\")) or (after and (after.isdigit() or after in "-/_@#\\")) \
                or (after == "." and after2.isalnum()):
            skip = True
        elif any(ch.isupper() for ch in w[1:]) and not w.isupper():
            skip = True                      # camelCase, McDonald
        valid = vphon.valid_syllable(low)
        pl_bad = valid and vphon.tone_style(low) == "bad"
        gap = text[last_end:s]
        sent_start = (not toks) or bool(_SENT_END.search(gap))
        t = _Tok(s, e, w, low, c, lex.wid.get(c), valid, pl_bad, skip, sent_start)
        if w.isupper() and len(w) >= 2 and not valid:
            t.skip = True                    # viết tắt: UBND, BCT, TP
        if KEEP_CAPS and _is_cap(w) and not t.sent_start and not t.valid:
            t.skip = True                    # tên riêng / chữ nước ngoài viết hoa giữa câu
        toks.append(t)
        last_end = e
    return toks


def _mark_english(toks: list[_Tok]) -> None:
    """Chữ không dấu mà nhận diện (langid.py) là tiếng Anh thì giữ nguyên hẳn: không sửa dấu, không đoán Telex, không báo nghi sai."""
    if not toks or not langid.available():
        return
    for t, en in zip(toks, langid.english_flags([t.text for t in toks])):
        if en and t.text.isascii():
            t.skip = t.en = True


def _segments(text: str, toks: list[_Tok]):
    seg: list[_Tok] = []
    for t in toks:
        if seg:
            gap = text[seg[-1].end:t.start]
            if gap.strip(" \t") != "" or "\n" in gap or len(gap) > 3:
                yield seg
                seg = []
        seg.append(t)
    if seg:
        yield seg


# ------------------------------------------------------------------ lưới ứng viên + Viterbi
def _orig_logp(lex: _Lex, t: _Tok) -> float:
    if t.oid is not None:
        u = lex.logu[t.oid]
        return u if t.valid else u - INVALID_COST
    return OOV_VALID_LOGP if t.valid else UNK_LOGP


def _states_for(lex: _Lex, t: _Tok):
    """[(id|None, emit, kind, penalty)]; phần tử đầu là chính chữ gõ."""
    first = (t.oid, 0.0, "orig", 0.0)
    if t.skip:
        return [first]
    sc = lex.__dict__.setdefault("_states_cache", {})
    ck = (t.low, t.valid, t.placement_bad, _is_cap(t.text))
    hit = sc.get(ck)
    if hit is not None:
        return list(hit)
    out = _states_build(lex, t, first)
    if len(sc) > 300_000:
        sc.clear()
    sc[ck] = tuple(out)
    return out


def _states_build(lex: _Lex, t: _Tok, first):
    out = [first]
    key = lex.key_of(t.low)
    own_u = lex.uni[t.oid] if t.oid is not None else 0
    cap_inner = _is_cap(t.text) and not t.sent_start
    seen = {t.oid}

    def add(i, kind, pen):
        if i not in seen:
            out.append((i, -pen, kind, pen))
            seen.add(i)

    if t.valid:
        for i in lex.by_key.get(key, ())[:6]:
            add(i, "context", P_CONTEXT)
        if own_u < RARE_COUNT and not t.placement_bad and not _is_cap(t.text):
            for k2 in lex.edit1_keys(key):
                for i in lex.by_key[k2][:4]:
                    add(i, "edit_rare", P_EDIT_RARE)
        return out
    for i in lex.by_key.get(key, ())[:8]:
        if lex.uni[i] >= TONE_RATIO * own_u:
            add(i, "tone", P_TONE_INVALID)
    if own_u < EDIT_MAX_ORIG and not _is_cap(t.text):
        for k2 in lex.edit1_keys(key):
            for i in lex.by_key[k2][:4]:
                if lex.uni[i] >= EDIT_MIN_CAND:
                    add(i, "edit", P_EDIT_INVALID)
    return out


def _decode(lex: _Lex, seg: list[_Tok], forced: dict[int, int] | None = None):
    """Viterbi trên một đoạn liền mạch. forced: {chỉ số chữ: chỉ số trạng thái bắt buộc}. Trả về (điểm, đường)."""
    import bisect
    keys, counts, uni, logu = lex.M["bkeys"], lex.M["bcounts"], lex.uni, lex.logu
    nb = len(keys)
    cache = lex.__dict__.setdefault("_trans_cache", {})   # dùng chung giữa các lần giải mã (cùng mô hình)
    if len(cache) > 1_500_000:
        cache.clear()

    def trans(a, b):
        if a is None or b is None:
            return UNK_LOGP if b is None else logu[b]
        k = (a, b)
        v = cache.get(k)
        if v is None:
            q = a * 2 ** 21 + b
            p = bisect.bisect_left(keys, q)
            v = math.log(counts[p] / uni[a]) if p < nb and keys[p] == q else math.log(0.4) + logu[b]
            cache[k] = v
        return v

    def uni_lp(t: _Tok, st):
        i, emit, kind, _ = st
        if kind == "orig":
            return _orig_logp(lex, t)
        return logu[i] + emit

    prev = None
    for j, t in enumerate(seg):
        sts = t.states
        if forced and j in forced:
            sts_idx = [forced[j]]
        else:
            sts_idx = range(len(sts))
        cur = []
        for k in sts_idx:
            st = sts[k]
            u = uni_lp(t, st)
            if prev is None:
                cur.append((u, (k,), k))
                continue
            best = None
            for sc, path, pk in prev:
                s = sc + trans(seg[j - 1].states[pk][0], st[0]) + u
                if best is None or s > best[0]:
                    best = (s, path + (k,), k)
            cur.append(best)
        prev = cur
    if not prev:
        return 0.0, ()
    b = max(prev, key=lambda x: x[0])
    return b[0], b[1]


def _context_fixes(text: str, toks: list[_Tok], lex: _Lex, sure_only_hint: bool = False) -> tuple[list[Fix], list[Suspect]]:
    fixes: list[Fix] = []
    suspects: list[Suspect] = []
    for t in toks:
        t.states = _states_for(lex, t)
    for seg in _segments(text, toks):
        if all(len(t.states) == 1 for t in seg):
            continue
        score, path = _decode(lex, seg)
        for j, (t, k) in enumerate(zip(seg, path)):
            if k == 0:
                continue
            i, emit, kind, pen = t.states[k]
            # lợi ròng = điểm đường tốt nhất - điểm đường giữ nguyên riêng chữ này
            alt, _ = _decode(lex, seg, {j: 0})
            gain = score - alt
            new = _apply_case(t.text, vnfix.realize(lex.words[i], t.low))
            if new == t.text:
                continue
            need = THRESH[kind] + (ASCII_EXTRA if t.text.isascii() and kind == "tone" else 0.0)
            tier = 2 if gain >= need else 1 if gain >= WIDE[kind] + (ASCII_EXTRA if need > THRESH[kind] else 0.0) else 0
            fixes.append(Fix(t.start, t.end, t.text, new, kind, sure=tier == 2, tier=tier, mark=True,
                             reason={"tone": "Âm tiết không hợp quy tắc chính tả",
                                     "edit": "Âm tiết không hợp quy tắc chính tả (thiếu/thừa/nhầm chữ cái)",
                                     "edit_rare": "Chữ hiếm gặp, gần với một chữ phổ biến",
                                     "context": "Sai theo ngữ cảnh"}[kind],
                             gain=round(gain, 1)))
    # chữ sai nhưng không sửa được: chỉ báo
    done = {f.start for f in fixes}
    for t in toks:
        if t.skip or t.valid or t.start in done:
            continue
        if not any(ord(ch) > 127 for ch in t.text):
            continue                         # chữ không dấu: thường là tiếng nước ngoài/viết tắt, không báo
        suspects.append(Suspect(t.start, t.end, t.text, "Không phải âm tiết tiếng Việt"))
    return fixes, suspects


# ------------------------------------------------------------------ Telex còn sót (giải mã: telex.py)
def _telex_fixes(toks: list[_Tok], lex: _Lex) -> list[Fix]:
    out = []
    for t in toks:
        if t.valid or len(t.text) < 3 or len(t.text) > 9 or any(ord(ch) > 127 for ch in t.text):
            continue
        if t.en or (t.skip and vphon.looks_vietnamese(t.low)) or t.text.isupper():
            continue                         # chữ Anh, hoặc viết tắt in hoa (BIF, DOS, ISO...): không phải Telex sót
        r = telex_decode(t.text)
        if r is None:
            continue
        new, signals = r
        c = vnfix.canon(new)
        i = lex.wid.get(c)
        if i is None or lex.uni[i] < 300 or not vphon.valid_syllable(new):
            continue
        if t.oid is not None and lex.uni[t.oid] >= 5:
            continue                         # đã có trong kho chữ (teen, sex, Queen, Saif...): chữ nước ngoài, không phải Telex sót
        out.append(Fix(t.start, t.end, t.text, _apply_case(t.text, new), "telex", sure=True, mark=True,
                       reason="Còn sót phím Telex"))
    return out


# ------------------------------------------------------------------ nhóm quy tắc kỹ thuật
_RE_DUP = re.compile(r"(?<![\w])(\w+)( +)\1(?![\w])", re.I | re.U)
_RE_SPACE2 = re.compile(r"(?<=[^\W\d_]|[,;:)]) {2}(?=[^\W\d_])")   # không đụng "I.  Tiêu đề", "-  Gạch đầu dòng" (thụt chủ ý)
_RE_SPACE_BEFORE = re.compile(r"(?<=[^\W_]) +(?=[,;:!?](?:\s|$|[)\"”’»]))")
_RE_NOSPACE_AFTER = re.compile(r"(?<=[^\W\d_]{2})([,;:])(?=[^\W\d_]{2})")
_RE_NOSPACE_PERIOD = re.compile(r"(?<=[a-zăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]{2})(\.)(?=[A-ZĂÂĐÊÔƠƯÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ][a-zăâđêôơư])")


def _tech_fixes(text: str) -> list[Fix]:
    out: list[Fix] = []
    if re.search(r" {3,}", text):
        spaces_ok = False                   # đoạn dùng dấu cách để căn cột (chữ ký, số hiệu...): không gộp
    else:
        spaces_ok = True
    if spaces_ok:
        for m in _RE_SPACE2.finditer(text):
            out.append(Fix(m.start(), m.end(), m.group(), " ", "space", mark=False, reason="Hai dấu cách liền nhau"))
    for m in _RE_SPACE_BEFORE.finditer(text):
        out.append(Fix(m.start(), m.end(), m.group(), "", "space", mark=False, reason="Thừa dấu cách trước dấu câu"))
    for m in _RE_NOSPACE_AFTER.finditer(text):
        around = text[max(0, m.start() - 12):m.end() + 12]
        if re.search(r"[/@\\]|www|http|\.(?:com|vn|gov|org|net)\b", around):
            continue
        out.append(Fix(m.start(), m.end(), m.group(), m.group() + " ", "space", mark=False, reason="Thiếu dấu cách sau dấu câu"))
    for m in _RE_NOSPACE_PERIOD.finditer(text):
        around = text[max(0, m.start() - 12):m.end() + 12]
        if re.search(r"[/@\\]|www|http", around):
            continue
        out.append(Fix(m.start(), m.end(), m.group(), ". ", "space", mark=False, reason="Thiếu dấu cách sau dấu chấm"))
    for m in _RE_DUP.finditer(text):
        w = m.group(1)
        if w.lower() in _DUP_WORDS:
            out.append(Fix(m.start(), m.end(), m.group(), w, "dup", mark=True, reason=f"Lặp từ \"{w}\""))
    return out


# ------------------------------------------------------------------ cặp sai–đúng chắc chắn
@lru_cache(maxsize=1)
def _pair_regex():
    keys = sorted(PAIRS, key=len, reverse=True)
    return re.compile(r"(?<![^\W\d_])(" + "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys) + r")(?![^\W\d_])",
                      re.I | re.U)


def _pair_fixes(text: str) -> list[Fix]:
    out = []
    for m in _pair_regex().finditer(text):
        key = re.sub(r"\s+", " ", m.group(1).lower())
        key = unicodedata.normalize("NFC", key)
        right = PAIRS.get(key)
        if not right:
            continue
        old = m.group(1)
        new = _apply_case(old, right)
        if new != old:
            out.append(Fix(m.start(), m.end(), old, new, "pair", mark=True, reason="Cặp sai–đúng thường gặp"))
    return out


# ------------------------------------------------------------------ dấu thanh đặt sai chỗ (không cần ngữ cảnh)
def _placement_fixes(toks: list[_Tok], style: str) -> list[Fix]:
    out = []
    for t in toks:
        if t.skip or not t.placement_bad:
            continue
        base, tone = vphon.split_tone(t.low)
        new_low = vphon.place_tone(base, tone, style)
        if new_low == t.low:
            continue
        out.append(Fix(t.start, t.end, t.text, _apply_case(t.text, new_low), "placement", mark=True,
                       reason="Dấu thanh đặt sai nguyên âm"))
    return out


# ------------------------------------------------------------------ điều phối cho một đoạn chữ
def _overlap(a: Fix, b: Fix) -> bool:
    return a.start < b.end and b.start < a.end


@dataclass
class Result:
    fixes: list[Fix]
    suspects: list[Suspect]


_ANALYZE_CACHE: dict = {}
_ANALYZE_MAX_CHARS = 6_000_000          # tổng số ký tự của các đoạn đang nhớ (~ vài văn bản dài)
_analyze_chars = 0


def analyze(text: str, style: str = "old", use_context: bool = True) -> Result:
    """Phân tích một đoạn chữ NFC (có nhớ kết quả: cùng một đoạn chữ không phải phân tích lại khi dựng bản không màu
    hoặc khi người dùng bấm "Áp dụng" nhiều lần). Trả về bản sao nên người gọi sửa thoải mái."""
    global _analyze_chars
    if not text or not available():
        return Result([], [])
    sp = core.speller()
    if sp is not None:                  # lõi Rust: đủ nhanh, không cần nhớ kết quả
        return _result(sp.analyze(text, style, use_context))
    key = (text, style, use_context)
    hit = _ANALYZE_CACHE.get(key)
    if hit is None:
        hit = _analyze(text, style, use_context)
        if _analyze_chars > _ANALYZE_MAX_CHARS:
            _ANALYZE_CACHE.clear()
            _analyze_chars = 0
        _ANALYZE_CACHE[key] = hit
        _analyze_chars += len(text)
    return Result([replace(f) for f in hit.fixes], [replace(x) for x in hit.suspects])


def _result(raw) -> Result:
    return Result([Fix(*f) for f in raw[0]], [Suspect(*s) for s in raw[1]])


def analyze_many(texts: list[str], style: str = "old", use_context: bool = True) -> list[Result]:
    """analyze() cho mọi đoạn của một văn bản; với lõi Rust là một lần gọi, không giữ GIL."""
    sp = core.speller()
    if sp is None or not available():
        return [analyze(t, style, use_context) for t in texts]
    return [_result(r) for r in sp.analyze_many(texts, style, use_context)]


def _analyze(text: str, style: str = "old", use_context: bool = True) -> Result:
    lex = lexicon()
    toks = _tokenize(text, lex)
    _mark_english(toks)
    fixes: list[Fix] = []
    fixes += _tech_fixes(text)
    fixes += _pair_fixes(text)
    fixes += _telex_fixes(toks, lex)
    suspects: list[Suspect] = []
    fixes += _placement_fixes(toks, style)
    if use_context:
        cf, suspects = _context_fixes(text, toks, lex)
        fixes += cf
    # chồng lấn: ưu tiên sửa chữ (có màu) hơn sửa dấu cách; trong cùng loại, giữ cái đến trước
    prio = {"pair": 0, "telex": 1, "placement": 2, "tone": 3, "edit": 3, "edit_rare": 4, "context": 4, "dup": 5, "style": 6, "space": 7}
    fixes.sort(key=lambda f: (prio.get(f.kind, 9), f.start))
    kept: list[Fix] = []
    for f in fixes:
        if any(_overlap(f, g) for g in kept):
            continue
        kept.append(f)
    kept.sort(key=lambda f: f.start)
    if style == "new":
        for f in kept:
            if f.kind in ("tone", "edit", "edit_rare", "context", "telex"):
                f.new = restyle(f.new, style)
    span = {(f.start, f.end) for f in kept}
    suspects = [s for s in suspects if not any(s.start < f.end and f.start < s.end for f in kept)]
    return Result(kept, suspects)


def restyle(word: str, style: str) -> str:
    """Đặt lại dấu thanh theo kiểu của văn bản ('old': hòa, thủy; 'new': hoà, thuỷ)."""
    if style != "new" or not word:
        return word
    base, tone = vphon.split_tone(word.lower())
    if not tone or not vphon.looks_vietnamese(base):
        return word
    return _apply_case(word, vphon.place_tone(base, tone, "new"))


def apply(text: str, fixes: list[Fix], only_sure: bool = True) -> str:
    out, pos = [], 0
    for f in sorted(fixes, key=lambda f: f.start):
        if only_sure and not f.sure:
            continue
        out.append(text[pos:f.start])
        out.append(f.new)
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


# ------------------------------------------------------------------ nhất quán trong cả văn bản
def tone_style_of_document(texts) -> str:
    """Cách đặt dấu thanh nhiều hơn trong văn bản ('old': hòa, thủy; 'new': hoà, thuỷ); mặc định old."""
    sp = core.speller()
    if sp is not None:
        return sp.tone_style_of_document(list(texts))
    old = new = 0
    for tx in texts:
        for m in _TOK.finditer(tx):
            w = m.group().lower()
            if len(w) < 3 or len(w) > MAX_TOKEN:
                continue
            st = vphon.tone_style(w)
            if st == "old":
                old += 1
            elif st == "new":
                new += 1
    return "new" if new > old else "old"


def style_fixes(texts: list[str]) -> list[list[Fix]]:
    """Với mỗi đoạn, các chỗ cần đổi để thống nhất cách viết; chỉ khi cả hai cách cùng có trong văn bản."""
    sp = core.speller()
    if sp is not None:
        return [[Fix(*f) for f in fs] for fs in sp.style_fixes(texts)]
    counts: dict[str, int] = {}
    for tx in texts:
        for m in _TOK.finditer(tx):
            counts[m.group().lower()] = counts.get(m.group().lower(), 0) + 1
    # cách đặt dấu thanh kiểu cũ/mới (hòa/hoà) cũng là một cặp
    plan: dict[str, str] = {}
    for a, b in STYLE_PAIRS:
        na, nb = counts.get(a, 0), counts.get(b, 0)
        if na and nb and na != nb:
            plan[b if na > nb else a] = a if na > nb else b
    # kiểu đặt dấu: đếm các từ oa/oe/uy ở cả hai kiểu
    old = new = 0
    forms: dict[str, tuple[str, str]] = {}
    for w, c in counts.items():
        if len(w) < 3 or len(w) > MAX_TOKEN:
            continue
        st = vphon.tone_style(w)
        if st not in ("old", "new"):
            continue
        base, tone = vphon.split_tone(w)
        other = vphon.place_tone(base, tone, "new" if st == "old" else "old")
        forms[w] = (st, other)
        if st == "old":
            old += c
        else:
            new += c
    majority = None
    if old and new and old != new:
        majority = "old" if old > new else "new"
    out: list[list[Fix]] = []
    for tx in texts:
        fs = []
        for m in _TOK.finditer(tx):
            w = m.group().lower()
            tgt = plan.get(w)
            if tgt is None and majority and w in forms and forms[w][0] != majority and counts.get(forms[w][1], 0):
                tgt = forms[w][1]
            if tgt and tgt != w:
                fs.append(Fix(m.start(), m.end(), m.group(), _apply_case(m.group(), tgt), "style", mark=True,
                              reason="Thống nhất cách viết trong văn bản"))
        out.append(fs)
    return out
