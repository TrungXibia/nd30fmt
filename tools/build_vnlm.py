"""Dựng mô hình ngôn ngữ âm tiết (unigram + bigram) cho bộ sửa lỗi dấu OCR (nd30fmt/mdlib/vnfix.py).

Nguồn dữ liệu (tải về máy dựng, KHÔNG đóng gói văn bản gốc – chỉ đóng gói bảng đếm đã rút gọn):
- VNTC (Vietnamese News Text Classification corpus) và VNESEcorpus, phát hành kèm dự án underthesea:
  https://github.com/undertheseanlp/underthesea/releases/download/resources/VNTC.zip
  https://github.com/undertheseanlp/underthesea/releases/download/resources/VNESEcorpus.txt
- Văn bản hành chính trong gói (mẫu, hướng dẫn) với trọng số cao để thích nghi lĩnh vực.

Cách chạy:  python tools/build_vnlm.py <thư mục chứa train.txt test.txt VNESE.txt> [--holdout 0.03]
Kết quả: nd30fmt/mdlib/data/vnlm.zip (từ vựng, đếm unigram, bảng bigram đã rút gọn).
"""
import argparse
import glob
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nd30fmt.mdlib.vnfix import canon  # noqa: E402

WORD = re.compile(r"[^\W\d_]+|[\d]+|[^\w\s]", re.U)
MIN_UNI = 20
MIN_BI = 3


HELD_OUT = []     # câu để riêng (không dùng khi dựng) khi chạy với --holdout-every


def sentences(path, skip_label=False, start=0.0, end=1.0, every=0):
    """Các câu của tệp (khoảng start..end của tệp). every=N > 0: cứ N câu để riêng 1 câu vào HELD_OUT, không dùng dựng
    (mẫu rải đều mọi chủ đề, dùng để đo chất lượng bộ sửa chính tả trên văn bản chưa từng thấy)."""
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    a, b = int(len(lines) * start), int(len(lines) * end)
    for k, ln in enumerate(lines[a:b]):
        if skip_label:
            ln = re.sub(r"^__label__\S+\s+", "", ln)
        ln = unicodedata.normalize("NFC", ln)
        if every and k % every == 0:
            HELD_OUT.append(ln)
            continue
        yield ln


_MARKED = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)


def accented(line):
    """Bỏ câu gõ không dấu (diễn đàn, email…): làm hỏng thống kê vì chữ không dấu trông như hợp lệ."""
    ws = re.findall(r"[^\W\d_]+", line)
    if len(ws) < 6:
        return True
    return sum(1 for w in ws if _MARKED.search(w)) / len(ws) >= 0.3


def tokens(line):
    """Chuỗi âm tiết chữ cái (chữ thường, dạng chuẩn); dấu câu/số cắt câu -> None."""
    for t in WORD.findall(line):
        if t[0].isalpha():
            yield canon(t.lower())
        else:
            yield None


def domain_texts():
    from docx import Document
    out = []
    for f in glob.glob(str(ROOT / "**/*.docx"), recursive=True):
        try:
            out.append("\n".join(p.text for p in Document(f).paragraphs))
        except Exception:  # noqa: BLE001
            pass
    for f in glob.glob(str(ROOT / "config/templates/**/*.json"), recursive=True):
        out.append(Path(f).read_text(encoding="utf-8"))
    out += (ROOT / "tools/vnlm_domain.txt").read_text(encoding="utf-8").splitlines()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--holdout", type=float, default=0.03)
    ap.add_argument("--holdout-every", type=int, default=0,
                    help="N > 0: cứ N câu để riêng 1 câu (ghi vào <src>/holdout.txt) thay cho phần đuôi --holdout")
    a = ap.parse_args()
    src = Path(a.src)
    uni = Counter()
    vocab = {}
    pairs = []

    def feed(lines, weight=1):
        buf = []
        for ln in lines:
            if not accented(ln):
                continue
            prev = None
            for t in tokens(ln):
                if t is None:
                    prev = None
                    continue
                uni[t] += weight
                i = vocab.setdefault(t, len(vocab))
                if prev is not None:
                    buf.append(prev * 2 ** 21 + i)
                prev = i
            if len(buf) > 5_000_000:
                pairs.append(np.repeat(np.array(buf, dtype=np.int64), weight))
                buf.clear()
        if buf:
            pairs.append(np.repeat(np.array(buf, dtype=np.int64), weight))

    if a.holdout_every:
        feed(sentences(src / "train.txt", True, every=a.holdout_every))
        feed(sentences(src / "test.txt", True, every=a.holdout_every))
        feed(sentences(src / "VNESE.txt", every=a.holdout_every))
        (src / "holdout.txt").write_text("\n".join(HELD_OUT), encoding="utf-8")
        print("để riêng", len(HELD_OUT), "câu ->", src / "holdout.txt")
    else:
        feed(sentences(src / "train.txt", True))
        feed(sentences(src / "test.txt", True, 0, 1 - a.holdout))
        feed(sentences(src / "VNESE.txt"))
    feed(domain_texts(), weight=50)
    keys = np.concatenate(pairs)
    keys, counts = np.unique(keys, return_counts=True)
    # từ vựng giữ: âm tiết đủ phổ biến
    inv = {i: t for t, i in vocab.items()}
    keep_words = sorted([t for t, c in uni.items() if c >= MIN_UNI], key=lambda t: -uni[t])
    new_id = {t: k for k, t in enumerate(keep_words)}
    w1, w2 = keys >> 21, keys & (2 ** 21 - 1)
    m1 = np.array([new_id.get(inv[int(x)], -1) for x in range(len(vocab))], dtype=np.int64)
    n1, n2 = m1[w1], m1[w2]
    ok = (n1 >= 0) & (n2 >= 0) & (counts >= MIN_BI)
    nk = n1[ok] * 2 ** 21 + n2[ok]
    order = np.argsort(nk)
    import zipfile
    out = ROOT / "nd30fmt/mdlib/data/vnlm.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("words.json", json.dumps(keep_words, ensure_ascii=False))
        zf.writestr("uni.bin", np.array([uni[t] for t in keep_words], dtype="<i8").tobytes())
        zf.writestr("bkeys.bin", nk[order].astype("<i8").tobytes())
        zf.writestr("bcounts.bin", counts[ok][order].astype("<u4").tobytes())
    print("vocab", len(keep_words), "bigrams", int(ok.sum()), "->", out, round(out.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
