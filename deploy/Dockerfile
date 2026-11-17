# ---- Lõi Rust (sửa chính tả, khôi phục dấu). Dựng lỗi hoặc RUST_CORE=0 -> ứng dụng tự dùng bản Python.
# Cùng Debian bookworm với ảnh chạy nên tệp .so tương thích glibc.
FROM rust:1-slim-bookworm AS core
ARG RUST_CORE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY rust/nd30core ./
# VPS ít RAM: tắt LTO đầy đủ khi dựng trong Docker (chậm hơn không đáng kể)
ENV CARGO_PROFILE_RELEASE_LTO=thin CARGO_PROFILE_RELEASE_CODEGEN_UNITS=4
RUN mkdir -p /out && if [ "$RUST_CORE" = "1" ]; then \
      (cargo build --release --locked && cp target/release/lib_core.so /out/_core.abi3.so) \
      || echo "CẢNH BÁO: không dựng được lõi Rust, ứng dụng sẽ chạy bản Python"; \
    fi

# Debian bookworm cố định để lệnh cài phông/LibreOffice ổn định
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
# MSCOREFONTS=1 -> cài bộ phông Microsoft (có Times New Roman) từ gói ttf-mscorefonts-installer
ARG MSCOREFONTS=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer-nogui poppler-utils fontconfig \
      fonts-liberation2 fonts-dejavu-core tesseract-ocr tesseract-ocr-vie antiword ffmpeg \
 && if [ "$MSCOREFONTS" = "1" ]; then \
      echo "deb http://deb.debian.org/debian bookworm contrib" > /etc/apt/sources.list.d/contrib.list \
      && apt-get update \
      && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
      && apt-get install -y --no-install-recommends ttf-mscorefonts-installer ; \
    fi \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nd30fmt ./nd30fmt
COPY --from=core /out/ ./nd30fmt/
COPY config ./config
RUN useradd -m app && mkdir -p /data && chown -R app /data
COPY deploy/entrypoint.sh /usr/local/bin/nd30-entrypoint
RUN chmod 755 /usr/local/bin/nd30-entrypoint
ENV DATA_DIR=/data
# Khởi động bằng root chỉ để trao quyền thư mục dữ liệu gắn từ máy chủ, rồi chạy ứng dụng bằng "app" (xem entrypoint.sh)
ENTRYPOINT ["/usr/local/bin/nd30-entrypoint"]
EXPOSE 8030
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8030/healthz')"
# fc-cache: nhận phông gắn từ máy chủ (thư mục /usr/share/fonts/host)
CMD ["sh", "-c", "fc-cache -f >/dev/null 2>&1; exec uvicorn nd30fmt.web:app --host 0.0.0.0 --port 8030 --proxy-headers --forwarded-allow-ips '*'"]
