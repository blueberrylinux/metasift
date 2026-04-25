-- Runtime configuration overrides — populated by the Settings UI so the user
-- can rotate the OpenMetadata JWT (and similar) without editing .env + restarting.
-- Resolution order at read time:
--   1. runtime_config[key] — set via the UI
--   2. .env / app.config.settings — bootstrap default
-- Empty / unset key means "no override; fall through to settings".
CREATE TABLE IF NOT EXISTS runtime_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
