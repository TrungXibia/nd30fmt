"""Đo bộ sửa chính tả vspell trên câu để riêng (mô hình chưa từng thấy):
  1) sửa nhầm trên câu sạch: tỉ lệ chữ bị đổi (chắc chắn / chỉ nghi);
  2) bắt đúng trên câu bị chèn lỗi giả lập, theo từng loại lỗi.
Cách dùng: python tools/eval_spell.py holdout.txt [số_câu] [--show N]
"""
import random
import re
import sys
import unicodedata
from collections import Counter

sys.path.insert(0, ".")
from nd30fmt import vspell, vphon  # noqa: E402

TONE_MARKS = "̣́̀̉̃"
W = re.compile(r"[^\W\d_]+")


def strip_tone(w):
    nf = unicodedata.normalize("NFD", w)
    return unicodedata.normalize("NFC", "".join(c for c in nf if c not in TONE_MARKS))


def add_tone(w, mark):
    return vphon.place_tone(vphon.split_tone(w.lower())[0], vphon_tone(mark)) if w else w


def vphon_tone(mark):
    return vphon._TONES[mark]


def inject(sent, rng):
    """Trả về (câu lỗi, [(loại, đúng, sai)]) với đúng 1 lỗi chèn vào 1 chữ tiếng Việt hợp lệ."""
    toks = [m for m in W.finditer(sent) if 2 <= len(m.group()) <= 6 and vphon.valid_syllable(m.group().lower())
            and m.group().islower()]
    if not toks:
        return None
    m = rng.choice(toks)
    w = m.group()
    kinds = []
    base, tone = vphon.split_tone(w)
    if tone:
        kinds += ["tone_drop"]
        kinds += ["tone_swap"]
    if len(w) >= 3:
        kinds += ["del", "swap"]
    kinds += ["ins", "dupl"]
    kind = rng.choice(kinds)
    if kind == "tone_drop":
        bad = base
    elif kind == "tone_swap":
        t2 = rng.choice([t for t in (1, 2, 3, 4, 5) if t != tone])
        bad = vphon.place_tone(base, t2)
    elif kind == "del":
        i = rng.randrange(len(w))
        bad = unicodedata.normalize("NFC", w[:i] + w[i + 1:])
    elif kind == "swap":
        i = rng.randrange(len(w) - 1)
        bad = w[:i] + w[i + 1] + w[i] + w[i + 2:]
    elif kind == "ins":
        i = rng.randrange(len(w) + 1)
        bad = w[:i] + rng.choice("aeiounth") + w[i:]
    else:  # dupl
        i = rng.randrange(len(w))
        bad = w[:i + 1] + w[i] + w[i + 1:]
    if bad == w or not bad:
        return None
    return sent[:m.start()] + bad + sent[m.end():], kind, w, bad, m.start()


def good_line(l):
    toks = W.findall(l)
    return len(toks) >= 5 and sum(len(t) == 1 for t in toks) / len(toks) < 0.12


def main():
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 3000
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
    lines = [unicodedata.normalize("NFC", l.strip()) for l in open(path, encoding="utf-8") if 25 < len(l.strip()) < 400]
    lines = [l for l in lines if good_line(l)]
    rng = random.Random(7)
    rng.shuffle(lines)
    lines = lines[:n]
    words = 0
    clean = []      # (kind, gain)
    sure_clean = []
    shown = 0
    for s in lines:
        words += len(W.findall(s))
        r = vspell.analyze(s)
        for f in r.fixes:
            if f.kind in ("space", "dup"):
                clean.append((f.kind, 99))
                continue
            clean.append((f.kind, f.gain))
            if f.sure:
                sure_clean.append(f.kind)
            if f.gain >= vspell.THRESH.get(f.kind, 0) and shown < show:
                shown += 1
                print("FP:", f.kind, f.gain, repr(f.old), "->", repr(f.new), "|", s[max(0, f.start - 30):f.end + 30])
    inj_rec = []    # (kind_inj, fix_kind, gain, correct)
    tally = Counter()
    nin = Counter()
    miss = []
    for s in lines:
        inj = inject(s, rng)
        if not inj:
            continue
        bad_s, kind, good, bad, pos = inj
        nin[kind] += 1
        r = vspell.analyze(bad_s)
        hit = [f for f in r.fixes if f.start <= pos < f.end and f.kind not in ("space", "dup")]
        if hit:
            f = hit[0]
            inj_rec.append((kind, f.kind, f.gain, f.new == good))
            tally[(kind, "ok" if f.new == good and f.sure else "wrong" if f.sure else "suggest_ok" if f.new == good else "suggest_wrong")] += 1
            if f.new != good and len(miss) < 300:
                miss.append(("WRONG", kind, f.kind, f.gain, good, bad, f.new, bad_s[max(0, pos - 25):pos + 30]))
        else:
            inj_rec.append((kind, None, 0, False))
            tally[(kind, "none")] += 1
            if len(miss) < 300:
                miss.append(("MISS", kind, "", 0, good, bad, "", bad_s[max(0, pos - 25):pos + 30]))
    print(f"=== TỔNG KẾT (chỉ tính sửa 'chắc chắn' = ghi thẳng vào file)")
    sc = Counter(sure_clean)
    print(f"Câu sạch: {sum(sc.values())} chữ bị đổi / {words} chữ = {100*sum(sc.values())/words:.3f}%  theo loại: {dict(sc)}")
    for kind in ("tone_drop", "tone_swap", "del", "swap", "ins", "dupl"):
        t = nin[kind]
        if t:
            print(f"  lỗi {kind:9s} n={t:4d}: sửa đúng {100*tally[(kind,'ok')]/t:5.1f}% | sửa sai {100*tally[(kind,'wrong')]/t:4.1f}% | chỉ gợi ý đúng {100*tally[(kind,'suggest_ok')]/t:4.1f}% | gợi ý sai {100*tally[(kind,'suggest_wrong')]/t:4.1f}% | bỏ qua {100*tally[(kind,'none')]/t:5.1f}%")
    print(f"{len(lines)} câu sạch, {words} chữ; {sum(nin.values())} câu chèn lỗi")
    kinds = sorted({k for k, _ in clean} | {r[1] for r in inj_rec if r[1]})
    for fk in (kinds if '--sweep' in sys.argv else []):
        print(f"--- loại sửa: {fk}")
        for th in (0, 3, 6, 9, 12, 16, 20, 30):
            fp = sum(1 for k, g in clean if k == fk and g >= th)
            ok = sum(1 for r in inj_rec if r[1] == fk and r[2] >= th and r[3])
            bad = sum(1 for r in inj_rec if r[1] == fk and r[2] >= th and not r[3])
            prec = 100 * ok / (ok + bad) if ok + bad else 0
            print(f"   gain>={th:2d}: câu sạch đổi nhầm {fp:4d} ({1e4*fp/words:5.1f}/10k chữ) | lỗi chèn sửa đúng {ok:4d} sai {bad:4d} (chính xác {prec:5.1f}%)")
    tot = sum(nin.values())
    print("bỏ sót / không sửa theo loại lỗi chèn:", {k: round(100 * sum(1 for r in inj_rec if r[0] == k and r[1] is None) / nin[k], 1) for k in nin})
    for m in miss[:show]:
        print(*m, sep=" | ")


if __name__ == "__main__":
    main()
