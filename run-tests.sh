#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p evidence test-work/state
chmod 700 test-work test-work/state
python3 integration-tests/test_container.py > evidence/container-tests.log 2>&1
docker run --rm --network none --init --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 768m --cpus 1 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  -v "$PWD/test-work/state:/state" -v "$PWD/integration-tests:/it:ro" \
  --entrypoint python wechat-dot-bridge:67c726e-tunnel0.0.16-amd64 \
  /it/test_mock_flow.py > evidence/mock-flow.log 2>&1
printf '%s\n' 'Container and offline mock tests passed. See evidence/*.log.'
