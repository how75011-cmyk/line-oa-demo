"""
Minimal LINE Messaging API client (stdlib only).

Signature check follows the LINE spec: base64(HMAC-SHA256(channel secret, raw
request body)) compared with the X-Line-Signature header.
"""

import base64
import hashlib
import hmac
import json
import urllib.request
from typing import Dict, List

API_BASE = "https://api.line.me/v2/bot/message"
MAX_MESSAGES = 5


def verify_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    if not channel_secret or not signature:
        return False
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode("utf-8"), signature)


class LineClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _post(self, path: str, payload: Dict) -> int:
        req = urllib.request.Request(
            f"{API_BASE}/{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status

    def reply(self, reply_token: str, messages: List[Dict]) -> None:
        if messages:
            self._post("reply", {"replyToken": reply_token, "messages": messages[:MAX_MESSAGES]})

    def push(self, to: str, messages: List[Dict]) -> None:
        if messages:
            self._post("push", {"to": to, "messages": messages[:MAX_MESSAGES]})

    def broadcast(self, messages: List[Dict]) -> None:
        if messages:
            self._post("broadcast", {"messages": messages[:MAX_MESSAGES]})
