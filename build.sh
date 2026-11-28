#!/usr/bin/env bash
# 一条命令构建并部署：前端 → 镜像（含 Pad 协议自动编译）→ 容器。
# 用法：
#   bash build.sh            # 构建并部署到本机 docker
#   bash build.sh --no-deploy # 只构建镜像
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-qq-farm-four-channels:latest}"
BASE_IMAGE="${BASE_IMAGE:-}"
DEPLOY=1
[[ "${1:-}" == "--no-deploy" ]] && DEPLOY=0

echo "[1/3] 构建 Web 前端"
pnpm -C web build

echo "[2/3] 构建镜像 $IMAGE（Pad 协议在镜像内编译）"
BUILD_ARGS=(-f core/Dockerfile.runtime -t "$IMAGE")
[[ -n "$BASE_IMAGE" ]] && BUILD_ARGS+=(--build-arg "BASE_IMAGE=$BASE_IMAGE")
DOCKER_BUILDKIT=1 docker build "${BUILD_ARGS[@]}" .

echo "[3/3] 完成：$IMAGE"
if [[ "$DEPLOY" == "1" && -x /root/deploy-four-production.py ]]; then
  echo "      部署到生产容器"
  python3 /root/deploy-four-production.py
fi

# 清理构建副产物，避免磁盘堆积
docker image prune -f >/dev/null 2>&1 || true
echo "构建缓存已清理"
