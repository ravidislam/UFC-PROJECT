-- ============================================================
-- UFC Preview Dashboard - Database Schema
-- ============================================================
-- Design philosophy:
--   Three core tables linked by fighter_id and event_id.
--   This "normalized" design means fighter stats are stored once
--   and reused across many fights — no duplication.
-- ============================================================

-- EVENTS: one row per UFC card (e.g. "UFC 300")
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,           -- "UFC 300: Pereira vs Hill"
    date        TEXT    NOT NULL,           -- ISO format: "2024-04-13"
    location    TEXT,                       -- "Las Vegas, Nevada, USA"
    url         TEXT    UNIQUE,             -- source URL for re-scraping
    scraped_at  TEXT    DEFAULT (datetime('now'))
);

-- FIGHTERS: one row per fighter, stats updated each scrape
CREATE TABLE IF NOT EXISTS fighters (
    fighter_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    nickname            TEXT,
    record_wins         INTEGER DEFAULT 0,
    record_losses       INTEGER DEFAULT 0,
    record_draws        INTEGER DEFAULT 0,
    height_cm           REAL,
    reach_cm            REAL,
    stance              TEXT,               -- Orthodox / Southpaw / Switch
    dob                 TEXT,               -- date of birth
    -- striking stats (per fight averages from ufcstats)
    sig_str_landed_pm   REAL,               -- significant strikes landed per minute
    sig_str_accuracy    REAL,               -- significant strike accuracy 0.0-1.0
    sig_str_absorbed_pm REAL,               -- sig strikes absorbed per minute
    sig_str_defense     REAL,               -- sig strike defense rate 0.0-1.0
    -- grappling stats
    td_avg              REAL,               -- takedown average per 15 min
    td_accuracy         REAL,               -- takedown accuracy 0.0-1.0
    td_defense          REAL,               -- takedown defense rate 0.0-1.0
    sub_avg             REAL,               -- submission attempts per 15 min
    -- derived metrics (calculated and stored for fast querying)
    total_fights        INTEGER DEFAULT 0,
    ko_wins             INTEGER DEFAULT 0,  -- KO/TKO wins
    sub_wins            INTEGER DEFAULT 0,  -- submission wins
    dec_wins            INTEGER DEFAULT 0,  -- decision wins
    current_win_streak  INTEGER DEFAULT 0,
    url                 TEXT    UNIQUE,     -- fighter's ufcstats page
    scraped_at          TEXT    DEFAULT (datetime('now'))
);

-- FIGHTS: one row per bout (links two fighters to one event)
CREATE TABLE IF NOT EXISTS fights (
    fight_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL REFERENCES events(event_id),
    fighter1_id     INTEGER NOT NULL REFERENCES fighters(fighter_id),
    fighter2_id     INTEGER NOT NULL REFERENCES fighters(fighter_id),
    weight_class    TEXT,                   -- "Heavyweight", "Welterweight", etc.
    is_main_event   INTEGER DEFAULT 0,      -- 1 = main event, 0 = otherwise
    is_title_fight  INTEGER DEFAULT 0,      -- 1 = title on the line
    bout_order      INTEGER,                -- 1 = main event, higher = earlier on card
    -- result fields (NULL until fight happens)
    winner_id       INTEGER REFERENCES fighters(fighter_id),
    method          TEXT,                   -- "KO/TKO", "SUB", "U-DEC", "S-DEC", "NC"
    round           INTEGER,
    time            TEXT,                   -- e.g. "4:32"
    scraped_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(event_id, fighter1_id, fighter2_id)  -- prevent duplicate bouts
);

-- ============================================================
-- Useful indexes for query performance
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_fights_event    ON fights(event_id);
CREATE INDEX IF NOT EXISTS idx_fights_f1       ON fights(fighter1_id);
CREATE INDEX IF NOT EXISTS idx_fights_f2       ON fights(fighter2_id);
CREATE INDEX IF NOT EXISTS idx_events_date     ON events(date);
CREATE INDEX IF NOT EXISTS idx_fighters_name   ON fighters(name);
