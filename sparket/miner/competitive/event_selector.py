"""Smart event/market selection.

Decides which markets to price in each cycle. Maximises the
Marginal and Uniqueness pillars by:
  1. Focusing on leagues where our model is validated.
  2. Skipping events with no consensus ground truth (0.999 sentinel).
  3. Prioritising events whose start time is closest — timeliness bonus.
  4. Skipping leagues we have no ESPN coverage for.

Selection rules (in order):
  A. League filter — only leagues in ALLOWED_LEAGUES
  B. Sentinel filter — skip if any consensus field ≈ 0.999
  C. Window filter  — game start must be within 7 days (validator rule)
  D. Min-hours      — optionally skip games starting very soon (in_play risk)
  E. Priority sort  — closest start first (timeliness), then by league priority
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# Leagues we support, in priority order (highest Marginal opportunity first).
# Adjust based on observed competition on the dashboard.
_DEFAULT_LEAGUES = ["mlb", "epl", "nba", "esp", "nfl"]

# Games with consensus ≥ this are sentinel/no-data — skip them
_SENTINEL_THRESHOLD = float(os.getenv("COMPETITIVE_SENTINEL_THRESHOLD", "0.98"))

# Acceptance window: validator allows odds up to 7 days ahead
_MAX_DAYS_AHEAD = 7

# Don't price games starting in < this many minutes (risk of in_play rejection)
_MIN_MINUTES_BEFORE = 5


class EventSelector:
    """Filters and ranks active markets for the current pricing cycle.

    Usage:
        selector = EventSelector(leagues=["mlb", "epl"])
        chosen = selector.select(markets, consensus_cache)
    """

    def __init__(
        self,
        leagues: Optional[List[str]] = None,
        sentinel_threshold: float = _SENTINEL_THRESHOLD,
        min_minutes_before: int = _MIN_MINUTES_BEFORE,
        max_markets_per_cycle: int = 300,
    ) -> None:
        env_leagues = os.getenv("COMPETITIVE_LEAGUES", "")
        if env_leagues:
            self._leagues = [l.strip().lower() for l in env_leagues.split(",") if l.strip()]
        else:
            self._leagues = [l.lower() for l in (leagues or _DEFAULT_LEAGUES)]

        self._sentinel = sentinel_threshold
        self._min_minutes = min_minutes_before
        self._max_markets = max_markets_per_cycle

        # League priority index (lower = higher priority)
        self._priority: Dict[str, int] = {lg: i for i, lg in enumerate(self._leagues)}

    def select(
        self,
        markets: List[Dict[str, Any]],
        consensus_cache: Optional[Dict[int, Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Filter and rank markets for this cycle.

        Args:
            markets: List of market dicts from GameDataSync.get_active_markets()
            consensus_cache: Optional dict of event_id → consensus snapshot
                             Used to skip sentinel (no-data) events.

        Returns:
            Ordered list of markets to price, capped at max_markets_per_cycle.
        """
        now = datetime.now(timezone.utc)
        cutoff_near = now + timedelta(minutes=self._min_minutes)
        cutoff_far = now + timedelta(days=_MAX_DAYS_AHEAD)

        selected = []
        for m in markets:
            # --- League filter ---
            league = (m.get("league") or m.get("sport") or "").lower()
            if league not in self._leagues:
                continue

            # --- Time window filter ---
            start = _parse_dt(m.get("start_time_utc"))
            if start is None:
                continue
            if start < cutoff_near or start > cutoff_far:
                continue

            # --- Sentinel filter ---
            if consensus_cache:
                event_id = m.get("event_id")
                if event_id and self._is_sentinel(consensus_cache.get(int(event_id))):
                    continue

            selected.append(m)

        # --- Priority sort: league priority ASC, then minutes_to_start ASC ---
        def _sort_key(m: Dict) -> tuple:
            league = (m.get("league") or m.get("sport") or "").lower()
            prio = self._priority.get(league, 99)
            start = _parse_dt(m.get("start_time_utc")) or datetime.max.replace(tzinfo=timezone.utc)
            mins = (start - now).total_seconds() / 60.0
            return (prio, mins)

        selected.sort(key=_sort_key)
        return selected[: self._max_markets]

    def _is_sentinel(self, consensus: Optional[Dict]) -> bool:
        """Return True if consensus data looks like a sentinel (no real data)."""
        if not consensus:
            return False
        data = consensus.get("data") or []
        if not data:
            return False
        latest = data[-1] if isinstance(data, list) else data
        for field in ("moneyline_home", "moneyline_away", "spread_home", "total"):
            val = latest.get(field)
            if val is not None and float(val) >= self._sentinel:
                return True
        return False

    def leagues(self) -> List[str]:
        return list(self._leagues)

    def should_submit_for_league(self, league: str) -> bool:
        return league.lower() in self._leagues


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def minutes_to_start(market: Dict[str, Any]) -> Optional[float]:
    start = _parse_dt(market.get("start_time_utc"))
    if start is None:
        return None
    now = datetime.now(timezone.utc)
    return (start - now).total_seconds() / 60.0
