"""Lõi Rust (nd30fmt/_core) phải cho kết quả giống hệt bản Python tham chiếu trên văn bản thật và văn bản bị làm hỏng
ngẫu nhiên (gõ sai, Telex sót, rơi dấu, dấu cách, chữ tổ hợp, ký tự lạ). Bỏ qua nếu máy không nạp được lõi."""
import os
import random
import unicodedata
from dataclasses import astuple
from pathlib import Path

import pytest

from nd30fmt import core, vspell
from nd30fmt.mdlib import vnfix

ROOT = Path(__file__).resolve().parents[2]
N = int(os.getenv("ND30_PARITY_N", "400"))
pytestmark = pytest.mark.skipif(core.speller() is None, reason="không có lõi Rust")

_ODD = ["²", "Ⅳ", "ǅ", "ß", "İ", "ς", " ", " ", "\x1c", "_", "9", "٣", "@", "/", "\\", "-", ".", "…", "”", "»",
        "\t", "\n", "   ", "www", "http", ".vn", ".com", "中", "й", "́", "̣", "​"]
_TELEX = {"ă": "aw", "â": "aa", "ê": "ee", "ô": "oo", "ơ": "ow", "ư": "uw", "đ": "dd"}
_TONE = {"́": "s", "̀": "f", "̉": "r", "̃": "x", "̣": "j"}


def _telex(w: str) -> str:
    tone, out = "", ""
    for ch in unicodedata.normalize("NFD", w):
        if ch in _TONE:
            tone = _TONE[ch]
        else:
            out += ch
    out = unicodedata.normalize("NFC", out)
    return "".join(_TELEX.get(c, c) for c in out) + tone


def _mutate(rnd: random.Random, s: str) -> str:
    for _ in range(rnd.randint(1, 4)):
        words = s.split(" ")
        i = rnd.randrange(len(words))
        w = words[i]
        op = rnd.randrange(16)
        if op == 0 and w:
            p = rnd.randrange(len(w)); w = w[:p] + w[p + 1:]
        elif op == 1:
            p = rnd.randrange(len(w) + 1); w = w[:p] + rnd.choice("abcdeghiklmnopqrstuvxyfjwz") + w[p:]
        elif op == 2 and len(w) > 1:
            p = rnd.randrange(len(w) - 1); w = w[:p] + w[p + 1] + w[p] + w[p + 2:]
        elif op == 3:
            w = "".join(c for c in unicodedata.normalize("NFD", w) if c not in _TONE)
            w = unicodedata.normalize("NFC", w)
        elif op == 4:
            w = vnfix.strip_marks(w) if rnd.random() < .5 else unicodedata.normalize("NFD", w)
        elif op == 5 and w.isalpha():
            w = _telex(w.lower())
        elif op == 6:
            w = rnd.choice([w.upper(), w.capitalize(), w.swapcase(), w.lower()])
        elif op == 7:
            w = w + " " + w
        elif op == 8:
            w = w + rnd.choice(["  ", " ,", ",", ";", ".", ". ", " : ", " ! ", "?)"])
        elif op == 9:
            p = rnd.randrange(len(w) + 1); w = w[:p] + rnd.choice(_ODD) + w[p:]
        elif op == 10 and i + 1 < len(words):
            w = w + rnd.choice([".", ",", ":", ";"]) + words.pop(i + 1)
        elif op == 11:
            base, tone = vnfix.split_tone(w.lower())
            if tone and len(base) > 1:               # dấu thanh đặt vào nguyên âm khác
                p = rnd.randrange(len(base))
                w = unicodedata.normalize("NFC", base[:p + 1] + vnfix._TONE_MARK[tone] + base[p + 1:])
        elif op == 12:
            w = rnd.choice(list(vspell.PAIRS)) if rnd.random() < .7 else rnd.choice(sum(vspell.STYLE_PAIRS, ()))
        elif op == 13:
            w = rnd.choice(["hoà", "hòa", "thuỷ", "thủy", "kĩ", "kỹ", "quí", "quý", "toà", "tòa", "khoẻ", "khỏe"])
        elif op == 14 and w:
            p = rnd.randrange(len(w)); w = w[:p] + rnd.choice("ăâêôơưđáàảãạ") + w[p + 1:]
        words[i] = w
        s = " ".join(words)
    return s


def _english_words():
    import zipfile
    with zipfile.ZipFile(ROOT / "nd30fmt" / "mdlib" / "data" / "enlm.zip") as z:
        rows = [l.split("\t") for l in z.read("words.tsv").decode().splitlines()]
    return [r[0] for r in rows], [10 ** (int(r[1]) / 100) for r in rows]


def _mix_english(rnd: random.Random, lines: list[str]) -> list[str]:
    """Câu Anh thuần, câu Việt chèn cụm Anh, câu Việt bỏ dấu, chữ viết tắt hoa, chữ Telex: các ca của nhận diện ngôn ngữ."""
    ws, wt = _english_words()
    def phrase(k):
        return " ".join(rnd.choices(ws, wt, k=k))
    out = []
    for _ in range(N):
        l = rnd.choice(lines)
        words = l.split(" ")
        pos = rnd.randrange(len(words) + 1)
        ph = phrase(rnd.randint(1, 4))
        kind = rnd.randrange(8)
        if kind == 0:
            out.append(phrase(rnd.randint(1, 12)).capitalize() + rnd.choice([".", "", ",", " , "]))
        elif kind == 1:
            out.append(" ".join(words[:pos] + [ph] + words[pos:]))
        elif kind == 2:
            out.append(vnfix.strip_marks(" ".join(words[:pos] + [ph] + words[pos:])))
        elif kind == 3:
            out.append(" ".join(words[:pos] + [rnd.choice(["BIF", "DOS", "ISO", "UBND", "DOI", "TP", "Ban"]), ph] + words[pos:]))
        elif kind == 4:
            out.append(_mutate(rnd, " ".join(words[:pos] + [ph] + words[pos:])))
        elif kind == 5:
            out.append(" ".join(words[:pos] + [_telex(rnd.choice(words).lower()), ph] + words[pos:]))
        elif kind == 6:
            out.append((" ".join(words[:pos] + [ph] + words[pos:])).upper())
        else:
            out.append(" ".join(words[:pos] + [ph.replace(" ", "-"), ph] + words[pos:]))
    return out


@pytest.fixture(scope="module")
def texts():
    rnd = random.Random(30)
    lines = [l.strip() for l in (ROOT / "tools" / "vnlm_domain.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = [unicodedata.normalize("NFC", l) for l in lines]
    out = rnd.sample(lines, min(N, len(lines)))
    out += [_mutate(rnd, rnd.choice(lines)) for _ in range(N * 3)]
    out += _mix_english(rnd, lines)
    out += ["", " ", "a", "Á", "của của của", "A.b", "x,y", "ab,cd", "ab.Cd ef", "tiến  độ", "UBND tỉnh", "đươc.Kêt qủa"]
    return out


def _py(fn, *a, **kw):
    core.FORCE_PY = True
    try:
        return fn(*a, **kw)
    finally:
        core.FORCE_PY = False


def _flat(res):
    return [astuple(f) for f in res.fixes], [astuple(s) for s in res.suspects]


@pytest.mark.parametrize("style,ctx", [("old", True), ("new", True), ("old", False)])
def test_analyze_same_as_python(texts, style, ctx):
    got = vspell.analyze_many(texts, style, ctx)
    for t, g in zip(texts, got):
        assert _flat(g) == _flat(vspell._analyze(t, style, ctx) if t else vspell.Result([], [])), repr(t)
        assert _flat(g) == _flat(vspell.analyze(t, style, ctx))


def test_document_style_same_as_python(texts):
    rnd = random.Random(5)
    for _ in range(12):
        doc = rnd.sample(texts, 60)
        assert vspell.tone_style_of_document(doc) == _py(vspell.tone_style_of_document, doc)
        assert [[astuple(f) for f in fs] for fs in vspell.style_fixes(doc)] == \
               [[astuple(f) for f in fs] for fs in _py(vspell.style_fixes, doc)]


def test_ocr_fix_same_as_python(texts):
    for t in texts:
        for s in (t, vnfix.strip_marks(t), t.upper()):
            assert vnfix.correct_text(s) == _py(vnfix.correct_text, s), repr(s)
            assert vnfix.correct_text(s, 3.0) == _py(vnfix.correct_text, s, 3.0), repr(s)
            assert [tuple(x) for x in vnfix.suspicious_spans(s)] == _py(vnfix.suspicious_spans, s), repr(s)


def test_alpha_caps_same_as_python(texts):
    for t in texts + ["ß", "ǅ", "İstanbul", "中文 ABC", "ⅣⅤ", "ａｂＣ", "µ"]:
        assert tuple(core.alpha_caps(t)) == core._alpha_caps_py(t), repr(t)
