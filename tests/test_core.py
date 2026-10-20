import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compliance  # noqa: E402
import core  # noqa: E402


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def make_bot(t=datetime(2026, 10, 20, 21, 0)):
    return core.Bot(now=Clock(t))


def first_text(messages):
    return next(m["text"] for m in messages if m["type"] == "text")


# ---- compliance --------------------------------------------------------------
def test_compliance_flags_medical_and_exaggerated_claims_ignoring_spaces():
    findings = compliance.check("這款茶能治療失眠，100 % 有效！")
    words = [f["word"] for f in findings]
    assert words == ["治療", "100%有效"]
    assert all(f["law"] for f in findings)


def test_compliance_passes_plain_copy():
    assert compliance.check("新品手作陶杯到貨，週末滿千免運。") == []


# ---- conversation ------------------------------------------------------------
def test_follow_greets_with_menu():
    msgs = make_bot().handle_follow("u1")
    assert "虛構示範店" in msgs[0]["text"]
    labels = [i["action"]["label"] for i in msgs[0]["quickReply"]["items"]]
    assert labels == core.MENU


def test_catalog_returns_flex_carousel_of_all_products():
    bot = make_bot()
    msgs = bot.handle_text("u1", "看商品")
    flex = msgs[0]
    assert flex["type"] == "flex"
    assert len(flex["contents"]["contents"]) == len(bot.catalog["products"])


def test_order_lookup_two_step_flow():
    bot = make_bot()
    assert "訂單編號" in first_text(bot.handle_text("u1", "查訂單"))
    reply = first_text(bot.handle_text("u1", "HG1023 678"))
    assert "已出貨" in reply and "手作陶杯" in reply
    assert "u1" not in bot.modes


def test_order_lookup_in_one_message_is_case_insensitive():
    reply = first_text(make_bot().handle_text("u1", "hg1024 215"))
    assert "備貨中" in reply


def test_order_lookup_rejects_wrong_phone_digits():
    reply = first_text(make_bot().handle_text("u1", "HG1023 111"))
    assert "查不到" in reply


def test_order_lookup_bad_format_exits_mode():
    bot = make_bot()
    bot.handle_text("u1", "查訂單")
    assert "格式" in first_text(bot.handle_text("u1", "我不知道"))
    assert "u1" not in bot.modes


def test_faq_answers_shipping_question():
    assert "免運" in first_text(make_bot().handle_text("u1", "請問運費多少？"))


def test_unknown_question_offers_handoff():
    assert "真人客服" in first_text(make_bot().handle_text("u1", "你們老闆是誰"))


# ---- handoff -----------------------------------------------------------------
def test_handoff_mutes_bot_until_resolved():
    bot = make_bot()
    alerts = []
    bot.on_handoff = alerts.append
    bot.handle_text("u1", "真人客服")
    assert alerts == ["u1"]
    assert bot.handle_text("u1", "我的杯子破了") == []
    assert bot.snapshot()["handoffs"][0]["messages"] == ["真人客服", "我的杯子破了"]

    bot.admin_reply("u1", "不好意思，我們幫你換新")
    bot.resolve_handoff("u1")
    pulled = bot.pull("u1")
    assert pulled[0]["text"].startswith("【客服回覆】")
    assert len(pulled) == 2
    assert bot.handle_text("u1", "運費") != []


# ---- broadcasts --------------------------------------------------------------
def test_broadcast_blocked_when_copy_has_findings():
    result = make_bot().schedule_broadcast("喝了立即見效")
    assert result["ok"] is False
    assert result["findings"][0]["word"] == "立即見效"


def test_broadcast_allowed_after_acknowledging_findings():
    result = make_bot().schedule_broadcast("喝了立即見效", acknowledge_findings=True)
    assert result["ok"] is True and result["broadcast"]["findings"]


def test_scheduled_broadcast_is_released_only_when_due():
    clock = Clock(datetime(2026, 10, 20, 21, 0))
    bot = core.Bot(now=clock)
    bot.handle_follow("sim-a")
    bot.schedule_broadcast("週末滿千免運", send_at=datetime(2026, 10, 21, 9, 0))
    assert bot.due_broadcasts() == []

    clock.t = datetime(2026, 10, 21, 9, 0)
    due = bot.due_broadcasts()
    assert [b["text"] for b in due] == ["週末滿千免運"]
    assert bot.deliver_to_simulator(due[0]["text"]) == 1
    assert bot.pull("sim-a")[0]["text"] == "週末滿千免運"
    assert bot.due_broadcasts() == []  # not sent twice
