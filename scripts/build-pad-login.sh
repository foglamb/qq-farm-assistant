#!/bin/sh
# 在 Docker 构建前生成自包含 AndroidPad 宿主，运行镜像无需 .NET SDK。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DOTNET=${DOTNET:-dotnet}
if ! command -v "$DOTNET" >/dev/null 2>&1 && [ ! -x "$DOTNET" ]; then
  if [ -x /tmp/dotnet8/dotnet ]; then DOTNET=/tmp/dotnet8/dotnet
  else echo "需要 .NET 8 SDK，或设置 DOTNET=/path/to/dotnet" >&2; exit 1; fi
fi
OUT="$ROOT/pad-login/.publish"
rm -rf "$OUT"
"$DOTNET" publish "$ROOT/pad-login/PadLogin.csproj" -c Release -r linux-x64 \
  --self-contained true -p:PublishSingleFile=true -p:DebugType=None -o "$OUT"
cp "$OUT/PadLogin" "$ROOT/pad-login/PadLogin"
chmod 755 "$ROOT/pad-login/PadLogin"
printf 'PadLogin=%s\n' "$ROOT/pad-login/PadLogin"
