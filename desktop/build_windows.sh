#!/usr/bin/env bash
# Dựng bộ cài Windows "Công cụ văn bản NĐ30" trên Linux (không cần máy Windows).
# Cần: curl, pip, 7z (p7zip-full), mingw-w64 (gcc, windres, strip), nsis (makensis), python3-pil.
# Dùng: desktop/build_windows.sh <thư mục làm việc> <file exe đầu ra>
# Tạo 2 file: <đầu ra> (ứng dụng) và <đầu ra>-OCR.exe -> đặt tên CongCuVanBanND30-OCR.exe (gói nhận dạng chữ)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="${1:?thư mục làm việc}"; OUT="${2:?file exe đầu ra}"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10%2B20241016-x86_64-pc-windows-msvc-install_only.tar.gz"
PY_SHA="647b66ff4552e70aec3bf634dd470891b4a2b291e8e8715b3bdb162f577d4c55"
TESS_URL="https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
TESS_SHA="c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"
VIE_URL="https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/vie.traineddata"   # cùng dữ liệu với bản máy chủ (Debian)
VIE_SHA="79df64caf7bcfb2a27df5042ecb6121e196eada34da774956995747636d5bfa1"
mkdir -p "$W/dl"; cd "$W"
get(){ [ -f "dl/$2" ] || curl -fsSL -o "dl/$2" "$1"; [ -z "${3:-}" ] || echo "$3  dl/$2" | sha256sum -c -; }
get "$PY_URL" py.tar.gz "$PY_SHA"
get "$TESS_URL" tess.exe "$TESS_SHA"
get "$VIE_URL" vie_fast.traineddata "$VIE_SHA"
rm -rf stage tess pyx && mkdir -p stage/tesseract/tessdata tess pyx
# Python
tar -xzf dl/py.tar.gz -C pyx && mv pyx/python stage/runtime
( cd stage/runtime && rm -rf Lib/test Lib/idlelib Lib/tkinter Lib/turtledemo Lib/lib2to3 Lib/ensurepip tcl \
    Lib/site-packages/pip* Scripts include libs DLLs/_tkinter.pyd DLLs/tcl*.dll DLLs/tk*.dll \
    Lib/venv Lib/distutils Lib/pydoc_data Lib/turtle.py Lib/msilib Lib/sqlite3/test && find . -name '*.pdb' -delete )
pip install -q --target stage/runtime/Lib/site-packages --platform win_amd64 --python-version 3.11 \
    --implementation cp --abi cp311 --only-binary=:all: -r "$ROOT/desktop/requirements-win.txt"
find stage/runtime -name __pycache__ -prune -exec rm -rf {} +
( cd stage/runtime/Lib/site-packages && rm -rf setuptools* pkg_resources _distutils_hack distutils-precedence.pth )
# Tesseract: chỉ giữ tesseract.exe và các DLL nó cần
( cd tess && 7z x -y ../dl/tess.exe >/dev/null )
cp tess/tesseract.exe tess/*.dll stage/tesseract/ && cp -r tess/tessdata/configs stage/tesseract/tessdata/
cp tess/tessdata/eng.traineddata stage/tesseract/tessdata/ && cp dl/vie_fast.traineddata stage/tesseract/tessdata/vie.traineddata   # osd không dùng (psm 4)
cp tess/doc/LICENSE stage/tesseract/LICENSE.txt 2>/dev/null || true
python3 - stage/tesseract <<'PY'
import os, re, subprocess, sys
d = sys.argv[1]; have = {f.lower(): f for f in os.listdir(d) if f.lower().endswith((".dll", ".exe"))}
need, todo = set(), ["tesseract.exe"]
while todo:
    out = subprocess.run(["x86_64-w64-mingw32-objdump", "-p", os.path.join(d, todo.pop())], capture_output=True, text=True).stdout
    for n in re.findall(r"DLL Name: (\S+)", out):
        if n.lower() in have and n.lower() not in need:
            need.add(n.lower()); todo.append(have[n.lower()])
for k, f in have.items():
    if k != "tesseract.exe" and k not in need:
        os.remove(os.path.join(d, f))
PY
x86_64-w64-mingw32-strip --strip-debug stage/tesseract/*.dll
# Ứng dụng
mkdir -p stage/app && cp -r "$ROOT/nd30fmt" "$ROOT/config" stage/app/ && find stage/app -name __pycache__ -prune -exec rm -rf {} +
cp "$ROOT/desktop/DOC_TRUOC.txt" stage/
# Trình khởi động
( cd "$ROOT/desktop" && x86_64-w64-mingw32-windres launcher.rc -O coff -o "$W/launcher.res" \
  && x86_64-w64-mingw32-gcc -O2 -municode -mwindows -s -o "$W/stage/CongCuVanBanND30.exe" launcher.c "$W/launcher.res" )
# Bộ cài
OCR_OUT="$(dirname "$OUT")/CongCuVanBanND30-OCR.exe"
( cd "$ROOT/desktop" && makensis -V2 -DSTAGE="$W/stage" -DOUT="$OUT" installer.nsi \
  && makensis -V2 -DSTAGE="$W/stage" -DOUT="$OCR_OUT" installer_ocr.nsi )
ls -la "$OUT" "$OCR_OUT"
