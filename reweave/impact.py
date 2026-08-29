"""Impact accounting: turn every approved heal into a defensible number.

Grounding (see docs/architecture.md#impact-model for sources):

* r/webscraping practitioners report **10–15% of scrapers breaking every
  week**, with a manual selector fix taking 1–3 engineer-hours once triage,
  reproduction, redeploy, and backfill are counted. We book the conservative
  floor: 90 minutes per fix.
* Fully-loaded data-engineering time is booked at $95/hour (US median
  fully-loaded cost, not salary).

The point is not precision — it's that the counter on the dashboard is a
formula you can argue with, not a vibe.
"""

from __future__ import annotations

MINUTES_PER_MANUAL_FIX = 90.0
HOURLY_RATE_USD = 95.0
WEEKLY_BREAK_RATE = 0.125  # midpoint of the 10-15% figure


def per_heal() -> tuple[float, float]:
    """(engineer_minutes_saved, dollars_saved) for one approved heal."""
    minutes = MINUTES_PER_MANUAL_FIX
    dollars = round(minutes / 60.0 * HOURLY_RATE_USD, 2)
    return minutes, dollars


def fleet_projection(n_scrapers: int, weeks: int = 52) -> dict[str, float]:
    """Projected annual toil for a scraper fleet without Reweave."""
    breaks = n_scrapers * WEEKLY_BREAK_RATE * weeks
    hours = breaks * MINUTES_PER_MANUAL_FIX / 60.0
    return {
        "expected_breaks_per_year": round(breaks, 1),
        "engineer_hours_per_year": round(hours, 1),
        "dollars_per_year": round(hours * HOURLY_RATE_USD, 2),
    }
