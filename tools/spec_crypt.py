"""Mã hoá / giải mã tệp quy chuẩn (config/*_spec.yaml <-> config/*_spec.yaml.enc), AES-256-GCM.

  python tools/spec_crypt.py keygen                 # in khoá mới (đặt vào ND30_SPEC_KEY, giữ bí mật)
  python tools/spec_crypt.py encrypt                # mã hoá mọi config/*_spec.yaml -> .enc (cần ND30_SPEC_KEY)
  python tools/spec_crypt.py decrypt                # giải mã .enc -> .yaml để sửa (tệp .yaml rõ KHÔNG đưa lên git)
  python tools/spec_crypt.py encrypt --remove-plain # mã hoá xong xoá tệp .yaml rõ

Ứng dụng tự đọc tệp .enc khi không có tệp .yaml rõ (nd30fmt/spec.py: read_spec_text).
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nd30fmt.spec import decrypt_bytes, encrypt_bytes, spec_key  # noqa: E402

CONFIG = ROOT / "config"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["keygen", "encrypt", "decrypt"])
    ap.add_argument("--remove-plain", action="store_true", help="encrypt: xoá tệp .yaml rõ sau khi mã hoá")
    a = ap.parse_args(argv)
    if a.command == "keygen":
        print(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))
        return 0
    key = spec_key()
    if a.command == "encrypt":
        files = sorted(CONFIG.glob("*_spec.yaml"))
        if not files:
            print("Không có config/*_spec.yaml để mã hoá", file=sys.stderr)
            return 1
        for p in files:
            data = p.read_bytes()
            enc = p.with_name(p.name + ".enc")
            enc.write_bytes(encrypt_bytes(data, key))
            assert decrypt_bytes(enc.read_bytes(), key) == data
            if a.remove_plain:
                p.unlink()
            print(f"đã mã hoá {p.name} -> {enc.name}")
        return 0
    for enc in sorted(CONFIG.glob("*_spec.yaml.enc")):
        out = enc.with_name(enc.name[:-4])
        out.write_bytes(decrypt_bytes(enc.read_bytes(), key))
        print(f"đã giải mã {enc.name} -> {out.name} (đừng đưa tệp này lên git)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
