CREATE TABLE IF NOT EXISTS telegram_review_updates (update_id INTEGER PRIMARY KEY, received_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS telegram_review_updates_received ON telegram_review_updates(received_at);
