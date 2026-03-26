"""
Unit tests for the scraper's parsing utility functions.

These test pure functions that have no external dependencies,
so they run instantly without hitting the network.

Run with:  python -m pytest tests/
"""

import sys
from pathlib import Path

# Add project root so we can import scraper
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import (
    inches_reach_to_cm,
    inches_to_cm,
    parse_float,
    parse_pct,
    parse_record,
)

from dashboard.generate_dashboard import finish_rate as dash_finish_rate


# ── parse_record ──────────────────────────────────────────────────────────────

def test_parse_record_standard():
    assert parse_record("25-3-0") == (25, 3, 0)

def test_parse_record_no_draws():
    assert parse_record("18-5-0") == (18, 5, 0)

def test_parse_record_with_draws():
    assert parse_record("10-2-1") == (10, 2, 1)

def test_parse_record_with_nc():
    # "(1 NC)" suffix should be ignored
    assert parse_record("25-3-0 (1 NC)") == (25, 3, 0)

def test_parse_record_empty():
    assert parse_record("") == (0, 0, 0)

def test_parse_record_none():
    assert parse_record(None) == (0, 0, 0)


# ── parse_pct ─────────────────────────────────────────────────────────────────

def test_parse_pct_standard():
    assert parse_pct("64%") == 0.64

def test_parse_pct_with_spaces():
    assert parse_pct("  50%  ") == 0.50

def test_parse_pct_zero():
    assert parse_pct("0%") == 0.0

def test_parse_pct_empty():
    assert parse_pct("") is None

def test_parse_pct_none():
    assert parse_pct(None) is None


# ── parse_float ───────────────────────────────────────────────────────────────

def test_parse_float_standard():
    assert parse_float("3.74") == 3.74

def test_parse_float_with_spaces():
    assert parse_float("  1.23  ") == 1.23

def test_parse_float_empty():
    assert parse_float("") is None

def test_parse_float_none():
    assert parse_float(None) is None


# ── inches_to_cm ──────────────────────────────────────────────────────────────

def test_inches_to_cm_standard():
    result = inches_to_cm("6' 2\"")
    assert result == 188.0  # 74 inches * 2.54 = 187.96, rounded to 1dp → 188.0

def test_inches_to_cm_short():
    result = inches_to_cm("5' 7\"")
    assert result == 170.2

def test_inches_to_cm_dash():
    assert inches_to_cm("--") is None

def test_inches_to_cm_empty():
    assert inches_to_cm("") is None


# ── inches_reach_to_cm ────────────────────────────────────────────────────────

def test_reach_to_cm_standard():
    result = inches_reach_to_cm('74"')
    assert result == 188.0  # 74 * 2.54 = 187.96, rounded to 1dp → 188.0

def test_reach_to_cm_dash():
    assert inches_reach_to_cm("--") is None

def test_reach_to_cm_empty():
    assert inches_reach_to_cm("") is None


# ── finish_rate (dashboard) ───────────────────────────────────────────────────

def test_finish_rate_standard():
    assert dash_finish_rate(10, 3, 20) == "65.0%"

def test_finish_rate_all_ko():
    assert dash_finish_rate(5, 0, 5) == "100.0%"

def test_finish_rate_zero_wins():
    assert dash_finish_rate(0, 0, 0) == "—"
