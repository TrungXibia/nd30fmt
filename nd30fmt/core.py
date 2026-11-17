"""Lõi Rust (nd30fmt/_core.abi3.so, mã nguồn ở rust/nd30core) cho phần nặng về chuỗi: sửa chính tả Word (vspell),
quy tắc âm tiết (vphon) và khôi phục dấu OCR (vnfix).

Lõi giữ mô hình ngôn ngữ trong bộ nhớ riêng (~15 MB), không cần các bảng nhớ tạm của bản Python và chạy ngoài GIL
nên không chặn các yêu cầu khác. Không nạp được lõi (máy khác kiến trúc, thiếu tệp .so, đặt ND30_NO_RUST=1) thì
vspell/vnfix tự chạy bằng bản Python; hai bản cho kết quả giống nhau (tests/common/test_core_parity.py).
"""
from __future__ import annotations

import json
import os
import zipfile
from functools import lru_cache

FORCE_PY = False        # test đặt True để ép chạy bản Python


@lru_cache(maxsize=1)
def _load():
    if os.getenv("ND30_NO_RUST") == "1":
        return None
    try:
        from . import _core
    except ImportError:
        return None
    from . import langid, vspell
    from .mdlib import vnfix
    if not vnfix.available():
        return None
    cfg = {k: getattr(vspell, k) for k in (
        "P_TONE_INVALID", "P_EDIT_INVALID", "P_EDIT_RARE", "P_CONTEXT", "INVALID_COST", "ASCII_EXTRA", "OOV_VALID_LOGP",
        "UNK_LOGP", "THRESH", "WIDE", "TONE_RATIO", "EDIT_MAX_ORIG", "EDIT_MIN_CAND", "RARE_COUNT", "MIN_CAND_COUNT",
        "MAX_TOKEN", "KEEP_CAPS", "STYLE_PAIRS")}
    cfg |= {"PAIRS": list(vspell.PAIRS.items()), "DUP_WORDS": vspell._DUP_WORDS, "CHANGE_PENALTY": vnfix.CHANGE_PENALTY,
            "DEGRADED_FACTOR": vnfix.DEGRADED_FACTOR, "MAX_CANDS": vnfix.MAX_CANDS}
    cfg |= {k: getattr(langid, k) for k in (
        "MU", "P_SWITCH", "P_EN0", "EN_BIAS", "TRI_K", "MIN_VI_KEY", "TINY", "MAX_SYLLABLE", "TELEX_PRIOR", "DELTA", "EN_PROTECT")}
    en_tsv = None
    if langid.available():
        with zipfile.ZipFile(langid._DATA) as z:
            en_tsv = z.read("words.tsv")
    with zipfile.ZipFile(vnfix._DATA) as z:
        return _core.Speller(json.loads(z.read("words.json")), z.read("uni.bin"), z.read("bkeys.bin"),
                             z.read("bcounts.bin"), cfg, en_tsv)


def _alpha_caps_py(s: str) -> tuple[int, int]:
    alpha = [c for c in s if c.isalpha()]
    return len(alpha), sum(1 for c in alpha if c == c.upper())


try:
    if os.getenv("ND30_NO_RUST") == "1":
        raise ImportError
    from ._core import alpha_caps        # (số chữ cái, số chữ cái viết hoa hoặc không phân biệt hoa thường)
except ImportError:
    alpha_caps = _alpha_caps_py


def speller():
    """Đối tượng Speller của lõi Rust, hoặc None nếu phải chạy bản Python."""
    return None if FORCE_PY else _load()


def name() -> str:
    return "rust" if speller() is not None else "python"
