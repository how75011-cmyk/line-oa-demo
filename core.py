"""
Conversation and back-office logic for the 禾光雜貨 LINE Official Account demo.

Platform-agnostic: every handler returns LINE Messaging API message objects as
plain dicts, so the same output feeds the real LINE webhook and the web
simulator. All shop, product and order data is fictional.
"""

import json
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import compliance

DATA_DIR = Path(__file__).parent / "data"
MAX_MESSAGES_PER_REPLY = 5  # LINE reply API limit

ORDER_RE = re.compile(r"([A-Za-z]{2}\d{4})\D*?(\d{3})(?!\d)")

MENU = ["看商品", "查訂單", "運費", "退換貨", "真人客服"]


def _load(name: str) -> Dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Message builders (LINE Messaging API JSON)
# ---------------------------------------------------------------------------
def quick_reply(labels: List[str]) -> Dict:
    return {
        "items": [
            {"type": "action", "action": {"type": "message", "label": label, "text": label}}
            for label in labels
        ]
    }


def text(body: str, menu: bool = False) -> Dict:
    msg = {"type": "text", "text": body}
    if menu:
        msg["quickReply"] = quick_reply(MENU)
    return msg


def product_bubble(p: Dict) -> Dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": p["color"],
            "paddingAll": "18px",
            "contents": [{"type": "text", "text": p["name"], "weight": "bold", "size": "lg", "color": "#FFFFFF"}],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"NT${p['price']:,}", "weight": "bold", "size": "md"},
                {"type": "text", "text": p["desc"], "size": "sm", "color": "#666666", "wrap": True},
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#06C755",
                    "height": "sm",
                    "action": {"type": "message", "label": "我要訂購", "text": f"我要訂購 {p['name']}"},
                }
            ],
        },
    }


def product_carousel(products: List[Dict]) -> Dict:
    return {
        "type": "flex",
        "altText": "禾光雜貨商品型錄",
        "contents": {"type": "carousel", "contents": [product_bubble(p) for p in products]},
    }


# ---------------------------------------------------------------------------
# Bot: customer-facing conversation + admin back office
# ---------------------------------------------------------------------------
class Bot:
    def __init__(self, catalog: Optional[Dict] = None, orders: Optional[Dict] = None,
                 now: Callable[[], datetime] = datetime.now):
        self.catalog = catalog or _load("catalog.json")
        self.orders = orders or _load("orders.json")
        self.now = now
        self._lock = threading.Lock()
        self.modes: Dict[str, str] = {}          # user_id -> "await_order" | "handoff"
        self.handoffs: Dict[str, Dict] = {}      # user_id -> {since, messages}
        self.outbox: Dict[str, List[Dict]] = {}  # simulator pull queue for pushes
        self.users: set = set()
        self.broadcasts: List[Dict] = []
        self.stats = Counter()
        self.on_handoff: Optional[Callable[[str], None]] = None  # e.g. notify staff on LINE

    # ---- customer side ---------------------------------------------------
    def handle_follow(self, user_id: str) -> List[Dict]:
        with self._lock:
            self.users.add(user_id)
            self.stats["follow"] += 1
        shop = self.catalog["shop"]
        return [
            text(
                f"歡迎加入{shop['name']}！\n（{shop['notice']}）\n\n"
                "可以直接點下面的按鈕看商品、查訂單，或輸入問題，例如「運費多少」。",
                menu=True,
            )
        ]

    def handle_text(self, user_id: str, raw: str) -> List[Dict]:
        msg = (raw or "").strip()
        with self._lock:
            self.users.add(user_id)
            self.stats["messages"] += 1
            mode = self.modes.get(user_id)

        if mode == "handoff":
            with self._lock:
                self.handoffs[user_id]["messages"].append(msg)
            return []  # a human is handling this chat; the bot stays quiet

        if msg in ("真人客服", "找真人", "客服"):
            return self._start_handoff(user_id, msg)

        if msg in ("看商品", "商品", "型錄"):
            self._hit("看商品")
            return [product_carousel(self.catalog["products"]), text("想了解哪一件，點「我要訂購」就好。", menu=True)]

        if msg.startswith("我要訂購"):
            self._hit("訂購")
            name = msg.replace("我要訂購", "").strip()
            return [text(
                f"收到，你想訂「{name}」。\n正式上線時，這裡會帶出購物車連結或 LINE Pay 付款。"
                "這是示範店，不會真的成立訂單。",
                menu=True,
            )]

        found = ORDER_RE.search(msg)
        if found or mode == "await_order":
            return self._lookup_order(user_id, msg, found)

        if msg in ("查訂單", "訂單"):
            self._hit("查訂單")
            with self._lock:
                self.modes[user_id] = "await_order"
            return [text("請輸入訂單編號和手機末三碼，中間空一格。\n例如：HG1023 678")]

        answer = self._faq(msg)
        if answer:
            return [text(answer, menu=True)]

        self._hit("未命中")
        return [text("這個問題我還不會回答。可以點下面的按鈕，或選「真人客服」請專人回覆。", menu=True)]

    def _hit(self, key: str) -> None:
        with self._lock:
            self.stats[f"kw:{key}"] += 1

    def _faq(self, msg: str) -> Optional[str]:
        low = msg.lower()
        for item in self.catalog["faq"]:
            for key in item["keys"]:
                if key in low:
                    self._hit(item["keys"][0])
                    return item["answer"].format(hours=self.catalog["shop"]["hours"])
        return None

    def _lookup_order(self, user_id: str, msg: str, found) -> List[Dict]:
        with self._lock:
            self.modes.pop(user_id, None)
        if not found:
            return [text("格式好像不對。請輸入訂單編號和手機末三碼，例如：HG1023 678", menu=True)]
        order_no, last3 = found.group(1).upper(), found.group(2)
        order = self.orders.get(order_no)
        if not order or order["phone_last3"] != last3:
            return [text("查不到這筆訂單，請確認編號和手機末三碼。需要的話可以點「真人客服」。", menu=True)]
        lines = [f"訂單 {order_no}", f"狀態：{order['status']}", "商品：" + "、".join(order["items"]),
                 f"配送：{order['shipping']}", order["eta"]]
        return [text("\n".join(lines), menu=True)]

    def _start_handoff(self, user_id: str, msg: str) -> List[Dict]:
        self._hit("真人客服")
        with self._lock:
            self.modes[user_id] = "handoff"
            self.handoffs[user_id] = {"since": self.now().isoformat(timespec="minutes"), "messages": [msg]}
            self.stats["handoff"] += 1
        if self.on_handoff:
            self.on_handoff(user_id)
        return [text(f"已通知客服人員，請直接留言說明狀況。\n客服時間：{self.catalog['shop']['hours']}")]

    # ---- admin side ------------------------------------------------------
    def admin_reply(self, user_id: str, body: str) -> Dict:
        msg = text(f"【客服回覆】{body}")
        with self._lock:
            self.outbox.setdefault(user_id, []).append(msg)
        return msg

    def resolve_handoff(self, user_id: str) -> Dict:
        msg = text("這次的客服對話已結束，之後的問題會先由自動回覆處理。", menu=True)
        with self._lock:
            self.modes.pop(user_id, None)
            self.handoffs.pop(user_id, None)
            self.outbox.setdefault(user_id, []).append(msg)
        return msg

    def pull(self, user_id: str) -> List[Dict]:
        with self._lock:
            return self.outbox.pop(user_id, [])

    def schedule_broadcast(self, body: str, send_at: Optional[datetime] = None,
                           acknowledge_findings: bool = False) -> Dict:
        findings = compliance.check(body)
        if findings and not acknowledge_findings:
            return {"ok": False, "findings": findings, "disclaimer": compliance.DISCLAIMER}
        with self._lock:
            item = {
                "id": len(self.broadcasts) + 1,
                "text": body,
                "send_at": (send_at or self.now()).isoformat(timespec="minutes"),
                "status": "scheduled",
                "findings": findings,
            }
            self.broadcasts.append(item)
        return {"ok": True, "broadcast": item}

    def due_broadcasts(self) -> List[Dict]:
        """Mark due broadcasts as sent and return them; the caller delivers."""
        now = self.now().isoformat(timespec="minutes")
        due = []
        with self._lock:
            for b in self.broadcasts:
                if b["status"] == "scheduled" and b["send_at"] <= now:
                    b["status"] = "sent"
                    due.append(b)
        return due

    def deliver_to_simulator(self, body: str) -> int:
        with self._lock:
            for uid in self.users:
                self.outbox.setdefault(uid, []).append(text(body))
            return len(self.users)

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "handoffs": [{"user_id": u, **h} for u, h in self.handoffs.items()],
                "broadcasts": list(self.broadcasts),
                "stats": dict(self.stats),
                "users": len(self.users),
            }
