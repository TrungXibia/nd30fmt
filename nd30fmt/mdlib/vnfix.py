"""Sửa lỗi dấu/chữ tiếng Việt do nhận dạng chữ (OCR) – chạy hoàn toàn trên máy chủ, không gửi văn bản ra ngoài.

Cách làm: khôi phục dấu theo ngữ cảnh bằng mô hình ngôn ngữ âm tiết (unigram + bigram) dựng từ kho tin tức
VNTC/VNESE (dự án underthesea) cộng văn bản hành chính trong gói – xem tools/build_vnlm.py, dữ liệu
data/vnlm.zip. Với mỗi âm tiết OCR, các ứng viên là những âm tiết có cùng "khung chữ" khi bỏ dấu (VD "thâm" ->
thẩm, thâm, thám, thắm…); thuật toán Viterbi chọn chuỗi âm tiết có xác suất cao nhất trong câu, có phạt mỗi lần
đổi khác bản OCR (OCR đúng là mặc định). Không thêm/bớt chữ, chỉ đổi dấu thanh, dấu mũ/móc/trăng và d/đ.
Viết hoa, viết tắt (BTC, TĐĐT…), số, tên riêng không có trong từ vựng được giữ nguyên.

Chỉ áp dụng trong vùng chữ do OCR sinh ra (OCR_OPEN … OCR_CLOSE); chữ có sẵn trong PDF/Word không bị đụng tới.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .. import core

OCR_OPEN, OCR_CLOSE = "", ""          # ký tự vùng riêng (Private Use): đánh dấu vùng chữ OCR
MARK_FIX_OPEN, MARK_FIX_CLOSE = "", ""  # dùng khi dựng HTML: tô chỗ đã sửa
MARK_SUS_OPEN, MARK_SUS_CLOSE = "", ""  # tô chỗ nghi sai còn lại
_DATA = Path(__file__).with_name("data") / "vnlm.zip"

CHANGE_PENALTY = 7.0     # log-xác suất phải lợi thêm bao nhiêu mới đổi khác bản OCR (chỉnh trên văn bản hành chính thử: sửa ~78% lỗi dấu, đổi nhầm ~0,03% chữ đúng)
MAX_CANDS = 10
DEGRADED_FACTOR = 0.35   # chữ OCR mất dấu (dạng không dấu hiếm gặp): phạt đổi nhẹ hơn
UNK_LOGP = math.log(1e-9)

_TONES = {"́": 1, "̀": 2, "̉": 3, "̃": 4, "̣": 5}
_TONE_MARK = {v: k for k, v in _TONES.items()}
_VOWELS = set("aăâeêioôơuưy")
_WORD = re.compile(r"[^\W\d_]+")


def strip_marks(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if not unicodedata.combining(c))


def split_tone(s: str) -> tuple[str, int]:
    """'hoà' / 'hòa' -> ('hoa', 2): phần chữ (giữ dấu mũ/móc/trăng) và thanh."""
    tone = 0
    out = []
    for c in unicodedata.normalize("NFD", s):
        if c in _TONES:
            tone = _TONES[c]
        else:
            out.append(c)
    return unicodedata.normalize("NFC", "".join(out)), tone


def canon(s: str) -> str:
    """Dạng chuẩn để so/đếm, không phụ thuộc kiểu đặt dấu (hóa = hoá, thủy = thuỷ)."""
    base, tone = split_tone(s)
    return f"{base}{tone}" if tone else base


def _tone_index(base: str, ref: str | None = None) -> int:
    """Vị trí đặt dấu thanh (kiểu truyền thống: hòa, thủy, quả, giữa); theo vị trí trong bản OCR nếu cùng chữ."""
    if ref:
        rb, rt = split_tone(ref)
        if rb == base and rt:
            nf = unicodedata.normalize("NFC", ref)
            for i, c in enumerate(nf):
                if any(m in unicodedata.normalize("NFD", c) for m in _TONES):
                    return i
    idx = [i for i, c in enumerate(base) if c in _VOWELS]
    if base.startswith("qu") and len(idx) > 1 and idx[0] == 1:
        idx = idx[1:]
    if base.startswith("gi") and len(idx) > 1 and idx[0] == 1:
        idx = idx[1:]
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
    return idx[1] if len(idx) >= 3 else idx[0]


def realize(c: str, ref: str | None = None) -> str:
    """Dạng chuẩn -> chữ viết (đặt dấu thanh)."""
    tone = int(c[-1]) if c[-1:].isdigit() else 0
    base = c[:-1] if tone else c
    if not tone:
        return base
    i = _tone_index(base, ref)
    if i < 0:
        return base
    return unicodedata.normalize("NFC", base[:i + 1] + _TONE_MARK[tone] + base[i + 1:])


@lru_cache(maxsize=1)
def _model():
    """Nạp mô hình: words.json (từ vựng, xếp theo tần suất), uni.bin (int64), bkeys.bin (int64, đã sắp xếp,
    = id1·2^21 + id2), bcounts.bin (uint32). Chỉ dùng thư viện chuẩn (không cần numpy)."""
    import array
    import sys
    import zipfile
    with zipfile.ZipFile(_DATA) as z:
        words = json.loads(z.read("words.json").decode("utf-8"))
        arrs = {}
        for name, code in (("uni.bin", "q"), ("bkeys.bin", "q"), ("bcounts.bin", "I")):
            a = array.array(code)
            a.frombytes(z.read(name))
            if sys.byteorder != "little":
                a.byteswap()
            arrs[name] = a
    uni = arrs["uni.bin"]
    wid = {w: i for i, w in enumerate(words)}
    by_key: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        by_key.setdefault(strip_marks(w.rstrip("012345")), []).append(i)          # words đã xếp theo tần suất giảm dần
    for k in by_key:
        by_key[k] = by_key[k][:MAX_CANDS]
    total = float(sum(uni))
    # chữ không dấu mà cùng khung chữ có dạng có dấu phổ biến hơn hẳn (VD "noi", "duoc", "tang"): thường là OCR
    # rơi dấu -> giảm mức phạt khi đổi
    key_total: dict[str, float] = {}
    for i, w in enumerate(words):
        k = strip_marks(w.rstrip("012345"))
        key_total[k] = key_total.get(k, 0.0) + uni[i]
    degraded = {i for i, w in enumerate(words)
                if not w[-1:].isdigit() and strip_marks(w) == w and uni[i] < 0.05 * key_total[w]}
    return {"degraded": degraded, "words": words, "wid": wid, "uni": uni,
            "logu": [math.log((u + 1) / total) for u in uni],
            "bkeys": arrs["bkeys.bin"], "bcounts": arrs["bcounts.bin"], "by_key": by_key}


def available() -> bool:
    return _DATA.exists()


def _bigram_logp(M, pairs: list[tuple[int, int]]) -> dict:
    import bisect
    keys, counts, uni, logu = M["bkeys"], M["bcounts"], M["uni"], M["logu"]
    n = len(keys)
    out = {}
    for a, b in pairs:
        k = a * 2 ** 21 + b
        p = bisect.bisect_left(keys, k)
        if p < n and keys[p] == k:
            out[(a, b)] = math.log(counts[p] / uni[a])
        else:
            out[(a, b)] = math.log(0.4) + logu[b]        # "stupid backoff"
    return out


def _apply_case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def _segments(text: str):
    """Các chuỗi âm tiết liền nhau (chỉ cách nhau bởi khoảng trắng); dấu câu/số/xuống dòng cắt chuỗi."""
    seg, last_end = [], None
    for m in _WORD.finditer(text):
        if seg and (last_end is None or text[last_end:m.start()].strip(" \t") != "" or "\n" in text[last_end:m.start()]):
            yield seg
            seg = []
        seg.append(m)
        last_end = m.end()
    if seg:
        yield seg


def _states(M, tok: str, before: str = "", after: str = ""):
    """(id ứng viên | None cho chữ ngoài từ vựng, có phải chính bản OCR không).
    Giữ nguyên: chữ 1 ký tự (a, b, o… đánh mục), chữ dài > 7, viết tắt viết hoa lạ, chữ dính "-", "/", "."
    (phiên âm Mát-xcơ-va, ký hiệu 06-CT/TU, đuôi tệp .doc)."""
    low = tok.lower()
    c = canon(low)
    oid = M["wid"].get(c)
    fixed = ((tok.isupper() and len(tok) <= 5 and oid is None) or len(tok) > 7 or len(tok) == 1
             or before[-1:] in ("-", "/", ".", "_") or after[:1] in ("-", "/", "_")
             or (after[:1] == "." and after[1:2].isalnum()))
    cands = [] if fixed else list(M["by_key"].get(strip_marks(low), []))
    states = [(oid, True)]
    states += [(i, False) for i in cands if i != oid]
    return states


def correct_text(text: str, penalty: float = None) -> tuple[str, list[dict]]:
    """Sửa một đoạn chữ OCR. Trả về (chữ đã sửa, [{from, to, start, end}] – vị trí trên chữ đã sửa)."""
    if not available():
        return text, []
    sp = core.speller()
    if sp is not None:
        fixed, fx = sp.ocr_correct_text(text, penalty)
        return fixed, [{"from": a, "to": b, "start": s, "end": e} for a, b, s, e in fx]
    M = _model()
    pen = CHANGE_PENALTY if penalty is None else penalty
    segs = list(_segments(text))
    lattice = [[_states(M, m.group(), text[max(0, m.start() - 2):m.start()], text[m.end():m.end() + 2])
                for m in seg] for seg in segs]
    need = set()
    for lat in lattice:
        for x, y in zip(lat, lat[1:]):
            for a, _ in x:
                for b, _ in y:
                    if a is not None and b is not None:
                        need.add((a, b))
    bi = _bigram_logp(M, list(need))
    repl = []
    for seg, lat in zip(segs, lattice):
        if all(len(s) == 1 for s in lat):
            continue
        # Viterbi
        def emit(st, ocr_id):
            i, is_ocr = st
            if is_ocr:
                return 0.0
            return -pen * (DEGRADED_FACTOR if ocr_id in M["degraded"] else 1.0)
        oids = [lt[0][0] for lt in lat]
        prev = [(((M["logu"][st[0]] if st[0] is not None else UNK_LOGP) + emit(st, oids[0])), [k])
                for k, st in enumerate(lat[0])]
        for t in range(1, len(lat)):
            cur = []
            for k, st in enumerate(lat[t]):
                best = None
                for (score, path), pst in zip(prev, lat[t - 1]):
                    a, b = pst[0], st[0]
                    if a is None or b is None:
                        tr = UNK_LOGP if b is None else M["logu"][b]
                    else:
                        tr = bi[(a, b)]
                    s = score + tr + emit(st, oids[t])
                    if best is None or s > best[0]:
                        best = (s, path)
                cur.append((best[0], best[1] + [k]))
            prev = cur
        _, path = max(prev, key=lambda x: x[0])
        for m, st_list, k in zip(seg, lat, path):
            wid, is_ocr = st_list[k]
            if is_ocr:
                continue
            new = _apply_case(m.group(), realize(M["words"][wid], m.group().lower()))
            if new != m.group():
                repl.append((m.start(), m.end(), new, m.group()))
    if not repl:
        return text, []
    buf, fixes, last, out_len = [], [], 0, 0
    for s, e, new, old in repl:
        chunk = text[last:s]
        buf.append(chunk)
        out_len += len(chunk)
        fixes.append({"from": old, "to": new, "start": out_len, "end": out_len + len(new)})
        buf.append(new)
        out_len += len(new)
        last = e
    buf.append(text[last:])
    return "".join(buf), fixes


def suspicious_spans(text: str) -> list[tuple[int, int]]:
    """Âm tiết không có trong từ vựng tiếng Việt nhưng trông như chữ Việt (VD "kêt", "thâm" đứng sai chỗ không tính)."""
    if not available():
        return []
    sp = core.speller()
    if sp is not None:
        return sp.ocr_suspicious_spans(text)
    M = _model()
    out = []
    for m in _WORD.finditer(text):
        w = m.group()
        if len(w) < 2 or (w.isupper() and len(w) <= 5):
            continue
        low = w.lower()
        if canon(low) in M["wid"]:
            continue
        if strip_marks(low) in M["by_key"]:
            out.append((m.start(), m.end()))
    return out


def correct_regions(text: str, disabled: set | None = None) -> tuple[str, list[dict]]:
    """Sửa trong các vùng OCR_OPEN…OCR_CLOSE (giữ ký hiệu vùng). disabled: tập (from, to) không áp dụng.
    Trả về (văn bản, chỗ sửa với vị trí trên văn bản trả về)."""
    disabled = disabled or set()
    out, fixes, pos = [], [], 0
    for m in re.finditer(re.escape(OCR_OPEN) + r"(.*?)" + re.escape(OCR_CLOSE), text, re.S):
        out.append(text[pos:m.start()] + OCR_OPEN)
        base = sum(len(x) for x in out)
        fixed, fx = correct_text(m.group(1))
        if disabled:
            fixed, fx = _undo(fixed, fx, disabled)
        for f in fx:
            fixes.append({**f, "start": f["start"] + base, "end": f["end"] + base})
        out.append(fixed + OCR_CLOSE)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), fixes


def _undo(fixed: str, fixes: list[dict], disabled: set) -> tuple[str, list[dict]]:
    buf, kept, last, shift = [], [], 0, 0
    for f in fixes:
        buf.append(fixed[last:f["start"]])
        if (f["from"], f["to"]) in disabled:
            buf.append(f["from"])
            shift += len(f["from"]) - len(f["to"])
        else:
            buf.append(f["to"])
            kept.append({**f, "start": f["start"] + shift, "end": f["end"] + shift})
        last = f["end"]
    buf.append(fixed[last:])
    return "".join(buf), kept


def strip_regions(text: str) -> str:
    return text.replace(OCR_OPEN, "").replace(OCR_CLOSE, "")


def group(fixes: list[dict]) -> list[dict]:
    cnt = Counter((f["from"], f["to"]) for f in fixes)
    return [{"from": a, "to": b, "n": n} for (a, b), n in cnt.most_common()]
