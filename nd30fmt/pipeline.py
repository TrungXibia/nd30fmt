"""Điều phối: trích xuất -> xác định vai trò (quy tắc + heuristic) -> so sánh -> sửa -> kiểm tra lại -> báo cáo."""
from __future__ import annotations

from pathlib import Path

from .check import check_document, mark_ignored, summarize
from .extract import ExtractedDoc, extract
from .fix import apply_fixes
from .manual_format import apply_manual_format
from .ooxml_order import save_docx
from .report import now_str, write_reports
from .roles import RoleDecision, mark_zones, propose_roles, propose_roles_dang, propose_roles_dean
from .spec import Spec


def analyze_roles(ex: ExtractedDoc, standard: str = "nd30") -> list[RoleDecision]:
    proposer = {"dang": propose_roles_dang, "dean": propose_roles_dean}.get(standard, propose_roles)
    return proposer(ex)


def evaluate(src: Path, ex: ExtractedDoc, decisions: list[RoleDecision], spec: Spec,
             out_dir: Path, fix: bool = True, write: bool = True, with_preview: bool = False,
             ignored=None, manual_format=None, spell=None) -> dict:
    """So sánh + (tùy chọn) sửa + kiểm tra lại + báo cáo. `ex` phải là bản trích xuất mới của file gốc."""
    stem = src.stem
    if not any(t.get("zone") for t in ex.tables_meta):
        mark_zones(ex)
    viols = check_document(ex, decisions, spec)
    mark_ignored(viols, ignored)
    result = {
        "file": src.name,
        "generated_at": now_str(),
        "min_role_confidence": float(spec.fix.get("min_role_confidence", 0.5)),
        "sections": [s.to_json() for s in ex.sections],
        "paragraphs": [p.to_json() for p in ex.paragraphs],
        "roles": [d.to_json() for d in decisions if d is not None],
        "role_labels": {k: r.label for k, r in spec.roles.items()} | {"empty": "(trống)", "page": "Trang in"},
        "violations": [v.to_json() for v in viols],
        "summary": summarize(viols),
    }
    preview = {"original": ex.preview_json()} if with_preview else None

    if fix:
        fixed_path = out_dir / f"{stem}_da_sua.docx"
        result["fix_stats"] = apply_fixes(ex, decisions, viols, spec, str(fixed_path), ignored)
        ex2 = extract(str(fixed_path))
        if manual_format:
            notes = apply_manual_format(ex2, manual_format)
            if notes:
                result.setdefault("manual_notes", []).extend(notes)
            save_docx(ex2.doc, fixed_path)
            ex2 = extract(str(fixed_path))
        if len(ex2.paragraphs) == len(decisions):
            mark_zones(ex2)
            viols2 = check_document(ex2, decisions, spec)
        else:  # phòng xa: số đoạn thay đổi -> xác định lại vai trò
            viols2 = check_document(ex2, propose_roles(ex2), spec)
        mark_ignored(viols2, ignored)
        result["violations_after"] = [v.to_json() for v in viols2]
        result["summary_after"] = summarize(viols2)
        result["fixed_file"] = fixed_path.name
        if spell and spell.get("on"):
            # sửa chính tả SAU khi đã kiểm tra định dạng: chữ đổi màu không bị tính là lỗi màu chữ
            from . import spellword
            result["spell"] = spellword.run_on_fixed(ex2, fixed_path, out_dir, stem, spell)
            ex2 = extract(str(fixed_path))
        remain = {v.key for v in viols2 if not v.ignored}
        for v in result["violations"]:
            v["fixed"] = not v["ignored"] and v["key"] not in remain
        if with_preview:
            preview["fixed"] = ex2.preview_json()

    if write:
        html_path = out_dir / f"{stem}_bao_cao.html"
        json_path = out_dir / f"{stem}_bao_cao.json"
        write_reports(result, str(html_path), str(json_path))
        result["report_html"] = html_path.name
        result["report_json"] = json_path.name
    if with_preview:
        result["preview"] = preview
    return result


def process(path: str, spec: Spec, out_dir: str | None = None, fix: bool = True,
            write: bool = True, standard: str = "nd30") -> dict:
    src = Path(path)
    out = Path(out_dir) if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    ex = extract(str(src))
    decisions = analyze_roles(ex, standard)
    return evaluate(src, ex, decisions, spec, out, fix=fix, write=write)
