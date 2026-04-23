"""Elo rating system for team strength estimation.

Maintains per-team Elo ratings updated from game outcomes.
Used as a baseline signal independent of market odds — directly
improves the Uniqueness pillar (SOS) in the SkillScore formula.

Key design choices:
- K-factor varies by league (MLB smaller sample → higher K)
- Home advantage baked into expected-score calculation
- Ratings persist to disk so history accumulates across restarts
- League-isolated: MLB Elo ≠ EPL Elo
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

# Default starting Elo for any new team
_DEFAULT_ELO = 1500.0

# Home field advantage in Elo points (equivalent to ~56% win probability)
HOME_ADVANTAGE = 65.0

# K-factors per league — higher K = faster adjustment to recent results.
# Each miner can override the global multiplier via COMPETITIVE_ELO_K env var
# so that different miners' Elo ratings diverge over time (Uniqueness pillar).
_K_SCALE = float(os.getenv("COMPETITIVE_ELO_K", "1.0")) if os.getenv("COMPETITIVE_ELO_K", "1.0").replace(".", "", 1).isdigit() else 1.0

# If COMPETITIVE_ELO_K > 5 it's treated as an absolute override for all leagues;
# otherwise it's a multiplier (e.g. 0.75 → conservative, 1.5 → aggressive).
_K_ABSOLUTE = float(os.getenv("COMPETITIVE_ELO_K", "0")) if float(os.getenv("COMPETITIVE_ELO_K", "0")) > 5 else None

_K_FACTORS: Dict[str, float] = {
    "mlb":  28.0,   # high variance sport, ~162-game season
    "nba":  20.0,   # moderate; teams are well-separated
    "nfl":  32.0,   # high variance, 17-game season
    "epl":  24.0,
    "la_liga":  24.0,
    "serie_a":  24.0,
    "bundesliga": 24.0,
    "mls":  26.0,
    "nhl":  28.0,
    "ncaab": 32.0,
    "ncaaf": 32.0,
    "default": 24.0,
}

def _k_for(league: str) -> float:
    """Return the K-factor for a league, scaled by COMPETITIVE_ELO_K."""
    if _K_ABSOLUTE is not None:
        return _K_ABSOLUTE
    base = _K_FACTORS.get(league.lower(), _K_FACTORS["default"])
    return base * _K_SCALE


class EloRatings:
    """Elo rating store for one or more leagues.

    Usage:
        elo = EloRatings(storage_path="~/.sparket/elo.json")
        elo.load()

        # After a game where home won
        elo.update("mlb", home_team="NYY", away_team="BOS", home_score=5, away_score=3)

        # Get win probability for upcoming game
        p_home, p_away = elo.win_probability("mlb", home_team="NYY", away_team="BOS")

        elo.save()
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        # Default path is hotkey-scoped so multiple miners don't share Elo state.
        if storage_path is None:
            hotkey = os.getenv("SPARKET_WALLET__HOTKEY", "default")
            storage_path = f"~/.sparket/elo_{hotkey}.json"
        self._path = Path(os.path.expanduser(str(storage_path)))
        # ratings[league][team_code] = elo_float
        self._ratings: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._ratings = data
            except Exception:
                self._ratings = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._ratings, indent=2))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, league: str, team: str) -> float:
        return self._ratings.get(league.lower(), {}).get(team.upper(), _DEFAULT_ELO)

    def win_probability(
        self,
        league: str,
        home_team: str,
        away_team: str,
    ) -> Tuple[float, float]:
        """Return (p_home_wins, p_away_wins) including home advantage."""
        r_home = self.get(league, home_team) + HOME_ADVANTAGE
        r_away = self.get(league, away_team)
        p_home = _expected(r_home, r_away)
        p_away = 1.0 - p_home
        return round(p_home, 6), round(p_away, 6)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        league: str,
        home_team: str,
        away_team: str,
        home_score: float,
        away_score: float,
    ) -> None:
        """Update ratings after a settled game."""
        league = league.lower()
        k = _k_for(league)

        r_home = self.get(league, home_team) + HOME_ADVANTAGE
        r_away = self.get(league, away_team)

        e_home = _expected(r_home, r_away)
        e_away = 1.0 - e_home

        # Actual outcome: 1 = win, 0.5 = draw, 0 = loss
        if home_score > away_score:
            s_home, s_away = 1.0, 0.0
        elif home_score < away_score:
            s_home, s_away = 0.0, 1.0
        else:
            s_home, s_away = 0.5, 0.5

        self._set(league, home_team, self.get(league, home_team) + k * (s_home - e_home))
        self._set(league, away_team, self.get(league, away_team) + k * (s_away - e_away))

    def bulk_update_from_results(
        self,
        results: list[dict],
    ) -> None:
        """Update from a list of result dicts with keys:
        league, home_team, away_team, home_score, away_score
        """
        for r in results:
            try:
                self.update(
                    league=r["league"],
                    home_team=r["home_team"],
                    away_team=r["away_team"],
                    home_score=float(r["home_score"]),
                    away_score=float(r["away_score"]),
                )
            except (KeyError, TypeError, ValueError):
                continue

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _set(self, league: str, team: str, rating: float) -> None:
        if league not in self._ratings:
            self._ratings[league] = {}
        # Floor at 1000, ceiling at 2500
        self._ratings[league][team.upper()] = max(1000.0, min(2500.0, rating))

    def league_summary(self, league: str) -> Dict[str, float]:
        return dict(sorted(
            self._ratings.get(league.lower(), {}).items(),
            key=lambda x: x[1],
            reverse=True,
        ))


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))
