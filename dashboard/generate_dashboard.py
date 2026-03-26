"""
UFC Preview Dashboard — HTML Generator
=======================================
Reads from the SQLite database and generates a self-contained HTML file.

Why HTML instead of Power BI?
  Power BI is great for enterprise, but requires a paid licence and can't
  be automated easily from Python. A generated HTML file:
    - Is 100% free and portable
    - Can be opened by anyone with a browser (no install required)
    - Is version-controllable (you can diff it)
    - Demonstrates Python templating skills (a real job skill)

How it works:
  1. Query SQLite for upcoming event + fighter stats
  2. Build an HTML string using an f-string template
  3. Write to dashboard/index.html

Interview talking point:
  "I chose HTML over Power BI so the dashboard is self-contained and
   doesn't require any external tools to view — the whole project is
   reproducible from a single git clone."
"""

import sqlite3
from pathlib import Path

DB_PATH   = Path(__file__).parent.parent / "data" / "ufc.db"
OUT_PATH  = Path(__file__).parent / "index.html"


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}.\n"
            "Run: python scraper.py  to populate it first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_next_event(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM events WHERE date >= date('now') ORDER BY date ASC LIMIT 1"
    ).fetchone()


def get_fights_for_event(conn: sqlite3.Connection, event_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            f.*,
            f1.name               AS f1_name,
            f1.nickname           AS f1_nickname,
            f1.record_wins        AS f1_wins,
            f1.record_losses      AS f1_losses,
            f1.record_draws       AS f1_draws,
            f1.current_win_streak AS f1_streak,
            f1.ko_wins            AS f1_ko,
            f1.sub_wins           AS f1_sub,
            f1.dec_wins           AS f1_dec,
            f1.sig_str_landed_pm  AS f1_slpm,
            f1.sig_str_accuracy   AS f1_str_acc,
            f1.sig_str_defense    AS f1_str_def,
            f1.td_avg             AS f1_td_avg,
            f1.td_defense         AS f1_td_def,
            f2.name               AS f2_name,
            f2.nickname           AS f2_nickname,
            f2.record_wins        AS f2_wins,
            f2.record_losses      AS f2_losses,
            f2.record_draws       AS f2_draws,
            f2.current_win_streak AS f2_streak,
            f2.ko_wins            AS f2_ko,
            f2.sub_wins           AS f2_sub,
            f2.dec_wins           AS f2_dec,
            f2.sig_str_landed_pm  AS f2_slpm,
            f2.sig_str_accuracy   AS f2_str_acc,
            f2.sig_str_defense    AS f2_str_def,
            f2.td_avg             AS f2_td_avg,
            f2.td_defense         AS f2_td_def
        FROM fights f
        JOIN fighters f1 ON f1.fighter_id = f.fighter1_id
        JOIN fighters f2 ON f2.fighter_id = f.fighter2_id
        WHERE f.event_id = ?
        ORDER BY f.bout_order DESC
        """,
        (event_id,),
    ).fetchall()


# ── Rendering helpers ─────────────────────────────────────────────────────────

def fmt_record(w, l, d) -> str:
    return f"{w}-{l}-{d}" if d else f"{w}-{l}"


def fmt_pct(val) -> str:
    if val is None:
        return "—"
    return f"{round(float(val) * 100, 1)}%"


def fmt_float(val, decimals=2) -> str:
    if val is None:
        return "—"
    return f"{round(float(val), decimals)}"


def finish_rate(ko, sub, wins) -> str:
    if not wins:
        return "—"
    return f"{round((ko + sub) / wins * 100, 1)}%"


def bar_width(val, max_val, pct=False) -> int:
    """Return a 0-100 percentage for a CSS bar width."""
    if val is None:
        return 0
    v = float(val) * 100 if pct else float(val)
    m = float(max_val)
    if m == 0:
        return 0
    return min(100, round(v / m * 100))


def render_stat_row(label: str, v1, v2, higher_is_better=True, pct=False) -> str:
    """
    Render a single comparison row with visual bars.
    The fighter with the better stat gets a highlighted bar.
    """
    f1_raw = float(v1) if v1 is not None else 0.0
    f2_raw = float(v2) if v2 is not None else 0.0
    if pct:
        f1_raw *= 100
        f2_raw *= 100

    max_val = max(f1_raw, f2_raw, 0.01)
    f1_bar  = round(f1_raw / max_val * 100)
    f2_bar  = round(f2_raw / max_val * 100)

    if higher_is_better:
        f1_better = f1_raw >= f2_raw
    else:
        f1_better = f1_raw <= f2_raw

    f1_class = "bar-better" if f1_better  else "bar-worse"
    f2_class = "bar-better" if not f1_better else "bar-worse"

    f1_disp = f"{round(f1_raw, 1)}{'%' if pct else ''}" if v1 is not None else "—"
    f2_disp = f"{round(f2_raw, 1)}{'%' if pct else ''}" if v2 is not None else "—"

    return f"""
    <tr>
      <td class="stat-f1">
        <span class="stat-val">{f1_disp}</span>
        <div class="bar-wrap bar-left">
          <div class="bar {f1_class}" style="width:{f1_bar}%"></div>
        </div>
      </td>
      <td class="stat-label">{label}</td>
      <td class="stat-f2">
        <div class="bar-wrap bar-right">
          <div class="bar {f2_class}" style="width:{f2_bar}%"></div>
        </div>
        <span class="stat-val">{f2_disp}</span>
      </td>
    </tr>"""


def render_fight_card(fight: sqlite3.Row, index: int) -> str:
    is_main  = fight["is_main_event"]
    is_title = fight["is_title_fight"]

    badge = ""
    if is_main:
        badge += '<span class="badge badge-main">MAIN EVENT</span> '
    if is_title:
        badge += '<span class="badge badge-title">TITLE FIGHT</span>'

    f1_record = fmt_record(fight["f1_wins"], fight["f1_losses"], fight["f1_draws"])
    f2_record = fmt_record(fight["f2_wins"], fight["f2_losses"], fight["f2_draws"])

    f1_finish = finish_rate(fight["f1_ko"] or 0, fight["f1_sub"] or 0, fight["f1_wins"] or 1)
    f2_finish = finish_rate(fight["f2_ko"] or 0, fight["f2_sub"] or 0, fight["f2_wins"] or 1)

    stat_rows = (
        render_stat_row("Sig. Strikes/min",  fight["f1_slpm"],    fight["f2_slpm"])
      + render_stat_row("Strike Accuracy",   fight["f1_str_acc"], fight["f2_str_acc"], pct=True)
      + render_stat_row("Strike Defense",    fight["f1_str_def"], fight["f2_str_def"], pct=True)
      + render_stat_row("TD Avg/15min",      fight["f1_td_avg"],  fight["f2_td_avg"])
      + render_stat_row("TD Defense",        fight["f1_td_def"],  fight["f2_td_def"], pct=True)
    )

    nickname1 = f'<div class="nickname">"{fight["f1_nickname"]}"</div>' if fight["f1_nickname"] else ""
    nickname2 = f'<div class="nickname">"{fight["f2_nickname"]}"</div>' if fight["f2_nickname"] else ""

    return f"""
  <div class="fight-card {'fight-card--main' if is_main else ''}">
    <div class="fight-header">
      <span class="weight-class">{fight['weight_class'] or 'Catchweight'}</span>
      {badge}
    </div>

    <div class="matchup">
      <div class="fighter fighter-left">
        <div class="fighter-name">{fight['f1_name']}</div>
        {nickname1}
        <div class="record">{f1_record}</div>
        <div class="streak">{'🔥 ' + str(fight['f1_streak']) + ' win streak' if (fight['f1_streak'] or 0) > 1 else ''}</div>
        <div class="finish-info">
          KO: {fight['f1_ko'] or 0} &nbsp;|&nbsp; SUB: {fight['f1_sub'] or 0} &nbsp;|&nbsp; DEC: {fight['f1_dec'] or 0}
          <br><strong>Finish rate: {f1_finish}</strong>
        </div>
      </div>

      <div class="vs-col">
        <div class="vs">VS</div>
      </div>

      <div class="fighter fighter-right">
        <div class="fighter-name">{fight['f2_name']}</div>
        {nickname2}
        <div class="record">{f2_record}</div>
        <div class="streak">{'🔥 ' + str(fight['f2_streak']) + ' win streak' if (fight['f2_streak'] or 0) > 1 else ''}</div>
        <div class="finish-info">
          KO: {fight['f2_ko'] or 0} &nbsp;|&nbsp; SUB: {fight['f2_sub'] or 0} &nbsp;|&nbsp; DEC: {fight['f2_dec'] or 0}
          <br><strong>Finish rate: {f2_finish}</strong>
        </div>
      </div>
    </div>

    <div class="stats-section">
      <h3 class="stats-title">Head-to-Head Stats</h3>
      <table class="stats-table">
        <thead>
          <tr>
            <th class="th-f1">{fight['f1_name'].split()[-1]}</th>
            <th class="th-label">Stat</th>
            <th class="th-f2">{fight['f2_name'].split()[-1]}</th>
          </tr>
        </thead>
        <tbody>
          {stat_rows}
        </tbody>
      </table>
    </div>
  </div>"""


# ── Full page ─────────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #0d0d0d;
  color: #f0f0f0;
  padding: 24px 16px;
}

.page-header {
  text-align: center;
  margin-bottom: 36px;
}
.page-header h1 {
  font-size: 2rem;
  color: #e8c84b;
  text-transform: uppercase;
  letter-spacing: 3px;
}
.event-meta {
  color: #aaa;
  margin-top: 6px;
  font-size: 0.95rem;
}

.fight-card {
  background: #1a1a1a;
  border: 1px solid #2e2e2e;
  border-radius: 10px;
  padding: 24px;
  margin-bottom: 24px;
  max-width: 900px;
  margin-left: auto;
  margin-right: auto;
}
.fight-card--main {
  border-color: #e8c84b;
  box-shadow: 0 0 18px rgba(232, 200, 75, 0.15);
}

.fight-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}
.weight-class {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #aaa;
  background: #2e2e2e;
  padding: 3px 10px;
  border-radius: 20px;
}
.badge {
  font-size: 0.7rem;
  font-weight: bold;
  padding: 3px 10px;
  border-radius: 20px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.badge-main  { background: #e8c84b; color: #000; }
.badge-title { background: #c0392b; color: #fff; }

.matchup {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 28px;
}
.fighter {
  flex: 1;
}
.fighter-left  { text-align: right; }
.fighter-right { text-align: left; }

.fighter-name {
  font-size: 1.25rem;
  font-weight: 700;
  color: #fff;
}
.nickname {
  color: #e8c84b;
  font-size: 0.85rem;
  font-style: italic;
  margin: 2px 0;
}
.record {
  font-size: 1rem;
  color: #ccc;
  margin-top: 4px;
}
.streak {
  font-size: 0.8rem;
  color: #e87d4b;
  margin-top: 4px;
  min-height: 1.2em;
}
.finish-info {
  font-size: 0.8rem;
  color: #aaa;
  margin-top: 8px;
  line-height: 1.5;
}
.finish-info strong { color: #e8c84b; }

.vs-col {
  width: 60px;
  text-align: center;
  padding-top: 12px;
}
.vs {
  font-size: 1.4rem;
  font-weight: 900;
  color: #444;
}

/* ── Stats table ── */
.stats-section { margin-top: 8px; }
.stats-title {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #666;
  margin-bottom: 12px;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
}
.stats-table th {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #777;
  padding-bottom: 6px;
}
.th-f1    { text-align: right; width: 38%; }
.th-label { text-align: center; width: 24%; }
.th-f2    { text-align: left;  width: 38%; }

.stat-f1    { text-align: right; padding: 6px 8px; width: 38%; }
.stat-label { text-align: center; color: #888; font-size: 0.8rem; padding: 6px 4px; white-space: nowrap; }
.stat-f2    { text-align: left;  padding: 6px 8px; width: 38%; }
.stat-val   { font-size: 0.9rem; color: #ddd; }

.bar-wrap {
  height: 6px;
  background: #2e2e2e;
  border-radius: 3px;
  margin-top: 3px;
  overflow: hidden;
}
.bar-left  { direction: rtl; }
.bar-right { direction: ltr; }
.bar {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.bar-better { background: #e8c84b; }
.bar-worse  { background: #3a3a3a; }

.no-data {
  text-align: center;
  color: #555;
  padding: 80px 20px;
  font-size: 1.1rem;
}

footer {
  text-align: center;
  color: #444;
  font-size: 0.75rem;
  margin-top: 40px;
  padding-bottom: 20px;
}
"""


def generate(conn: sqlite3.Connection) -> str:
    event = get_next_event(conn)

    if not event:
        body = '<div class="no-data">No upcoming events in database.<br>Run <code>python scraper.py</code> to populate.</div>'
        event_title = "No Upcoming Events"
        event_meta  = ""
    else:
        fights = get_fights_for_event(conn, event["event_id"])
        fight_cards = "".join(render_fight_card(f, i) for i, f in enumerate(fights))
        body = fight_cards or '<div class="no-data">Event found but no fights scraped yet.</div>'
        event_title = event["name"]
        event_meta  = f'{event["date"]} &nbsp;·&nbsp; {event["location"] or "TBA"}'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UFC Preview — {event_title}</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="page-header">
    <h1>UFC Card Preview</h1>
    <div class="event-meta">{event_title}</div>
    <div class="event-meta">{event_meta}</div>
  </header>

  <main>
    {body}
  </main>

  <footer>
    Data source: ufcstats.com &nbsp;·&nbsp; Generated by UFC Preview Dashboard
  </footer>
</body>
</html>"""


def main():
    conn = get_conn()
    html = generate(conn)
    conn.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {OUT_PATH}")
    print(f"Open in browser: file://{OUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
