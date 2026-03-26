"""
UFC Preview Dashboard — Scraper
================================
Pulls upcoming card + fighter stats from ufcstats.com and stores them
in a local SQLite database.

How it works (high level):
  1. Fetch the "upcoming events" page → find the next scheduled event URL
  2. Fetch that event page → extract each fight matchup
  3. For each fighter in the matchup → fetch their stats page
  4. Write everything to SQLite using our schema

Why ufcstats.com?
  It's the official data source used by ESPN, UFC itself, and most
  analytics sites. The HTML is stable and doesn't require a browser
  (no JavaScript rendering needed).

Interview talking points:
  - requests + BeautifulSoup is the standard Python scraping stack
  - We add delays between requests (time.sleep) to be a polite scraper
  - We use INSERT OR REPLACE to handle re-scrapes without duplicates
"""

import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Constants ────────────────────────────────────────────────────────────────

BASE_URL = "http://www.ufcstats.com"
UPCOMING_URL = f"{BASE_URL}/statistics/events/upcoming"
COMPLETED_URL = f"{BASE_URL}/statistics/events/completed"
DB_PATH = Path(__file__).parent / "data" / "ufc.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Polite delay between HTTP requests (seconds).
# Too fast = risk of being blocked. 1 second is fine for a portfolio project.
REQUEST_DELAY = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UFC-Portfolio-Scraper/1.0; "
        "educational use only)"
    )
}


# ── Database helpers ──────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and apply the schema.

    sqlite3.Row makes rows behave like dicts: row['name'] instead of row[0].
    This makes the code much more readable.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # enforce FK constraints
    # Apply schema (CREATE IF NOT EXISTS — safe to run repeatedly)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    return conn


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup | None:
    """
    Fetch a URL and return a parsed BeautifulSoup object.

    Returns None on failure so callers can decide how to handle errors
    rather than crashing the whole scrape.
    """
    try:
        print(f"  GET {url}")
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()  # raises on 4xx/5xx
        time.sleep(REQUEST_DELAY)    # be polite
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return None


# ── Parsing helpers ───────────────────────────────────────────────────────────

def parse_record(record_str: str) -> tuple[int, int, int]:
    """
    Parse a UFC record string like "25-3-0" into (wins, losses, draws).

    Some fighters have NC (no contests) appended; we strip those.
    """
    if not record_str:
        return 0, 0, 0
    # Remove anything after a space (e.g. "25-3-0 (1 NC)")
    clean = record_str.strip().split()[0]
    parts = clean.split("-")
    try:
        wins   = int(parts[0]) if len(parts) > 0 else 0
        losses = int(parts[1]) if len(parts) > 1 else 0
        draws  = int(parts[2]) if len(parts) > 2 else 0
        return wins, losses, draws
    except (ValueError, IndexError):
        return 0, 0, 0


def parse_pct(pct_str: str) -> float | None:
    """
    Convert "64%" → 0.64. Returns None if unparseable.
    """
    if not pct_str:
        return None
    try:
        return float(pct_str.strip().replace("%", "")) / 100.0
    except ValueError:
        return None


def parse_float(val: str) -> float | None:
    """Strip whitespace and convert to float, or return None."""
    if not val:
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def inches_to_cm(inches_str: str) -> float | None:
    """
    Convert "6' 2\"" → 187.96. ufcstats stores height in feet/inches.
    """
    if not inches_str or inches_str.strip() == "--":
        return None
    match = re.search(r"(\d+)'\s*(\d+)", inches_str)
    if match:
        feet, inches = int(match.group(1)), int(match.group(2))
        return round((feet * 12 + inches) * 2.54, 1)
    return None


def inches_reach_to_cm(reach_str: str) -> float | None:
    """Convert reach from inches string (e.g. '74\"') to cm."""
    if not reach_str or reach_str.strip() == "--":
        return None
    match = re.search(r"(\d+\.?\d*)", reach_str)
    if match:
        return round(float(match.group(1)) * 2.54, 1)
    return None


# ── Fighter scraper ───────────────────────────────────────────────────────────

def scrape_fighter(url: str, conn: sqlite3.Connection) -> int | None:
    """
    Scrape a single fighter's stats page and upsert into the DB.

    Returns the fighter_id on success, None on failure.

    ufcstats fighter page structure:
      - .b-content__title-highlight → fighter name
      - .b-list__box-list-item       → career stats (striking, grappling)
      - .b-content__title-record    → overall record
    """
    soup = fetch(url)
    if not soup:
        return None

    # ── Name ────────────────────────────────────────────────────────────────
    name_tag = soup.select_one(".b-content__title-highlight")
    name = name_tag.get_text(strip=True) if name_tag else "Unknown"

    nickname_tag = soup.select_one(".b-content__Nickname")
    nickname = nickname_tag.get_text(strip=True).strip('"') if nickname_tag else None

    # ── Record ──────────────────────────────────────────────────────────────
    record_tag = soup.select_one(".b-content__title-record")
    record_str = record_tag.get_text(strip=True).replace("Record:", "").strip() if record_tag else "0-0-0"
    wins, losses, draws = parse_record(record_str)

    # ── Career stats (height, reach, stance, DOB + fight stats) ─────────────
    # ufcstats puts all career stats in a list of <li> items.
    # Each item has a label and a value. We build a dict for easy lookup.
    stats: dict[str, str] = {}
    for li in soup.select(".b-list__box-list-item"):
        text = li.get_text(separator="|", strip=True)
        if "|" in text:
            label, _, value = text.partition("|")
            stats[label.strip().lower().rstrip(":")] = value.strip()

    height_cm  = inches_to_cm(stats.get("height", ""))
    reach_cm   = inches_reach_to_cm(stats.get("reach", ""))
    stance     = stats.get("stance") or None
    dob        = stats.get("dob") or None

    sig_str_landed_pm   = parse_float(stats.get("sig. str. landed", stats.get("slpm", "")))
    sig_str_accuracy    = parse_pct(stats.get("sig. str. acc.", stats.get("str. acc.", "")))
    sig_str_absorbed_pm = parse_float(stats.get("sig. str. absorbed", stats.get("sapm", "")))
    sig_str_defense     = parse_pct(stats.get("sig. str. def", stats.get("str. def", "")))
    td_avg              = parse_float(stats.get("takedown avg.", stats.get("td avg.", "")))
    td_accuracy         = parse_pct(stats.get("takedown acc.", stats.get("td acc.", "")))
    td_defense          = parse_pct(stats.get("takedown def.", stats.get("td def.", "")))
    sub_avg             = parse_float(stats.get("submission avg.", stats.get("sub. avg.", "")))

    # ── Win method breakdown (from fight history table) ─────────────────────
    ko_wins = sub_wins = dec_wins = 0
    current_streak = 0
    last_result = None  # track for streak calculation

    fight_rows = soup.select(".b-fight-details__table-body tr")
    for row in fight_rows:
        cols = row.select("td")
        if len(cols) < 8:
            continue
        result_text = cols[0].get_text(strip=True).upper()   # W / L / D / NC
        method_text = cols[7].get_text(strip=True).upper()   # KO/TKO / SUB / DEC

        if result_text == "W":
            if "KO" in method_text or "TKO" in method_text:
                ko_wins += 1
            elif "SUB" in method_text:
                sub_wins += 1
            elif "DEC" in method_text:
                dec_wins += 1

            # Build current win streak
            if last_result is None or last_result == "W":
                current_streak += 1
            last_result = "W"
        else:
            # Streak breaks on any non-win (loss, draw, NC)
            if last_result == "W":
                last_result = result_text  # freeze streak counting
            elif last_result is None:
                last_result = result_text

    total_fights = wins + losses + draws

    # ── Upsert into DB ───────────────────────────────────────────────────────
    # INSERT OR REPLACE: if this URL already exists, overwrite with fresh data.
    with conn:
        cur = conn.execute(
            """
            INSERT INTO fighters (
                name, nickname,
                record_wins, record_losses, record_draws,
                height_cm, reach_cm, stance, dob,
                sig_str_landed_pm, sig_str_accuracy,
                sig_str_absorbed_pm, sig_str_defense,
                td_avg, td_accuracy, td_defense, sub_avg,
                total_fights, ko_wins, sub_wins, dec_wins,
                current_win_streak, url, scraped_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, datetime('now')
            )
            ON CONFLICT(url) DO UPDATE SET
                name                = excluded.name,
                nickname            = excluded.nickname,
                record_wins         = excluded.record_wins,
                record_losses       = excluded.record_losses,
                record_draws        = excluded.record_draws,
                height_cm           = excluded.height_cm,
                reach_cm            = excluded.reach_cm,
                stance              = excluded.stance,
                dob                 = excluded.dob,
                sig_str_landed_pm   = excluded.sig_str_landed_pm,
                sig_str_accuracy    = excluded.sig_str_accuracy,
                sig_str_absorbed_pm = excluded.sig_str_absorbed_pm,
                sig_str_defense     = excluded.sig_str_defense,
                td_avg              = excluded.td_avg,
                td_accuracy         = excluded.td_accuracy,
                td_defense          = excluded.td_defense,
                sub_avg             = excluded.sub_avg,
                total_fights        = excluded.total_fights,
                ko_wins             = excluded.ko_wins,
                sub_wins            = excluded.sub_wins,
                dec_wins            = excluded.dec_wins,
                current_win_streak  = excluded.current_win_streak,
                scraped_at          = datetime('now')
            """,
            (
                name, nickname,
                wins, losses, draws,
                height_cm, reach_cm, stance, dob,
                sig_str_landed_pm, sig_str_accuracy,
                sig_str_absorbed_pm, sig_str_defense,
                td_avg, td_accuracy, td_defense, sub_avg,
                total_fights, ko_wins, sub_wins, dec_wins,
                current_streak, url,
            ),
        )
        fighter_id = cur.lastrowid or conn.execute(
            "SELECT fighter_id FROM fighters WHERE url = ?", (url,)
        ).fetchone()["fighter_id"]

    print(f"  ✓ Fighter: {name} ({wins}-{losses}-{draws})")
    return fighter_id


# ── Event scraper ─────────────────────────────────────────────────────────────

def scrape_event(event_url: str, conn: sqlite3.Connection) -> int | None:
    """
    Scrape a single event page:
      1. Extract event metadata (name, date, location)
      2. Extract each fight row (fighter links + weight class)
      3. Scrape each fighter and record the matchup

    ufcstats event page structure:
      - .b-content__title-highlight → event name
      - .b-list__box-list-item       → date, location
      - .b-fight-details__table-row  → each fight (one row per bout)
    """
    soup = fetch(event_url)
    if not soup:
        return None

    # ── Event metadata ───────────────────────────────────────────────────────
    name_tag = soup.select_one(".b-content__title-highlight")
    event_name = name_tag.get_text(strip=True) if name_tag else "Unknown Event"

    event_meta: dict[str, str] = {}
    for li in soup.select(".b-list__box-list-item"):
        text = li.get_text(separator="|", strip=True)
        if "|" in text:
            label, _, value = text.partition("|")
            event_meta[label.strip().lower().rstrip(":")] = value.strip()

    event_date     = event_meta.get("date", "")
    event_location = event_meta.get("location", "")

    # Normalise date from "March 01, 2025" → "2025-03-01"
    try:
        dt = datetime.strptime(event_date, "%B %d, %Y")
        event_date = dt.strftime("%Y-%m-%d")
    except ValueError:
        pass  # keep raw string if format doesn't match

    # ── Upsert event ─────────────────────────────────────────────────────────
    with conn:
        cur = conn.execute(
            """
            INSERT INTO events (name, date, location, url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                name     = excluded.name,
                date     = excluded.date,
                location = excluded.location
            """,
            (event_name, event_date, event_location, event_url),
        )
        event_id = cur.lastrowid or conn.execute(
            "SELECT event_id FROM events WHERE url = ?", (event_url,)
        ).fetchone()["event_id"]

    print(f"\n{'='*60}")
    print(f"Event: {event_name}")
    print(f"Date:  {event_date}  |  {event_location}")
    print(f"{'='*60}")

    # ── Fight rows ───────────────────────────────────────────────────────────
    # Each row in the fight table has two fighter <a> tags.
    # bout_order: 1 = last row shown (main event), incremented backwards.
    fight_rows = soup.select("tr.b-fight-details__table-row")
    total_rows = len(fight_rows)

    for bout_order, row in enumerate(reversed(fight_rows), start=1):
        # Fighter links
        fighter_links = row.select("td.b-fight-details__table-col a")
        if len(fighter_links) < 2:
            continue

        f1_url = fighter_links[0]["href"]
        f2_url = fighter_links[1]["href"]
        f1_name = fighter_links[0].get_text(strip=True)
        f2_name = fighter_links[1].get_text(strip=True)

        # Weight class (3rd column)
        cols = row.select("td.b-fight-details__table-col")
        weight_class = cols[6].get_text(strip=True) if len(cols) > 6 else None

        is_main  = 1 if bout_order == 1 else 0
        is_title = 1 if "title" in (weight_class or "").lower() else 0

        print(f"\n  Bout {bout_order}: {f1_name} vs {f2_name} [{weight_class}]")

        # Scrape each fighter
        f1_id = scrape_fighter(f1_url, conn)
        f2_id = scrape_fighter(f2_url, conn)

        if f1_id is None or f2_id is None:
            print(f"  [SKIP] Could not scrape one or both fighters")
            continue

        # Upsert the fight
        with conn:
            conn.execute(
                """
                INSERT INTO fights
                    (event_id, fighter1_id, fighter2_id,
                     weight_class, is_main_event, is_title_fight, bout_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, fighter1_id, fighter2_id) DO UPDATE SET
                    weight_class   = excluded.weight_class,
                    is_main_event  = excluded.is_main_event,
                    is_title_fight = excluded.is_title_fight,
                    bout_order     = excluded.bout_order
                """,
                (event_id, f1_id, f2_id,
                 weight_class, is_main, is_title, bout_order),
            )

    return event_id


# ── Upcoming events ───────────────────────────────────────────────────────────

def get_next_event_url() -> str | None:
    """
    Scrape the upcoming events list and return the URL of the
    most imminent event.

    ufcstats lists upcoming events in ascending date order — the
    first link is always the soonest upcoming card.
    """
    soup = fetch(UPCOMING_URL)
    if not soup:
        return None

    # Each row in the upcoming events table has a link to the event page
    rows = soup.select("tr.b-statistics__table-row")
    for row in rows:
        link = row.select_one("td.b-statistics__table-col a")
        if link and link.get("href"):
            return link["href"]

    return None


def get_all_upcoming_event_urls() -> list[str]:
    """Return URLs for ALL upcoming events (useful for a full refresh)."""
    soup = fetch(UPCOMING_URL)
    if not soup:
        return []

    urls = []
    for row in soup.select("tr.b-statistics__table-row"):
        link = row.select_one("td.b-statistics__table-col a")
        if link and link.get("href"):
            urls.append(link["href"])
    return urls


# ── Entry points ──────────────────────────────────────────────────────────────

def scrape_next_card():
    """Scrape only the immediate next card — fast, good for weekly refresh."""
    print("UFC Preview Dashboard — Scraper")
    print(f"Target: next upcoming event")
    print(f"DB:     {DB_PATH}\n")

    conn = get_db()

    event_url = get_next_event_url()
    if not event_url:
        print("[ERROR] Could not find any upcoming events.")
        return

    print(f"Next event URL: {event_url}")
    scrape_event(event_url, conn)
    conn.close()
    print("\n✓ Scrape complete.")


def scrape_all_upcoming():
    """Scrape every event on the upcoming schedule."""
    print("UFC Preview Dashboard — Full Upcoming Scrape")
    print(f"DB: {DB_PATH}\n")

    conn = get_db()
    urls = get_all_upcoming_event_urls()
    print(f"Found {len(urls)} upcoming event(s)\n")

    for url in urls:
        scrape_event(url, conn)

    conn.close()
    print("\n✓ All upcoming events scraped.")


if __name__ == "__main__":
    # Default: scrape just the next card
    scrape_next_card()
