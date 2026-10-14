#!/bin/sh
set -eu
cd "$(dirname "$0")"
case "$(uname -m)" in x86_64|amd64) ;; *) echo '本部署模板只支持 linux/amd64' >&2; exit 2;; esac
mkdir -p vendor/wheels vendor/tunnel
python3.11 -m pip download --only-binary=:all: --require-hashes --dest vendor/wheels -r requirements.lock
python3.11 - <<'PYTHON'
import hashlib, io, pathlib, urllib.request, zipfile
url = "https://github.com/openai/tunnel-client/releases/download/v0.0.16/tunnel-client-v0.0.16-linux-amd64.zip"
data = urllib.request.urlopen(url, timeout=120).read()
expected = "d60cdba019bce451bcc3a15478cc5b9cb11270b049f5b56ea39a80b517f8b117"
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit("Tunnel 下载校验失败；停止，不执行下载文件")
root = pathlib.Path("vendor/tunnel").resolve()
with zipfile.ZipFile(io.BytesIO(data)) as z:
    for item in z.infolist():
        target = (root / item.filename).resolve()
        if not target.is_relative_to(root):
            raise SystemExit("非法压缩包路径")
    z.extractall(root)
for name in ("tunnel-client", "cloudflared"):
    target = root / name
    if not target.is_file():
        raise SystemExit("官方压缩包布局变化；请检查，不继续构建")
    target.chmod(0o755)
print("Tunnel 下载与 SHA256 校验成功")
PYTHON
