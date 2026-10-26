#!/usr/bin/env bash
set -Eeuo pipefail

cd /home/thaianhvu/eventflow

# Ngăn hai tiến trình triển khai chạy cùng lúc.
exec 9>/home/thaianhvu/.eventflow-deploy.lock
flock -w 60 9

commit="${1:?Missing commit SHA}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Commit SHA không hợp lệ"
  exit 1
}

compose() {
  docker compose -p eventflow \
    --env-file .env -f compose.deploy.yaml "$@"
}

export DEPLOY_IMAGE="ghcr.io/thaianhvu29/eventflow:$commit"
export APP_VERSION="$commit"

# Ghi nhận chính xác image và phiên bản đang chạy.
old_container="$(compose ps -q web)"
if [[ -z "$old_container" ]]; then
  echo "Không tìm thấy web đang chạy để làm bản rollback."
  exit 1
fi

old_image="$(docker inspect --format '{{.Image}}' "$old_container")"
old_version="$(docker inspect "$old_container" | python3 -c '
import json, sys
env = json.load(sys.stdin)[0]["Config"]["Env"]
print(next(v.split("=", 1)[1] for v in env if v.startswith("APP_VERSION=")))
')"

port="$(compose port web 8000)"
port="${port##*:}"
base_url="http://127.0.0.1:$port"

verify() {
  local expected="$1"
  local attempts="$2"
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 3 "$base_url/health/ready" >/dev/null; then
      if curl -fsS --max-time 3 "$base_url/health/live" |
        python3 -c '
import json, sys
sys.exit(0 if json.load(sys.stdin)["version"] == sys.argv[1] else 1)
' "$expected"; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

# Chỉ triển khai khi bản hiện tại đang khỏe.
if ! verify "$old_version" 3; then
  echo "Bản hiện tại chưa khỏe. Dừng để kiểm tra, chưa thay web."
  exit 1
fi

echo "Phiên bản hiện tại: $old_version"
echo "Phiên bản mới: $commit"

# Các lỗi ở giai đoạn này chưa thay container web hiện tại.
compose pull init web
compose up -d --no-build --no-deps init

init_id="$(compose ps -aq init)"
if ! init_exit="$(timeout 120 docker wait "$init_id")"; then
  echo "Khởi tạo quá thời gian hoặc gặp lỗi. Chưa thay web."
  docker logs --tail=50 "$init_id"
  exit 1
fi

if [[ "$init_exit" != "0" ]]; then
  docker logs --tail=50 "$init_id"
  echo "Khởi tạo thất bại. Chưa thay web."
  exit 1
fi

if compose up -d --no-build --no-deps web; then
  if verify "$commit" 30; then
    echo "DEPLOY SUCCESS: $commit"
    exit 0
  fi
fi

echo "Bản mới thất bại. Bắt đầu rollback."
compose logs --tail=50 web || true

# Dùng image ID cũ tại máy, không phụ thuộc việc tải lại registry.
export DEPLOY_IMAGE="$old_image"
export APP_VERSION="$old_version"

if compose up -d --no-build --no-deps --pull never web; then
  if verify "$old_version" 30; then
    echo "ROLLBACK SUCCESS: $old_version"
    # Job vẫn đỏ vì phiên bản mới triển khai thất bại.
    exit 1
  fi
fi

echo "ROLLBACK FAILED: cần kiểm tra thủ công."
compose logs --tail=80 web || true
exit 1
