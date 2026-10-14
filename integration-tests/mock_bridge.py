"""TEST ONLY: redirect two network boundaries to a local fixture HTTP server.

The production image does not contain or import this file. CLI, workers, MCP
SDK, SQLite, event signing, deduplication and recovery all remain real.
"""
import http.client
import json
import sys

from wechat_dot_bridge import cli
from wechat_dot_bridge.errors import BridgeError
from wechat_dot_bridge.events import Events
from wechat_dot_bridge.transport import IlinkClient

config, port = sys.argv[1], int(sys.argv[2])


def exchange(path, body, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body, headers or {"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def post(self, binding, path, body, timeout, allow_empty=False):
    code, raw = exchange(path, json.dumps(body).encode())
    if code == 504:
        raise BridgeError("network_timeout")
    if code != 200:
        raise BridgeError("network_error")
    return json.loads(raw)


def callback(url, body, headers):
    if url != "https://callback.example.com/synthetic-private-route":
        raise BridgeError("callback_not_allowed")
    return exchange("/callback", body, headers)


IlinkClient._post = post
IlinkClient.stop_typing = lambda self, binding, ticket: self.send_typing(binding, ticket, 2)
cli.Events = lambda store, **kw: Events(store, post=callback, **kw)
raise SystemExit(cli.main(["--config", config, "serve"]))
