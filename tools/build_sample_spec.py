"""Dựng bộ quy chuẩn mẫu mở (config/sample/*_spec.yaml) từ quy chuẩn đầy đủ (cần ND30_SPEC_KEY).

Bộ mẫu giữ các quy định bắt buộc của văn bản gốc (khổ giấy, lề, phông, cỡ chữ, thành phần thể thức) và bỏ:
- phần quy ước bổ sung (vai trò profile "convention": chỉ còn kiểm tra phông chữ, như chế độ "Chỉ quy định");
- ghi chú, đường link nguồn, trạng thái đối chiếu; căn cứ chỉ ghi tên văn bản gốc.
Ứng dụng dùng bộ mẫu khi không có khoá giải mã (nd30fmt/spec.py: read_spec_text).

  ND30_SPEC_KEY=... python tools/build_sample_spec.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nd30fmt.spec import SPEC_PATHS, decrypt_bytes, spec_key  # noqa: E402

OUT = ROOT / "config" / "sample"
INFO = {
    "nd30": ("Quy chuẩn mẫu – thể thức văn bản hành chính theo Nghị định 30/2020/NĐ-CP",
             "Nghị định số 30/2020/NĐ-CP ngày 05/3/2020 của Chính phủ về công tác văn thư, Phụ lục I"),
    "dang": ("Quy chuẩn mẫu – thể thức văn bản của Đảng theo Hướng dẫn 05-HD/VPTW",
             "Hướng dẫn số 05-HD/VPTW của Văn phòng Trung ương Đảng về thể thức và kỹ thuật trình bày văn bản của Đảng"),
    "dean": ("Quy chuẩn mẫu – trình bày luận văn, đề án",
             "Quy định trình bày luận văn, đề án (bản mẫu)"),
}
DROP = {"url", "verified"}
CONV_NEUTRAL = {"bold": "any", "italic": "any", "underline": "any", "caps": "any", "align": "any"}
CONV_DROP = ("size", "first_line_indent_cm", "line_spacing", "fix_line_spacing")


def _clean(obj, src: str):
    """Bỏ ghi chú/link; mọi trường 'source' thay bằng tên văn bản gốc (bộ kiểm tra cần trường này)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in DROP or k == "note" or k.startswith("note_"):
                continue
            out[k] = src if k == "source" else _clean(v, src)
        return out
    if isinstance(obj, list):
        return [_clean(v, src) for v in obj]
    return obj


def make_sample(raw: dict, std: str) -> dict:
    name, src = INFO[std]
    raw = copy.deepcopy(raw)
    for role in (raw.get("roles") or {}).values():
        if role.get("profile") == "convention":
            role.update(CONV_NEUTRAL)
            for k in CONV_DROP:
                role.pop(k, None)
    raw = _clean(raw, src)
    raw["meta"] = {"name": name, "version": "mau-1.0", "sample": True,
                   "sources": [{"id": std.upper(), "title": src}]}
    return raw


def main() -> int:
    key = spec_key()
    OUT.mkdir(parents=True, exist_ok=True)
    for std, p in SPEC_PATHS.items():
        enc = p.with_name(p.name + ".enc")
        raw = yaml.safe_load(decrypt_bytes(enc.read_bytes(), key).decode("utf-8"))
        sample = make_sample(raw, std)
        head = (f"# {sample['meta']['name']}\n# Bộ quy chuẩn MẪU, mở (MIT): chỉ các quy định bắt buộc của văn bản gốc.\n"
                "# Dùng khi không có ND30_SPEC_KEY. Có thể sửa trực tiếp tệp này cho đơn vị mình.\n")
        (OUT / p.name).write_text(head + yaml.safe_dump(sample, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print("đã ghi", (OUT / p.name).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
