"""Dòng lệnh.

Ví dụ:
  python -m nd30fmt check  bao_cao.docx                 # chỉ kiểm tra, xuất báo cáo
  python -m nd30fmt fix    bao_cao.docx -o ket_qua/     # kiểm tra + sửa + kiểm tra lại
  python -m nd30fmt fix    thu_muc_word/ -o ket_qua/     # chạy cả thư mục
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import process
from .spec import SPEC_PATHS, STANDARDS, load_spec


def _collect(inputs: list[str]) -> list[Path]:
    files = []
    for x in inputs:
        p = Path(x)
        if p.is_dir():
            files += sorted(q for q in p.rglob("*.docx") if not q.name.startswith("~$")
                            and not q.stem.endswith("_da_sua"))
        elif p.suffix.lower() == ".docx":
            files.append(p)
        else:
            print(f"Bỏ qua (không phải .docx): {p}", file=sys.stderr)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nd30fmt", description="So sánh và sửa định dạng Word theo NĐ 30/2020")
    ap.add_argument("command", choices=["check", "fix"],
                    help="check: chỉ kiểm tra; fix: kiểm tra và sửa")
    ap.add_argument("inputs", nargs="*", help="file .docx hoặc thư mục")
    ap.add_argument("-o", "--out", help="thư mục kết quả (mặc định: cạnh file gốc)")
    ap.add_argument("--spec", help="file quy chuẩn YAML (mặc định config/nd30_spec.yaml)")
    ap.add_argument("--standard", choices=list(STANDARDS), default="nd30",
                    help="chuẩn thể thức dùng để xác định vai trò đoạn (mặc định nd30; dùng 'dang' khi --spec "
                         "trỏ tới config/dang_spec.yaml, vì cách xác định vai trò khác nhau giữa hai chuẩn)")
    ap.add_argument("--skip-conventions", action="store_true",
                    help="bỏ qua các quy ước báo cáo dài, chỉ kiểm tra quy định NĐ 30")
    a = ap.parse_args(argv)

    spec_path = a.spec or str(SPEC_PATHS[a.standard])
    spec = load_spec(spec_path, skip_conventions=a.skip_conventions)
    files = _collect(a.inputs)
    if not files:
        print("Không có file .docx nào.", file=sys.stderr)
        return 2
    worst = 0
    for f in files:
        try:
            r = process(str(f), spec, a.out, fix=(a.command == "fix"), standard=a.standard)
        except Exception as e:  # tiếp tục các file khác
            print(f"[LỖI] {f.name}: {e}", file=sys.stderr)
            worst = max(worst, 3)
            continue
        s = r["summary"]
        line = f"{f.name}: {s['total']} lỗi ({s['paragraphs_with_errors']} đoạn)"
        if "summary_after" in r:
            line += f" -> còn {r['summary_after']['total']} sau khi sửa -> {r['fixed_file']}"
        line += f" | báo cáo: {r['report_html']}"
        print(line)
        if s["total"]:
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
