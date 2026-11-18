# nd30fmt – Kiểm tra, chuẩn hoá và soạn thảo văn bản Word theo Nghị định 30/2020/NĐ-CP

Công cụ web (FastAPI) và dòng lệnh để:

- **Chuẩn hoá thể thức** tệp Word (.docx) theo Nghị định số 30/2020/NĐ-CP ngày 05/3/2020 của Chính phủ về công tác văn thư, theo Hướng dẫn số 05-HD/VPTW (văn bản của Đảng) và theo quy ước trình bày luận văn/đề án. Công cụ tô lỗi trên bản xem trước, tự sửa, kiểm tra lại, xuất báo cáo và tạo mục lục, danh mục hình/bảng.
- **Soạn thảo** văn bản hành chính theo các Mẫu 1.1–1.10 (Phụ lục III, Nghị định 30/2020/NĐ-CP) và mẫu văn bản của Đảng, xuất .docx.
- **Sửa chính tả tiếng Việt**: sai dấu, lỗi gõ Telex, thiếu/đảo ký tự, lặp từ, khoảng trắng. Chữ tiếng Anh xen trong văn bản được nhận diện để không bị "sửa" thành chữ Việt.
- **Chuyển Markdown**: chuyển Word/PDF/PDF quét/ảnh sang Markdown (có OCR tiếng Việt, khôi phục dấu), và chuyển Markdown sang Word.
- **Chuyển âm thanh thành văn bản** (tuỳ chọn, qua Groq Whisper). Người triển khai tự điền khoá `GROQ_API_KEY` của mình vào `deploy/.env`.

Phần xử lý nặng (sửa chính tả, khôi phục dấu) có lõi **Rust** (PyO3). Không có lõi Rust, ứng dụng tự chạy bản Python với cùng kết quả, chỉ chậm hơn và tốn bộ nhớ hơn.

> Công cụ hỗ trợ rà soát, không thay thế việc kiểm tra của người soạn thảo và văn thư. Các đoạn có vai trò chưa chắc chắn (viền tím) chỉ được báo, không tự sửa theo vai trò.

## Cài đặt nhanh

Cần Python ≥ 3.9. Muốn có "Bản in" (PDF) thì cài thêm LibreOffice và poppler-utils. Tab Chuyển Markdown cần Tesseract (gói `tesseract-ocr-vie`), tab Âm thanh cần ffmpeg.

```bash
pip install -r requirements.txt
uvicorn nd30fmt.web:app --host 127.0.0.1 --port 8030
# mở http://127.0.0.1:8030
```

Dòng lệnh:

```bash
python -m nd30fmt check bao_cao.docx                 # chỉ kiểm tra, xuất báo cáo HTML/JSON
python -m nd30fmt fix   bao_cao.docx -o ket_qua/     # kiểm tra + sửa + kiểm tra lại
python -m nd30fmt fix   thu_muc/ --standard dang
```

**Hai bộ quy chuẩn.** Ai cũng chạy được ngay với **bộ quy chuẩn mẫu mở** `config/sample/*_spec.yaml`: các quy định
bắt buộc của văn bản gốc (khổ giấy, lề, phông, cỡ chữ, thành phần thể thức), sửa trực tiếp được cho đơn vị mình.
**Bộ đầy đủ** (thêm quy ước trình bày báo cáo dài, hiệu chỉnh riêng) nằm ở `config/*_spec.yaml.enc`, mã hoá AES-256-GCM,
chỉ dùng khi có khoá `ND30_SPEC_KEY` do chủ dự án cấp. `/healthz` cho biết đang dùng bộ nào (`"spec": "sample"` hoặc
`"encrypted"`). Giao diện, API và báo cáo không hiển thị nguồn/căn cứ của quy chuẩn.

## Lõi Rust (tuỳ chọn, khuyến nghị cho máy chủ)

```bash
pip install maturin ziglang
bash rust/build.sh          # ghi nd30fmt/_core.abi3.so (Linux x86_64, glibc >= 2.17, Python >= 3.9)
curl -s http://127.0.0.1:8030/healthz   # "core":"rust" là đã dùng lõi Rust
```

Tệp `.so` không đưa vào kho mã; ảnh Docker tự dựng lõi Rust (tắt bằng `--build-arg RUST_CORE=0`). Đặt `ND30_NO_RUST=1` để buộc dùng bản Python.

## Chạy bằng Docker

```bash
cp deploy/.env.example deploy/.env       # BẮT BUỘC đặt APP_TOKEN; tuỳ chọn ND30_SPEC_KEY, GROQ_API_KEY
cd deploy && docker compose up -d --build   # ảnh tự dựng lõi Rust
curl -s http://127.0.0.1:8030/healthz
```

- `deploy/nginx-nd30.conf`: mẫu cấu hình nginx khi chạy dưới tiền tố `/nd30/`.
- `deploy/update.sh`: cập nhật máy chủ đang chạy bằng một lệnh, có sao lưu và tự trả lại bản cũ khi lỗi (`--dry-run` để xem trước).
- Tên cơ quan, logo ở đầu trang đặt bằng biến môi trường (`ORG_NAME`, `ORG_LOGO`...). Xem `deploy/.env.example`.
- Link đăng nhập nhanh: `https://<máy chủ>/nd30/#token=<mã>` (phần sau `#` không gửi lên máy chủ nên không nằm trong log).

## Bảo mật

Mã truy cập theo người dùng (quản trị viên cấp, chỉ lưu bản băm), chặn tạm khi nhập sai nhiều lần, giới hạn dung lượng giải nén tệp Word, lọc liên kết nguy hiểm trong Markdown, trang chia sẻ công khai chạy trong sandbox và có hạn dùng, gỡ ảnh/trường liên kết ra ngoài trước khi LibreOffice dựng bản in. Xem `SECURITY.md` để báo lỗ hổng và các khuyến nghị khi triển khai.

## Cấu hình quy chuẩn

| Tệp | Nội dung |
|---|---|
| `config/sample/*_spec.yaml` | Bộ quy chuẩn mẫu mở (dùng khi không có khoá) |
| `config/nd30_spec.yaml.enc` | Thể thức văn bản hành chính (mã hoá) |
| `config/dang_spec.yaml.enc` | Thể thức văn bản của Đảng (mã hoá) |
| `config/dean_spec.yaml.enc` | Quy ước trình bày luận văn/đề án (mã hoá) |
| `config/templates/` | Schema các mẫu soạn thảo (Mẫu 1.1–1.10, mẫu văn bản Đảng) |

Người dùng có thể chỉnh thông số trên giao diện, bản chỉnh được lưu riêng, không ghi đè tệp gốc.

## Kiểm thử

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                  # có lõi Rust: thêm phép so khớp Rust/Python
ND30_NO_RUST=1 python -m pytest tests -q   # chỉ bản Python
```

Không có `ND30_SPEC_KEY` thì test chạy với bộ quy chuẩn mẫu; có khoá thì kiểm tra cả bộ đầy đủ.

Test giao diện cần Playwright (`pip install playwright && playwright install chromium`), không có thì tự bỏ qua. Test bản in cần LibreOffice.

## Cấu trúc thư mục

```
nd30fmt/            mã nguồn Python (web.py: dịch vụ web; cli.py: dòng lệnh; vspell.py: sửa chính tả; ...)
nd30fmt/static/     giao diện web (HTML/CSS/JS thuần, không cần build)
nd30fmt/mdlib/      chuyển Markdown, OCR, khôi phục dấu; data/ là dữ liệu thống kê ngôn ngữ
rust/nd30core/      lõi Rust (PyO3)
config/             quy chuẩn YAML và schema mẫu soạn thảo
deploy/             Dockerfile, docker-compose, nginx, script cập nhật
desktop/            dựng bộ cài Windows (tuỳ chọn)
tools/              script dựng lại dữ liệu ngôn ngữ, schema mẫu và đo chất lượng sửa chính tả
tests/              kiểm thử (pytest); samples/ là tệp Word mẫu có lỗi định dạng
```

## Giấy phép

- Mã nguồn: **MIT** (xem `LICENSE`).
- `nd30fmt/mdlib/data/vnlm.zip`: bảng đếm âm tiết dựng từ kho VNTC/VNESE đi kèm underthesea (Apache-2.0), không chứa văn bản gốc. Xem `nd30fmt/mdlib/data/README.md` và `LICENSE-underthesea.txt`.
- `nd30fmt/mdlib/data/enlm.zip`: tần suất từ tiếng Anh từ wordfreq, giấy phép **CC BY-SA 4.0** (`LICENSE-wordfreq.txt`).
- Phụ thuộc **PyMuPDF** dùng giấy phép AGPL-3.0 (hoặc giấy phép thương mại của Artifex). Khi phân phối hoặc cung cấp dịch vụ có kèm PyMuPDF, cần tuân thủ điều kiện của AGPL-3.0.
- `tests/nd30/fixtures/`: hai công văn hướng dẫn thực hiện Nghị định 30/2020/NĐ-CP đã công bố công khai, dùng làm dữ liệu thử.
