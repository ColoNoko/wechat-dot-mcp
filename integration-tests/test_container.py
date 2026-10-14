"""Host-side checks for the actual final image; requires local Docker only."""
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "wechat-dot-bridge:67c726e-tunnel0.0.16-amd64"
SYNTHETIC_KEY = "SYNTHETIC_CONTAINER_SECRET_6f4ce628_never_a_real_key"


def command(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=kwargs.pop("timeout", 45), **kwargs)


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="container-", dir=ROOT / "test-work")
        self.root = Path(self.temp.name)
        self.names = []
        for name in ("config", "state", "secrets"):
            (self.root / name).mkdir(mode=0o700)
        for source, target in (("bridge.example.json", "bridge.json"), ("tunnel.example.yaml", "tunnel.yaml")):
            text = (ROOT / "container" / source).read_text().replace("REPLACE_WITH_YOUR_TUNNEL_ID", "tunnel_" + "0"*32)
            (self.root / "config" / target).write_text(text)
            (self.root / "config" / target).chmod(0o600)
        self.key = self.root / "secrets/tunnel-runtime-key"

    def tearDown(self):
        for name in self.names:
            command(["docker", "rm", "-f", name])
        self.temp.cleanup()

    def args(self, entry=None, mounted=True):
        result = ["--platform", "linux/amd64", "--network", "none", "--init", "--read-only",
                  "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128",
                  "--memory", "768m", "--memory-swap", "768m", "--cpus", "1",
                  "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m"]
        if mounted:
            for src, dst, readonly in (("config", "/config", True), ("secrets", "/run/secrets", True), ("state", "/state", False)):
                result += ["--mount", f"type=bind,src={self.root/src},dst={dst}" + (",readonly" if readonly else "")]
        if entry:
            result += ["--entrypoint", entry]
        return result

    def run_image(self, *args, entry=None, mounted=True):
        return command(["docker", "run", "--rm", *self.args(entry, mounted), IMAGE, *args])

    def make_key(self):
        self.key.write_text(SYNTHETIC_KEY)
        self.key.chmod(0o600)

    def test_01_architecture_non_root_cli_and_no_exposed_port(self):
        info = json.loads(command(["docker", "image", "inspect", IMAGE]).stdout)[0]
        self.assertEqual((info["Os"], info["Architecture"]), ("linux", "amd64"))
        self.assertEqual(info["Config"]["User"], "1000:1000")
        self.assertFalse(info["Config"].get("ExposedPorts"))
        self.assertEqual(info["Config"]["StopSignal"], "SIGTERM")
        version = self.run_image("version", mounted=False)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertTrue(version.stdout.startswith("0.0.16+"))
        help_result = self.run_image("bridge", "--help", mounted=False)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        result = self.run_image("-c", "import os; assert os.getuid()==1000; assert not os.access('/opt/container/entrypoint.py',os.W_OK); print('non_root_read_only_programs_ok')", entry="python", mounted=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_02_missing_config_and_key_fail_safely(self):
        missing = self.run_image(mounted=False)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stderr)["error"], "config_missing")
        missing = self.run_image()
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stderr)["error"], "key_missing")
        self.assertEqual(missing.stdout, "")

    def test_03_invalid_id_and_unsafe_secret_are_redacted(self):
        self.make_key()
        self.key.chmod(0o644)
        result = self.run_image()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "unsafe_key_file")
        self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)
        self.key.chmod(0o600)
        path = self.root / "config/tunnel.yaml"
        profile = json.loads(path.read_text())
        profile["control_plane"]["tunnel_id"] = "UNCONFIGURED"
        path.write_text(json.dumps(profile))
        result = self.run_image()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "tunnel_id_invalid")

    def test_04_root_and_symlink_config_rejected(self):
        result = command(["docker", "run", "--rm", *self.args(), "--user", "0:0", IMAGE])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "non_root_required")
        config = self.root / "config/bridge.json"
        config.rename(config.with_name("actual.json"))
        config.symlink_to("actual.json")
        result = self.run_image("bridge", "status")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "config_unsafe_path")

    def test_05_initial_status_paused_and_private_database(self):
        result = self.run_image("bridge", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertFalse(status["bound"])
        self.assertFalse(status["enabled"])
        self.assertEqual(status["active_subscriptions"], 0)
        path = self.root / "state/bridge.sqlite3"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.stat().st_uid, os.getuid())

    def create_server(self):
        name = "wdb-test-" + uuid.uuid4().hex[:12]
        self.names.append(name)
        created = command(["docker", "create", "--name", name, "-i", "-a", "stdin", "-a", "stdout", "-a", "stderr",
                           *self.args(), IMAGE, "bridge", "serve"])
        self.assertEqual(created.returncode, 0, created.stderr)
        return name

    def attach(self, name):
        return subprocess.Popen(["docker", "start", "-ai", name], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def rpc(self, proc, method, params=None):
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        self.assertTrue(select.select([proc.stdout], [], [], 20)[0], "stdio response missing")
        result = json.loads(proc.stdout.readline())
        self.assertNotIn("error", result, result)
        return result["result"]

    def stop(self, name, proc):
        start = time.monotonic()
        # A standalone stdio client's orderly shutdown closes its input. The
        # deployment's tunnel owns this pipe; direct Docker -i keeps it open.
        proc.stdin.close()
        proc.stdin = None
        proc.communicate(timeout=20)
        self.assertLess(time.monotonic() - start, 15)
        status = json.loads(command(["docker", "inspect", name]).stdout)[0]["State"]
        self.assertEqual(status["ExitCode"], 0)
        self.assertFalse(status["OOMKilled"])

    def test_06_stdio_database_persistence_real_container_restart_and_eof(self):
        seed = """
from wechat_dot_bridge.store import Store
s=Store('/state')
s.import_binding({'id':'synthetic-container-bot','owner':'synthetic-container-owner',
                  'token':'synthetic-container-binding-not-real','base_url':'https://ilinkai.weixin.qq.com'})
s.set_enabled(True)
s.ingest('synthetic-container-bot',[{'source_id':'persistent-source-id','peer':'synthetic-container-owner',
          'text':'persistent synthetic text','created_at':100,'context_token':'synthetic-context'}], 'persistent-cursor')
s.set_enabled(False)
s.close()
"""
        result = self.run_image("-c", seed, entry="python")
        self.assertEqual(result.returncode, 0, result.stderr)
        name = self.create_server()
        mid = None
        for turn in range(2):
            proc = self.attach(name)
            self.assertEqual(self.rpc(proc, "server/discover")["supportedVersions"], ["2026-07-28"])
            self.assertEqual(len(self.rpc(proc, "tools/list")["tools"]), 11)
            status = self.rpc(proc, "tools/call", {"name": "get_weixin_status"})["structuredContent"]
            self.assertTrue(status["bound"])
            self.assertFalse(status["enabled"])
            self.assertEqual(status["pending"], 1)
            # Mutation CLI must refuse the live worker's lock.
            locked = self.run_image("bridge", "pause")
            self.assertEqual(locked.returncode, 2)
            self.assertEqual(json.loads(locked.stderr)["error"], "already_running")
            pending = self.rpc(proc, "tools/call", {"name": "list_pending_weixin_messages"})["structuredContent"]
            current = pending["messages"][0]["message_id"]
            if mid is not None:
                self.assertEqual(current, mid)
            mid = current
            self.stop(name, proc)
        verify = self.run_image("-c", "from wechat_dot_bridge.store import Store; s=Store('/state'); assert s.get_binding()['cursor']=='persistent-cursor'; assert s.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; s.close(); print('persistent_cursor_and_integrity_ok')", entry="python")
        self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_07_real_default_entrypoint_compose_resources_restart_and_stop(self):
        self.make_key()
        project = "wdb-compose-" + uuid.uuid4().hex[:8]
        override = self.root / "offline.yaml"
        override.write_text("services:\n  bridge:\n    network_mode: none\n")
        env = dict(os.environ, PUID=str(os.getuid()), PGID=str(os.getgid()), WDB_ROOT=str(self.root))
        prefix = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.yaml"), "-f", str(override)]
        config = command([*prefix, "config", "--format", "json"], env=env)
        self.assertEqual(config.returncode, 0, config.stderr)
        self.assertFalse(json.loads(config.stdout)["services"]["bridge"].get("ports"))
        try:
            result = command([*prefix, "up", "-d"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            cid = command([*prefix, "ps", "-q"], env=env).stdout.strip()
            for turn in range(2):
                end = time.monotonic() + 12
                while not (self.root / "state/health.url").exists() and time.monotonic() < end:
                    time.sleep(0.1)
                self.assertTrue((self.root / "state/health.url").is_file())
                info = json.loads(command(["docker", "inspect", cid]).stdout)[0]
                self.assertTrue(info["State"]["Running"])
                host = info["HostConfig"]
                self.assertEqual(host["Memory"], 768*1024*1024)
                self.assertEqual(host["MemorySwap"], 768*1024*1024)
                self.assertEqual(host["NanoCpus"], 1000000000)
                self.assertEqual(host["PidsLimit"], 128)
                self.assertTrue(host["ReadonlyRootfs"])
                self.assertTrue(host["Init"])
                self.assertEqual(host["CapDrop"], ["ALL"])
                self.assertIn("no-new-privileges:true", host["SecurityOpt"])
                self.assertEqual(host["RestartPolicy"]["Name"], "unless-stopped")
                self.assertFalse(info["NetworkSettings"]["Ports"])
                result = command(["docker", "exec", cid, "python", "-c", "from pathlib import Path; import urllib.request; u=Path('/state/health.url').read_text().strip(); assert u.startswith('http://127.0.0.1:'); assert urllib.request.urlopen(u+'/healthz',timeout=3).status==200; print('loopback_health_ok')"])
                self.assertEqual(result.returncode, 0, result.stderr)
                if turn == 0:
                    self.assertEqual(command([*prefix, "restart"], env=env).returncode, 0)
            start = time.monotonic()
            self.assertEqual(command([*prefix, "stop"], env=env).returncode, 0)
            self.assertLess(time.monotonic() - start, 45)
            state = json.loads(command(["docker", "inspect", cid]).stdout)[0]["State"]
            self.assertEqual(state["ExitCode"], 0)
            logs = command(["docker", "logs", cid])
            self.assertNotIn(SYNTHETIC_KEY, logs.stdout + logs.stderr)
        finally:
            command([*prefix, "down"], env=env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
