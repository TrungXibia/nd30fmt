# Báo cáo lỗ hổng bảo mật

Vui lòng không mở issue công khai cho lỗ hổng bảo mật. Hãy dùng chức năng
**Security → Report a vulnerability** (Private vulnerability reporting) của kho này.

## Khuyến nghị khi triển khai

- Luôn đặt `APP_TOKEN` là mã ngẫu nhiên ≥ 16 ký tự khi mở dịch vụ ra Internet:
  `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
- Chạy sau nginx có HTTPS; chỉ mở cổng 8030 cho 127.0.0.1 (như `deploy/docker-compose.yml`).
- Không đưa `deploy/.env`, khoá API hay khoá SSH vào kho mã.
- Khoá Groq (`GROQ_API_KEY`) là của người triển khai: mỗi máy chủ tự điền khoá của mình, phí phiên âm tính vào tài khoản đó.
