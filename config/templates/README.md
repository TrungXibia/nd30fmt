# Schema mẫu văn bản cho trình soạn thảo

Thư mục này là **nguồn quyết định cuối cùng** cho bố cục, trường nhập, kiểm tra và xuất Word của tab
*Soạn thảo văn bản*. Giao diện (`nd30fmt/static/soan_thao.html`) không viết cứng thông số trình bày: nó
đọc schema qua `GET /api/compose/templates`, gửi bản thảo tới `POST /api/compose/layout` và vẽ lại bố cục
máy chủ trả về. File Word (`POST /api/compose/docx`) được ghi từ **cùng** bố cục đó.

Trình soạn thảo có 2 chuẩn: `nd30/` (Nghị định 30/2020/NĐ-CP) và `hd05/` (văn bản Đảng). Chuẩn Đề án/Luận văn
thạc sĩ (Phụ lục 4.1, `config/dean_spec.yaml`) dùng cho kiểm tra và chuẩn hoá ở tab Chuẩn hoá văn bản.

## nd30/

| File | Nội dung | Căn cứ |
|---|---|---|
| `_format.json` | Khổ giấy, lề, phông, số trang, cỡ/kiểu chữ từng thành phần (role), bộ cỡ chữ đồng bộ 13/14, đường kẻ, chữ ký, nơi nhận, số/ký hiệu, ngày tháng | NĐ 30/2020 Phụ lục I (Mục I, II, III, V) |
| `_fields.json` | Trường dùng chung (cơ quan, số, ngày, nơi nhận, người ký…) | Ghi chú của Mẫu 1.1–1.10 |
| `catalog.json` | 29 loại văn bản của Điều 7 (Quyết định tách 1.2/1.3), chữ viết tắt, mẫu áp dụng; loại chưa có mẫu: `template_status = unsupported` | Điều 7; Phụ lục III Mục I, II |
| `mau_1_1.json` … `mau_1_10.json` | Mỗi mẫu: `layout` (thứ tự khối ngữ nghĩa), `fields`, `validation`, `geometry` (độ rộng cột bảng theo mẫu), `number` (ký hiệu), `notes`, `docx` | Mẫu 1.1–1.10 Phụ lục III + Phụ lục I |

Các `kind` trong `layout` do `nd30fmt/composer/layout.py` hiểu: `header`, `ten_loai`, `trich_yeu`,
`line_trich_yeu`, `tham_quyen`, `can_cu`, `chuyen_tiep`, `kinh_gui`, `cong_dien_gui`, `dieu_co_dinh`,
`text_line`, `body`, `sign_footer`, `bien_ban_sign`, `nghi_phep_sign`, `lien_he` (và `party_header`, `party_summary_rule`, `party_sign_footer`, `party_bien_ban_sign`, `party_extra` cho văn bản Đảng).

Kiểu trường (`type`): `text`, `code`, `number_text`, `date`, `date_text`, `select`, `checkbox`, `multiline`,
`list` (mỗi dòng một mục), `lines` (căn cứ), `blocks` (Điều/khoản/điểm/đoạn/gạch đầu dòng…).

## hd05/

`van_ban_dang.json` (bố cục, trường nhập, quy tắc trình bày văn bản Đảng theo Hướng dẫn 05-HD/VPTW ngày 27/5/2026,
Phần II và Phụ lục 1) và `catalog.json` (thể loại, ký hiệu tên loại theo mục 3.1.2.a). Cỡ/kiểu chữ, lề, giãn dòng
không ghi trong JSON mà đọc trực tiếp từ
`config/dang_spec.yaml` (hoặc bản quy chuẩn Đảng đã lưu trong giao diện Thông số) – cùng nguồn với bộ kiểm tra.

## font_metrics_tnr.json

Độ rộng ký tự Liberation Serif (tương thích số đo Times New Roman) dùng tính độ dài đường kẻ dưới Tiêu ngữ
(bằng độ dài dòng chữ) và dưới tên cơ quan/trích yếu (1/3–1/2 độ dài dòng chữ) theo Phụ lục I.

## Sửa schema

Có thể sửa trực tiếp JSON rồi khởi động lại dịch vụ. `tools/build_templates.py` là script đã sinh các file này
(chạy lại sẽ ghi đè). Schema được kiểm tra khi nạp (`nd30fmt/composer/schema.py`): thiếu mẫu, loại trỏ sai
mẫu, khối dùng trường chưa khai báo, khoảng cỡ chữ sai đều báo lỗi.
