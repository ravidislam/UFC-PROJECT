-- ============================================================
-- UFC Preview Dashboard — Key SQL Queries
-- ============================================================
-- Run these with:  sqlite3 data/ufc.db < queries/key_metrics.sql
-- Or copy individual queries into a Python cursor.execute() call.
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- 1. UPCOMING CARD — full fight card with fighter records
--    Shows every scheduled fight for the next event.
-- ────────────────────────────────────────────────────────────
SELECT
    e.name                                         AS event,
    e.date,
    e.location,
    f.weight_class,
    f.bout_order,
    CASE WHEN f.is_main_event  = 1 THEN 'YES' ELSE '' END AS main_event,
    CASE WHEN f.is_title_fight = 1 THEN 'YES' ELSE '' END AS title_fight,
    -- Fighter 1
    f1.name                                        AS fighter1,
    f1.record_wins || '-' || f1.record_losses || '-' || f1.record_draws
                                                   AS f1_record,
    f1.current_win_streak                          AS f1_streak,
    -- Fighter 2
    f2.name                                        AS fighter2,
    f2.record_wins || '-' || f2.record_losses || '-' || f2.record_draws
                                                   AS f2_record,
    f2.current_win_streak                          AS f2_streak
FROM fights f
JOIN events  e  ON e.event_id  = f.event_id
JOIN fighters f1 ON f1.fighter_id = f.fighter1_id
JOIN fighters f2 ON f2.fighter_id = f.fighter2_id
WHERE e.date >= date('now')          -- only upcoming events
ORDER BY e.date ASC, f.bout_order DESC;


-- ────────────────────────────────────────────────────────────
-- 2. FINISH RATE — what % of a fighter's wins are finishes?
--    Interviewers love this: it shows you can compute derived
--    metrics from raw counts rather than storing redundant data.
-- ────────────────────────────────────────────────────────────
SELECT
    name,
    record_wins                                            AS wins,
    ko_wins,
    sub_wins,
    dec_wins,
    ROUND(
        CAST(ko_wins + sub_wins AS REAL)
        / NULLIF(record_wins, 0) * 100,
    1)                                                     AS finish_rate_pct,
    ROUND(CAST(ko_wins AS REAL) / NULLIF(record_wins, 0) * 100, 1)
                                                           AS ko_rate_pct,
    ROUND(CAST(sub_wins AS REAL) / NULLIF(record_wins, 0) * 100, 1)
                                                           AS sub_rate_pct
FROM fighters
ORDER BY finish_rate_pct DESC NULLS LAST;


-- ────────────────────────────────────────────────────────────
-- 3. HEAD-TO-HEAD COMPARISON — side-by-side stats for a matchup
--    Pass in fighter names (or IDs) to get a comparison table.
--    Replace the names below with any fighters in your DB.
-- ────────────────────────────────────────────────────────────
SELECT
    'Record'                AS stat,
    f1.record_wins || '-' || f1.record_losses AS fighter1_val,
    f2.record_wins || '-' || f2.record_losses AS fighter2_val
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%'   -- ← change to fighter you want
  AND f2.name LIKE '%Hill%'      -- ← change to opponent

UNION ALL SELECT
    'Win Streak',
    CAST(f1.current_win_streak AS TEXT),
    CAST(f2.current_win_streak AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'Finish Rate %',
    CAST(ROUND(CAST(f1.ko_wins + f1.sub_wins AS REAL) / NULLIF(f1.record_wins,0)*100,1) AS TEXT),
    CAST(ROUND(CAST(f2.ko_wins + f2.sub_wins AS REAL) / NULLIF(f2.record_wins,0)*100,1) AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'Sig Strikes/min',
    CAST(f1.sig_str_landed_pm AS TEXT),
    CAST(f2.sig_str_landed_pm AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'Strike Accuracy %',
    CAST(ROUND(f1.sig_str_accuracy * 100, 1) AS TEXT),
    CAST(ROUND(f2.sig_str_accuracy * 100, 1) AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'Strike Defense %',
    CAST(ROUND(f1.sig_str_defense * 100, 1) AS TEXT),
    CAST(ROUND(f2.sig_str_defense * 100, 1) AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'TD Avg/15min',
    CAST(f1.td_avg AS TEXT),
    CAST(f2.td_avg AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%'

UNION ALL SELECT
    'TD Defense %',
    CAST(ROUND(f1.td_defense * 100, 1) AS TEXT),
    CAST(ROUND(f2.td_defense * 100, 1) AS TEXT)
FROM fighters f1, fighters f2
WHERE f1.name LIKE '%Pereira%' AND f2.name LIKE '%Hill%';


-- ────────────────────────────────────────────────────────────
-- 4. STRIKING COMPARISON — who are the most active strikers
--    on the upcoming card? Sorted by sig strikes landed/min.
-- ────────────────────────────────────────────────────────────
SELECT
    fi.name,
    fi.sig_str_landed_pm                                   AS str_landed_pm,
    ROUND(fi.sig_str_accuracy * 100, 1)                    AS accuracy_pct,
    fi.sig_str_absorbed_pm                                 AS str_absorbed_pm,
    ROUND(fi.sig_str_defense * 100, 1)                     AS defense_pct,
    -- "differential" = how many more strikes you land than absorb
    ROUND(fi.sig_str_landed_pm - fi.sig_str_absorbed_pm, 2) AS str_differential
FROM fights f
JOIN events   e   ON e.event_id    = f.event_id
JOIN fighters fi  ON fi.fighter_id IN (f.fighter1_id, f.fighter2_id)
WHERE e.date >= date('now')
ORDER BY fi.sig_str_landed_pm DESC NULLS LAST;


-- ────────────────────────────────────────────────────────────
-- 5. GRAPPLING SNAPSHOT — takedown stats for upcoming fights
-- ────────────────────────────────────────────────────────────
SELECT
    fi.name,
    fi.td_avg                                              AS td_per_15min,
    ROUND(fi.td_accuracy * 100, 1)                         AS td_accuracy_pct,
    ROUND(fi.td_defense * 100, 1)                          AS td_defense_pct,
    fi.sub_avg                                             AS sub_attempts_per_15min
FROM fights f
JOIN events   e   ON e.event_id    = f.event_id
JOIN fighters fi  ON fi.fighter_id IN (f.fighter1_id, f.fighter2_id)
WHERE e.date >= date('now')
ORDER BY fi.td_avg DESC NULLS LAST;


-- ────────────────────────────────────────────────────────────
-- 6. EVENT SUMMARY — quick stats about each stored event
-- ────────────────────────────────────────────────────────────
SELECT
    e.name,
    e.date,
    e.location,
    COUNT(f.fight_id)                                      AS total_bouts,
    SUM(f.is_title_fight)                                  AS title_fights,
    SUM(f.is_main_event)                                   AS main_events
FROM events e
JOIN fights f ON f.event_id = e.event_id
GROUP BY e.event_id
ORDER BY e.date DESC;
