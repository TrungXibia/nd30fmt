#!/bin/sh
# Khởi động container: sửa quyền thư mục dữ liệu rồi chạy ứng dụng bằng tài khoản thường "app" (không chạy bằng root).
# Thư mục deploy/data trên máy chủ thường do Docker tạo ra với chủ sở hữu root -> ứng dụng báo
# "Permission denied: '/data/jobs'". Bước này trao quyền cho "app" một lần (lần sau thấy đúng chủ thì bỏ qua).
set -e
D="${DATA_DIR:-/data}"
if [ "$(id -u)" = 0 ]; then
  mkdir -p "$D"
  if [ "$(stat -c %U "$D")" != app ] || [ -n "$(find "$D" -maxdepth 2 ! -user app -print -quit)" ]; then
    chown -R app:app "$D"
  fi
  export HOME=/home/app
  exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi
exec "$@"
