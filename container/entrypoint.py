"""Private NAS entrypoint. Errors are fixed categories, never secret values."""
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.path.insert(0, "/opt/bridge/scripts")
from install_local import validate_secret_file
from wechat_dot_bridge.cli import load_config, parser, private_directory

CONFIG = "/config/bridge.json"
PROFILE = "/config/tunnel.yaml"
KEY = "/run/secrets/tunnel-runtime-key"


def fail(code):
    print(json.dumps({"error": code}), file=sys.stderr)
    raise SystemExit(2)


def private_config(path):
    p = Path(path)
    for item in (p, *p.parents):
        if item.is_symlink():
            fail("config_unsafe_path")
    if not p.exists():
        fail("config_missing")
    info = p.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or info.st_size > 16384):
        fail("config_unsafe_permissions")
    return p


def check_bridge():
    private_config(CONFIG)
    args = parser().parse_args(["--config", CONFIG, "status"])
    state, _, locks, *_ = load_config(args)
    if str(state) != "/state" or str(locks) != "/state/locks":
        fail("config_invalid_state_path")
    private_directory(state)
    private_directory(locks)


def check_tunnel():
    # JSON is a YAML subset. The supplied tunnel.yaml intentionally uses JSON
    # so the private profile can be checked without an extra YAML dependency.
    profile = json.loads(private_config(PROFILE).read_text())
    control = profile.get("control_plane", {})
    if not re.fullmatch(r"tunnel_[0-9a-f]{32}", control.get("tunnel_id", "")):
        fail("tunnel_id_invalid")
    expected = json.loads(Path("/opt/container/tunnel.example.yaml").read_text())
    expected["control_plane"]["tunnel_id"] = control["tunnel_id"]
    if profile != expected:
        fail("tunnel_profile_invalid")
    try:
        validate_secret_file(KEY)
    except ValueError as error:
        fail(str(error))
    # Check content without printing it; the upstream metadata check covers
    # ownership, symlinks, hard links, permissions and size.
    key = Path(KEY).read_bytes().strip()
    if len(key) < 20 or any(chr(c).isspace() for c in key):
        fail("key_invalid")


def main():
    os.umask(0o077)
    if os.getuid() == 0:
        fail("non_root_required")
    action, *args = sys.argv[1:] or ["run"]
    if action == "version":
        os.execv("/opt/tunnel/tunnel-client", ["tunnel-client", "--version"])
    if action == "bridge" and args == ["--help"]:
        os.execvp("wechat-dot-bridge", ["wechat-dot-bridge", "--help"])
    check_bridge()
    if action == "bridge":
        os.execvp("wechat-dot-bridge", ["wechat-dot-bridge", "--config", CONFIG, *args])
    if action == "qr":
        os.execvp("python", ["python", "/opt/bridge/scripts/render_login_qr.py",
                            "--state-dir", "/state", "--output", "/state/weixin-login-qr.png"])
    if action not in {"run", "doctor", "check"} or args:
        fail("command_invalid")
    check_tunnel()
    if action == "check":
        os.execvp("python", ["python", "/opt/bridge/scripts/check_runtime.py",
                            "--key-file", KEY, "--state-dir", "/state", "--config", CONFIG,
                            "--command", "/usr/local/bin/wechat-dot-bridge"])
    os.execv("/opt/tunnel/tunnel-client", ["tunnel-client", action, "--profile-file", PROFILE])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        fail("startup_validation_failed")
