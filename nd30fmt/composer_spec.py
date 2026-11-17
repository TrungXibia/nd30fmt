"""Projection of the active Party checker specification for the drafting UI."""
from __future__ import annotations

from . import jobs

PARTY_ROLES = {
    "title": "dang_tieu_de",
    "superior": "dang_co_quan_cap_tren",
    "issuer": "dang_co_quan_ban_hanh",
    "number": "dang_so_ky_hieu",
    "date": "dang_dia_danh_thoi_gian",
    "document_type": "dang_the_loai",
    "summary": "dang_trich_yeu",
    "letter_summary": "dang_trich_yeu_cong_van",
    "body": "dang_body",
    "sign_authority": "dang_quyen_han_ky",
    "sign_position": "dang_chuc_vu_ky",
    "sign_name": "dang_ho_ten_ky",
    "recipients_label": "dang_noi_nhan_label",
    "recipient": "dang_noi_nhan_item",
    "part_label": "dang_phan_chuong_label",
    "part_title": "dang_phan_chuong_title",
    "section_label": "dang_muc_label",
    "section_title": "dang_muc_title",
    "article": "dang_dieu",
}


def party_composer_spec() -> dict:
    """Read the same effective YAML (including saved overrides) used by the checker."""
    raw = jobs.default_raw("dang")
    spec = jobs.build_spec(raw)  # reject invalid custom spec rather than silently drafting to another standard
    margins = spec.page["margins_mm"]
    roles = {}
    for name, key in PARTY_ROLES.items():
        rule = spec.roles[key]
        roles[name] = {
            "size": list(rule.size or []), "fix_size": rule.fix_size,
            "bold": rule.bold, "italic": rule.italic,
            "caps": rule.caps, "align": rule.align,
            "underline": rule.underline,
        }
    body = spec.body
    return {
        "name": raw["meta"]["name"], "version": raw["meta"].get("version", ""),
        "source": raw["meta"]["sources"][-1]["title"],
        "margins_mm": {side: float(margins[side]["fix"]) for side in ("top", "bottom", "left", "right")},
        "page_number": {"size": float(spec.page["page_number"]["fix_size"]),
                        "distance_from_top_mm": float(spec.page["page_number"].get("distance_from_top_mm",10)),
                        "hide_first_page": bool(spec.page["page_number"]["hide_first_page"])},
        "body": {"indent_cm": float(body["fix_first_line_indent_cm"]),
                 "line_spacing_pt": float(body["fix_line_spacing_pt"]),
                 "space_before_pt": float(body["fix_space_before_pt"]),
                 "space_after_pt": float(body["fix_space_after_pt"])},
        "roles": roles,
    }
