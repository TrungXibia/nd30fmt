"""Nạp file quy chuẩn định dạng (YAML) và cung cấp truy cập tiện dụng."""
from __future__ import annotations

import base64
import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SPEC_PATH = Path(__file__).resolve().parent.parent / "config" / "nd30_spec.yaml"
DANG_SPEC_PATH = Path(__file__).resolve().parent.parent / "config" / "dang_spec.yaml"
DEAN_SPEC_PATH = Path(__file__).resolve().parent.parent / "config" / "dean_spec.yaml"
STANDARDS = ("nd30", "dang", "dean")
SPEC_PATHS = {"nd30": DEFAULT_SPEC_PATH, "dang": DANG_SPEC_PATH, "dean": DEAN_SPEC_PATH}


@dataclass
class RoleRule:
    key: str
    label: str
    profile: str = "nd30"
    size: list[float] | None = None
    fix_size: float | None = None
    bold: Any = "any"
    italic: Any = "any"
    underline: Any = "any"
    caps: Any = "any"
    align: str = "any"
    first_line_indent_cm: list[float] | None = None
    body_like: bool = False
    line_spacing: list[float] | None = None      # giãn dòng riêng của vai trò (lines, kiểu Multiple)
    fix_line_spacing: float | None = None
    source: str = ""
    verified: bool = True

    @property
    def severity(self) -> str:
        """lỗi = quy định chính thức (NĐ 30 hoặc Đảng) đã đối chiếu; lỗi_cần_đối_chiếu; cảnh_báo = quy ước bổ sung."""
        if self.profile == "convention":
            return "canh_bao"
        return "loi" if self.verified else "loi_can_doi_chieu"


@dataclass
class Spec:
    raw: dict
    roles: dict[str, RoleRule] = field(default_factory=dict)

    @property
    def page(self) -> dict:
        return self.raw["page"]

    @property
    def body(self) -> dict:
        return self.raw["body"]

    @property
    def fix(self) -> dict:
        return self.raw.get("fix", {})

    @property
    def font_name(self) -> str:
        return self.page["font"]["name"]

    def source_title(self, sid: str) -> str:
        for s in self.raw.get("meta", {}).get("sources", []):
            if s.get("id") == sid:
                return s.get("title", sid)
        return sid


# ------------------------------------------------------------------ quy chuẩn mã hoá
# Tệp quy chuẩn trong kho được mã hoá AES-256-GCM: config/<tên>.yaml.enc. Khoá đặt ở biến môi trường
# ND30_SPEC_KEY (chuỗi base64 32 byte) hoặc tệp chỉ ra bởi ND30_SPEC_KEY_FILE. Có tệp .yaml rõ thì dùng tệp rõ.
# Tạo khoá / mã hoá / giải mã để sửa: python tools/spec_crypt.py --help
ENC_MAGIC = b"ND30ENC1"


class SpecKeyError(RuntimeError):
    pass


def spec_key() -> bytes:
    k = (os.getenv("ND30_SPEC_KEY") or "").strip()
    kf = os.getenv("ND30_SPEC_KEY_FILE")
    if not k and kf and Path(kf).is_file():
        k = Path(kf).read_text(encoding="utf-8").strip()
    if not k:
        raise SpecKeyError("Thiếu khoá giải mã quy chuẩn: đặt biến môi trường ND30_SPEC_KEY (xem tools/spec_crypt.py)")
    try:
        key = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
    except ValueError as e:
        raise SpecKeyError("ND30_SPEC_KEY không hợp lệ (phải là base64 của 32 byte)") from e
    if len(key) != 32:
        raise SpecKeyError("ND30_SPEC_KEY không hợp lệ (phải là base64 của 32 byte)")
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return ENC_MAGIC + nonce + AESGCM(key).encrypt(nonce, data, ENC_MAGIC)


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(ENC_MAGIC):
        raise SpecKeyError("Tệp quy chuẩn mã hoá không đúng định dạng")
    nonce, ct = blob[len(ENC_MAGIC):len(ENC_MAGIC) + 12], blob[len(ENC_MAGIC) + 12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, ENC_MAGIC)
    except InvalidTag as e:
        raise SpecKeyError("Sai khoá ND30_SPEC_KEY: không giải mã được quy chuẩn") from e


def read_spec_text(p: Path) -> str:
    """Nội dung tệp quy chuẩn: tệp rõ nếu có, nếu không thì giải mã <tệp>.enc."""
    if p.is_file():
        return p.read_text(encoding="utf-8")
    enc = p.with_name(p.name + ".enc")
    if enc.is_file():
        return decrypt_bytes(enc.read_bytes(), spec_key()).decode("utf-8")
    raise FileNotFoundError(str(p))


def spec_exists(p: str | Path) -> bool:
    p = Path(p)
    return p.is_file() or p.with_name(p.name + ".enc").is_file()


def load_raw(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_SPEC_PATH
    text = read_spec_text(p)
    return json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)


# ------------------------------------------------------------------ ẩn quy chuẩn gốc/nguồn khỏi người dùng
HIDDEN_KEYS = {"source", "sources", "url", "verified"}


def _hidden(k) -> bool:
    return isinstance(k, str) and (k in HIDDEN_KEYS or k == "note" or k.startswith("note_"))


def public_raw(obj):
    """Bản sao bỏ các trường nguồn/căn cứ (source, sources, url, verified, note*) để trả cho giao diện."""
    if isinstance(obj, dict):
        return {k: public_raw(v) for k, v in obj.items() if not _hidden(k)}
    if isinstance(obj, list):
        return [public_raw(v) for v in obj]
    return obj


def restore_hidden(raw, base):
    """Ghép lại các trường nguồn đã ẩn (lấy từ quy chuẩn gốc) vào bộ thông số người dùng gửi lên."""
    if isinstance(raw, dict) and isinstance(base, dict):
        out = {k: restore_hidden(v, base.get(k)) for k, v in raw.items()}
        for k, v in base.items():
            if _hidden(k) and k not in out:
                out[k] = copy.deepcopy(v)
        return out
    return raw


def _num(x, name):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"{name}: phải là số")
    return float(x)


def normalize_raw(raw: dict) -> list[str]:
    """Kiểm tra kiểu dữ liệu và tự mở rộng khoảng cho phép nếu giá trị sửa nằm ngoài khoảng.
    Trả về danh sách ghi chú điều chỉnh."""
    notes = []
    pg = raw.get("page", {})
    for side, m in (pg.get("margins_mm") or {}).items():
        if not isinstance(m, dict) or "range" not in m:
            continue
        lo, hi = (_num(v, f"lề {side}") for v in m["range"])
        fix = _num(m.get("fix", lo), f"lề {side}")
        if lo > hi:
            lo, hi = hi, lo
        if not lo <= fix <= hi:
            notes.append(f"Lề {side}: mở rộng khoảng cho phép để chứa giá trị sửa {fix:g} mm")
            lo, hi = min(lo, fix), max(hi, fix)
        m["range"], m["fix"] = [lo, hi], fix
    b = raw.get("body", {})
    if b:
        if b.get("line_spacing_mode") == "exact_pt":
            if b.get("line_spacing_pt"):
                lo, hi = (_num(v, "giãn dòng (pt)") for v in b["line_spacing_pt"])
                fx = _num(b.get("fix_line_spacing_pt", (lo + hi) / 2), "giãn dòng (pt)")
                if not lo <= fx <= hi:
                    notes.append(f"Giãn dòng (pt): mở rộng khoảng cho phép để chứa {fx:g}")
                    lo, hi = min(lo, fx), max(hi, fx)
                b["line_spacing_pt"], b["fix_line_spacing_pt"] = [lo, hi], fx
        else:
            for a, c in (("line_spacing_min", "line_spacing_max"),):
                lo, hi = _num(b[a], "giãn dòng"), _num(b[c], "giãn dòng")
                fx = _num(b.get("fix_line_spacing", lo), "giãn dòng")
                if not lo <= fx <= hi:
                    notes.append(f"Giãn dòng: mở rộng khoảng cho phép để chứa {fx:g}")
                    lo, hi = min(lo, fx), max(hi, fx)
                b[a], b[c], b["fix_line_spacing"] = lo, hi, fx
        if b.get("first_line_indent_cm"):
            lo, hi = (_num(v, "lùi đầu dòng") for v in b["first_line_indent_cm"])
            fx = _num(b.get("fix_first_line_indent_cm", hi), "lùi đầu dòng")
            if not lo <= fx <= hi:
                notes.append(f"Lùi đầu dòng: mở rộng khoảng cho phép để chứa {fx:g} cm")
                lo, hi = min(lo, fx), max(hi, fx)
            b["first_line_indent_cm"], b["fix_first_line_indent_cm"] = [lo, hi], fx
        sp = _num(b.get("fix_space_before_pt", 6), "khoảng cách trước") + _num(b.get("fix_space_after_pt", 0), "khoảng cách sau")
        if sp < _num(b.get("paragraph_spacing_min_pt", 6), "khoảng cách đoạn"):
            notes.append("Khoảng cách đoạn: giá trị sửa nhỏ hơn mức tối thiểu – đã hạ mức tối thiểu")
            b["paragraph_spacing_min_pt"] = sp
    for key, r in (raw.get("roles") or {}).items():
        if not isinstance(r, dict):
            raise ValueError(f"role {key}: sai cấu trúc")
        for tog in ("bold", "italic", "caps"):
            if r.get(tog) not in (True, False, "any", None):
                raise ValueError(f"{key}.{tog}: chỉ nhận true/false/any")
        if r.get("align") not in (None, "any", "left", "right", "center", "justify"):
            raise ValueError(f"{key}.align: giá trị không hợp lệ")
        if r.get("size"):
            lo, hi = (_num(v, f"{key}.size") for v in r["size"])
            if lo > hi:
                lo, hi = hi, lo
            fx = _num(r.get("fix_size") or hi, f"{key}.fix_size")
            if not lo <= fx <= hi:
                notes.append(f"{r.get('label', key)}: mở rộng khoảng cỡ chữ để chứa {fx:g}")
                lo, hi = min(lo, fx), max(hi, fx)
            r["size"], r["fix_size"] = [lo, hi], fx
        if r.get("first_line_indent_cm"):
            r["first_line_indent_cm"] = [_num(v, f"{key}.indent") for v in r["first_line_indent_cm"]]
        if r.get("line_spacing"):
            lo, hi = sorted(_num(v, f"{key}.line_spacing") for v in r["line_spacing"])
            fx = _num(r.get("fix_line_spacing") or hi, f"{key}.fix_line_spacing")
            if not lo <= fx <= hi:
                notes.append(f"{r.get('label', key)}: mở rộng khoảng giãn dòng để chứa {fx:g}")
                lo, hi = min(lo, fx), max(hi, fx)
            r["line_spacing"], r["fix_line_spacing"] = [lo, hi], fx
    return notes


def build_spec(raw: dict, skip_conventions: bool = False) -> Spec:
    raw = copy.deepcopy(raw)
    spec = Spec(raw=raw)
    body = raw.get("body", {})
    for key, r in (raw.get("roles") or {}).items():
        rule = RoleRule(
            key=key,
            label=r.get("label", key),
            profile=r.get("profile", "nd30"),
            size=r.get("size"),
            fix_size=r.get("fix_size"),
            bold=r.get("bold", "any"),
            italic=r.get("italic", "any"),
            underline=r.get("underline", "any"),
            caps=r.get("caps", "any"),
            align=r.get("align", "any"),
            first_line_indent_cm=r.get("first_line_indent_cm"),
            body_like=bool(r.get("body_like", False)),
            line_spacing=r.get("line_spacing"),
            fix_line_spacing=r.get("fix_line_spacing"),
            source=r.get("source", ""),
            verified=bool(r.get("verified", True)),
        )
        if rule.body_like and rule.first_line_indent_cm is None:
            rule.first_line_indent_cm = body.get("first_line_indent_cm")
        if skip_conventions and rule.profile == "convention":
            # Chỉ còn kiểm tra phông chữ cho các thành phần theo quy ước
            rule.size = None
            rule.bold = rule.italic = rule.underline = rule.caps = "any"
            rule.align = "any"
            rule.first_line_indent_cm = None
            rule.line_spacing = None
        spec.roles[key] = rule
    if "other" not in spec.roles:
        spec.roles["other"] = RoleRule(key="other", label="Khác")
    return spec


def load_spec(path: str | Path | None = None, skip_conventions: bool = False) -> Spec:
    return build_spec(load_raw(path), skip_conventions)
