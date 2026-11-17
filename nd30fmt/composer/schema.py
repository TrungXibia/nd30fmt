"""Nạp schema mẫu văn bản (config/templates/nd30/*.json, hd05/*.json).

Schema là nguồn quyết định cuối cùng cho bố cục, trường nhập, kiểm tra và xuất Word của trình soạn
thảo. Không có thông số trình bày nào được viết cứng trong HTML/JS: giao diện nhận toàn bộ qua
GET /api/compose/templates và bố cục qua POST /api/compose/layout.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .. import jobs

TEMPLATE_DIR = Path(jobs.BASE_SPEC["nd30"]).parent / "templates"
STANDARDS = ("nd30", "hd05")


class SchemaError(ValueError):
    pass


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:  # pragma: no cover - file giao kèm
        raise SchemaError(f"Không đọc được schema {path.name}: {e}") from e


@lru_cache(maxsize=1)
def _nd30_bundle() -> dict:
    base = TEMPLATE_DIR / "nd30"
    fmt = _read(base / "_format.json")
    common = _read(base / "_fields.json")["fields"]
    catalog = _read(base / "catalog.json")
    templates = {}
    for p in sorted(base.glob("mau_*.json")):
        t = _read(p)
        fields = []
        for f in t["fields"]:
            if isinstance(f, str):
                if f not in common:
                    raise SchemaError(f"{p.name}: trường chung '{f}' chưa khai báo trong _fields.json")
                fields.append({"id": f, **common[f]})
            else:
                fields.append(f)
        t["fields"] = fields
        t["file"] = f"config/templates/nd30/{p.name}"
        templates[t["id"]] = t
    _check_nd30(fmt, catalog, templates)
    return {"format": fmt, "catalog": catalog, "templates": templates}


def _check_nd30(fmt: dict, catalog: dict, templates: dict) -> None:
    expected = [f"1.{i}" for i in range(1, 11)]
    if sorted(templates, key=lambda x: int(x.split(".")[1])) != expected:
        raise SchemaError("Thiếu schema Mẫu 1.1–1.10")
    ids = set()
    for t in catalog["types"]:
        ids.add(t["id"])
        if t["template_status"] == "supported" and t["template"] not in templates:
            raise SchemaError(f"Loại {t['id']} trỏ tới mẫu chưa có: {t['template']}")
    for num, t in templates.items():
        for d in t["doc_types"]:
            if d not in ids:
                raise SchemaError(f"Mẫu {num}: loại {d} không có trong danh mục")
            owner = next(x for x in catalog["types"] if x["id"] == d)
            if owner["template"] != num:
                raise SchemaError(f"Loại {d}: danh mục ghi mẫu {owner['template']} nhưng schema mẫu {num} khai báo")
        known = {f["id"] for f in t["fields"]}
        for comp in t["layout"]:
            for key in ("field", "list_field"):
                if key in comp and comp[key] not in known:
                    raise SchemaError(f"Mẫu {num}: khối {comp['kind']} dùng trường chưa khai báo {comp[key]}")
    for role, r in fmt["roles"].items():
        if "size" in r and not (isinstance(r["size"], list) and len(r["size"]) == 2 and r["size"][0] <= r["size"][1]):
            raise SchemaError(f"Vai trò {role}: khoảng cỡ chữ không hợp lệ")


@lru_cache(maxsize=1)
def _hd05_bundle() -> dict:
    base = TEMPLATE_DIR / "hd05"
    t = _read(base / "van_ban_dang.json")
    t["file"] = "config/templates/hd05/van_ban_dang.json"
    return {"template": t, "catalog": _read(base / "catalog.json")}


def reload() -> None:
    _nd30_bundle.cache_clear()
    _hd05_bundle.cache_clear()


def nd30_format() -> dict:
    return copy.deepcopy(_nd30_bundle()["format"])


def catalog(standard: str) -> dict:
    if standard == "nd30":
        return copy.deepcopy(_nd30_bundle()["catalog"])
    if standard == "hd05":
        return copy.deepcopy(_hd05_bundle()["catalog"])
    raise SchemaError("Chỉ hỗ trợ chuẩn nd30 (NĐ 30/2020) và hd05 (văn bản Đảng)")


def type_info(standard: str, type_id: str) -> dict:
    for t in catalog(standard)["types"]:
        if t["id"] == type_id:
            return t
    raise SchemaError(f"Loại văn bản không có trong danh mục {standard}: {type_id}")


def template_for(standard: str, type_id: str) -> dict:
    info = type_info(standard, type_id)
    if info["template_status"] != "supported":
        raise SchemaError(f"{info['label']}: {info.get('status_note') or 'chưa có mẫu chuẩn'}")
    if standard == "nd30":
        return copy.deepcopy(_nd30_bundle()["templates"][info["template"]])
    return copy.deepcopy(_hd05_bundle()["template"])


def party_format() -> dict:
    """Thông số Đảng lấy từ dang_spec.yaml đang hiệu lực (cùng nguồn với bộ kiểm tra)."""
    raw = jobs.default_raw("dang")
    spec = jobs.build_spec(raw)
    t = _hd05_bundle()["template"]
    roles = {}
    for name, key in t["role_map"].items():
        r = spec.roles[key]
        size = list(r.size or [14, 14])
        roles[name] = {"size": size, "default": float(r.fix_size or size[0]), "bold": r.bold is True,
                       "italic": r.italic is True, "caps": r.caps is True, "underline": bool(r.underline),
                       "align": r.align, "source": r.source}
    m = spec.page["margins_mm"]
    b = spec.body
    pn = spec.page["page_number"]
    return {
        "name": raw["meta"]["name"], "version": raw["meta"].get("version", ""),
        "source": raw["meta"]["sources"][-1]["title"],
        "margins_mm": {s: {"range": list(m[s].get("range") or [m[s]["fix"], m[s]["fix"]]), "default": float(m[s]["fix"])}
                       for s in ("top", "bottom", "left", "right")},
        "page_number": {"size": float(pn["fix_size"]), "distance_from_top_mm": float(pn.get("distance_from_top_mm", 10)),
                        "hide_first_page": bool(pn["hide_first_page"])},
        "body": {"size": {"range": list(b["size"]), "default": float(b["fix_size"])},
                 "first_line_indent_cm": {"range": list(b["first_line_indent_cm"]), "default": float(b["fix_first_line_indent_cm"])},
                 "space_before_pt": {"range": [float(b.get("paragraph_spacing_min_pt", 6)), 12], "default": float(b["fix_space_before_pt"])},
                 "space_after_pt": {"default": float(b["fix_space_after_pt"])},
                 "line_spacing_pt": {"range": list(b["line_spacing_pt"]), "default": float(b["fix_line_spacing_pt"])}},
        "roles": roles,
    }


def public_templates() -> dict:
    """Toàn bộ schema cho giao diện (form động, cài đặt, danh mục)."""
    b = _nd30_bundle()
    h = _hd05_bundle()
    return {
        "nd30": {"format": b["format"], "catalog": b["catalog"], "templates": b["templates"]},
        "hd05": {"format": party_format(), "catalog": h["catalog"], "template": h["template"]},
    }
