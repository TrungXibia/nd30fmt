"""Nhận diện chữ tiếng Anh xen trong văn bản tiếng Việt, để bộ sửa chính tả (vspell.py) không "sửa" chữ Anh thành chữ Việt
("must" -> "mút", "that" -> "thật", "docker" -> ...).

Cách làm (mô hình ẩn hai trạng thái, giải bằng Viterbi trên toàn bộ chữ của một đoạn):
  - Trạng thái VI / EN. Chuyển trạng thái bị phạt (P_SWITCH) nên một cụm chữ Anh liền nhau được giữ chung một nhãn, và
    chữ nhập nhằng (it, no, can, ban, con...) theo ngữ cảnh xung quanh.
  - Xác suất phát sinh của chữ không dấu (a–z):
        P_en = (1-MU)·tần suất tiếng Anh (bảng enlm.zip, 60.000 từ) + MU·xác suất theo mô hình chữ cái ba-gram tiếng Anh
        P_vi = (1-MU)·tần suất tiếng Việt (cộng mọi chữ có dấu cùng khung chữ, từ vnlm.zip) + MU·ba-gram âm tiết Việt
    Nhờ mô hình chữ cái, chữ chưa có trong bảng (tên riêng, thuật ngữ như "docker") vẫn được phân loại theo hình dạng.
  - Trong đoạn đã có chữ có dấu tiếng Việt ("chế độ có dấu"), chữ không dấu hiếm khi là chữ Việt bị quên dấu: xác suất của
    chữ Việt bỏ dấu chỉ tính DELTA lần ("chat" trong "tài liệu chat" là tiếng Anh, không phải "chất"). Đoạn gõ hoàn toàn
    không dấu thì tính đủ. Chữ Việt vốn không có dấu (ba, cho, con, anh) luôn tính đủ.
  - Quy tắc cứng: trong đoạn có dấu, chữ không dấu là từ tiếng Anh thông dụng (zipf ≥ 3,5) và không phải chữ Việt vốn không
    dấu thì chắc chắn là tiếng Anh, không để mô hình ẩn cân nhắc ("chat", "hat", "cap" gõ giữa câu có dấu).
  - Trong đoạn có dấu, chữ viết tắt không dấu viết hoa (BIF, DOI, UBND) không phải chữ Việt bị quên dấu: coi như ngoài tiếng Việt.
  - Chữ có dấu tiếng Việt chắc chắn là VI; chữ có f, j, w, z hoặc chữ cái lạ chắc chắn không phải âm tiết Việt.
  - EN_BIAS > 0 làm lệch về phía "tiếng Anh" vì sửa nhầm một chữ Anh trong văn bản chính thức tệ hơn bỏ sót một lỗi gõ.

Chỉ dùng thư viện chuẩn. Bản Rust (rust/nd30core) làm đúng từng bước này; tests/common/test_core_parity.py kiểm giống hệt.
"""
from __future__ import annotations

import math
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from . import vphon
from .mdlib import vnfix
from .telex import telex_decode

_DATA = Path(__file__).with_name("mdlib") / "data" / "enlm.zip"

MU = 1e-3             # tỉ trọng của mô hình chữ cái so với bảng tần suất
P_SWITCH = 0.08       # xác suất đổi ngôn ngữ giữa hai chữ liền nhau
P_EN0 = 0.3           # xác suất đoạn bắt đầu bằng tiếng Anh
EN_BIAS = 2.0         # cộng vào log-xác suất của trạng thái EN (xem chú thích đầu tệp)
TRI_K = 0.1           # làm trơn cộng-k của ba-gram chữ cái
MIN_VI_KEY = 5        # khung chữ Việt phải xuất hiện ít nhất ngần này lần mới dựng ba-gram
EN_PROTECT = 350      # zipf×100 tối thiểu để một từ Anh thông dụng được bảo vệ trong đoạn có dấu
DELTA = 0.01          # xác suất một chữ Việt bị bỏ dấu trong đoạn có dấu (xem chú thích đầu tệp)
TELEX_PRIOR = 0.001   # xác suất một âm tiết Việt bị gõ sót dạng Telex ("Vieejt"); khiến chữ Telex sót không bị coi là tiếng Anh
TINY = 1e-30
MAX_SYLLABLE = 7      # âm tiết Việt dài nhất (nghiêng, nguyễn...) có 7 chữ cái
_ALPHA = 27           # a–z và dấu kết thúc "$"
_AZ = re.compile(r"[a-z]+")


def available() -> bool:
    return _DATA.exists() and vnfix.available()


def _grams(words) -> tuple[dict, dict]:
    tri: dict[str, int] = {}
    bi: dict[str, int] = {}
    for w in words:
        s = "^^" + w + "$"
        for i in range(2, len(s)):
            tri[s[i - 2:i + 1]] = tri.get(s[i - 2:i + 1], 0) + 1
            bi[s[i - 2:i]] = bi.get(s[i - 2:i], 0) + 1
    return tri, bi


@lru_cache(maxsize=1)
def _model() -> dict:
    with zipfile.ZipFile(_DATA) as z:
        raw = z.read("words.tsv").decode("utf-8")
    en: dict[str, int] = {}
    for line in raw.splitlines():
        w, k = line.split("\t")
        en[w] = int(k)
    vm = vnfix._model()
    kt: dict[str, int] = {}                      # khung chữ (bỏ dấu) -> tổng tần suất của các âm tiết Việt hợp lệ
    kn: dict[str, int] = {}                      # phần trong đó vốn không có dấu (ba, cho, con, anh)
    for w, u in zip(vm["words"], vm["uni"]):
        s = vnfix.realize(w)
        if vphon.looks_vietnamese(s) and vphon.valid_syllable(s):      # bỏ "email", "google"... có trong kho tin tức
            k = vnfix.strip_marks(s)
            kt[k] = kt.get(k, 0) + u
            if s.isascii():
                kn[k] = kn.get(k, 0) + u
    return {"en": en, "kt": kt, "kn": kn, "total": float(sum(vm["uni"])), "wid": vm["wid"], "uni": vm["uni"],
            "g_en": _grams(en), "g_vi": _grams(k for k, c in kt.items() if c >= MIN_VI_KEY and _AZ.fullmatch(k))}


def _logchar(g: tuple[dict, dict], w: str) -> float:
    tri, bi = g
    s = "^^" + w + "$"
    t = 0.0
    for i in range(2, len(s)):
        t += math.log((tri.get(s[i - 2:i + 1], 0) + TRI_K) / (bi.get(s[i - 2:i], 0) + TRI_K * _ALPHA))
    return t


def emission(tok: str, accented: bool = False) -> tuple[float, float]:
    """(log P(chữ | VI), log P(chữ | EN)) – đã cộng EN_BIAS cho EN ở chữ không dấu. accented: đoạn có chữ có dấu."""
    if len(tok) == 1:
        return 0.0, 0.0
    low = tok.lower()
    floor = math.log(TINY)
    if not low.isascii():
        return (0.0, floor) if vphon.looks_vietnamese(low) else (floor, 0.0)
    if accented and tok.isupper():
        return floor, 0.0                      # viết tắt viết hoa trong đoạn có dấu
    m = _model()
    k = m["en"].get(low)
    pe = 10.0 ** (k / 100.0 - 9.0) if k is not None else 0.0
    ce = math.exp(_logchar(m["g_en"], low))
    en = math.log(max((1.0 - MU) * pe + MU * ce, TINY)) + EN_BIAS
    if accented and k is not None and k >= EN_PROTECT and m["kn"].get(low, 0) == 0:
        return floor, en
    tel = telex_decode(low)
    if tel is None and (len(low) > MAX_SYLLABLE or not vphon.looks_vietnamese(low)):
        return floor, en                       # quá dài hoặc có f, j, w, z mà không phải Telex: không phải âm tiết Việt
    kn = m["kn"].get(low, 0)
    pv = (kn + (DELTA if accented else 1.0) * (m["kt"].get(low, 0) - kn)) / m["total"]
    if tel is not None:                        # "Vieejt": chữ Việt gõ sót Telex
        i = m["wid"].get(vnfix.canon(tel[0]))
        if i is not None:
            pv += TELEX_PRIOR * m["uni"][i] / m["total"]
    cv = math.exp(_logchar(m["g_vi"], low))
    return math.log(max((1.0 - MU) * pv + MU * cv, TINY)), en


def english_flags(tokens: list[str]) -> list[bool]:
    """Nhãn "là tiếng Anh" cho từng chữ (theo thứ tự trong đoạn). Hoà thì chọn VI."""
    n = len(tokens)
    if n == 0 or not available():
        return [False] * n
    accented = any(not t.isascii() and vphon.looks_vietnamese(t.lower()) for t in tokens)
    em = [emission(t, accented) for t in tokens]
    stay, move = math.log(1.0 - P_SWITCH), math.log(P_SWITCH)
    v = math.log(1.0 - P_EN0) + em[0][0]
    e = math.log(P_EN0) + em[0][1]
    back: list[tuple[int, int]] = []              # back[i] = (trạng thái trước của VI, trạng thái trước của EN)
    for i in range(1, n):
        from_v, from_e = v + stay, e + move
        bv, nv = (1, from_e) if from_e > from_v else (0, from_v)
        from_v, from_e = v + move, e + stay
        be, ne = (0, from_v) if from_v > from_e else (1, from_e)
        v, e = nv + em[i][0], ne + em[i][1]
        back.append((bv, be))
    s = 1 if e > v else 0
    out = [False] * n
    for i in range(n - 1, -1, -1):
        out[i] = s == 1
        if i:
            s = back[i - 1][s]
    return out
