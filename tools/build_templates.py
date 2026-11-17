"""Sinh config/templates/nd30/*.json và hd05/*.json (chạy một lần; JSON là nguồn chuẩn giao kèm)."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "config" / "templates"
PL1 = "NĐ 30/2020/NĐ-CP, Phụ lục I"
PL3 = "NĐ 30/2020/NĐ-CP, Phụ lục III"


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- định dạng chung NĐ30
FORMAT = {
    "standard": "nd30",
    "name": "Nghị định 30/2020/NĐ-CP – văn bản hành chính",
    "version": "40.0",
    "sources": [
        {"id": "ND30_PL1", "title": "Nghị định 30/2020/NĐ-CP ngày 05/3/2020, Phụ lục I – Thể thức, kỹ thuật trình bày văn bản hành chính"},
        {"id": "ND30_PL3", "title": "Nghị định 30/2020/NĐ-CP, Phụ lục III – Bảng chữ viết tắt và Mẫu 1.1–1.10"},
        {"id": "MAU_FILES", "title": "Mẫu 1.1–1.10 (Phụ lục III NĐ 30/2020/NĐ-CP) – vị trí tương đối các khối và độ rộng cột bảng"},
    ],
    "rule": "Cỡ chữ, kiểu chữ theo Phụ lục I (Mục II, III, V); vị trí các khối theo Mẫu 1.1–1.10.",
    "page": {
        "size_mm": [210, 297],
        "orientation": "portrait",
        "margins_mm": {"top": {"range": [20, 25], "default": 20}, "bottom": {"range": [20, 25], "default": 20},
                        "left": {"range": [30, 35], "default": 30}, "right": {"range": [15, 20], "default": 15}},
        "margins_source": f"{PL1} Mục I.3; giá trị mặc định = lề đo được trong file Mẫu 1.1–1.10 (T20 B20 L30 R15)",
        "font": "Times New Roman",
        "font_source": f"{PL1} Mục I.4",
        "header_distance_mm": 12.7,
        "header_distance_source": "Khoảng cách đầu trang đo được trong file mẫu (12,7 mm); số trang nằm trong lề trên theo PL I Mục I.7",
        "page_number": {"align": "center", "position": "header", "hide_first_page": True, "role": "so_trang",
                         "source": f"{PL1} Mục I.7"},
    },
    "body": {
        "size": {"range": [13, 14], "default": 14},
        "align": "justify",
        "first_line_indent_cm": {"allowed": [1.0, 1.27], "default": 1.27},
        "space_before_pt": {"range": [6, 12], "default": 6, "note": "tối thiểu 6pt"},
        "space_after_pt": {"default": 0},
        "line_spacing": {"range": [1.0, 1.5], "default": 1.5, "note": "tối thiểu dòng đơn, tối đa 1,5 lines"},
        "source": f"{PL1} Mục II.6.e",
    },
    "size_profiles": {
        "note": "Chú thích 1 bảng Mục V PL I: cỡ chữ trong cùng văn bản tăng/giảm phải thống nhất (QH 13–TN 14–ngày 14 hoặc QH 12–TN 13–ngày 13).",
        "14": {"quoc_hieu": 13, "tieu_ngu": 14, "co_quan_chu_quan": 13, "co_quan_ban_hanh": 13, "so_ky_hieu": 13,
               "dia_danh_ngay": 14, "ten_loai": 14, "trich_yeu": 14, "trich_yeu_cong_van": 13, "body": 14,
               "kinh_gui": 14, "quyen_han_ky": 14, "chuc_vu_ky": 14, "ho_ten_ky": 14, "so_trang": 14},
        "13": {"quoc_hieu": 12, "tieu_ngu": 13, "co_quan_chu_quan": 12, "co_quan_ban_hanh": 12, "so_ky_hieu": 13,
               "dia_danh_ngay": 13, "ten_loai": 13, "trich_yeu": 13, "trich_yeu_cong_van": 12, "body": 13,
               "kinh_gui": 13, "quyen_han_ky": 13, "chuc_vu_ky": 13, "ho_ten_ky": 13, "so_trang": 13},
    },
    "roles": {
        "quoc_hieu": {"size": [12, 13], "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.1.a"},
        "tieu_ngu": {"size": [13, 14], "bold": True, "align": "center", "text": "Độc lập - Tự do - Hạnh phúc",
                     "source": f"{PL1} Mục II.1.b"},
        "co_quan_chu_quan": {"size": [12, 13], "bold": False, "caps": True, "align": "center", "source": f"{PL1} Mục II.2.b"},
        "co_quan_ban_hanh": {"size": [12, 13], "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.2.b"},
        "so_ky_hieu": {"size": [13, 13], "bold": False, "align": "center", "source": f"{PL1} Mục II.3.c"},
        "dia_danh_ngay": {"size": [13, 14], "italic": True, "align": "center", "source": f"{PL1} Mục II.4.c"},
        "ten_loai": {"size": [13, 14], "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.5.b"},
        "trich_yeu": {"size": [13, 14], "bold": True, "align": "center", "source": f"{PL1} Mục II.5.b"},
        "trich_yeu_cong_van": {"size": [12, 13], "bold": False, "align": "center", "space_before_pt": 6,
                               "source": f"{PL1} Mục II.5.b (đoạn 2): sau chữ “V/v”, cách dòng 6pt với số, ký hiệu"},
        "tham_quyen": {"size_role": "body", "bold": True, "caps": True, "align": "center",
                       "source": "Mẫu 1.1–1.3 (dòng THẨM QUYỀN BAN HÀNH: in hoa, đậm, canh giữa – đối chiếu ảnh mẫu); cỡ chữ theo phần lời văn"},
        "can_cu": {"size_role": "body", "italic": True, "align": "justify", "indent": "body",
                   "source": f"{PL1} Mục II.6.a: in thường, nghiêng, mỗi căn cứ một dòng, cuối dòng “;”, dòng cuối “.”"},
        "chuyen_tiep": {"size_role": "body", "bold": True, "align": "center",
                        "source": "Mẫu 1.1 (QUYẾT NGHỊ:), Mẫu 1.2–1.3 (QUYẾT ĐỊNH:) – canh giữa, đậm theo ảnh mẫu"},
        "body": {"size_role": "body", "align": "justify", "indent": "body", "source": f"{PL1} Mục II.6.e"},
        "phan_label": {"size_role": "body", "bold": True, "align": "center", "numbering": "roman", "source": f"{PL1} Mục II.6.đ"},
        "phan_title": {"size_role": "body", "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.6.đ"},
        "chuong_label": {"size_role": "body", "bold": True, "align": "center", "numbering": "roman", "source": f"{PL1} Mục II.6.đ"},
        "chuong_title": {"size_role": "body", "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.6.đ"},
        "muc_label": {"size_role": "body", "bold": True, "align": "center", "numbering": "arabic", "source": f"{PL1} Mục II.6.đ"},
        "muc_title": {"size_role": "body", "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.6.đ"},
        "dieu": {"size_role": "body", "bold": True, "align": "justify", "indent": "body",
                 "source": f"{PL1} Mục II.6.đ: “Điều n.” + tiêu đề, in thường, đứng, đậm, lùi đầu dòng 1 cm hoặc 1,27 cm"},
        "khoan": {"size_role": "body", "bold": False, "align": "justify", "indent": "body",
                  "bold_if_title": True, "source": f"{PL1} Mục II.6.đ và Mục V.6.b: số “1.” đứng; khoản có tiêu đề: đậm"},
        "diem": {"size_role": "body", "bold": False, "align": "justify", "indent": "body",
                 "source": f"{PL1} Mục II.6.đ: “a)” in thường, đứng"},
        "la_ma": {"size_role": "body", "bold": True, "caps": True, "align": "justify", "indent": "body",
                  "source": f"{PL1} Mục V.6.b: số thứ tự và tiêu đề của mục (I. …) in hoa, đứng, đậm"},
        "bullet": {"size_role": "body", "align": "justify", "indent": "body", "marker": "-",
                   "source": f"{PL1} Mục II.6.e (cỡ, căn đều); dấu gạch đầu dòng “-” như trình bày nơi nhận/kính gửi"},
        "kinh_gui": {"size": [13, 14], "align": "left", "indent_left_twips": 2268,
                     "source": f"{PL1} Mục II.9.d (ô 9a); lề trái 4 cm đo từ Mẫu 1.5"},
        "quyen_han_ky": {"size": [13, 14], "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.7.đ"},
        "chuc_vu_ky": {"size": [13, 14], "bold": True, "caps": True, "align": "center", "source": f"{PL1} Mục II.7.đ, Mục V.7"},
        "ho_ten_ky": {"size": [13, 14], "bold": True, "align": "center", "source": f"{PL1} Mục II.7.đ"},
        "noi_nhan_label": {"size": [12, 12], "bold": True, "italic": True, "align": "left", "text": "Nơi nhận:",
                           "source": f"{PL1} Mục II.9.d (ô 9b)"},
        "noi_nhan_item": {"size": [11, 11], "align": "left", "source": f"{PL1} Mục II.9.d (ô 9b)"},
        "ky_hieu_soan_thao": {"size": [11, 11], "source": f"{PL1} Mục III.3"},
        "lien_he": {"size": [11, 12], "default_size": 11, "align": "left",
                    "source": f"{PL1} Mục III.4: trang thứ nhất, dưới đường kẻ nét liền hết chiều ngang vùng trình bày"},
        "so_trang": {"size": [13, 14], "align": "center", "source": f"{PL1} Mục I.7"},
        "nhan_dien_ky": {"size_role": "body", "bold": True, "caps": True, "align": "center",
                         "source": "Mẫu 1.9 (THƯ KÝ, CHỦ TỌA) – tiêu đề khu vực ký"},
        "xac_nhan": {"size_role": "body", "italic": True, "align": "center",
                     "source": "Mẫu 1.10 – khu vực xác nhận nơi nghỉ phép: nghiêng, canh giữa"},
    },
    "lines": {
        "tieu_ngu": {"length": "text", "source": f"{PL1} Mục II.1.b: độ dài bằng độ dài dòng chữ Tiêu ngữ"},
        "co_quan": {"length": "ratio_of_text", "range": [0.333, 0.5], "default": 0.4,
                    "source": f"{PL1} Mục II.2.b: 1/3 đến 1/2 độ dài dòng chữ, đặt cân đối"},
        "trich_yeu": {"length": "ratio_of_text", "range": [0.333, 0.5], "default": 0.4,
                      "source": f"{PL1} Mục II.5.b: 1/3 đến 1/2 độ dài dòng chữ, đặt cân đối"},
        "lien_he": {"length": "full", "source": f"{PL1} Mục III.4"},
        "docx_rule": "Đường kẻ = viền dưới (w:pBdr/w:bottom) của đoạn văn có lề trái/phải tính theo độ dài; không dùng ký tự ‘-----’, không dùng hình vẽ (shape)",
        "preview_rule": "CSS border-bottom trên khối có cùng độ rộng tính từ bảng độ rộng ký tự Times New Roman",
    },
    "signature": {
        "blank_lines": 4,
        "note": "PL I không quy định khoảng trống chữ ký; mặc định 4 dòng trống, chỉnh được trong Cài đặt.",
        "authorities": ["", "TM.", "Q.", "KT.", "TL.", "TUQ."],
        "source": f"{PL1} Mục II.7.b",
    },
    "noi_nhan": {
        "last_line": "Lưu: VT, {don_vi_soan}.",
        "item_end": ";",
        "source": f"{PL1} Mục II.9.d: mỗi dòng bắt đầu “-”, cuối “;”, dòng cuối “Lưu: VT, …”, kết thúc “.”",
    },
    "number": {
        "pad": 2,
        "format_default": "Số: {so}/{ky_hieu}",
        "source": f"{PL1} Mục II.3: số < 10 thêm 0; giữa số và ký hiệu “/”, giữa nhóm chữ viết tắt “-”, không cách chữ",
    },
    "date": {"format": "{dia_danh}, ngày {dd} tháng {mm} năm {yyyy}", "pad_day_lt10": True, "pad_month_1_2": True,
             "source": f"{PL1} Mục II.4.b: ngày < 10 và tháng 1, 2 thêm số 0"},
    "end_mark": {"text": "/.", "source": "Mẫu 1.1–1.10: kết thúc nội dung bằng “/.”"},
}

# các trường dùng chung (định nghĩa 1 lần, template tham chiếu theo id)
COMMON_FIELDS = {
    "co_quan_chu_quan": {"label": "Cơ quan, tổ chức chủ quản trực tiếp (nếu có)", "type": "text", "caps": True,
                         "group": "header", "default_from": "defaults.co_quan_chu_quan", "note": "Mẫu – ghi chú 1"},
    "co_quan_ban_hanh": {"label": "Cơ quan, tổ chức ban hành", "type": "text", "caps": True, "required": True,
                         "group": "header", "default_from": "defaults.co_quan_ban_hanh", "note": "Mẫu – ghi chú 2"},
    "ma_co_quan": {"label": "Chữ viết tắt tên cơ quan ban hành", "type": "code", "required": True,
                   "group": "header", "default_from": "defaults.ma_co_quan", "note": "Mẫu – ghi chú 3"},
    "so": {"label": "Số văn bản", "type": "number_text", "group": "header", "placeholder": "để trống nếu chưa lấy số"},
    "ky_hieu_tuy_chinh": {"label": "Số và ký hiệu (sửa tay, nếu cần)", "type": "text", "group": "header",
                          "placeholder": "để trống: tự tạo theo mẫu"},
    "dia_danh": {"label": "Địa danh", "type": "text", "group": "header", "default": "Hà Nội"},
    "ngay": {"label": "Ngày ban hành", "type": "date", "group": "header", "placeholder": "để trống: ngày … tháng … năm …"},
    "trich_yeu": {"label": "Trích yếu nội dung", "type": "text", "group": "title"},
    "noi_nhan": {"label": "Nơi nhận", "type": "list", "group": "footer", "item_end": ";"},
    "luu": {"label": "Lưu (sau “VT,”): đơn vị soạn thảo, số bản lưu, ký hiệu người soạn", "type": "text",
            "group": "footer", "placeholder": "VD: VP, NVA(05)"},
    "quyen_han": {"label": "Quyền hạn ký", "type": "select", "options": ["", "TM.", "Q.", "KT.", "TL.", "TUQ."],
                  "group": "sign"},
    "quyen_han_cua": {"label": "Ký thay/thay mặt cho (chức vụ, tập thể)", "type": "text", "caps": True, "group": "sign",
                      "show_if": {"quyen_han": ["TM.", "KT.", "TL.", "TUQ."]}, "placeholder": "VD: VIỆN TRƯỞNG"},
    "chuc_vu": {"label": "Chức vụ người ký", "type": "text", "caps": True, "group": "sign",
                "default_from": "defaults.chuc_vu", "required": True},
    "ho_ten": {"label": "Họ và tên người ký", "type": "text", "group": "sign", "default_from": "defaults.ho_ten"},
}

HEADER_STD = {"kind": "header", "left": ["co_quan_chu_quan", "co_quan_ban_hanh", "line_co_quan", "so_ky_hieu"],
              "right": ["quoc_hieu", "tieu_ngu", "line_tieu_ngu", "dia_danh_ngay"]}
SIGN_STD = {"kind": "sign_footer"}
BASE_HEADER_FIELDS = ["co_quan_chu_quan", "co_quan_ban_hanh", "ma_co_quan", "so", "ky_hieu_tuy_chinh", "dia_danh", "ngay"]
BASE_SIGN_FIELDS = ["noi_nhan", "luu", "quyen_han", "quyen_han_cua", "chuc_vu", "ho_ten"]


def tpl(num, name, doc_types, number_code, header_cols, footer_cols, layout, fields, notes, validation=(),
        noi_nhan_default=None, extra=None):
    data = {
        "id": num, "standard": "nd30", "name": name,
        "source": {"template": f"{PL3} – Mẫu {num} ({name})", "format": PL1,
                   "observed": f"Mẫu {num}: bảng đầu trang 2 cột không viền "
                               f"{header_cols[0]}/{header_cols[1]} pt; bảng ký {footer_cols[0]}/{footer_cols[1]} pt"},
        "template_status": "supported",
        "doc_types": doc_types,
        "number": {"ky_hieu": number_code},
        "geometry": {"header_cols_pt": header_cols, "footer_cols_pt": footer_cols,
                     "note": "Độ rộng cột đo từ file mẫu; nếu tổng vượt vùng trình bày thì co theo tỉ lệ"},
        "layout": layout,
        "fields": fields,
        "noi_nhan_default": noi_nhan_default or [],
        "validation": list(validation),
        "notes": notes,
        "docx": {"page_number": "header, từ trang 2", "header_table": "2 cột, không viền",
                 "lines": "viền dưới đoạn văn", "footer_table": "2 cột, không viền"},
    }
    if extra:
        data.update(extra)
    return data


F = lambda **kw: kw  # noqa: E731

TEMPLATES = {}
TEMPLATES["1.1"] = tpl(
    "1.1", "Nghị quyết (cá biệt)", ["NGHI_QUYET"], "NQ-{ma_co_quan}", [177.1, 291.9], [141.8, 340.2],
    [HEADER_STD,
     {"kind": "ten_loai", "text": "NGHỊ QUYẾT"},
     {"kind": "trich_yeu", "field": "trich_yeu"},
     {"kind": "line_trich_yeu"},
     {"kind": "tham_quyen", "field": "tham_quyen"},
     {"kind": "can_cu", "field": "can_cu"},
     {"kind": "chuyen_tiep", "text": "QUYẾT NGHỊ:"},
     {"kind": "body", "field": "noi_dung", "allowed_blocks": ["dieu", "khoan", "diem", "p", "bullet", "chuong", "muc", "phan"]},
     SIGN_STD],
    BASE_HEADER_FIELDS + [
        {"id": "trich_yeu", "label": "Trích yếu nội dung nghị quyết", "type": "text", "required": True, "group": "title"},
        {"id": "tham_quyen", "label": "Thẩm quyền ban hành (in hoa)", "type": "text", "caps": True, "required": True,
         "group": "content", "placeholder": "VD: HỘI ĐỒNG QUẢN LÝ VIỆN …"},
        {"id": "can_cu", "label": "Căn cứ ban hành (mỗi dòng một căn cứ)", "type": "lines", "group": "content",
         "line_prefix": "Căn cứ "},
        {"id": "noi_dung", "label": "Nội dung nghị quyết (Điều, khoản, điểm)", "type": "blocks", "group": "content",
         "starter": [{"type": "dieu", "html": ""}]},
    ] + BASE_SIGN_FIELDS,
    ["Ghi chú mẫu 5: trích yếu; 6: nội dung; 7–8: đơn vị soạn thảo, ký hiệu người soạn, số bản."],
    validation=["can_cu_punctuation", "required_fields", "number_padding", "noi_nhan_punctuation"],
    noi_nhan_default=["Như Điều …;"])

for num, name, trich_ph, cols_h, cols_f, extra_dieu, note in [
    ("1.2", "Quyết định (cá biệt) quy định trực tiếp", "Về việc …", [174.4, 303.1], [170.1, 311.9], False,
     "Mẫu 1.2: trích yếu “Về việc …”; Điều 1 là nội dung quy định trực tiếp."),
    ("1.3", "Quyết định (cá biệt) ban hành hay phê duyệt một văn bản khác", "Ban hành (Phê duyệt) …", [183.4, 282.1],
     [177.2, 290.6], True,
     "Mẫu 1.3 (ghi chú *): áp dụng đối với quyết định (cá biệt) ban hành hay phê duyệt một văn bản khác; "
     "Điều 1 cố định “Ban hành (Phê duyệt) kèm theo Quyết định này …”."),
]:
    layout = [HEADER_STD,
              {"kind": "ten_loai", "text": "QUYẾT ĐỊNH"},
              {"kind": "trich_yeu", "field": "trich_yeu"},
              {"kind": "line_trich_yeu"},
              {"kind": "tham_quyen", "field": "tham_quyen"},
              {"kind": "can_cu", "field": "can_cu", "then_field": "de_nghi"},
              {"kind": "chuyen_tiep", "text": "QUYẾT ĐỊNH:"}]
    fields = BASE_HEADER_FIELDS + [
        {"id": "trich_yeu", "label": "Trích yếu nội dung quyết định", "type": "text", "required": True,
         "group": "title", "placeholder": trich_ph},
        {"id": "tham_quyen", "label": "Thẩm quyền ban hành (chức vụ người đứng đầu hoặc tên tập thể/cơ quan, in hoa)",
         "type": "text", "caps": True, "required": True, "group": "content", "placeholder": "VD: VIỆN TRƯỞNG VIỆN …",
         "note": "Mẫu – ghi chú 6"},
        {"id": "can_cu", "label": "Căn cứ ban hành (mỗi dòng một căn cứ)", "type": "lines", "group": "content",
         "line_prefix": "Căn cứ "},
        {"id": "de_nghi", "label": "Theo đề nghị của …", "type": "text", "group": "content",
         "placeholder": "VD: Trưởng phòng Tổ chức – Hành chính"},
    ]
    if extra_dieu:
        layout.append({"kind": "dieu_co_dinh", "number": 1,
                       "template": "Ban hành (Phê duyệt) kèm theo Quyết định này {van_ban_kem_theo}.",
                       "field": "van_ban_kem_theo"})
        fields.append({"id": "van_ban_kem_theo", "label": "Điều 1 – Tên văn bản được ban hành/phê duyệt kèm theo",
                       "type": "text", "required": True, "group": "content",
                       "placeholder": "VD: Quy chế chi tiêu nội bộ của Viện"})
        fields.append({"id": "hinh_thuc_dieu1", "label": "Điều 1 dùng từ", "type": "select",
                       "options": ["Ban hành", "Phê duyệt"], "default": "Ban hành", "group": "content"})
        layout[-1]["template"] = "{hinh_thuc_dieu1} kèm theo Quyết định này {van_ban_kem_theo}."
        layout.append({"kind": "body", "field": "noi_dung", "start_dieu": 2,
                       "allowed_blocks": ["dieu", "khoan", "diem", "p", "bullet"]})
        fields.append({"id": "noi_dung", "label": "Các điều tiếp theo (từ Điều 2)", "type": "blocks", "group": "content",
                       "starter": [{"type": "dieu", "html": ""}]})
    else:
        layout.append({"kind": "body", "field": "noi_dung",
                       "allowed_blocks": ["dieu", "khoan", "diem", "p", "bullet", "chuong", "muc", "phan"]})
        fields.append({"id": "noi_dung", "label": "Nội dung quyết định (Điều 1, Điều 2, …)", "type": "blocks",
                       "group": "content", "starter": [{"type": "dieu", "html": ""}]})
    layout.append(SIGN_STD)
    TEMPLATES[num] = tpl(num, name, ["QUYET_DINH_TRUC_TIEP" if num == "1.2" else "QUYET_DINH_GIAN_TIEP"],
                         "QĐ-{ma_co_quan}", cols_h, cols_f, layout, fields + BASE_SIGN_FIELDS, [note],
                         validation=["can_cu_punctuation", "required_fields", "number_padding", "noi_nhan_punctuation"],
                         noi_nhan_default=["Như Điều …;"])

TEMPLATES["1.4"] = tpl(
    "1.4", "Văn bản có tên loại",
    ["CHI_THI", "QUY_CHE", "QUY_DINH", "THONG_CAO", "THONG_BAO", "HUONG_DAN", "CHUONG_TRINH", "KE_HOACH",
     "PHUONG_AN", "DE_AN", "DU_AN", "BAO_CAO", "TO_TRINH", "GIAY_UY_QUYEN", "PHIEU_GUI", "PHIEU_CHUYEN", "PHIEU_BAO"],
    "{ma_loai}-{ma_co_quan}", [174.4, 302.1], [177.2, 290.6],
    [HEADER_STD,
     {"kind": "ten_loai", "from": "doc_type"},
     {"kind": "trich_yeu", "field": "trich_yeu"},
     {"kind": "line_trich_yeu"},
     {"kind": "kinh_gui", "field": "kinh_gui", "only_types": ["TO_TRINH", "BAO_CAO"]},
     {"kind": "body", "field": "noi_dung",
      "allowed_blocks": ["p", "bullet", "la_ma", "khoan", "diem", "phan", "chuong", "muc", "dieu"]},
     SIGN_STD],
    BASE_HEADER_FIELDS + [
        {"id": "trich_yeu", "label": "Trích yếu nội dung văn bản", "type": "text", "group": "title",
         "required": True},
        {"id": "kinh_gui", "label": "Kính gửi (Tờ trình, Báo cáo gửi cấp trên – mỗi dòng một nơi)", "type": "list",
         "group": "content", "only_types": ["TO_TRINH", "BAO_CAO"], "note": f"{PL1} Mục II.9.b"},
        {"id": "noi_dung", "label": "Nội dung văn bản", "type": "blocks", "group": "content",
         "starter": [{"type": "p", "html": ""}]},
    ] + BASE_SIGN_FIELDS,
    ["Mẫu 1.4 ghi chú 6: áp dụng chung cho chỉ thị, quy chế, quy định, thông cáo, thông báo, hướng dẫn, chương trình, "
     "kế hoạch, phương án, đề án, dự án, báo cáo, tờ trình, giấy ủy quyền, phiếu gửi, phiếu chuyển, phiếu báo.",
     "Ký hiệu: chữ viết tắt tên loại (Phụ lục III Mục I) + chữ viết tắt cơ quan ban hành."],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation", "kinh_gui_punctuation"])

TEMPLATES["1.5"] = tpl(
    "1.5", "Công văn", ["CONG_VAN"], "{ma_co_quan}-{ma_don_vi}", [174.4, 291.1], [111.0, 385.2],
    [{"kind": "header", "left": ["co_quan_chu_quan", "co_quan_ban_hanh", "line_co_quan", "so_ky_hieu", "vv"],
      "right": ["quoc_hieu", "tieu_ngu", "line_tieu_ngu", "dia_danh_ngay"]},
     {"kind": "kinh_gui", "field": "kinh_gui"},
     {"kind": "body", "field": "noi_dung", "allowed_blocks": ["p", "bullet", "la_ma", "khoan", "diem"]},
     SIGN_STD,
     {"kind": "lien_he", "field": "lien_he"}],
    BASE_HEADER_FIELDS[:3] + [
        {"id": "ma_don_vi", "label": "Chữ viết tắt đơn vị soạn thảo / lĩnh vực", "type": "code", "required": True,
         "group": "header", "default_from": "defaults.ma_don_vi", "note": "Mẫu 1.5 – ghi chú 4; PL I Mục II.3.b"},
    ] + BASE_HEADER_FIELDS[3:] + [
        {"id": "trich_yeu", "label": "Trích yếu (sau “V/v”)", "type": "text", "required": True, "group": "title",
         "prefix": "V/v ", "placeholder": "VD: góp ý dự thảo Kế hoạch …"},
        {"id": "kinh_gui", "label": "Kính gửi (mỗi dòng một cơ quan/cá nhân)", "type": "list", "required": True,
         "group": "content"},
        {"id": "noi_dung", "label": "Nội dung công văn", "type": "blocks", "group": "content",
         "starter": [{"type": "p", "html": ""}]},
    ] + BASE_SIGN_FIELDS + [
        {"id": "lien_he", "label": "Địa chỉ; thư điện tử; trang thông tin điện tử; điện thoại; Fax (nếu cần)",
         "type": "multiline", "group": "footer", "default_from": "defaults.lien_he", "note": "Mẫu 1.5 – ghi chú 10"},
    ],
    ["Công văn không có dòng tên loại; trích yếu “V/v …” đặt dưới số, ký hiệu (PL I Mục II.5.b).",
     "Ký hiệu công văn: chữ viết tắt cơ quan + chữ viết tắt đơn vị soạn thảo (PL I Mục II.3.b).",
     "Nơi nhận của công văn bắt đầu bằng “Như trên;” (PL I Mục II.9.b)."],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation", "kinh_gui_punctuation", "no_ten_loai"],
    noi_nhan_default=["Như trên;"])

TEMPLATES["1.6"] = tpl(
    "1.6", "Công điện", ["CONG_DIEN"], "CĐ-{ma_co_quan}", [181.9, 285.8], [163.1, 304.8],
    [HEADER_STD,
     {"kind": "ten_loai", "text": "CÔNG ĐIỆN"},
     {"kind": "trich_yeu", "field": "trich_yeu"},
     {"kind": "line_trich_yeu"},
     {"kind": "cong_dien_gui", "field": "nguoi_dien", "list_field": "noi_nhan_dien"},
     {"kind": "body", "field": "noi_dung", "allowed_blocks": ["p", "bullet", "khoan", "diem"]},
     SIGN_STD],
    BASE_HEADER_FIELDS + [
        {"id": "trich_yeu", "label": "Trích yếu nội dung điện", "type": "text", "required": True, "group": "title"},
        {"id": "nguoi_dien", "label": "Tên cơ quan, tổ chức hoặc chức danh người đứng đầu (… điện:)", "type": "text",
         "required": True, "group": "content", "placeholder": "VD: VIỆN TRƯỞNG VIỆN …", "note": "Mẫu 1.6 – ghi chú 6"},
        {"id": "noi_nhan_dien", "label": "Cơ quan, tổ chức nhận điện (mỗi dòng một nơi)", "type": "list",
         "required": True, "group": "content", "note": "Mẫu 1.6 – ghi chú 7"},
        {"id": "noi_dung", "label": "Nội dung điện", "type": "blocks", "group": "content",
         "starter": [{"type": "p", "html": ""}]},
    ] + BASE_SIGN_FIELDS,
    ["Sau trích yếu: dòng “… điện:” (canh giữa) và danh sách nơi nhận điện, mỗi dòng bắt đầu “-”, cuối “;”."],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation"])

TEMPLATES["1.7"] = tpl(
    "1.7", "Giấy mời", ["GIAY_MOI"], "GM-{ma_co_quan}", [174.4, 298.1], [141.8, 340.2],
    [HEADER_STD,
     {"kind": "ten_loai", "text": "GIẤY MỜI"},
     {"kind": "trich_yeu", "field": "trich_yeu"},
     {"kind": "line_trich_yeu"},
     {"kind": "text_line", "template": "{chu_the} trân trọng kính mời: {nguoi_duoc_moi}"},
     {"kind": "text_line", "template": "Tới dự {cuoc_hop}"},
     {"kind": "text_line", "template": "Chủ trì: {chu_tri}"},
     {"kind": "text_line", "template": "Thời gian: {thoi_gian}"},
     {"kind": "text_line", "template": "Địa điểm: {dia_diem}"},
     {"kind": "body", "field": "luu_y", "allowed_blocks": ["p", "bullet"], "optional": True},
     SIGN_STD],
    BASE_HEADER_FIELDS + [
        {"id": "trich_yeu", "label": "Trích yếu nội dung cuộc họp", "type": "text", "required": True, "group": "title"},
        {"id": "chu_the", "label": "Tên cơ quan, tổ chức mời (viết thường, đầu câu)", "type": "text", "required": True,
         "group": "content", "default_from": "defaults.chu_the", "placeholder": "VD: Tên cơ quan, tổ chức"},
        {"id": "nguoi_duoc_moi", "label": "Người/cơ quan được mời", "type": "text", "required": True,
         "group": "content", "note": "Mẫu 1.7 – ghi chú 6"},
        {"id": "cuoc_hop", "label": "Tới dự (tên, nội dung cuộc họp/hội nghị/hội thảo)", "type": "text",
         "required": True, "group": "content"},
        {"id": "chu_tri", "label": "Chủ trì", "type": "text", "group": "content"},
        {"id": "thoi_gian", "label": "Thời gian", "type": "text", "required": True, "group": "content",
         "placeholder": "VD: 08 giờ 30, ngày 05 tháng 10 năm 2026"},
        {"id": "dia_diem", "label": "Địa điểm", "type": "text", "required": True, "group": "content"},
        {"id": "luu_y", "label": "Các vấn đề cần lưu ý", "type": "blocks", "group": "content",
         "starter": [{"type": "p", "html": ""}], "note": "Mẫu 1.7 – ghi chú 8"},
    ] + BASE_SIGN_FIELDS,
    ["Nội dung Giấy mời trình bày theo các dòng cố định của Mẫu 1.7."],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation"])

TEMPLATES["1.8"] = tpl(
    "1.8", "Giấy giới thiệu", ["GIAY_GIOI_THIEU"], "GGT-{ma_co_quan}", [174.4, 303.1], [170.1, 304.8],
    [HEADER_STD,
     {"kind": "ten_loai", "text": "GIẤY GIỚI THIỆU"},
     {"kind": "line_trich_yeu", "of": "ten_loai"},
     {"kind": "text_line", "template": "{chu_the} trân trọng giới thiệu:", "align": "center", "indent": False},
     {"kind": "text_line", "template": "Ông (bà) {nguoi_duoc_gt}"},
     {"kind": "text_line", "template": "Chức vụ: {chuc_vu_gt}"},
     {"kind": "text_line", "template": "Được cử đến: {cu_den}"},
     {"kind": "text_line", "template": "Về việc: {ve_viec}"},
     {"kind": "text_line", "template": "Đề nghị Quý cơ quan tạo điều kiện để ông (bà) có tên ở trên hoàn thành nhiệm vụ."},
     {"kind": "text_line", "template": "Giấy này có giá trị đến hết ngày {gia_tri_den}/.", "end_mark": False},
     SIGN_STD],
    BASE_HEADER_FIELDS + [
        {"id": "chu_the", "label": "Tên cơ quan, tổ chức cấp giấy (viết thường, đầu câu)", "type": "text",
         "required": True, "group": "content", "default_from": "defaults.chu_the"},
        {"id": "nguoi_duoc_gt", "label": "Ông (bà) – họ tên, đơn vị công tác", "type": "text", "required": True,
         "group": "content", "note": "Mẫu 1.8 – ghi chú 5"},
        {"id": "chuc_vu_gt", "label": "Chức vụ", "type": "text", "group": "content"},
        {"id": "cu_den", "label": "Được cử đến", "type": "text", "required": True, "group": "content",
         "note": "Mẫu 1.8 – ghi chú 6"},
        {"id": "ve_viec", "label": "Về việc", "type": "text", "required": True, "group": "content"},
        {"id": "gia_tri_den", "label": "Giấy có giá trị đến hết ngày", "type": "date_text", "required": True,
         "group": "content", "placeholder": "VD: 31/10/2026"},
    ] + BASE_SIGN_FIELDS,
    ["Mẫu 1.8 không có trích yếu; đường kẻ nằm ngay dưới tên loại “GIẤY GIỚI THIỆU”.",
     "Nơi nhận theo mẫu: “- Như trên;” “- Lưu: VT.”"],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation"],
    noi_nhan_default=["Như trên;"])

TEMPLATES["1.9"] = tpl(
    "1.9", "Biên bản", ["BIEN_BAN"], "BB-{ma_co_quan}", [174.4, 298.1], [200.8, 271.5],
    [{"kind": "header", "left": ["co_quan_chu_quan", "co_quan_ban_hanh", "line_co_quan", "so_ky_hieu"],
      "right": ["quoc_hieu", "tieu_ngu", "line_tieu_ngu"]},
     {"kind": "ten_loai", "text": "BIÊN BẢN"},
     {"kind": "trich_yeu", "field": "trich_yeu"},
     {"kind": "line_trich_yeu"},
     {"kind": "text_line", "template": "Thời gian bắt đầu: {thoi_gian_bat_dau}"},
     {"kind": "text_line", "template": "Địa điểm: {dia_diem}"},
     {"kind": "text_line", "template": "Thành phần tham dự: {thanh_phan}"},
     {"kind": "text_line", "template": "Chủ trì (chủ tọa): {chu_toa}"},
     {"kind": "text_line", "template": "Thư ký (người ghi biên bản): {thu_ky}"},
     {"kind": "text_line", "template": "Nội dung (theo diễn biến cuộc họp/hội nghị/hội thảo):"},
     {"kind": "body", "field": "noi_dung", "allowed_blocks": ["p", "bullet", "la_ma", "khoan", "diem"],
      "end_mark": False},
     {"kind": "text_line", "template": "{loai_su_kien} kết thúc vào {ket_thuc}/.", "end_mark": False},
     {"kind": "bien_ban_sign"}],
    [f for f in BASE_HEADER_FIELDS if f not in ("dia_danh", "ngay")] + [
        {"id": "trich_yeu", "label": "Tên cuộc họp hoặc hội nghị, hội thảo", "type": "text", "required": True,
         "group": "title", "note": "Mẫu 1.9 – ghi chú 4"},
        {"id": "thoi_gian_bat_dau", "label": "Thời gian bắt đầu", "type": "text", "required": True, "group": "content",
         "placeholder": "VD: 08 giờ 30, ngày 05 tháng 10 năm 2026"},
        {"id": "dia_diem", "label": "Địa điểm", "type": "text", "required": True, "group": "content"},
        {"id": "thanh_phan", "label": "Thành phần tham dự", "type": "multiline", "required": True, "group": "content"},
        {"id": "chu_toa", "label": "Chủ trì (chủ tọa)", "type": "text", "required": True, "group": "content"},
        {"id": "thu_ky", "label": "Thư ký (người ghi biên bản)", "type": "text", "required": True, "group": "content"},
        {"id": "noi_dung", "label": "Nội dung (theo diễn biến cuộc họp/hội nghị/hội thảo)", "type": "blocks",
         "group": "content", "starter": [{"type": "p", "html": ""}]},
        {"id": "loai_su_kien", "label": "Loại (câu kết thúc)", "type": "select",
         "options": ["Cuộc họp", "Hội nghị", "Hội thảo"], "default": "Cuộc họp", "group": "content"},
        {"id": "ket_thuc", "label": "Kết thúc vào (giờ, ngày)", "type": "text", "required": True, "group": "content",
         "placeholder": "VD: 11 giờ 00, ngày 05 tháng 10 năm 2026"},
        {"id": "ho_ten_thu_ky", "label": "THƯ KÝ – họ và tên", "type": "text", "group": "sign"},
        {"id": "chuc_vu_chinh_quyen", "label": "CHỦ TỌA – chức vụ chính quyền (nếu cần)", "type": "text",
         "caps": True, "group": "sign", "note": "Mẫu 1.9 – ghi chú 5"},
        {"id": "ho_ten_chu_toa", "label": "CHỦ TỌA – họ và tên", "type": "text", "group": "sign"},
        {"id": "noi_nhan", "label": "Nơi nhận", "type": "list", "group": "footer", "item_end": ";"},
        {"id": "luu", "label": "Lưu (sau “VT,”)", "type": "text", "group": "footer", "default": "Hồ sơ"},
    ],
    ["Mẫu 1.9: góc phải đầu trang chỉ có Quốc hiệu, Tiêu ngữ; không có dòng địa danh, ngày tháng.",
     "Cuối biên bản: bảng 2 vùng ký THƯ KÝ | CHỦ TỌA, không dùng khối chữ ký chung; Nơi nhận đặt dưới, bên trái.",
     "Dòng cuối nơi nhận theo mẫu: “- Lưu: VT, Hồ sơ.”"],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation"])

TEMPLATES["1.10"] = tpl(
    "1.10", "Giấy nghỉ phép", ["GIAY_NGHI_PHEP"], "GNP-{ma_co_quan}", [174.4, 291.1], [191.4, 283.5],
    [HEADER_STD,
     {"kind": "ten_loai", "text": "GIẤY NGHỈ PHÉP"},
     {"kind": "line_trich_yeu", "of": "ten_loai"},
     {"kind": "text_line", "template": "Xét Đơn đề nghị nghỉ phép ngày {ngay_don} của ông (bà) {nguoi_de_nghi}, {chu_the} cấp cho:"},
     {"kind": "text_line", "template": "Ông (bà): {nguoi_nghi}"},
     {"kind": "text_line", "template": "Chức vụ: {chuc_vu_nguoi_nghi}"},
     {"kind": "text_line", "template": "Được nghỉ phép trong thời gian {thoi_gian_nghi} kể từ ngày {tu_ngay} đến hết ngày {den_ngay} tại {noi_nghi}."},
     {"kind": "text_line", "template": "Số ngày nghỉ phép nêu trên được tính vào thời gian {tinh_vao}/.", "end_mark": False},
     {"kind": "nghi_phep_sign"}],
    BASE_HEADER_FIELDS + [
        {"id": "ngay_don", "label": "Ngày của Đơn đề nghị nghỉ phép", "type": "date_text", "required": True,
         "group": "content", "placeholder": "VD: 20/9/2026"},
        {"id": "nguoi_de_nghi", "label": "Người đề nghị (ông/bà)", "type": "text", "required": True, "group": "content"},
        {"id": "chu_the", "label": "Tên cơ quan, tổ chức cấp giấy (viết thường)", "type": "text", "required": True,
         "group": "content", "default_from": "defaults.chu_the"},
        {"id": "nguoi_nghi", "label": "Người được cấp giấy – họ tên, đơn vị công tác", "type": "text",
         "required": True, "group": "content", "note": "Mẫu 1.10 – ghi chú 5"},
        {"id": "chuc_vu_nguoi_nghi", "label": "Chức vụ", "type": "text", "group": "content"},
        {"id": "thoi_gian_nghi", "label": "Thời gian nghỉ (số ngày)", "type": "text", "required": True,
         "group": "content", "placeholder": "VD: 05 ngày"},
        {"id": "tu_ngay", "label": "Từ ngày", "type": "date_text", "required": True, "group": "content"},
        {"id": "den_ngay", "label": "Đến hết ngày", "type": "date_text", "required": True, "group": "content"},
        {"id": "noi_nghi", "label": "Nơi nghỉ phép", "type": "text", "required": True, "group": "content",
         "note": "Mẫu 1.10 – ghi chú 6"},
        {"id": "tinh_vao", "label": "Loại/thời gian nghỉ được tính vào", "type": "text", "required": True,
         "group": "content", "placeholder": "VD: nghỉ hằng năm có hưởng lương năm 2026", "note": "Mẫu 1.10 – ghi chú 7"},
        {"id": "hien_xac_nhan", "label": "Hiện vùng “Xác nhận của cơ quan (tổ chức) hoặc chính quyền địa phương nơi nghỉ phép (nếu cần)”",
         "type": "checkbox", "default": True, "group": "sign"},
    ] + BASE_SIGN_FIELDS,
    ["Mẫu 1.10 không có trích yếu; đường kẻ ngay dưới tên loại.",
     "Cuối văn bản: bảng 2 hàng – hàng 1: Nơi nhận | người ký; hàng 2 (trái): vùng xác nhận nơi nghỉ phép "
     "(nghiêng) “(Chữ ký, dấu)” và “Họ và tên” (đậm)."],
    validation=["required_fields", "number_padding", "noi_nhan_punctuation"],
    noi_nhan_default=["{nguoi_nghi};"])

# --------------------------------------------------------------------------- danh mục loại (Điều 7 + PL III Mục I)
TYPES = [
    ("NGHI_QUYET", "Nghị quyết (cá biệt)", "NGHỊ QUYẾT", "NQ", "1.1"),
    ("QUYET_DINH_TRUC_TIEP", "Quyết định (cá biệt) – quy định trực tiếp", "QUYẾT ĐỊNH", "QĐ", "1.2"),
    ("QUYET_DINH_GIAN_TIEP", "Quyết định – ban hành/phê duyệt văn bản khác", "QUYẾT ĐỊNH", "QĐ", "1.3"),
    ("CHI_THI", "Chỉ thị", "CHỈ THỊ", "CT", "1.4"), ("QUY_CHE", "Quy chế", "QUY CHẾ", "QC", "1.4"),
    ("QUY_DINH", "Quy định", "QUY ĐỊNH", "QyĐ", "1.4"), ("THONG_CAO", "Thông cáo", "THÔNG CÁO", "TC", "1.4"),
    ("THONG_BAO", "Thông báo", "THÔNG BÁO", "TB", "1.4"), ("HUONG_DAN", "Hướng dẫn", "HƯỚNG DẪN", "HD", "1.4"),
    ("CHUONG_TRINH", "Chương trình", "CHƯƠNG TRÌNH", "CTr", "1.4"), ("KE_HOACH", "Kế hoạch", "KẾ HOẠCH", "KH", "1.4"),
    ("PHUONG_AN", "Phương án", "PHƯƠNG ÁN", "PA", "1.4"), ("DE_AN", "Đề án", "ĐỀ ÁN", "ĐA", "1.4"),
    ("DU_AN", "Dự án", "DỰ ÁN", "DA", "1.4"), ("BAO_CAO", "Báo cáo", "BÁO CÁO", "BC", "1.4"),
    ("BIEN_BAN", "Biên bản", "BIÊN BẢN", "BB", "1.9"), ("TO_TRINH", "Tờ trình", "TỜ TRÌNH", "TTr", "1.4"),
    ("HOP_DONG", "Hợp đồng", "HỢP ĐỒNG", "HĐ", None), ("CONG_VAN", "Công văn", "", None, "1.5"),
    ("CONG_DIEN", "Công điện", "CÔNG ĐIỆN", "CĐ", "1.6"), ("BAN_GHI_NHO", "Bản ghi nhớ", "BẢN GHI NHỚ", "BGN", None),
    ("BAN_THOA_THUAN", "Bản thỏa thuận", "BẢN THỎA THUẬN", "BTT", None),
    ("GIAY_UY_QUYEN", "Giấy ủy quyền", "GIẤY ỦY QUYỀN", "GUQ", "1.4"), ("GIAY_MOI", "Giấy mời", "GIẤY MỜI", "GM", "1.7"),
    ("GIAY_GIOI_THIEU", "Giấy giới thiệu", "GIẤY GIỚI THIỆU", "GGT", "1.8"),
    ("GIAY_NGHI_PHEP", "Giấy nghỉ phép", "GIẤY NGHỈ PHÉP", "GNP", "1.10"),
    ("PHIEU_GUI", "Phiếu gửi", "PHIẾU GỬI", "PG", "1.4"), ("PHIEU_CHUYEN", "Phiếu chuyển", "PHIẾU CHUYỂN", "PC", "1.4"),
    ("PHIEU_BAO", "Phiếu báo", "PHIẾU BÁO", "PB", "1.4"), ("THU_CONG", "Thư công", "THƯ CÔNG", None, None),
]
CATALOG = {
    "standard": "nd30",
    "source": "NĐ 30/2020/NĐ-CP Điều 7 (29 loại văn bản hành chính); Phụ lục III Mục I (chữ viết tắt); Phụ lục III Mục II (Mẫu 1.1–1.10)",
    "types": [
        {"id": i, "label": l, "ten_loai": t, "ma_loai": c, "template": m,
         "template_status": "supported" if m else "unsupported",
         **({} if m else {"status_note": "Chưa có mẫu chuẩn trong Phụ lục III NĐ 30/2020 (Mẫu 1.1–1.10); "
                                         "công cụ không tự dựng bố cục cho loại này."}),
         **({"ma_loai_note": "Phụ lục III Mục I không có chữ viết tắt cho loại này"} if not c and i != "CONG_VAN" else {})}
        for i, l, t, c, m in TYPES
    ],
}

# --------------------------------------------------------------------------- HD05 (Đảng)
HD = "Hướng dẫn 05-HD/VPTW ngày 27/5/2026 của Văn phòng Trung ương Đảng"
HD05 = {
    "id": "hd05", "standard": "hd05", "name": "Văn bản của Đảng",
    "source": {"format": HD + "; cỡ chữ, kiểu chữ theo config/dang_spec.yaml (Phụ lục 2 của Hướng dẫn)",
               "layout": HD + ", Phần II và Phụ lục 1 (sơ đồ bố trí các thành phần thể thức)"},
    "template_status": "supported",
    "role_map": {"tieu_de": "dang_tieu_de", "cap_tren": "dang_co_quan_cap_tren", "ban_hanh": "dang_co_quan_ban_hanh",
                 "so_ky_hieu": "dang_so_ky_hieu", "dia_danh_ngay": "dang_dia_danh_thoi_gian", "the_loai": "dang_the_loai",
                 "trich_yeu": "dang_trich_yeu", "trich_yeu_cong_van": "dang_trich_yeu_cong_van",
                 "kinh_gui": "dang_kinh_gui", "can_cu": "dang_can_cu", "body": "dang_body", "dieu": "dang_dieu",
                 "phan_label": "dang_phan_chuong_label", "phan_title": "dang_phan_chuong_title",
                 "muc_label": "dang_muc_label", "muc_title": "dang_muc_title",
                 "quyen_han_ky": "dang_quyen_han_ky", "chuc_vu_ky": "dang_chuc_vu_ky", "ho_ten_ky": "dang_ho_ten_ky",
                 "noi_nhan_label": "dang_noi_nhan_label", "noi_nhan_item": "dang_noi_nhan_item",
                 "dau_khan": "dang_dau_khan", "du_thao": "dang_du_thao", "pham_vi": "dang_pham_vi_luu_hanh",
                 "lien_he": "dang_thong_tin_lien_he"},
    "rules": {
        "tieu_de": "Góc phải, dòng đầu; dưới có đường kẻ nét liền dài bằng tiêu đề (mục 1.2)",
        "co_quan": "Góc trái, dòng đầu, ngang tiêu đề; dưới có dấu sao (*); cân đối dưới tên cơ quan cấp trên (mục 2.2)",
        "so_ky_hieu": "Cân đối dưới tên cơ quan; số < 10 thêm 0; Số {so}-{ký hiệu loại}/{ký hiệu cơ quan} (mục 3.2)",
        "dia_danh_ngay": "Cân đối dưới tiêu đề; ngày < 10 và tháng < 3 thêm 0 (mục 4.2)",
        "ten_loai_trich_yeu": "Chính giữa trang đầu; dưới trích yếu có 05 dấu gạch nối (-); công văn: trích yếu dưới số, ký hiệu (mục 5.2)",
        "noi_dung": "Dàn đều hai lề; lùi đầu dòng khoảng 10 mm; cách đoạn tối thiểu 6pt; giãn dòng 18–22pt (Exactly); kết thúc bằng dấu chấm (mục 6.2.2)",
        "can_cu": "Mỗi căn cứ một dòng, trước có gạch ngang (-), sau có “;”, căn cứ cuối có “.” (mục 6.2.3)",
        "bo_cuc": "Phần, Chương (La Mã hoặc chữ), Mục (Ả-rập) chính giữa, tên ở dòng dưới; Điều n. cùng dòng tên điều; khoản 1.; điểm a) (mục 6.2.4)",
        "chu_ky": "Góc phải dưới nội dung: quyền hạn (T/M, K/T, T/L, Q.), chức vụ, chữ ký, họ tên (mục 7)",
        "noi_nhan": "Góc trái dưới nội dung; “Nơi nhận:” có gạch chân; mỗi nơi nhận kết thúc “;”, dòng lưu kết thúc “.”; công văn, tờ trình dòng đầu “Như trên” (mục 9.2)",
        "kinh_gui": "Công văn: “Kính gửi” chính giữa trang đầu; tờ trình: “Kính trình” dưới tên loại và trích yếu; sau mỗi nơi nhận có “;” (mục 9.2.3–9.2.5)",
        "bien_ban": "Biên bản hội nghị: chủ trì hội nghị bên phải, người ghi biên bản bên trái (mục 7.1.4.e, 7.2.4)",
        "bo_sung": "Dấu mức độ khẩn, chỉ dẫn dự thảo dưới số và ký hiệu (công văn: dưới trích yếu); chỉ dẫn phạm vi phổ biến góc phải trang đầu cách mép trên 10 mm; thông tin liên hệ trang cuối dưới đường kẻ hết chiều ngang (Phần II mục II)",
        "trang": "A4; lề trên 20, dưới 20, trái 30, phải 15 mm; in hai mặt: mặt sau trái 15, phải 30 mm; số trang giữa, cách mép trên 10 mm, không hiện ở trang đầu (Phần II mục IV)",
    },
    "layout": [
        {"kind": "party_header"},
        {"kind": "ten_loai", "from": "doc_type", "skip_types": ["CONG_VAN"]},
        {"kind": "trich_yeu", "field": "trich_yeu", "skip_types": ["CONG_VAN"]},
        {"kind": "party_summary_rule", "skip_types": ["CONG_VAN"]},
        {"kind": "kinh_gui", "field": "kinh_gui", "only_types": ["CONG_VAN", "TO_TRINH"]},
        {"kind": "can_cu", "field": "can_cu"},
        {"kind": "body", "field": "noi_dung",
         "allowed_blocks": ["p", "bullet", "la_ma", "khoan", "diem", "dieu", "phan", "chuong", "muc"]},
        {"kind": "party_sign_footer", "skip_types": ["BIEN_BAN"]},
        {"kind": "party_bien_ban_sign", "only_types": ["BIEN_BAN"]},
        {"kind": "party_extra"},
    ],
    "number": {"format": "Số {so}-{ma_loai}/{ma_co_quan}", "cong_van": "Số {so}-CV/{ma_co_quan}"},
    "fields": [
        {"id": "co_quan_chu_quan", "label": "Tên cơ quan cấp trên trực tiếp (nếu có)", "type": "multiline", "caps": True,
         "group": "header", "default_from": "defaults.co_quan_chu_quan", "note": "Mục 2.1, 2.2.2"},
        {"id": "co_quan_ban_hanh", "label": "Tên cơ quan ban hành", "type": "multiline", "caps": True, "required": True,
         "group": "header", "default_from": "defaults.co_quan_ban_hanh", "note": "Mục 2.1; tên dài có thể xuống dòng"},
        {"id": "ma_co_quan", "label": "Ký hiệu cơ quan ban hành (VD: TU, ĐU, CB, BTGDVTU, ĐH)", "type": "code",
         "required": True, "group": "header", "default_from": "defaults.ma_co_quan", "note": "Mục 3.1.2.b"},
        {"id": "so", "label": "Số văn bản", "type": "number_text", "group": "header", "note": "Mục 3.1.1, 3.2.2"},
        {"id": "ky_hieu_tuy_chinh", "label": "Số và ký hiệu (sửa tay, nếu cần)", "type": "text", "group": "header",
         "placeholder": "VD: Số 05-QC/BTCTU-BNCTU"},
        {"id": "dia_danh", "label": "Địa danh", "type": "text", "group": "header", "default": "Hà Nội", "note": "Mục 4.1.1"},
        {"id": "ngay", "label": "Ngày ban hành", "type": "date", "group": "header"},
        {"id": "do_khan", "label": "Mức độ khẩn (nếu có)", "type": "select", "options": ["", "KHẨN", "THƯỢNG KHẨN", "HỎA TỐC"],
         "group": "header", "note": "Phần II mục II.3"},
        {"id": "du_thao", "label": "Chỉ dẫn dự thảo (nếu có)", "type": "text", "group": "header",
         "placeholder": "VD: Dự thảo lần 2", "note": "Phần II mục II.4.2"},
        {"id": "pham_vi", "label": "Chỉ dẫn phạm vi phổ biến (nếu có)", "type": "text", "group": "header",
         "placeholder": "VD: LƯU HÀNH NỘI BỘ", "note": "Phần II mục II.4.1"},
        {"id": "trich_yeu", "label": "Trích yếu nội dung (công văn: “về việc …”)", "type": "multiline", "group": "title",
         "note": "Mục 5.1, 5.2"},
        {"id": "kinh_gui", "label": "Kính gửi (công văn) / Kính trình (tờ trình) – mỗi dòng một nơi", "type": "list",
         "group": "content", "only_types": ["CONG_VAN", "TO_TRINH"], "required": True, "note": "Mục 9.2.3–9.2.5"},
        {"id": "can_cu", "label": "Căn cứ ban hành (nếu có, mỗi dòng một căn cứ)", "type": "lines", "group": "content",
         "line_prefix": "Căn cứ ", "note": "Mục 6.2.3"},
        {"id": "noi_dung", "label": "Nội dung", "type": "blocks", "group": "content",
         "starter": [{"type": "p", "html": ""}]},
        {"id": "quyen_han", "label": "Quyền hạn ký", "type": "select", "options": ["", "T/M", "K/T", "T/L", "Q."],
         "group": "sign", "skip_types": ["BIEN_BAN"], "note": "Mục 7.1.1"},
        {"id": "quyen_han_cua", "label": "Thay mặt / ký thay / thừa lệnh cho (in hoa)", "type": "text", "caps": True,
         "group": "sign", "show_if": {"quyen_han": ["T/M", "K/T", "T/L"]}, "placeholder": "VD: BAN THƯỜNG VỤ"},
        {"id": "chuc_vu", "label": "Chức vụ người ký (có thể nhiều dòng, dòng “kiêm”)", "type": "multiline", "caps": True,
         "group": "sign", "default_from": "defaults.chuc_vu", "skip_types": ["BIEN_BAN"], "note": "Mục 7.1.2"},
        {"id": "ho_ten", "label": "Họ và tên người ký", "type": "text", "group": "sign", "default_from": "defaults.ho_ten",
         "skip_types": ["BIEN_BAN"]},
        {"id": "ho_ten_nguoi_ghi", "label": "NGƯỜI GHI BIÊN BẢN – họ và tên", "type": "text", "group": "sign",
         "only_types": ["BIEN_BAN"], "note": "Mục 7.1.4.e"},
        {"id": "ho_ten_chu_tri", "label": "CHỦ TRÌ HỘI NGHỊ – họ và tên", "type": "text", "group": "sign",
         "only_types": ["BIEN_BAN"]},
        {"id": "noi_nhan", "label": "Nơi nhận (mỗi dòng một nơi)", "type": "list", "group": "footer", "item_end": ";",
         "note": "Mục 9.2"},
        {"id": "luu", "label": "Nơi lưu (sau chữ “Lưu”), ký hiệu người soạn thảo, số bản", "type": "text", "group": "footer",
         "default": "Văn phòng", "note": "Mục 9.2.5; Phần II mục II.5"},
        {"id": "lien_he", "label": "Thông tin liên hệ (nếu cần)", "type": "multiline", "group": "footer",
         "default_from": "defaults.lien_he", "note": "Phần II mục II.6"},
    ],
    "noi_nhan_default_types": {"CONG_VAN": ["Như trên;"], "TO_TRINH": ["Như trên;"]},
    "validation": ["required_fields", "party_number", "party_punctuation"],
    "notes": ["Chỉ áp dụng cho văn bản của Đảng; không dùng thông số Nghị định 30/2020/NĐ-CP."],
}
HD05_CATALOG = {
    "standard": "hd05",
    "source": HD + ", mục 3.1.2.a (ký hiệu tên loại: chữ cái đầu các âm tiết; Quyết định, Quy định: QĐ; Chỉ thị: CT; "
              "Chương trình: CTr; Thông tri: TT; Tờ trình: TTr)",
    "types": [{"id": i, "label": l, "ten_loai": t, "ma_loai": c, "template": "hd05", "template_status": "supported"}
              for i, l, t, c in [
                  ("NGHI_QUYET", "Nghị quyết", "NGHỊ QUYẾT", "NQ"), ("QUYET_DINH", "Quyết định", "QUYẾT ĐỊNH", "QĐ"),
                  ("CHI_THI", "Chỉ thị", "CHỈ THỊ", "CT"), ("KET_LUAN", "Kết luận", "KẾT LUẬN", "KL"),
                  ("QUY_CHE", "Quy chế", "QUY CHẾ", "QC"), ("QUY_DINH", "Quy định", "QUY ĐỊNH", "QĐ"),
                  ("THONG_TRI", "Thông tri", "THÔNG TRI", "TT"), ("HUONG_DAN", "Hướng dẫn", "HƯỚNG DẪN", "HD"),
                  ("THONG_BAO", "Thông báo", "THÔNG BÁO", "TB"), ("BAO_CAO", "Báo cáo", "BÁO CÁO", "BC"),
                  ("TO_TRINH", "Tờ trình", "TỜ TRÌNH", "TTr"), ("KE_HOACH", "Kế hoạch", "KẾ HOẠCH", "KH"),
                  ("CHUONG_TRINH", "Chương trình", "CHƯƠNG TRÌNH", "CTr"), ("BIEN_BAN", "Biên bản", "BIÊN BẢN", "BB"),
                  ("CONG_VAN", "Công văn", "", "CV")]],
}

dump(OUT / "nd30" / "_format.json", FORMAT)
dump(OUT / "nd30" / "_fields.json", {"standard": "nd30", "fields": COMMON_FIELDS})
dump(OUT / "nd30" / "catalog.json", CATALOG)
for num, data in TEMPLATES.items():
    dump(OUT / "nd30" / f"mau_{num.replace('.', '_')}.json", data)
dump(OUT / "hd05" / "van_ban_dang.json", HD05)
dump(OUT / "hd05" / "catalog.json", HD05_CATALOG)
print("ok", len(TEMPLATES))
