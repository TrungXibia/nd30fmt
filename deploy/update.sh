#!/usr/bin/env bash
# Cập nhật ứng dụng nd30fmt trên máy chủ bằng MỘT lệnh (chạy bằng user thường; các bước ghi vào thư mục cài dùng sudo).
#
#   git clone <repo> /tmp/nd30fmt_new   (hoặc giải nén bản tải về)  && bash /tmp/nd30fmt_new/deploy/update.sh
#
# Việc script làm, theo thứ tự:
#   1. Tìm thư mục cài từ container "nd30fmt" (mặc định /opt/nd30fmt).
#   2. Sao lưu mã đang chạy vào <thư mục cài>/deploy/backup/ (giữ 5 bản gần nhất).
#   3. Thay nd30fmt/, chép đè config/, requirements.txt, deploy/Dockerfile, .dockerignore.
#      KHÔNG đụng tới deploy/.env, deploy/docker-compose.yml, deploy/data (dữ liệu người dùng), cấu hình nginx.
#   4. Nhắc nếu deploy/.env chưa có GROQ_API_KEY (tab Âm thanh).
#   5. docker compose up -d --build, chờ /healthz báo đúng phiên bản mới.
#   6. Nếu bản mới không lên được: tự trả lại bản vừa sao lưu và build lại.
#
# Tuỳ chọn:
#   --dry-run       chỉ in những gì sẽ làm, không thay đổi gì
#   --rollback      trả lại bản sao lưu gần nhất rồi build lại
#   --no-rollback   không tự trả lại bản cũ khi bản mới lỗi (để xem log)
set -euo pipefail

MODE=update; AUTO_ROLLBACK=1; DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --rollback) MODE=rollback ;;
    --no-rollback) AUTO_ROLLBACK=0 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "Tuỳ chọn không hợp lệ: $a" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${ND30_CONTAINER:-nd30fmt}"
HEALTH_URL="${ND30_HEALTH_URL:-http://127.0.0.1:8030/healthz}"
WAIT_SECONDS="${ND30_WAIT_SECONDS:-180}"
if [ -z "${SUDO+x}" ]; then
  if [ "$(id -u)" = 0 ]; then SUDO=""; else SUDO="sudo"; fi
fi

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'LỖI: %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then say "   (chạy thử) $*"; else "$@"; fi; }

command -v docker >/dev/null 2>&1 || die "Máy này chưa có docker."
if $SUDO docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else die "Không tìm thấy 'docker compose' hay 'docker-compose'."; fi

# ---------------------------------------------------------------- 1. thư mục cài
D="${ND30_DEPLOY_DIR:-}"
if [ -z "$D" ]; then
  D="$($SUDO docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$CONTAINER" 2>/dev/null || true)"
fi
[ -n "$D" ] || D=/opt/nd30fmt/deploy
[ -f "$D/docker-compose.yml" ] || die "Không thấy $D/docker-compose.yml. Đặt ND30_DEPLOY_DIR=<thư mục deploy> rồi chạy lại."
ROOT="$(dirname "$D")"
BK="$D/backup"

version_of() { sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' "$1/nd30fmt/__init__.py" 2>/dev/null | head -1; }
health()     { curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true; }
running_version() { health | sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p'; }

build_and_wait() {   # $1 = phiên bản mong đợi
  local want="$1" t=0 got=""
  if ! ( cd "$D" && $SUDO $COMPOSE up -d --build ); then
    say "docker compose báo lỗi khi build/khởi động (xem các dòng ngay phía trên)."
    return 1
  fi
  say "Chờ ứng dụng khởi động (tối đa ${WAIT_SECONDS}s)..."
  while [ "$t" -lt "$WAIT_SECONDS" ]; do
    got="$(running_version)"
    if [ -n "$got" ] && { [ -z "$want" ] || [ "$got" = "$want" ]; }; then
      say "Đang chạy phiên bản $got: $(health)"
      return 0
    fi
    sleep 3; t=$((t + 3))
  done
  say "Sau ${WAIT_SECONDS}s vẫn chưa thấy phiên bản ${want:-mới} (đang thấy: '${got:-không trả lời}')."
  $SUDO docker logs --tail 30 "$CONTAINER" 2>&1 || true
  return 1
}

restore_latest() {
  local last
  last="$($SUDO sh -c "ls -1t '$BK'/nd30fmt_*.tgz 2>/dev/null" | head -1)"
  [ -n "$last" ] || die "Không có bản sao lưu nào trong $BK."
  say "Trả lại từ $last"
  $SUDO rm -rf "$ROOT/nd30fmt"
  $SUDO tar -xzf "$last" -C "$ROOT"
}

# ---------------------------------------------------------------- --rollback
if [ "$MODE" = rollback ]; then
  step "Trả lại bản sao lưu gần nhất"
  if [ "$DRY" = 1 ]; then say "   (chạy thử) khôi phục bản mới nhất trong $BK rồi build lại"; exit 0; fi
  restore_latest
  build_and_wait "$(version_of "$ROOT")" || die "Bản cũ cũng không khởi động được. Xem log ở trên."
  say "Đã trả lại bản cũ."
  exit 0
fi

# ---------------------------------------------------------------- kiểm tra gói
NEW="$(version_of "$SRC")"
[ -n "$NEW" ] && [ -f "$SRC/nd30fmt/web.py" ] && [ -f "$SRC/requirements.txt" ] && [ -f "$SRC/deploy/Dockerfile" ] \
  || die "Gói ở $SRC không đầy đủ (thiếu nd30fmt/, requirements.txt hoặc deploy/Dockerfile)."
[ "$SRC" != "$ROOT" ] || die "Hãy giải nén gói ra thư mục khác thư mục cài (ví dụ /tmp/nd30fmt_new) rồi chạy lại."
OLD="$(version_of "$ROOT")"

step "Cập nhật nd30fmt ${OLD:-?} -> $NEW"
say "Thư mục cài : $ROOT"
say "Gói mới     : $SRC"
say "Đang chạy   : $(running_version || true)"

# ---------------------------------------------------------------- 1b. khoá giải mã quy chuẩn
# Bản mới chỉ có quy chuẩn mã hoá (config/*_spec.yaml.enc): thiếu khoá thì trang web không chạy -> dừng TRƯỚC khi thay mã.
if [ "$MODE" = update ] && ls "$SRC"/config/*_spec.yaml.enc >/dev/null 2>&1 && ! ls "$SRC"/config/*_spec.yaml >/dev/null 2>&1; then
  if ! $SUDO grep -qE '^ND30_SPEC_KEY=.+' "$D/.env" 2>/dev/null; then
    die "deploy/.env chưa có ND30_SPEC_KEY (khoá giải mã quy chuẩn). Thêm bằng:
  echo 'ND30_SPEC_KEY=<khoá>' | sudo tee -a $D/.env
rồi chạy lại script. Chưa thay đổi gì."
  fi
  if command -v python3 >/dev/null 2>&1 && python3 -c "import cryptography, yaml" 2>/dev/null; then
    KEYV="$($SUDO grep -E '^ND30_SPEC_KEY=' "$D/.env" | tail -1 | cut -d= -f2-)"
    if ! ND30_SPEC_KEY="$KEYV" PYTHONPATH="$SRC" python3 -c "from nd30fmt.spec import load_raw; load_raw()" 2>/dev/null; then
      die "ND30_SPEC_KEY trong $D/.env không giải mã được quy chuẩn của bản mới (sai khoá). Chưa thay đổi gì."
    fi
    say "Khoá giải mã quy chuẩn: đúng."
  fi
fi

# ---------------------------------------------------------------- 2. sao lưu
step "Sao lưu mã đang chạy"
STAMP="$(date +%Y%m%d_%H%M%S)"; BKFILE=""
items=""
for f in nd30fmt config requirements.txt deploy/Dockerfile .dockerignore; do
  [ -e "$ROOT/$f" ] && items="$items $f"
done
same=0
if [ -n "$items" ] && diff -rq -x __pycache__ "$SRC/nd30fmt" "$ROOT/nd30fmt" >/dev/null 2>&1 \
   && cmp -s "$SRC/requirements.txt" "$ROOT/requirements.txt" && cmp -s "$SRC/deploy/Dockerfile" "$D/Dockerfile"; then
  same=1
fi
if [ "$same" = 1 ]; then
  # chạy lại cùng một gói: không tạo bản sao lưu mới, để --rollback vẫn trỏ về bản trước khi cập nhật
  say "Mã trên máy chủ đã giống gói này: không sao lưu lại, chỉ build và kiểm tra."
elif [ -n "$items" ]; then
  run $SUDO mkdir -p "$BK"
  BKFILE="$BK/nd30fmt_${OLD:-x}_$STAMP.tgz"
  # shellcheck disable=SC2086
  run $SUDO tar -czf "$BKFILE" -C "$ROOT" $items
  [ "$DRY" = 1 ] || say "Đã lưu: $BKFILE"
  if [ "$DRY" = 0 ]; then    # giữ 5 bản gần nhất
    $SUDO sh -c "ls -1t '$BK'/nd30fmt_*.tgz 2>/dev/null | tail -n +6 | xargs -r rm -f"
  fi
else
  say "Chưa có mã cũ để sao lưu (cài lần đầu)."
fi

# ---------------------------------------------------------------- 3. chép mã mới
step "Chép mã mới"
run $SUDO rm -rf "$ROOT/nd30fmt.new"
run $SUDO cp -r "$SRC/nd30fmt" "$ROOT/nd30fmt.new"
run $SUDO find "$ROOT/nd30fmt.new" -name __pycache__ -type d -prune -exec rm -rf {} +
run $SUDO rm -rf "$ROOT/nd30fmt"                       # bỏ cả tệp thừa của bản cũ (vnlm.npz, *.bak ...)
run $SUDO mv "$ROOT/nd30fmt.new" "$ROOT/nd30fmt"
run $SUDO mkdir -p "$ROOT/config"
run $SUDO cp -r "$SRC/config/." "$ROOT/config/"
run $SUDO cp "$SRC/requirements.txt" "$ROOT/requirements.txt"
run $SUDO cp "$SRC/deploy/Dockerfile" "$D/Dockerfile"
for f in .env.example nginx-nd30.conf update.sh; do
  [ -f "$SRC/deploy/$f" ] && run $SUDO cp "$SRC/deploy/$f" "$D/$f"
done
[ -f "$SRC/.dockerignore" ] && run $SUDO cp "$SRC/.dockerignore" "$ROOT/.dockerignore"
say "Giữ nguyên: $D/.env, $D/docker-compose.yml, $D/data"

# ---------------------------------------------------------------- 4. khoá Groq cho tab Âm thanh
step "Khoá Groq cho tab Chuyển đổi Âm thanh"
env_get() { $SUDO sh -c "[ -f '$1' ] && grep -E '^$2=' '$1' | tail -1 | cut -d= -f2-" 2>/dev/null || true; }
if [ -n "$(env_get "$D/.env" GROQ_API_KEY)" ]; then
  say "deploy/.env đã có GROQ_API_KEY."
else
  say "CHƯA CÓ GROQ_API_KEY: tab Âm thanh sẽ báo \"Chưa cấu hình\"."
  say "  Thêm dòng GROQ_API_KEY=<khoá> vào $D/.env (dùng nano), rồi: cd $D && $SUDO $COMPOSE up -d"
fi

if [ "$DRY" = 1 ]; then
  step "Chạy thử xong, chưa thay đổi gì"
  say "   (chạy thử) cd $D && $SUDO $COMPOSE up -d --build; chờ $HEALTH_URL báo phiên bản $NEW"
  exit 0
fi

# ---------------------------------------------------------------- 5. build + kiểm tra
step "Build và khởi động lại (lần đầu có thể mất vài phút vì cài thêm ffmpeg)"
if ! build_and_wait "$NEW"; then
  if [ "$AUTO_ROLLBACK" = 1 ] && [ -n "$items" ] && [ "$same" = 0 ]; then
    step "Bản mới không khởi động được: trả lại bản cũ"
    restore_latest
    build_and_wait "$OLD" || die "Bản cũ cũng không khởi động được. Xem log ở trên."
    $SUDO rm -f "$BKFILE"      # máy chủ đã về đúng trạng thái này; bỏ để --rollback vẫn trỏ về bản trước đó
    die "Đã trả lại bản $OLD. Bản $NEW CHƯA được cài; gửi phần log ở trên để kiểm tra."
  fi
  die "Bản mới chưa khởi động được (chưa trả lại bản cũ). Trả lại bằng: bash $D/update.sh --rollback"
fi

# ---------------------------------------------------------------- 6. kiểm tra sau cập nhật
step "Kiểm tra sau cập nhật"
if $SUDO docker exec "$CONTAINER" ffmpeg -version >/dev/null 2>&1; then say "ffmpeg trong container : có"
else say "ffmpeg trong container : KHÔNG CÓ (tab Âm thanh sẽ không chạy)"; fi
case "$(health)" in
  *'"audio":true'*|*'"audio": true'*) say "Tab Âm thanh           : sẵn sàng" ;;
  *) say "Tab Âm thanh           : chưa sẵn sàng (thiếu GROQ_API_KEY hoặc ffmpeg)" ;;
esac
if command -v nginx >/dev/null 2>&1; then
  if $SUDO nginx -T 2>/dev/null | grep -q 'api/audio/'; then say "nginx                  : đã có khối riêng cho /api/audio/"
  else
    say "nginx                  : CHƯA có khối riêng cho /api/audio/ -> tệp ghi âm lớn hơn giới hạn chung của nginx"
    say "                         sẽ bị từ chối (lỗi 413). Mẫu khối cần thêm: $D/nginx-nd30.conf"
  fi
fi
say ""
say "XONG: nd30fmt $NEW đang chạy. Mở trang web và bấm Ctrl+F5."
say "Trả lại bản trước nếu cần: bash $D/update.sh --rollback"
