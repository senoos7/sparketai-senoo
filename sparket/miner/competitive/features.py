"""Feature engineering for competitive odds prediction.

Builds a feature vector for each (home_team, away_team, league) matchup
from ESPN stats and Elo ratings. All features are independent of market
odds — this keeps the Uniqueness pillar high (SOS ≈ 1 - |correlation|).

Feature set (13 features):
  1.  elo_diff          — Elo(home) - Elo(away)  [range: -800 to +800]
  2.  p_elo_home        — Elo win probability for home (includes home advantage)
  3.  win_rate_home     — Season W/(W+L) for home team
  4.  win_rate_away     — Season W/(W+L) for away team
  5.  win_rate_diff     — win_rate_home - win_rate_away
  6.  home_win_rate     — Home team's record AT HOME
  7.  away_win_rate     — Away team's record AWAY
  8.  pts_diff_home     — (points_for - points_against) / games for home
  9.  pts_diff_away     — (points_for - points_against) / games for away
  10. pts_margin_diff   — pts_diff_home - pts_diff_away
  11. streak_home       — Current win streak (positive) or losing streak (negative)
  12. streak_away       — Same for away team
  13. league_encoded    — Ordinal league code (for tree-based model splits)
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import numpy as np

from sparket.miner.base.data.stats import TeamStats
from sparket.miner.competitive.elo import EloRatings

# League → int encoding (deterministic, model can split on this)
_LEAGUE_CODES: Dict[str, int] = {
    "mlb": 0, "nba": 1, "nfl": 2, "nhl": 3,
    "epl": 4, "esp": 5, "bun": 6, "fra": 7, "ita": 8,
}

FEATURE_NAMES: List[str] = [
    "elo_diff",
    "p_elo_home",
    "win_rate_home",
    "win_rate_away",
    "win_rate_diff",
    "home_win_rate",
    "away_win_rate",
    "pts_diff_home",
    "pts_diff_away",
    "pts_margin_diff",
    "streak_home",
    "streak_away",
    "league_encoded",
]

N_FEATURES = len(FEATURE_NAMES)


def build_feature_vector(
    league: str,
    home_team: str,
    away_team: str,
    home_stats: Optional[TeamStats],
    away_stats: Optional[TeamStats],
    elo: EloRatings,
) -> np.ndarray:
    """Build a 1D feature vector for a matchup.

    Falls back gracefully when stats are unavailable — uses Elo only
    so we always have *some* independent signal.

    Args:
        league: League code (e.g. "mlb", "epl")
        home_team: Home team abbreviation
        away_team: Away team abbreviation
        home_stats: TeamStats for home team (may be None)
        away_stats: TeamStats for away team (may be None)
        elo: EloRatings instance with current ratings

    Returns:
        np.ndarray of shape (N_FEATURES,)
    """
    league = league.lower()

    # --- Elo features (always available) ---
    r_home = elo.get(league, home_team)
    r_away = elo.get(league, away_team)
    elo_diff = r_home - r_away
    p_elo_home, _ = elo.win_probability(league, home_team, away_team)

    # --- Season record features ---
    win_rate_home = _win_rate(home_stats)
    win_rate_away = _win_rate(away_stats)
    win_rate_diff = win_rate_home - win_rate_away

    home_win_rate = _home_win_rate(home_stats)   # how often home team wins at home
    away_win_rate = _away_win_rate(away_stats)   # how often away team wins away

    # --- Points differential (normalized) ---
    pts_diff_home = _pts_diff(home_stats)
    pts_diff_away = _pts_diff(away_stats)
    pts_margin_diff = pts_diff_home - pts_diff_away

    # --- Streak ---
    streak_home = _streak(home_stats)
    streak_away = _streak(away_stats)

    # --- League encoding ---
    league_encoded = float(_LEAGUE_CODES.get(league, len(_LEAGUE_CODES)))

    return np.array([
        elo_diff,
        p_elo_home,
        win_rate_home,
        win_rate_away,
        win_rate_diff,
        home_win_rate,
        away_win_rate,
        pts_diff_home,
        pts_diff_away,
        pts_margin_diff,
        streak_home,
        streak_away,
        league_encoded,
    ], dtype=np.float32)


def build_training_row(
    league: str,
    home_team: str,
    away_team: str,
    home_stats: Optional[TeamStats],
    away_stats: Optional[TeamStats],
    elo: EloRatings,
    outcome: float,  # 1.0 = home win, 0.0 = away win, 0.5 = draw
) -> Dict[str, Any]:
    """Build a labeled training row (features + label) for model training."""
    features = build_feature_vector(
        league, home_team, away_team, home_stats, away_stats, elo
    )
    row: Dict[str, Any] = {name: float(features[i]) for i, name in enumerate(FEATURE_NAMES)}
    row["outcome"] = outcome
    return row


# ------------------------------------------------------------------
# Helper extractors — all return 0.5 (neutral) when data missing
# ------------------------------------------------------------------

def _win_rate(stats: Optional[TeamStats]) -> float:
    if not stats:
        return 0.5
    total = stats.wins + stats.losses + stats.ties
    if total == 0:
        return 0.5
    return stats.wins / total


def _home_win_rate(stats: Optional[TeamStats]) -> float:
    if not stats:
        return 0.5
    total = stats.home_wins + stats.home_losses
    if total == 0:
        return 0.5
    return stats.home_wins / total


def _away_win_rate(stats: Optional[TeamStats]) -> float:
    if not stats:
        return 0.5
    total = stats.away_wins + stats.away_losses
    if total == 0:
        return 0.5
    return stats.away_wins / total


def _pts_diff(stats: Optional[TeamStats]) -> float:
    """Points per game differential, clamped to [-1, 1] for stability."""
    if not stats:
        return 0.0
    pf = stats.points_for or 0.0
    pa = stats.points_against or 0.0
    total = stats.wins + stats.losses + stats.ties
    if total == 0 or (pf == 0 and pa == 0):
        return 0.0
    # Normalize by games played, clip to reasonable range
    diff_per_game = (pf - pa) / total
    return float(np.clip(diff_per_game / 20.0, -1.0, 1.0))


def _streak(stats: Optional[TeamStats]) -> float:
    """Win streak (positive) or losing streak (negative), normalized to [-1,1]."""
    if not stats:
        return 0.0
    raw = float(stats.extra.get("streak", 0) if stats.extra else 0)
    return float(np.clip(raw / 10.0, -1.0, 1.0))
