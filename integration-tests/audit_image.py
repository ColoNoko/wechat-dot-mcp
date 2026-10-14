"""Inspect every saved Docker layer without extracting or executing its files."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tarfile

archive = Path(sys.argv[1])
findings = []
members = 0
markers = [b"SYNTHETIC_CONTAINER_SECRET_6f4ce628_never_a_real_key",
           b"synthetic-runtime-key-not-real-0000", b"only-a-synthetic-signing-key-32!!",
           b"persistent synthetic text"]
secret_pattern = re.compile(rb"(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{35,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
with tarfile.open(archive) as saved:
    manifest = json.load(saved.extractfile("manifest.json"))
    assert len(manifest) == 1
    record = manifest[0]
    raw_config = saved.extractfile(record["Config"]).read()
    config = json.loads(raw_config)
    assert config["architecture"] == "amd64" and config["os"] == "linux"
    assert config["config"]["User"] == "1000:1000"
    assert not config["config"].get("ExposedPorts")
    assert not any(marker in raw_config for marker in markers)
    for layer_name in record["Layers"]:
        with tarfile.open(fileobj=saved.extractfile(layer_name), mode="r|*") as layer:
            for item in layer:
                members += 1
                name = item.name.removeprefix("./")
                if not item.isfile():
                    continue
                if (name.startswith(("state/", "config/", "run/secrets/"))
                        or re.search(r"(?:^|/)(?:bridge\.sqlite3(?:-.*)?|weixin-login\.json|tunnel-runtime-key)$", name)
                        or "/.git/" in name or "/.venv/" in name):
                    findings.append({"path": name, "category": "unexpected_runtime_file"})
                data = layer.extractfile(item).read()
                if any(marker in data for marker in markers):
                    findings.append({"path": name, "category": "test_secret_in_image"})
                if name.startswith(("opt/bridge/", "opt/container/")) and secret_pattern.search(data):
                    findings.append({"path": name, "category": "credential_pattern"})
                if name in {"opt/tunnel/tunnel-client", "opt/tunnel/cloudflared"}:
                    assert data[:4] == b"\x7fELF" and struct.unpack("<H", data[18:20])[0] == 62
    result = {"ok": not findings, "image_id": "sha256:" + hashlib.sha256(raw_config).hexdigest(),
              "platform": "linux/amd64", "layers": len(record["Layers"]), "layer_members": members,
              "checks": ["image metadata", "ELF x86-64", "all-layer runtime paths", "test-secret markers",
                         "application credential patterns", "no published ports"],
              "findings": findings}
print(json.dumps(result, indent=2))
raise SystemExit(bool(findings))
