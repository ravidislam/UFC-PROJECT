# Databricks notebook source
"""
UFC Weekly Scrape — Databricks Notebook
========================================
Scrapes ALL upcoming UFC events from ufcstats.com and writes fighter + event
data to Delta Lake tables using MERGE (upsert) so it's safe to re-run weekly
without creating duplicates.

Scheduled via Databricks Jobs: every Monday at 06:00 (see ../resources/ufc_job.yml).

Tables written
--------------
  {catalog}.{schema}.events    — one row per UFC card
  {catalog}.{schema}.fighters  — one row per fighter, updated each scrape
  {catalog}.{schema}.fights    — one row per bout (links fighters to an event)

All three tables use Delta Lake with Change Data Feed enabled so you can build
incremental pipelines downstream.
"""

# COMMAND ----------

# MAGIC %pip install requests beautifulsoup4 lxml --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# ── Widgets (overridden by Databricks Job parameters) ─────────────────────────
# These act as defaults when running the notebook interactively.
# The job YAML passes catalog/schema as base_parameters, which override these.
dbutils.widgets.text("catalog", "main",        "Unity Catalog name")
dbutils.widgets.text("schema",  "ufc_preview", "Schema / database name")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA  = dbutils.widgets.get("schema")

EVENTS_TABLE   = f"{CATALOG}.{SCHEMA}.events"
FIGHTERS_TABLE = f"{CATALOG}.{SCHEMA}.fighters"
FIGHTS_TABLE   = f"{CATALOG}.{SCHEMA}.fights"

print(f"Target: {CATALOG}.{SCHEMA}  (three tables: events, fighters, fights)")

# COMMAND ----------

import re
import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup
from delta.tables import DeltaTable

# COMMAND ----------

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL     = "http://www.ufcstats.com"
UPCOMING_URL = f"{BASE_URL}/statistics/events/upcoming"
REQUEST_DELAY = 1.0          # seconds between HTTP requests — be a polite scraper

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UFC-Databricks-Scraper/1.0; "
        "educational use only)"
    )
}

# COMMAND ----------

# ── Create schema + Delta tables ──────────────────────────────────────────────
# CREATE TABLE IF NOT EXISTS is idempotent — safe to run on every execution.
# We store fighter stats on the fighters table and join via url as the natural key
# (ufcstats gives every fighter a stable URL we can use as a surrogate key).

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
    event_id   BIGINT GENERATED ALWAYS AS IDENTITY,
    name       STRING NOT NULL,
    date       STRING NOT NULL,
    location   STRING,
    url        STRING NOT NULL,
    scraped_at TIMESTAMP
)
USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {FIGHTERS_TABLE} (
    fighter_id          BIGINT GENERATED ALWAYS AS IDENTITY,
    name                STRING NOT NULL,
    nickname            STRING,
    record_wins         INT,
    record_losses       INT,
    record_draws        INT,
    height_cm           DOUBLE,
    reach_cm            DOUBLE,
    stance              STRING,
    dob                 STRING,
    -- striking stats (per-fight averages from ufcstats)
    sig_str_landed_pm   DOUBLE,   -- significant strikes landed per minute
    sig_str_accuracy    DOUBLE,   -- accuracy as 0.0–1.0
    sig_str_absorbed_pm DOUBLE,   -- sig strikes absorbed per minute
    sig_str_defense     DOUBLE,   -- defense rate 0.0–1.0
    -- grappling stats
    td_avg              DOUBLE,   -- takedown avg per 15 min
    td_accuracy         DOUBLE,   -- takedown accuracy 0.0–1.0
    td_defense          DOUBLE,   -- takedown defense 0.0–1.0
    sub_avg             DOUBLE,   -- submission attempts per 15 min
    -- derived finish metrics
    total_fights        INT,
    ko_wins             INT,
    sub_wins            INT,
    dec_wins            INT,
    current_win_streak  INT,
    url                 STRING NOT NULL,   -- stable ufcstats page URL (natural key)
    scraped_at          TIMESTAMP
)
USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {FIGHTS_TABLE} (
    fight_id        BIGINT GENERATED ALWAYS AS IDENTITY,
    -- We store URLs instead of IDs so joins work before identity columns resolve
    event_url       STRING NOT NULL,
    fighter1_url    STRING NOT NULL,
    fighter2_url    STRING NOT NULL,
    weight_class    STRING,
    is_main_event   INT,     -- 1 = main event
    is_title_fight  INT,     -- 1 = title on the line
    bout_order      INT,     -- 1 = main event, higher number = earlier on card
    -- result fields — NULL until the fight is completed
    winner_url      STRING,
    method          STRING,  -- KO/TKO | SUB | U-DEC | S-DEC | NC
    round           INT,
    time            STRING,  -- e.g. "4:32"
    scraped_at      TIMESTAMP
)
USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

print("Schema and tables ready.")

# COMMAND ----------

# ── Parsing helpers ───────────────────────────────────────────────────────────
# Pure functions with no side effects — easy to unit test.

def parse_record(record_str):
    """'25-3-0 (1 NC)' → (25, 3, 0)"""
    if not record_str:
        return 0, 0, 0
    clean = record_str.strip().split()[0]
    parts = clean.split("-")
    try:
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )
    except (ValueError, IndexError):
        return 0, 0, 0


def parse_pct(pct_str):
    """'64%' → 0.64"""
    if not pct_str:
        return None
    try:
        return float(pct_str.strip().replace("%", "")) / 100.0
    except ValueError:
        return None


def parse_float(val):
    if not val:
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def inches_to_cm(s):
    """'6\' 2"' → 188.0"""
    if not s or s.strip() == "--":
        return None
    m = re.search(r"(\d+)'\s*(\d+)", s)
    if m:
        return round((int(m.group(1)) * 12 + int(m.group(2))) * 2.54, 1)
    return None


def inches_reach_to_cm(s):
    """'74"' → 188.0"""
    if not s or s.strip() == "--":
        return None
    m = re.search(r"(\d+\.?\d*)", s)
    if m:
        return round(float(m.group(1)) * 2.54, 1)
    return None

# COMMAND ----------

# ── HTTP helper ───────────────────────────────────────────────────────────────

def fetch(url):
    """GET a URL and return a parsed BeautifulSoup, or None on failure."""
    try:
        print(f"  GET {url}")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [WARN] {url}: {e}")
        return None

# COMMAND ----------

# ── Fighter scraper ───────────────────────────────────────────────────────────

def scrape_fighter(url):
    """
    Scrape one fighter's ufcstats page.
    Returns a dict ready for a DataFrame row, or None on failure.
    """
    soup = fetch(url)
    if not soup:
        return None

    name = (soup.select_one(".b-content__title-highlight") or object()).get_text(strip=True) or "Unknown"
    nn   = soup.select_one(".b-content__Nickname")
    nickname = nn.get_text(strip=True).strip('"') if nn else None

    rec_tag = soup.select_one(".b-content__title-record")
    record_str = rec_tag.get_text(strip=True).replace("Record:", "").strip() if rec_tag else "0-0-0"
    wins, losses, draws = parse_record(record_str)

    # ufcstats puts career stats in <li> items with "Label: Value" text
    stats = {}
    for li in soup.select(".b-list__box-list-item"):
        text = li.get_text(separator="|", strip=True)
        if "|" in text:
            label, _, value = text.partition("|")
            stats[label.strip().lower().rstrip(":")] = value.strip()

    # Win method breakdown from fight history table
    ko_wins = sub_wins = dec_wins = current_streak = 0
    last_result = None
    for row in soup.select(".b-fight-details__table-body tr"):
        cols = row.select("td")
        if len(cols) < 8:
            continue
        result = cols[0].get_text(strip=True).upper()
        method = cols[7].get_text(strip=True).upper()
        if result == "W":
            if "KO" in method or "TKO" in method:
                ko_wins += 1
            elif "SUB" in method:
                sub_wins += 1
            elif "DEC" in method:
                dec_wins += 1
            if last_result is None or last_result == "W":
                current_streak += 1
            last_result = "W"
        else:
            if last_result is None:
                last_result = result

    print(f"    + {name} ({wins}-{losses}-{draws})")
    return {
        "name":                name,
        "nickname":            nickname,
        "record_wins":         wins,
        "record_losses":       losses,
        "record_draws":        draws,
        "height_cm":           inches_to_cm(stats.get("height", "")),
        "reach_cm":            inches_reach_to_cm(stats.get("reach", "")),
        "stance":              stats.get("stance") or None,
        "dob":                 stats.get("dob") or None,
        "sig_str_landed_pm":   parse_float(stats.get("sig. str. landed", stats.get("slpm", ""))),
        "sig_str_accuracy":    parse_pct(stats.get("sig. str. acc.", stats.get("str. acc.", ""))),
        "sig_str_absorbed_pm": parse_float(stats.get("sig. str. absorbed", stats.get("sapm", ""))),
        "sig_str_defense":     parse_pct(stats.get("sig. str. def", stats.get("str. def", ""))),
        "td_avg":              parse_float(stats.get("takedown avg.", stats.get("td avg.", ""))),
        "td_accuracy":         parse_pct(stats.get("takedown acc.", stats.get("td acc.", ""))),
        "td_defense":          parse_pct(stats.get("takedown def.", stats.get("td def.", ""))),
        "sub_avg":             parse_float(stats.get("submission avg.", stats.get("sub. avg.", ""))),
        "total_fights":        wins + losses + draws,
        "ko_wins":             ko_wins,
        "sub_wins":            sub_wins,
        "dec_wins":            dec_wins,
        "current_win_streak":  current_streak,
        "url":                 url,
        "scraped_at":          datetime.utcnow(),
    }

# COMMAND ----------

# ── Event scraper ─────────────────────────────────────────────────────────────

def scrape_event(event_url):
    """
    Scrape one event page.
    Returns (event_dict, [fight_dicts], [fighter_dicts]).
    """
    soup = fetch(event_url)
    if not soup:
        return None, [], []

    name_tag   = soup.select_one(".b-content__title-highlight")
    event_name = name_tag.get_text(strip=True) if name_tag else "Unknown Event"

    meta = {}
    for li in soup.select(".b-list__box-list-item"):
        text = li.get_text(separator="|", strip=True)
        if "|" in text:
            label, _, value = text.partition("|")
            meta[label.strip().lower().rstrip(":")] = value.strip()

    event_date = meta.get("date", "")
    try:
        event_date = datetime.strptime(event_date, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    event_row = {
        "name":       event_name,
        "date":       event_date,
        "location":   meta.get("location", ""),
        "url":        event_url,
        "scraped_at": datetime.utcnow(),
    }

    print(f"\n{'='*60}")
    print(f"  {event_name}  |  {event_date}")
    print(f"{'='*60}")

    fights   = []
    fighters = []

    for bout_order, row in enumerate(
        reversed(soup.select("tr.b-fight-details__table-row")), start=1
    ):
        links = row.select("td.b-fight-details__table-col a")
        if len(links) < 2:
            continue

        f1_url  = links[0]["href"]
        f2_url  = links[1]["href"]
        f1_name = links[0].get_text(strip=True)
        f2_name = links[1].get_text(strip=True)

        cols         = row.select("td.b-fight-details__table-col")
        weight_class = cols[6].get_text(strip=True) if len(cols) > 6 else None
        is_main      = 1 if bout_order == 1 else 0
        is_title     = 1 if "title" in (weight_class or "").lower() else 0

        print(f"\n  Bout {bout_order}: {f1_name} vs {f2_name}  [{weight_class}]")

        f1_data = scrape_fighter(f1_url)
        f2_data = scrape_fighter(f2_url)

        if f1_data:
            fighters.append(f1_data)
        if f2_data:
            fighters.append(f2_data)

        if f1_data and f2_data:
            fights.append({
                "event_url":      event_url,
                "fighter1_url":   f1_url,
                "fighter2_url":   f2_url,
                "weight_class":   weight_class,
                "is_main_event":  is_main,
                "is_title_fight": is_title,
                "bout_order":     bout_order,
                "winner_url":     None,
                "method":         None,
                "round":          None,
                "time":           None,
                "scraped_at":     datetime.utcnow(),
            })

    return event_row, fights, fighters


def get_all_upcoming_event_urls():
    """Return URLs for every upcoming event on ufcstats."""
    soup = fetch(UPCOMING_URL)
    if not soup:
        return []
    urls = []
    for row in soup.select("tr.b-statistics__table-row"):
        link = row.select_one("td.b-statistics__table-col a")
        if link and link.get("href"):
            urls.append(link["href"])
    return urls

# COMMAND ----------

# ── Delta upsert helpers ──────────────────────────────────────────────────────
# We collect all scraped rows into Python lists, convert to Spark DataFrames,
# then MERGE into Delta — one bulk write per table rather than row-by-row.

def merge_into(table_name, df, merge_condition):
    """
    MERGE source df into an existing Delta table on merge_condition.
    Falls back to overwrite on first run (table empty, no delta log yet).
    """
    if DeltaTable.isDeltaTable(spark, table_name):
        (
            DeltaTable.forName(spark, table_name)
            .alias("t")
            .merge(df.alias("s"), merge_condition)
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        df.write.format("delta").mode("overwrite").saveAsTable(table_name)


def upsert_events(rows):
    if not rows:
        return
    df = spark.createDataFrame(
        pd.DataFrame(rows).drop_duplicates(subset=["url"])
    )
    merge_into(EVENTS_TABLE, df, "t.url = s.url")
    print(f"  events   → {len(rows)} row(s) upserted")


def upsert_fighters(rows):
    if not rows:
        return
    df = spark.createDataFrame(
        pd.DataFrame(rows).drop_duplicates(subset=["url"])
    )
    merge_into(FIGHTERS_TABLE, df, "t.url = s.url")
    print(f"  fighters → {len(rows)} row(s) upserted")


def upsert_fights(rows):
    if not rows:
        return
    df = spark.createDataFrame(
        pd.DataFrame(rows).drop_duplicates(
            subset=["event_url", "fighter1_url", "fighter2_url"]
        )
    )
    merge_into(
        FIGHTS_TABLE,
        df,
        "t.event_url = s.event_url "
        "AND t.fighter1_url = s.fighter1_url "
        "AND t.fighter2_url = s.fighter2_url",
    )
    print(f"  fights   → {len(rows)} row(s) upserted")

# COMMAND ----------

# ── Main: scrape all upcoming events ─────────────────────────────────────────

event_urls = get_all_upcoming_event_urls()
print(f"\nFound {len(event_urls)} upcoming event(s)")

all_events   = []
all_fights   = []
all_fighters = []

for url in event_urls:
    ev, fights, fighters = scrape_event(url)
    if ev:
        all_events.append(ev)
    all_fights.extend(fights)
    all_fighters.extend(fighters)

print(f"\nScrape complete — events: {len(all_events)}, "
      f"fights: {len(all_fights)}, fighters: {len(all_fighters)}")

# COMMAND ----------

# ── Write to Delta Lake ───────────────────────────────────────────────────────

print("Writing to Delta tables...")
upsert_events(all_events)
upsert_fighters(all_fighters)
upsert_fights(all_fights)
print("Done.")

# COMMAND ----------

# ── Summary: upcoming card preview ───────────────────────────────────────────
# display() renders an interactive table in the Databricks notebook UI.

display(spark.sql(f"""
    SELECT
        e.name                                              AS event,
        e.date,
        e.location,
        f.weight_class,
        CASE WHEN f.is_main_event  = 1 THEN 'YES' END      AS main_event,
        CASE WHEN f.is_title_fight = 1 THEN 'YES' END      AS title_fight,
        f1.name                                            AS fighter_1,
        f1.record_wins || '-' || f1.record_losses          AS f1_record,
        f1.current_win_streak                              AS f1_streak,
        ROUND(
            (f1.ko_wins + f1.sub_wins)
            / NULLIF(f1.record_wins, 0) * 100, 1)          AS f1_finish_pct,
        f2.name                                            AS fighter_2,
        f2.record_wins || '-' || f2.record_losses          AS f2_record,
        f2.current_win_streak                              AS f2_streak,
        ROUND(
            (f2.ko_wins + f2.sub_wins)
            / NULLIF(f2.record_wins, 0) * 100, 1)          AS f2_finish_pct
    FROM   {FIGHTS_TABLE}   f
    JOIN   {EVENTS_TABLE}   e  ON e.url = f.event_url
    JOIN   {FIGHTERS_TABLE} f1 ON f1.url = f.fighter1_url
    JOIN   {FIGHTERS_TABLE} f2 ON f2.url = f.fighter2_url
    WHERE  e.date >= current_date()
    ORDER  BY e.date ASC, f.bout_order DESC
"""))

# COMMAND ----------

# ── Striking snapshot ─────────────────────────────────────────────────────────

display(spark.sql(f"""
    SELECT
        fi.name,
        fi.sig_str_landed_pm                               AS str_landed_pm,
        ROUND(fi.sig_str_accuracy * 100, 1)                AS str_accuracy_pct,
        fi.sig_str_absorbed_pm                             AS str_absorbed_pm,
        ROUND(fi.sig_str_defense * 100, 1)                 AS str_defense_pct,
        ROUND(fi.sig_str_landed_pm
              - fi.sig_str_absorbed_pm, 2)                 AS str_differential,
        fi.td_avg                                          AS td_per_15min,
        ROUND(fi.td_defense * 100, 1)                      AS td_defense_pct
    FROM   {FIGHTS_TABLE}   f
    JOIN   {EVENTS_TABLE}   e  ON e.url = f.event_url
    JOIN   {FIGHTERS_TABLE} fi
           ON fi.url IN (f.fighter1_url, f.fighter2_url)
    WHERE  e.date >= current_date()
    ORDER  BY fi.sig_str_landed_pm DESC NULLS LAST
"""))
