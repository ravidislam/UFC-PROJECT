# UFC Card Preview Dashboard

A portfolio project that scrapes upcoming UFC event data, stores it in a local SQLite database, and generates a visual HTML dashboard with head-to-head fighter stats.

---

## What It Does

- Scrapes **upcoming UFC cards** and **fighter stats** from [ufcstats.com](http://ufcstats.com)
- Stores clean, normalized data in **SQLite**
- Generates a **self-contained HTML dashboard** showing:
  - Full fight card with fighter records
  - Finish rates (KO/TKO + submission breakdowns)
  - Win streaks
  - Head-to-head striking and grappling stats with visual comparison bars
- Includes **SQL queries** for ad-hoc analysis

---

## Stack

| Layer | Tool | Why |
|---|---|---|
| Scraping | Python + BeautifulSoup | Standard, lightweight, no browser needed |
| Storage | SQLite | Zero setup, file-based, perfect for a portfolio DB |
| Analysis | SQL | Demonstrates query skills with real sports data |
| Visualization | Generated HTML/CSS | Self-contained, zero dependencies, works offline |

---

## Project Structure

```
UFC-PROJECT/
├── scraper.py                  # Pulls data from ufcstats.com → SQLite
├── schema.sql                  # Database design (3 tables: events, fighters, fights)
├── requirements.txt
├── data/
│   └── ufc.db                  # SQLite database (auto-created on first scrape)
├── queries/
│   └── key_metrics.sql         # SQL queries: card preview, finish rates, head-to-head
├── dashboard/
│   ├── generate_dashboard.py   # Reads DB → writes index.html
│   └── index.html              # Generated dashboard (open in any browser)
└── tests/
    └── test_parsers.py         # Unit tests for parsing functions
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Scrape the next upcoming card
python scraper.py

# 3. Generate the HTML dashboard
python dashboard/generate_dashboard.py

# 4. Open in browser
open dashboard/index.html   # macOS
# or xdg-open dashboard/index.html  (Linux)
# or just double-click the file in Windows Explorer
```

---

## Database Schema

Three tables, normalized to avoid data duplication:

```
events          fighters          fights
──────────      ──────────────    ──────────────────
event_id  PK    fighter_id  PK    fight_id  PK
name            name              event_id  FK→events
date            record_wins       fighter1_id FK→fighters
location        record_losses     fighter2_id FK→fighters
url             ko_wins           weight_class
                sub_wins          is_main_event
                sig_str_*         is_title_fight
                td_*              bout_order
                ...               winner_id FK→fighters
                                  method, round, time
```

**Why normalized?** A fighter's stats are stored once and linked to many fights. If you update Jon Jones's record, every fight he's in reflects the new data automatically — no manual updates in multiple places.

---

## Key SQL Queries

Run any query directly:

```bash
sqlite3 data/ufc.db "
SELECT f1.name, f2.name, f.weight_class
FROM fights f
JOIN fighters f1 ON f1.fighter_id = f.fighter1_id
JOIN fighters f2 ON f2.fighter_id = f.fighter2_id
JOIN events e ON e.event_id = f.event_id
WHERE e.date >= date('now')
ORDER BY f.bout_order DESC;
"
```

Or run the full query file:

```bash
sqlite3 data/ufc.db < queries/key_metrics.sql
```

Queries included:

| Query | What It Answers |
|---|---|
| Upcoming card | Every scheduled bout with records |
| Finish rate | What % of each fighter's wins are KO or sub? |
| Head-to-head | Side-by-side stat comparison for any matchup |
| Striking snapshot | Who hits hardest and absorbs least? |
| Grappling snapshot | TD averages and sub threat by fighter |
| Event summary | Total bouts, title fights per event |

---

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests cover all parsing functions (record strings, percentages, height/reach conversions) without hitting the network.

---

## How the Scraper Works

1. **Fetch upcoming events list** → find the first link (next upcoming card)
2. **Fetch the event page** → extract fight rows (fighter names + URLs + weight class)
3. **Fetch each fighter's page** → parse career stats block (height, reach, striking, grappling, fight history)
4. **Write to SQLite** using `INSERT ... ON CONFLICT DO UPDATE` — safe to re-run weekly without creating duplicates

The scraper adds a 1-second delay between requests to be a respectful client.

---

## Interview Talking Points

- **Why SQLite over PostgreSQL?** This is a read-heavy, single-user project. SQLite is a file — zero infrastructure, fully portable, version-controllable. PostgreSQL would be the right choice if this were a multi-user API backend.
- **Why not Pandas for storage?** Pandas DataFrames live in memory and don't persist. SQLite gives us durable, queryable storage with proper schema enforcement and foreign key relationships.
- **Why HTML over Power BI?** Power BI requires a licence and can't be automated from Python in a CI/CD pipeline. The generated HTML file can be committed to git, diffed, and viewed by anyone without installing anything.
- **What would you add next?** Historical fight scraping, an odds API integration, a trend chart (win streak over time), and a scheduled GitHub Action to auto-refresh weekly.

---

## Data Source

All data is scraped from [ufcstats.com](http://ufcstats.com), the official statistical database used by the UFC, ESPN, and most combat sports analytics sites. This project is for educational/portfolio purposes only.
