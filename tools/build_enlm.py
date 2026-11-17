"""Dựng nd30fmt/mdlib/data/enlm.zip: bảng tần suất từ tiếng Anh để nhận diện chữ Anh xen trong văn bản Việt (langid.py).

Cách dùng (cần `pip install wordfreq`; chỉ chạy khi dựng dữ liệu, ứng dụng không cần wordfreq):
    python tools/build_enlm.py [số_từ=60000]
Dữ liệu từ wordfreq (Robyn Speer; giấy phép CC BY-SA 4.0 cho dữ liệu) – xem nd30fmt/mdlib/data/LICENSE-wordfreq.txt.
Mỗi dòng của words.tsv: từ (chữ thường, a–z) <TAB> zipf×100 (số nguyên). Zipf = log10(tần suất mỗi tỉ từ).
"""
import json
import re
import sys
import zipfile
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

N = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
# mảnh vụn khi tách "don't", "I'll", "we're"...: trùng chữ Việt không dấu (don, ve, re) nên bỏ khỏi bảng
FRAGMENTS = set("ll ve re don isn didn doesn wasn weren couldn wouldn shouldn aren hasn haven hadn won ain mustn needn shan mightn "
                "doesnt dont isnt cant wont".split())
out = []
for w in top_n_list("en", N * 2):
    if not re.fullmatch(r"[a-z]{2,20}", w) or w in FRAGMENTS:
        continue
    out.append((w, round(zipf_frequency(w, "en") * 100)))
    if len(out) >= N:
        break
dest = Path(__file__).resolve().parents[1] / "nd30fmt" / "mdlib" / "data" / "enlm.zip"
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    z.writestr("words.tsv", "".join(f"{w}\t{k}\n" for w, k in out))
    z.writestr("meta.json", json.dumps({"source": "wordfreq 3.1.1 (en, large)", "words": len(out),
                                         "min_zipf": out[-1][1] / 100}, ensure_ascii=False))
print(dest, dest.stat().st_size, "bytes;", len(out), "từ; zipf thấp nhất", out[-1][1] / 100)
