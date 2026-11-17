# Dữ liệu cho bộ sửa lỗi dấu OCR (vnfix.py)

`vnlm.zip` – bảng đếm âm tiết (unigram) và cặp âm tiết (bigram, chỉ giữ cặp xuất hiện ≥ 3 lần) dùng để khôi phục
dấu tiếng Việt theo ngữ cảnh. Không chứa văn bản gốc. Dựng lại bằng `python tools/build_vnlm.py <thư mục kho văn bản>`.

Nguồn thống kê:
- VNTC – Vietnamese News Text Classification corpus và VNESEcorpus, phát hành kèm dự án underthesea
  (https://github.com/undertheseanlp/underthesea, giấy phép Apache-2.0 – xem LICENSE-underthesea.txt;
  dữ liệu VNTC: Vu Cong Duy Hoang và cộng sự, 2007).
- `tools/vnlm_domain.txt`: Nghị định 30/2020/NĐ-CP (văn bản công khai) và danh mục cụm từ hành chính, cùng văn bản
  mẫu/biểu mẫu trong gói, nhân trọng số để thích nghi lĩnh vực hành chính – pháp lý.

Kết quả thử (văn bản Hướng dẫn 05-HD/VPTW, không dùng khi dựng): sửa đúng ~80% lỗi dấu mô phỏng OCR,
đổi nhầm ~0,01% chữ vốn đúng (mức phạt CHANGE_PENALTY = 7).

Bản dựng từ v42: mỗi 30 câu của VNTC/VNESE được **để riêng** (`--holdout-every 30`, không đưa vào bảng đếm) để đo
bộ sửa chính tả `vspell.py` trên văn bản mô hình chưa từng thấy (kho để riêng không nằm trong gói; dựng lại được
bằng lệnh trên với cùng tham số). Chương trình đo: `tools/eval_spell.py`.
Từ vựng 15.661 âm tiết, 791.473 cặp.

## enlm.zip – nhận diện chữ tiếng Anh cho bộ sửa chính tả

`enlm.zip` chứa 60.000 từ tiếng Anh thông dụng nhất (chỉ a–z, 2–20 chữ cái) kèm tần suất (zipf × 100), lấy từ gói
`wordfreq` (Robyn Speer và cộng sự, https://github.com/rspeer/wordfreq). Dùng để `langid.py` (Python) và `lib.rs` (Rust)
gán nhãn Việt/Anh cho từng chữ bằng mô hình ẩn hai trạng thái, nhằm không "sửa" chữ tiếng Anh thành chữ Việt.
Dữ liệu wordfreq theo giấy phép CC BY-SA 4.0 – xem `LICENSE-wordfreq.txt`. Dựng lại bằng `python tools/build_enlm.py`.
