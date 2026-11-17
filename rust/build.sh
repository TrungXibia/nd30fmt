#!/usr/bin/env bash
# Dựng lại lõi Rust và đặt vào nd30fmt/_core.abi3.so (Linux, cùng kiến trúc với máy dựng; chạy với Python >= 3.9).
#   pip install maturin ziglang && bash rust/build.sh
# Bản trong gói là x86_64, liên kết với glibc >= 2.17 nên chạy được trong image python:3.11-slim-bookworm.
# Máy khác kiến trúc (ARM): chạy script này trên chính máy đó, hoặc bỏ qua – ứng dụng tự dùng bản Python.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/nd30core"
out="$(mktemp -d)"
maturin build --release --zig --compatibility manylinux2014 -o "$out"
python3 - "$out" <<'PY'
import glob, sys, zipfile
whl = glob.glob(sys.argv[1] + "/*.whl")[0]
with zipfile.ZipFile(whl) as z:
    so = next(n for n in z.namelist() if n.endswith(".so"))
    open("../../nd30fmt/_core.abi3.so", "wb").write(z.read(so))
print("Đã ghi nd30fmt/_core.abi3.so từ", whl.rsplit("/", 1)[-1])
PY
rm -rf "$out"
