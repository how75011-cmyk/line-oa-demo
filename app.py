"""
禾光雜貨 LINE OA demo — web service.

Routes:
  POST /callback          LINE webhook (needs LINE_CHANNEL_SECRET + LINE_CHANNEL_ACCESS_TOKEN)
  GET  /                  web simulator (works with no LINE credentials)
  GET  /admin             back office: broadcasts with compliance check, handoff queue, stats
  /api/sim/*              simulator endpoints
  /api/admin/*            admin endpoints (protected by ADMIN_TOKEN when set)

Env vars:
  LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN — LINE Developers Console (optional)
  STAFF_NOTIFY_TO   — LINE user/group id to push handoff alerts to (optional)
  ADMIN_TOKEN       — required header X-Admin-Token for /api/admin/* (set it when public)
  PORT              — provided by the host; default 8000

State is in memory, so run a single worker (see Procfile).
"""

import json
import logging
import os
import threading
import time
from datetime import datetime

from flask import Flask, abort, jsonify, request, send_from_directory

import compliance
import core
from line_api import LineClient, verify_signature

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("line-oa-demo")

SCHEDULER_INTERVAL_SEC = 15


def create_app(bot=None, line=None, channel_secret=None, admin_token=None,
               staff_notify_to=None, start_scheduler=False) -> Flask:
    app = Flask(__name__, static_folder="static")
    bot = bot or core.Bot()
    if channel_secret is None:
        channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    if line is None and os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        line = LineClient(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
    if admin_token is None:
        admin_token = os.getenv("ADMIN_TOKEN", "")
    if staff_notify_to is None:
        staff_notify_to = os.getenv("STAFF_NOTIFY_TO", "")
    app.config["bot"] = bot

    def is_sim(user_id: str) -> bool:
        return user_id.startswith("sim-")

    def notify_staff(user_id: str) -> None:
        if line and staff_notify_to and not is_sim(user_id):
            _safe(line.push, staff_notify_to, [core.text("有顧客要求真人客服，請到後台查看。")])

    bot.on_handoff = notify_staff

    def require_admin() -> None:
        if admin_token and request.headers.get("X-Admin-Token") != admin_token:
            abort(401)

    def deliver_due() -> int:
        sent = 0
        for b in bot.due_broadcasts():
            if line:
                _safe(line.broadcast, [core.text(b["text"])])
            bot.deliver_to_simulator(b["text"])
            sent += 1
        return sent

    app.config["deliver_due"] = deliver_due

    # ---- pages -------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "simulator.html")

    @app.get("/admin")
    def admin_page():
        return send_from_directory(app.static_folder, "admin.html")

    @app.get("/healthz")
    def health():
        return {"ok": True, "line_connected": bool(line and channel_secret)}

    # ---- LINE webhook ------------------------------------------------------
    @app.post("/callback")
    def callback():
        if not (line and channel_secret):
            abort(503, "LINE credentials are not configured")
        body = request.get_data()
        if not verify_signature(channel_secret, body, request.headers.get("X-Line-Signature", "")):
            abort(400)
        for event in json.loads(body or b"{}").get("events", []):
            user_id = event.get("source", {}).get("userId", "anon")
            if event.get("type") == "follow":
                messages = bot.handle_follow(user_id)
            elif event.get("type") == "message" and event.get("message", {}).get("type") == "text":
                messages = bot.handle_text(user_id, event["message"]["text"])
            else:
                continue
            if messages and event.get("replyToken"):
                _safe(line.reply, event["replyToken"], messages)
        return "OK"

    # ---- simulator API -----------------------------------------------------
    def sim_user() -> str:
        user_id = str((request.get_json(silent=True) or {}).get("user_id") or request.args.get("user_id") or "")
        if not is_sim(user_id) or len(user_id) > 40:
            abort(400, "user_id must start with sim-")
        return user_id

    @app.post("/api/sim/follow")
    def sim_follow():
        return {"messages": bot.handle_follow(sim_user())}

    @app.post("/api/sim/message")
    def sim_message():
        user_id = sim_user()
        body = str((request.get_json(silent=True) or {}).get("text", ""))[:500]
        return {"messages": bot.handle_text(user_id, body)}

    @app.get("/api/sim/pull")
    def sim_pull():
        return {"messages": bot.pull(sim_user())}

    # ---- admin API ---------------------------------------------------------
    @app.get("/api/admin/state")
    def admin_state():
        require_admin()
        return {**bot.snapshot(), "line_connected": bool(line and channel_secret)}

    @app.post("/api/admin/check")
    def admin_check():
        require_admin()
        body = str((request.get_json(silent=True) or {}).get("text", ""))
        return {"findings": compliance.check(body), "disclaimer": compliance.DISCLAIMER}

    @app.post("/api/admin/broadcast")
    def admin_broadcast():
        require_admin()
        data = request.get_json(silent=True) or {}
        body = str(data.get("text", "")).strip()[:1000]
        if not body:
            abort(400, "text is required")
        send_at = None
        if data.get("send_at"):
            try:
                send_at = datetime.fromisoformat(str(data["send_at"]))
            except ValueError:
                abort(400, "send_at must be ISO format")
        result = bot.schedule_broadcast(body, send_at, bool(data.get("acknowledge")))
        if result["ok"]:
            deliver_due()
        return jsonify(result), (200 if result["ok"] else 422)

    @app.post("/api/admin/reply")
    def admin_reply():
        require_admin()
        data = request.get_json(silent=True) or {}
        user_id, body = str(data.get("user_id", "")), str(data.get("text", "")).strip()[:500]
        if not user_id or not body:
            abort(400)
        msg = bot.admin_reply(user_id, body)
        if line and not is_sim(user_id):
            _safe(line.push, user_id, [msg])
        return {"ok": True}

    @app.post("/api/admin/resolve")
    def admin_resolve():
        require_admin()
        user_id = str((request.get_json(silent=True) or {}).get("user_id", ""))
        msg = bot.resolve_handoff(user_id)
        if line and not is_sim(user_id):
            _safe(line.push, user_id, [msg])
        return {"ok": True}

    if start_scheduler:
        def loop():
            while True:
                time.sleep(SCHEDULER_INTERVAL_SEC)
                try:
                    deliver_due()
                except Exception:  # keep the scheduler alive
                    logger.exception("scheduler tick failed")

        threading.Thread(target=loop, daemon=True).start()

    return app


def _safe(fn, *args) -> None:
    """Call the LINE API without letting a network error break the request."""
    try:
        fn(*args)
    except Exception:
        logger.exception("LINE API call failed: %s", getattr(fn, "__name__", fn))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    create_app(start_scheduler=True).run(host="0.0.0.0", port=port, threaded=True)
