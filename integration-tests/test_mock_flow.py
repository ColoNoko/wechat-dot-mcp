"""Run inside the shipped image with --network none; all HTTP is loopback.

Actual official tunnel-client polls a mock control plane and runs the actual
bridge CLI/SDK child. Only the Weixin/callback network boundary is replaced.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time
import unittest

from wechat_dot_bridge.store import Store

SIGNING_BYTES = b"only-a-synthetic-signing-key-32!!"
SIGNING_SECRET = "whsec_" + base64.b64encode(SIGNING_BYTES).decode()
ACCOUNT, OWNER = "synthetic@im.bot", "synthetic@im.wechat"
TEXT = "容器模拟验收：收到请回复一次。"
REPLY = "模拟文字回复，验证同一会话与幂等。"


class FlowTests(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.directory = tempfile.TemporaryDirectory(prefix="mock-flow-", dir="/state")
        self.root = Path(self.directory.name)
        self.state = self.root / "db"
        self.state.mkdir(mode=0o700)
        self.config = self.root / "bridge.json"
        self.config.write_text(json.dumps({"state_dir": str(self.state), "lock_dir": str(self.root / "locks"),
                                           "callback_hosts": ["callback.example.com"]}))

    def prepare_runtime(self, uncertain=False):
        store = Store(self.state)
        store.import_binding({"id": ACCOUNT, "owner": OWNER, "token": "synthetic-bot-token-not-real",
                              "base_url": "https://ilinkai.weixin.qq.com"})
        store.set_enabled(True)
        store.close()
        self.commands, self.responses = queue.Queue(), {}
        self.event = threading.Event()
        self.events, self.posts, self.challenges, self.http_errors = [], [], [], []
        self.polls = 0
        self.release_message = False
        self.uncertain = uncertain
        self.counter = 0
        case = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, payload, code=200):
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when a mock long poll is canceled on stop.

            def do_GET(self):
                if self.path == "/v1/tunnels/tunnel_" + "0"*32:
                    return self.respond({"id": "tunnel_" + "0"*32, "name": "synthetic", "description": "offline fixture"})
                if "/poll" not in self.path:
                    case.http_errors.append("unexpected_get:" + self.path)
                    return self.respond({}, 404)
                if self.headers.get("Authorization") != "Bearer synthetic-runtime-key-not-real-0000":
                    case.http_errors.append("wrong_control_auth")
                try:
                    command = case.commands.get(timeout=0.15)
                    commands = [command]
                except queue.Empty:
                    commands = []
                self.respond({"commands": commands})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw)
                if self.path.endswith("/response"):
                    case.responses[body["request_id"]] = body
                    return self.respond({})
                if self.path == "/ilink/bot/getupdates":
                    time.sleep(0.08)
                    case.polls += 1
                    message = {"message_id": 18446744073709551615, "from_user_id": OWNER,
                               "to_user_id": ACCOUNT, "create_time_ms": int(time.time()*1000),
                               "message_type": 1, "message_state": 2,
                               "context_token": "synthetic-context-not-real",
                               "item_list": [{"type": 1, "text_item": {"text": TEXT}}]}
                    return self.respond({"ret": 0, "msgs": [message] if case.release_message else [],
                                         "get_updates_buf": "synthetic-cursor-after-poll"})
                if self.path == "/ilink/bot/getconfig":
                    return self.respond({"ret": 0, "typing_ticket": "synthetic-typing-ticket"})
                if self.path == "/ilink/bot/sendtyping":
                    return self.respond({})
                if self.path == "/ilink/bot/sendmessage":
                    case.posts.append(body)
                    return self.respond({}, 504 if case.uncertain else 200)
                if self.path == "/callback":
                    material = (self.headers["webhook-id"] + "." + self.headers["webhook-timestamp"] + ".").encode() + raw
                    signature = "v1," + base64.b64encode(hmac.new(SIGNING_BYTES, material, hashlib.sha256).digest()).decode()
                    if not hmac.compare_digest(signature, self.headers["webhook-signature"]):
                        case.http_errors.append("bad_webhook_signature")
                        return self.respond({}, 401)
                    if abs(int(self.headers["webhook-timestamp"]) - time.time()) > 30:
                        case.http_errors.append("stale_webhook_signature")
                    if body.get("type") == "verification":
                        case.challenges.append(body)
                        return self.respond({"challenge": body["challenge"]})
                    if set(body["data"]) != {"message_id"}:
                        case.http_errors.append("private_data_in_event")
                    if body["eventId"] != self.headers["webhook-id"]:
                        case.http_errors.append("event_id_mismatch")
                    case.events.append(body)
                    case.event.set()
                    return self.respond({})
                case.http_errors.append("unexpected_post")
                self.respond({}, 404)

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        key = self.root / "synthetic.key"
        key.write_text("synthetic-runtime-key-not-real-0000")
        profile = {"config_version": 1,
                   "control_plane": {"base_url": "http://127.0.0.1:" + str(self.http.server_port),
                                     "tunnel_id": "tunnel_" + "0"*32, "api_key": "file:" + str(key)},
                   "health": {"listen_addr": "127.0.0.1:0", "url_file": str(self.root / "health.url")},
                   "admin_ui": {"open_browser": False},
                   "log": {"level": "warn", "format": "json", "file": "/dev/null"},
                   "mcp": {"commands": [{"channel": "main", "command":
                             f"python /it/mock_bridge.py {self.config} {self.http.server_port}"}]}}
        self.profile = self.root / "tunnel.yaml"
        self.profile.write_text(json.dumps(profile))
        self.process = None
        self.start()

    def tearDown(self):
        if getattr(self, "process", None):
            self.stop()
        if hasattr(self, "http"):
            self.http.shutdown()
            self.http.server_close()
        self.directory.cleanup()

    def start(self):
        self.session_headers = {}
        self.process = subprocess.Popen(["/opt/tunnel/tunnel-client", "run", "--profile-file", str(self.profile)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        discovered = self.request("server/discover")
        self.assertEqual(discovered["supportedVersions"], ["2026-07-28"])
        self.assertEqual(self.request("initialize", {"protocolVersion": "2026-07-28", "capabilities": {},
                         "clientInfo": {"name": "synthetic-container-client", "version": "1"}})["protocolVersion"], "2026-07-28")
        self.request("notifications/initialized", notification=True)
        self.assertEqual(len(self.request("tools/list")["tools"]), 11)
        self.assertEqual(self.request("events/list")["events"][0]["name"], "weixin.message")

    def stop(self):
        start = time.monotonic()
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        output, errors = self.process.communicate(timeout=12)
        self.assertLess(time.monotonic() - start, 12)
        self.assertEqual(self.process.returncode, 0, errors.decode())
        for value in (SIGNING_SECRET, TEXT, REPLY, "synthetic-bot-token-not-real"):
            self.assertNotIn(value.encode(), output + errors)
        self.process = None
        # Let the old mock long poll finish before the next process polls.
        time.sleep(0.3)

    def request(self, method, params=None, notification=False):
        self.counter += 1
        rid = "fixture-" + str(self.counter)
        rpc = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            rpc["id"] = self.counter
        self.commands.put({"command_type": "jsonrpc", "request_id": rid, "channel": "main",
                           "shard_token": rid, "created_at": datetime.now(timezone.utc).isoformat(),
                           "headers": {"Content-Type": ["application/json"], **self.session_headers},
                           "jsonrpc": rpc})
        end = time.monotonic() + 20
        while rid not in self.responses and time.monotonic() < end:
            if self.process.poll() is not None:
                self.fail("official tunnel exited before answering: " + self.process.stderr.read().decode())
            time.sleep(0.02)
        self.assertTrue(rid in self.responses, "mock control-plane command did not finish")
        response = self.responses[rid]
        for key, value in response.get("resp_headers", {}).items():
            if key.lower() == "mcp-session-id":
                self.session_headers[key] = value
        if notification:
            self.assertEqual(response["resp_type"], "notify_ack")
            return {}
        self.assertEqual(response["resp_type"], "jsonrpc_response")
        result = response["resp_json"]
        self.assertNotIn("error", result, result)
        return result["result"]

    def call(self, name, arguments=None):
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]

    def run_flow(self, uncertain):
        self.prepare_runtime(uncertain)
        self.request("events/subscribe", {"name": "weixin.message", "arguments": {}, "ttlMs": None,
                     "delivery": {"mode": "webhook", "url": "https://callback.example.com/synthetic-private-route",
                                  "secret": SIGNING_SECRET}})
        self.assertEqual(len(self.challenges), 1)
        self.release_message = True
        self.assertTrue(self.event.wait(12), "incoming message event missing")
        mid = self.events[0]["data"]["message_id"]
        message = self.call("read_weixin_message", {"message_id": mid})
        self.assertIn(TEXT, json.dumps(message, ensure_ascii=False))
        reply = {"message_id": mid, "text": REPLY, "reply_key": "synthetic-once"}
        queued = self.call("reply_weixin_message", reply)
        end = time.monotonic() + 12
        expected = "uncertain" if uncertain else "accepted"
        while time.monotonic() < end:
            status = self.call("get_weixin_send_status", {"message_id": mid, "reply_id": queued["reply_id"]})
            if status["status"] == expected:
                break
            time.sleep(0.1)
        self.assertEqual(status["status"], expected)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]["msg"]["to_user_id"], OWNER)
        self.assertEqual(self.posts[0]["msg"]["item_list"], [{"type": 1, "text_item": {"text": REPLY}}])
        self.assertEqual(self.call("reply_weixin_message", reply)["reply_id"], queued["reply_id"])
        self.stop()
        self.start()
        self.assertEqual(self.call("get_weixin_send_status", {"message_id": mid})["status"], expected)
        self.assertEqual(self.call("reply_weixin_message", reply)["status"], expected)
        after = self.polls
        end = time.monotonic() + 6
        while self.polls < after + 3 and time.monotonic() < end:
            time.sleep(0.05)
        self.assertGreaterEqual(self.polls, after + 3)
        self.assertEqual(len(self.posts), 1, "duplicate reply sent after restart")
        self.assertEqual(len(self.events), 1, "duplicate message was re-notified after completed work")
        public = json.dumps(self.call("get_weixin_status"), ensure_ascii=False)
        for value in (SIGNING_SECRET, OWNER, ACCOUNT, TEXT, REPLY, "synthetic-bot-token-not-real"):
            self.assertNotIn(value, public)
        self.assertEqual(self.http_errors, [])
        self.stop()
        for path in self.state.glob("bridge.sqlite3*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())

    def test_text_in_event_read_reply_once_and_restart(self):
        self.run_flow(False)

    def test_uncertain_send_survives_restart_without_resend(self):
        self.run_flow(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
