import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from line_api import verify_signature  # noqa: E402

SECRET = "test-secret"


class FakeLine:
    def __init__(self):
        self.calls = []

    def reply(self, token, messages):
        self.calls.append(("reply", token, messages))

    def push(self, to, messages):
        self.calls.append(("push", to, messages))

    def broadcast(self, messages):
        self.calls.append(("broadcast", messages))


def sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


@pytest.fixture
def line():
    return FakeLine()


@pytest.fixture
def client(line):
    app = create_app(line=line, channel_secret=SECRET, admin_token="", staff_notify_to="Cstaff")
    return app.test_client()


def test_verify_signature_rejects_tampered_body():
    body = b'{"events":[]}'
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body + b" ", sign(body))
    assert not verify_signature(SECRET, body, "")


def test_webhook_rejects_bad_signature(client):
    resp = client.post("/callback", data=b'{"events":[]}', headers={"X-Line-Signature": "nope"})
    assert resp.status_code == 400


def test_webhook_without_credentials_returns_503():
    app = create_app(line=None, channel_secret="", admin_token="")
    assert app.test_client().post("/callback", data=b"{}").status_code == 503


def test_webhook_replies_to_text_message(client, line):
    body = json.dumps({"events": [{
        "type": "message", "replyToken": "rt1",
        "source": {"userId": "Uabc"},
        "message": {"type": "text", "text": "運費"},
    }]}).encode()
    resp = client.post("/callback", data=body, headers={"X-Line-Signature": sign(body)})
    assert resp.status_code == 200
    kind, token, messages = line.calls[0]
    assert (kind, token) == ("reply", "rt1")
    assert "免運" in messages[0]["text"]


def test_handoff_on_real_line_notifies_staff(client, line):
    body = json.dumps({"events": [{
        "type": "message", "replyToken": "rt2",
        "source": {"userId": "Uabc"},
        "message": {"type": "text", "text": "真人客服"},
    }]}).encode()
    client.post("/callback", data=body, headers={"X-Line-Signature": sign(body)})
    assert ("push", "Cstaff") in [(c[0], c[1]) for c in line.calls]


def test_simulator_requires_sim_prefix(client):
    assert client.post("/api/sim/message", json={"user_id": "Ureal", "text": "hi"}).status_code == 400


def test_simulator_conversation(client):
    resp = client.post("/api/sim/message", json={"user_id": "sim-1", "text": "看商品"})
    assert resp.get_json()["messages"][0]["type"] == "flex"


def test_broadcast_now_reaches_simulator_and_line(client, line):
    client.post("/api/sim/follow", json={"user_id": "sim-1"})
    resp = client.post("/api/admin/broadcast", json={"text": "新品到貨"})
    assert resp.status_code == 200
    assert client.get("/api/sim/pull?user_id=sim-1").get_json()["messages"][0]["text"] == "新品到貨"
    assert line.calls[-1][0] == "broadcast"


def test_broadcast_with_violation_returns_422(client):
    resp = client.post("/api/admin/broadcast", json={"text": "保證有效"})
    assert resp.status_code == 422
    assert resp.get_json()["findings"][0]["word"] == "保證有效"


def test_admin_token_enforced():
    app = create_app(line=None, channel_secret="", admin_token="s3cret")
    c = app.test_client()
    assert c.get("/api/admin/state").status_code == 401
    assert c.get("/api/admin/state", headers={"X-Admin-Token": "s3cret"}).status_code == 200
