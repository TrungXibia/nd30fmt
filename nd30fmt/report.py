"""Xuất báo cáo so sánh định dạng (HTML tự chứa + JSON)."""
from __future__ import annotations

import html
import json
from datetime import datetime

from .check import SEV_LABEL, summarize

FIELD_VI = {
    "font": "Phông chữ", "color": "Màu chữ", "size": "Cỡ chữ", "bold": "Đậm", "italic": "Nghiêng",
    "caps": "In hoa/thường", "align": "Căn lề đoạn", "indent": "Lùi đầu dòng", "spacing": "Khoảng cách đoạn",
    "line_spacing": "Giãn dòng", "margin": "Lề trang", "paper": "Khổ giấy", "orientation": "Hướng trang",
    "page_number": "Số trang",
    "heading_applied": "Gán cấp đề mục (Heading) cho mục lục", "heading_removed": "Gỡ cấp đề mục gán nhầm vào nội dung",
}
METHOD_VI = {"regex": "quy tắc", "context": "ngữ cảnh", "heuristic": "heuristic", "skip": "-"}

NOT_CHECKED = [
    "Đường kẻ ngang dưới Tiêu ngữ, tên cơ quan ban hành, trích yếu (thường là hình vẽ, không đọc được bằng python-docx).",
    "Vị trí tuyệt đối của các ô thể thức trên trang, dấu, chữ ký số, chỉ dẫn độ mật/độ khẩn.",
    "Quy tắc viết hoa (Phụ lục II NĐ 30) và nội dung chữ (chính tả, số 0 trước ngày/tháng).",
    "Chú thích cuối trang (footnote), text box, nội dung trong hình ảnh.",
]

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6b6b70;--line:#e3e3e6;--err:#b42318;--warn:#b54708;--ok:#067647;--chip:#f2f2f4}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececef;--mut:#a0a0a8;--line:#2e2e33;--err:#f97066;--warn:#fdb022;--ok:#47cd89;--chip:#232327}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.mut{color:var(--mut)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
.card{border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:24px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--bg)}.wrap{overflow-x:auto}
.sev-loi{color:var(--err);font-weight:600}.sev-loi_can_doi_chieu{color:var(--err)}.sev-canh_bao{color:var(--warn)}
.ok{color:var(--ok);font-weight:600}.chip{background:var(--chip);border-radius:6px;padding:1px 6px;font-size:12px;white-space:nowrap}
details{border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}summary{cursor:pointer;font-weight:600}
code{font-size:12px}
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def build_json(result: dict) -> dict:
    return result


def render_html(result: dict) -> str:
    r = result
    before = summarize_dicts(r["violations"])
    after = summarize_dicts(r.get("violations_after") or []) if r.get("violations_after") is not None else None
    roles = {d["pid"]: d for d in r["roles"]}
    labels = r.get("role_labels", {})
    paras = {p["id"]: p for p in r["paragraphs"]}

    cards = [
        ("Lỗi phát hiện", before["total"]),
        ("Đoạn có lỗi", before["paragraphs_with_errors"]),
        ("Lỗi theo quy định", before["by_severity"].get("loi", 0) + before["by_severity"].get("loi_can_doi_chieu", 0)),
        ("Cảnh báo quy ước", before["by_severity"].get("canh_bao", 0)),
    ]
    if after is not None:
        cards.append(("Còn lại sau khi sửa", after["total"]))
    if before.get("ignored"):
        cards.append(("Đã bỏ qua (phát hiện nhầm)", before["ignored"]))
    cards_html = "".join(f'<div class="card"><span class="mut">{_e(k)}</span><b>{_e(v)}</b></div>' for k, v in cards)

    # --- trang ---
    sec_rows = "".join(
        f"<tr><td>{s['idx'] + 1}</td><td>{s['width_mm']:.0f} × {s['height_mm']:.0f}</td><td>{_e(s['orientation'])}</td>"
        f"<td>{s['top_mm']:.1f} / {s['bottom_mm']:.1f} / {s['left_mm']:.1f} / {s['right_mm']:.1f}</td>"
        f"<td>{'lề trên' if s['has_page_field_header'] else ('lề dưới' if s['has_page_field_footer'] else 'không có')}"
        f"{' – ẩn trang 1' if s['title_pg'] else ''}</td></tr>"
        for s in r["sections"])

    # --- lỗi ---
    after_keys = {v.get("key") or f"{v['target']}|{v['field']}" for v in (r.get("violations_after") or []) if not v.get("ignored")}
    rows = []
    for n, v in enumerate(r["violations"], 1):
        d = roles.get(v["target"], {})
        how = ""
        if d:
            how = METHOD_VI.get(d.get("method"), d.get("method"))
        chip = f'<br><span class="chip">{_e(how)}</span>' if how else ""
        if v.get("ignored"):
            status = '<span class="mut">đã bỏ qua</span>'
        elif after is None:
            status = '<span class="mut">chưa sửa</span>'
        elif (v.get("key") or f"{v['target']}|{v['field']}") in after_keys:
            status = '<span class="sev-loi">còn lỗi</span>'
        else:
            status = '<span class="ok">đã sửa</span>'
        rows.append(
            f"<tr><td>{n}</td><td><code>{_e(v['target'])}</code></td>"
            f"<td>{_e(labels.get(v['role'], v['role']))}{chip}</td>"
            f"<td>{_e(v.get('excerpt'))}</td><td>{_e(FIELD_VI.get(v['field'], v['field']))}</td>"
            f"<td>{_e(v['expected'])}</td><td>{_e(v['actual'])}</td>"
            f"<td class=\"sev-{_e(v['severity'])}\">{_e(SEV_LABEL.get(v['severity'], v['severity']))}</td>"
            f"<td>{status}</td></tr>")
    viol_html = ("<div class=wrap><table><thead><tr><th>#</th><th>Đoạn</th><th>Thành phần</th><th>Trích đoạn</th>"
                 "<th>Thuộc tính</th><th>Yêu cầu</th><th>Thực tế</th><th>Mức độ</th><th>Trạng thái</th>"
                 "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>") if rows else \
        '<p class="ok">Không phát hiện lỗi định dạng.</p>'

    # --- cần kiểm tra ---
    review = [d for d in r["roles"] if d.get("method") == "heuristic" and
              (d.get("confidence", 1) < r.get("min_role_confidence", 0.5) or "kiểm tra" in (d.get("note") or ""))]
    review_rows = "".join(
        f"<tr><td><code>{_e(d['pid'])}</code></td><td>{_e(paras.get(d['pid'], {}).get('text', '')[:120])}</td>"
        f"<td>{_e(labels.get(d['role'], d['role']))}</td><td>{_e(', '.join(f'{k}: {v:.2f}' for k, v in d.get('scores', {}).items()))}</td></tr>"
        for d in review)
    review_html = (f"<div class=wrap><table><thead><tr><th>Đoạn</th><th>Nội dung</th><th>Vai trò tạm</th><th>Điểm</th></tr></thead>"
                   f"<tbody>{review_rows}</tbody></table></div>") if review else '<p class="mut">Không có.</p>'

    # --- vai trò ---
    role_rows = "".join(
        f"<tr><td><code>{_e(d['pid'])}</code></td><td>{_e(labels.get(d['role'], d['role']))}</td>"
        f"<td>{_e(METHOD_VI.get(d['method'], d['method']))}</td><td>{d.get('confidence', 0):.2f}</td>"
        f"<td>{_e(paras.get(d['pid'], {}).get('text', '')[:110])}</td></tr>"
        for d in r["roles"] if d["role"] != "empty")

    not_checked = "".join(f"<li>{_e(x)}</li>" for x in NOT_CHECKED)
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Báo cáo định dạng – {_e(r['file'])}</title>
<style>{CSS}</style></head><body><main>
<h1>Báo cáo so sánh định dạng</h1>
<div class="mut">{_e(r['file'])} · {_e(r['generated_at'])}</div>
<div class="cards">{cards_html}</div>
<h2>Trang và số trang</h2>
<div class=wrap><table><thead><tr><th>Section</th><th>Khổ (mm)</th><th>Hướng</th><th>Lề trên/dưới/trái/phải (mm)</th><th>Số trang</th></tr></thead>
<tbody>{sec_rows}</tbody></table></div>
<h2>Chi tiết lỗi</h2>{viol_html}
<h2>Đoạn cần người kiểm tra (vai trò chưa chắc chắn)</h2>{review_html}
<details><summary>Vai trò của toàn bộ đoạn ({len(r['roles'])})</summary><div class=wrap><table><thead><tr><th>Đoạn</th><th>Vai trò</th><th>Cách xác định</th><th>Tin cậy</th><th>Nội dung</th></tr></thead><tbody>{role_rows}</tbody></table></div></details>
<h2>Chưa kiểm tra tự động</h2><ul>{not_checked}</ul>
<p class="mut">Mức độ: "Lỗi (NĐ 30)" = trái quy định Phụ lục I NĐ 30/2020/NĐ-CP; "cần đối chiếu" = quy định điền theo PL I nhưng chưa đối chiếu bản gốc; "Cảnh báo (quy ước)" = quy ước cho báo cáo dài, không phải quy định bắt buộc của NĐ 30.</p>
</main></body></html>"""


def summarize_dicts(viols: list[dict]) -> dict:
    class V:  # adapter cho summarize()
        def __init__(self, d):
            self.__dict__.update(d)
    return summarize([V(v) for v in viols])


def write_reports(result: dict, html_path: str | None, json_path: str | None):
    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(result))
    if json_path:
        # json.dumps không indent dùng bộ mã hoá C: nhanh hơn ~5 lần với văn bản dài
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
