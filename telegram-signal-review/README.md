# Telegram Signal Review V2 — isolated Cloudflare Worker

This is a **standalone preview**: it does not alter the current Cloudflare V1
website, does not read private groups, and never places trades. It evaluates
**manually forwarded photos with captions** or standalone signal texts, without OCR.

## Deployment checklist (NOT performed automatically)

1. Create a new Cloudflare D1 database named `whale-telegram-review-v2`.
   Record its ID in a **local** copy of `wrangler.toml` as the DB binding.
2. Apply `schema.sql` to that D1 database (e.g., with Wrangler D1 execute
   using `--remote --file=telegram-signal-review/schema.sql`).
3. Set Cloudflare **secrets** for the new Worker:
   `TELEGRAM_BOT_TOKEN` (existing bot), `TELEGRAM_CHAT_ID` (your private
   Telegram chat), and `TELEGRAM_WEBHOOK_SECRET` (new random 32+ char string).
   **Never write any secret into GitHub or share it in chat.**
4. Deploy the Worker in **a separate name** `whale-telegram-review-v2`.
5. **IMPORTANT:** Telegram allows only **one active webhook per bot**.
   Switching this existing bot to the new webhook would interrupt any other
   webhook receiver. Check its existing webhook first. Existing GitHub Actions
   `sendMessage` alerts need no webhook and can continue independently.
   Do **not** switch the existing webhook until the old setup is understood.
6. Only after verifying current bot ownership/route, set Telegram's webhook to
   `https://<new-worker-domain>/webhook` with the new
   `X-Telegram-Bot-Api-Secret-Token` secret configured in `setWebhook`
   (the HTTPS call should be done from a secure terminal, never in public logs).
7. Forward **one fresh photo and caption** from the signal group to the bot.
   Check D1 update deduplication and the reply. Check `/health` for readiness.
8. Validate direct Binance **USD-M Futures** public price access from Cloudflare.
   If blocked (e.g. 451), the reply explicitly says unverified price. It must
   never silently substitute Spot/other exchanges.

## Limits / security

- Private-chat allowlist only. Telegram webhook secret required.
- D1 unique update ID prevents Telegram retry duplicates; delivery is at-most
  once and may require manual retry if Telegram send fails.
- Image data is **not downloaded/OCR processed**. Numeric levels must be in
  the caption; ambiguous direction remains incomplete.
- No orders, no entry recommendation, no automatic copying of group content.
- A test pass is not evidence of a deployed or working live Telegram webhook.

Run offline locally: `node telegram-signal-review/test.mjs`.
