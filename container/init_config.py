"""Initialize only new private NAS directories; never overwrite an install."""
import json
import os
from pathlib import Path
import re
import sys

os.umask(0o077)
root = Path("/setup")
try:
    if os.getuid() == 0:
        raise ValueError("run_as_existing_non_root_user")
    if len(sys.argv) != 2 or not re.fullmatch(r"tunnel_[0-9a-f]{32}", sys.argv[1]):
        raise ValueError("invalid_tunnel_id")
    if any((root / name).exists() or (root / name).is_symlink()
           for name in ("config", "state", "secrets", ".env")):
        raise ValueError("installation_already_exists")
    for name in ("config", "state", "secrets"):
        (root / name).mkdir(mode=0o700)
    profile = json.loads(Path("/opt/container/tunnel.example.yaml").read_text())
    profile["control_plane"]["tunnel_id"] = sys.argv[1]
    (root / "config/tunnel.yaml").write_text(json.dumps(profile, indent=2) + "\n")
    (root / "config/bridge.json").write_bytes(Path("/opt/container/bridge.example.json").read_bytes())
    (root / ".env").write_text(f"PUID={os.getuid()}\nPGID={os.getgid()}\nWDB_ROOT=REPLACE_WITH_ABSOLUTE_DEPLOYMENT_DIRECTORY\n")
    print(json.dumps({"initialized": True, "key_created": False, "started": False}))
except Exception as error:
    # Only fixed errors, never report input values.
    code = str(error) if isinstance(error, ValueError) else "initialization_failed"
    print(json.dumps({"error": code}), file=sys.stderr)
    raise SystemExit(2)
