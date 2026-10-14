#!/bin/sh
set -eu
cd "$(dirname "$0")"
test -x vendor/tunnel/tunnel-client || { echo '请先运行 prepare-vendor.sh' >&2; exit 2; }
docker build --platform linux/amd64 --network none --pull=false -t wechat-dot-bridge:67c726e-tunnel0.0.16-amd64 .
docker image inspect wechat-dot-bridge:67c726e-tunnel0.0.16-amd64 --format '{{.Os}}/{{.Architecture}} {{.Id}}'
