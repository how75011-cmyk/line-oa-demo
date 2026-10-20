# LINE Official Account automation demo — 禾光雜貨 (fictional shop)

A portfolio demo of LINE OA back-office automation for small Taiwanese e-commerce
shops. Everything (shop, products, orders) is fictional.

## What it shows

| Feature | Where |
|---|---|
| Welcome message + quick-reply menu on follow | `core.Bot.handle_follow` |
| Product catalog as a Flex Message carousel | `core.product_carousel` |
| Order lookup by order no. + last 3 phone digits (two-step or one message) | `core.Bot._lookup_order` |
| Keyword FAQ (shipping, returns, hours, payment) | `data/catalog.json` |
| Human handoff: bot goes quiet, staff alerted on LINE, staff replies from the back office | `core.Bot._start_handoff`, `/admin` |
| Scheduled broadcasts with an ad-copy compliance pre-check (food / cosmetics wording) | `compliance.py`, `/admin` |
| Basic stats: users, messages, top intents | `/admin` |
| Web simulator so prospects can try it without adding a LINE friend | `/` |

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python app.py          # http://localhost:8000  and  /admin
.venv/bin/python -m pytest -q
```

No LINE credentials are needed for the simulator.

## Connect a real LINE channel

1. LINE Developers Console → create a Messaging API channel.
2. Set env vars: `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `ADMIN_TOKEN`
   (and optionally `STAFF_NOTIFY_TO` = a staff user/group id for handoff alerts).
3. Deploy (Railway / Render / any Docker host) and set the webhook URL to
   `https://<host>/callback`, enable "Use webhook", disable the default auto-reply.

Run a single worker: state (handoffs, broadcasts, stats) is kept in memory.
A production version would move it to a database or Google Sheets.

## Notes

- The compliance word list is a small demo sample, not legal advice.
- Webhook requests are verified with the `X-Line-Signature` HMAC before processing.
- Secrets come from environment variables only; never commit `.env`.
