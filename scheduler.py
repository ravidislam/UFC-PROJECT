"""
UFC Weekly Scheduler
====================
Scrapes ALL upcoming UFC events and regenerates the dashboard once per week.

Usage
-----
  python scheduler.py           # start the long-running scheduler daemon
  python scheduler.py --now     # run once immediately, then keep scheduling
  python scheduler.py --cron    # print a ready-to-paste crontab entry, then exit

How it works
------------
  The `schedule` library keeps a lightweight in-process job queue.
  The main loop wakes every 60 seconds, checks whether any job is due,
  and runs it if so.  Everything is logged to both stdout and
  data/scheduler.log so you have a persistent audit trail.

Why `schedule` and not cron directly?
  - No system-level access needed; works the same on Linux/Mac/Windows.
  - The --cron flag still gives you a copy-paste crontab line if you'd
    rather hand the scheduling to the OS.
  - Easier to test (`schedule.run_all()` in a unit test).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import schedule

# ── Path bootstrap ────────────────────────────────────────────────────────────
# Ensure the project root is on sys.path so relative imports work regardless
# of the working directory the user launches from.
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from scraper import scrape_all_upcoming                    # noqa: E402
from dashboard.generate_dashboard import main as regen_dashboard  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH = ROOT / "data" / "scheduler.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Day / time the weekly job runs ────────────────────────────────────────────
# Monday 06:00 local time — early in the week, well before weekend events.
# Change WEEKLY_DAY to "tuesday", "wednesday", etc. if you prefer a different day.
WEEKLY_DAY  = "monday"
WEEKLY_TIME = "06:00"


# ── Core job ──────────────────────────────────────────────────────────────────

def weekly_job() -> None:
    """Scrape all upcoming events and rebuild the HTML dashboard."""
    log.info("=" * 60)
    log.info("UFC weekly scrape — started")
    log.info("=" * 60)
    try:
        scrape_all_upcoming()
        regen_dashboard()
        log.info("UFC weekly scrape — complete")
    except Exception:
        log.exception("UFC weekly scrape — FAILED (see traceback above)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="UFC weekly scheduler — keeps fighter & event data fresh.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--now",
        action="store_true",
        help="Run the scrape immediately before entering the weekly schedule.",
    )
    p.add_argument(
        "--cron",
        action="store_true",
        help="Print a ready-to-paste crontab entry and exit.",
    )
    return p


def print_cron_entry() -> None:
    """Print a crontab line that runs this script weekly via cron."""
    python = sys.executable
    script = Path(__file__).resolve()
    cron_log = ROOT / "data" / "cron.log"
    print()
    print("# ── UFC weekly scrape crontab entry ──────────────────────────────")
    print(f"# Runs every {WEEKLY_DAY.capitalize()} at {WEEKLY_TIME} local time.")
    print("# Add with:  crontab -e")
    print("#")
    print(
        f"0 6 * * 1  cd {script.parent} && "
        f"{python} {script} --now >> {cron_log} 2>&1"
    )
    print()
    print("# Tip: check it ran with:  tail -f data/cron.log")
    print()


def main() -> None:
    args = build_parser().parse_args()

    if args.cron:
        print_cron_entry()
        return

    if args.now:
        log.info("--now flag: running immediate scrape before scheduling.")
        weekly_job()

    # Register the recurring job
    getattr(schedule.every(), WEEKLY_DAY).at(WEEKLY_TIME).do(weekly_job)

    next_run = schedule.next_run()
    log.info(f"Scheduler active — next run: {next_run} (every {WEEKLY_DAY.capitalize()} at {WEEKLY_TIME})")
    log.info("Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)   # wake every minute to check for due jobs
    except KeyboardInterrupt:
        log.info("Scheduler stopped by user.")


if __name__ == "__main__":
    main()
