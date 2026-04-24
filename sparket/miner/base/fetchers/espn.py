"""ESPN public API fetcher for scores and standings.

Uses ESPN's public (unofficial) API endpoints. No API key required.
These endpoints are used by ESPN's website and are generally reliable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from sparket.miner.base.data.stats import TeamStats
from sparket.miner.base.data.teams import get_espn_sport_path, get_team_info, LEAGUE_TEAMS
from sparket.miner.base.fetchers.interface import GameResult, RecentGame, ScoreFetcher, StatsFetcher
from sparket.miner.base.utils.cache import TTLCache


# ESPN public API base URL
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports"


class ESPNFetcher(ScoreFetcher, StatsFetcher):
    """Fetches scores and standings from ESPN's public API.
    
    Features:
    - No API key required (uses public endpoints)
    - Caches responses to minimize requests
    - Provides team stats, standings, and game results
    
    Example:
        fetcher = ESPNFetcher()
        stats = await fetcher.get_team_stats("KC", "NFL")
        print(f"Chiefs record: {stats.wins}-{stats.losses}")
    """
    
    def __init__(
        self,
        cache_ttl_seconds: float = 3600,  # 1 hour default
        timeout: float = 10.0,
    ) -> None:
        """Initialize ESPN fetcher.
        
        Args:
            cache_ttl_seconds: How long to cache responses
            timeout: HTTP request timeout
        """
        self._cache = TTLCache[Dict[str, Any]](ttl_seconds=cache_ttl_seconds)
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client
    
    async def _fetch_json(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch JSON from URL with caching."""
        # Check cache first
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            self._cache.set(url, data)
            return data
        except Exception:
            return None
    
    # -------------------------------------------------------------------------
    # StatsFetcher implementation
    # -------------------------------------------------------------------------
    
    async def get_team_stats(self, team_code: str, league: str) -> Optional[TeamStats]:
        """Fetch statistics for a team from ESPN standings."""
        standings = await self.get_standings(league)
        for stats in standings:
            if stats.team_code.upper() == team_code.upper():
                return stats
        return None
    
    async def get_standings(self, league: str) -> List[TeamStats]:
        """Fetch standings for all teams in a league."""
        sport_path = get_espn_sport_path(league)
        if not sport_path:
            return []
        
        url = f"{ESPN_API_BASE}/{sport_path}/standings"
        data = await self._fetch_json(url)
        if not data:
            return []
        
        return self._parse_standings(data, league)
    
    def _parse_standings(self, data: Dict[str, Any], league: str) -> List[TeamStats]:
        """Parse ESPN standings response into TeamStats list."""
        results = []
        
        # ESPN structure: children -> standings -> entries
        children = data.get("children", [])
        for division in children:
            standings = division.get("standings", {})
            entries = standings.get("entries", [])
            
            for entry in entries:
                stats = self._parse_team_entry(entry, league)
                if stats:
                    results.append(stats)
        
        return results
    
    def _parse_team_entry(self, entry: Dict[str, Any], league: str) -> Optional[TeamStats]:
        """Parse a single team entry from standings."""
        team = entry.get("team", {})
        team_id = team.get("id")
        abbreviation = team.get("abbreviation", "").upper()
        
        # Map ESPN team to our code
        team_code = abbreviation
        if not team_code:
            return None
        
        # Parse stats from the entry
        stats_list = entry.get("stats", [])
        stats_dict = {s.get("name"): s.get("value", 0) for s in stats_list}
        
        # Extract key stats (names vary by league)
        wins = int(stats_dict.get("wins", 0))
        losses = int(stats_dict.get("losses", 0))
        ties = int(stats_dict.get("ties", 0))
        
        # Home/away records
        home_record = stats_dict.get("homeRecord", "")
        away_record = stats_dict.get("awayRecord", "")
        
        home_wins, home_losses = self._parse_record(home_record)
        away_wins, away_losses = self._parse_record(away_record)
        
        # Points for/against
        points_for = stats_dict.get("pointsFor")
        points_against = stats_dict.get("pointsAgainst")
        
        # Last 5 games (streak info)
        streak = stats_dict.get("streak", 0)
        
        return TeamStats(
            team_code=team_code,
            league=league.upper(),
            wins=wins,
            losses=losses,
            ties=ties,
            home_wins=home_wins,
            home_losses=home_losses,
            away_wins=away_wins,
            away_losses=away_losses,
            points_for=points_for,
            points_against=points_against,
            extra={"espn_id": team_id, "streak": streak},
        )
    
    def _parse_record(self, record_str: str) -> tuple[int, int]:
        """Parse record string like '7-1' into (wins, losses)."""
        if not record_str or not isinstance(record_str, str):
            return 0, 0
        try:
            parts = record_str.split("-")
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            pass
        return 0, 0
    
    async def get_recent_games(
        self, 
        team_code: str, 
        league: str, 
        limit: int = 5
    ) -> List[RecentGame]:
        """Fetch recent game results for a team."""
        sport_path = get_espn_sport_path(league)
        if not sport_path:
            return []
        
        team_info = get_team_info(league, team_code)
        if not team_info:
            return []
        
        espn_id = team_info.get("espn_id")
        if not espn_id:
            return []
        
        url = f"{ESPN_API_BASE}/{sport_path}/teams/{espn_id}/schedule"
        data = await self._fetch_json(url)
        if not data:
            return []
        
        return self._parse_schedule(data, team_code, limit)
    
    def _parse_schedule(
        self, 
        data: Dict[str, Any], 
        team_code: str,
        limit: int
    ) -> List[RecentGame]:
        """Parse ESPN schedule response into recent games."""
        results = []
        events = data.get("events", [])
        
        # Filter to completed games, most recent first
        completed = []
        for event in events:
            status = event.get("competitions", [{}])[0].get("status", {})
            if status.get("type", {}).get("completed", False):
                completed.append(event)
        
        # Sort by date descending
        completed.sort(
            key=lambda e: e.get("date", ""),
            reverse=True
        )
        
        for event in completed[:limit]:
            game = self._parse_game_event(event, team_code)
            if game:
                results.append(game)
        
        return results
    
    def _parse_game_event(
        self, 
        event: Dict[str, Any], 
        team_code: str
    ) -> Optional[RecentGame]:
        """Parse a single game event."""
        try:
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            
            if len(competitors) != 2:
                return None
            
            # Find our team and opponent
            our_team = None
            opponent = None
            for c in competitors:
                abbrev = c.get("team", {}).get("abbreviation", "").upper()
                if abbrev == team_code.upper():
                    our_team = c
                else:
                    opponent = c
            
            if not our_team or not opponent:
                return None
            
            # Parse scores
            our_score = int(our_team.get("score", 0))
            opp_score = int(opponent.get("score", 0))
            was_home = our_team.get("homeAway") == "home"
            won = our_score > opp_score
            
            # Parse date
            date_str = event.get("date", "")
            try:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                date = datetime.now(timezone.utc)
            
            return RecentGame(
                date=date,
                opponent_code=opponent.get("team", {}).get("abbreviation", ""),
                was_home=was_home,
                score_for=our_score,
                score_against=opp_score,
                won=won,
            )
        except Exception:
            return None
    
    # -------------------------------------------------------------------------
    # ScoreFetcher implementation
    # -------------------------------------------------------------------------
    
    async def get_result(self, event: Dict[str, Any]) -> Optional[GameResult]:
        """Fetch the result of a game."""
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        start_time = event.get("start_time_utc")

        # Try sport field first, then league field as fallback
        sport = event.get("sport") or event.get("league") or "NFL"
        sport_path = get_espn_sport_path(sport)
        if not sport_path:
            # Last-ditch: try normalising (strip underscores/spaces)
            normalised = sport.upper().replace(" ", "_").replace("-", "_")
            sport_path = get_espn_sport_path(normalised)
        if not sport_path:
            return None
        
        # Fetch scoreboard for the date
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except ValueError:
                start_time = None
        
        if start_time:
            date_str = start_time.strftime("%Y%m%d")
            url = f"{ESPN_API_BASE}/{sport_path}/scoreboard?dates={date_str}"
        else:
            url = f"{ESPN_API_BASE}/{sport_path}/scoreboard"
        
        data = await self._fetch_json(url)
        if not data:
            return None
        
        return self._find_game_result(data, home_team, away_team)
    
    @staticmethod
    def _team_matches(espn_team: Dict[str, Any], lookup: str) -> bool:
        """Return True if the ESPN team dict matches a lookup string.

        Tries (in order):
          1. Exact abbreviation match  (e.g. "MCI" == "MCI")
          2. Full display name contains lookup (e.g. "Manchester City" in event)
          3. lookup contains ESPN display name (reverse contains)
          4. Location name match (e.g. "Manchester")
        All comparisons are case-insensitive.
        """
        if not lookup:
            return False
        lu = lookup.strip().lower()
        abbrev = espn_team.get("abbreviation", "").lower()
        name   = espn_team.get("displayName", espn_team.get("name", "")).lower()
        loc    = espn_team.get("location", "").lower()
        short  = espn_team.get("shortDisplayName", "").lower()

        return (
            abbrev == lu
            or name == lu
            or (lu in name and len(lu) >= 4)
            or (name in lu and len(name) >= 4)
            or (loc and loc == lu)
            or (short and short == lu)
        )

    def _find_game_result(
        self, 
        data: Dict[str, Any], 
        home_team: str, 
        away_team: str
    ) -> Optional[GameResult]:
        """Find and parse a specific game from scoreboard.

        Uses fuzzy team matching so that full team names sent by the validator
        (e.g. "Manchester City", "Arsenal") are matched against ESPN's
        abbreviation, displayName, and location fields.
        """
        events = data.get("events", [])
        
        for event in events:
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            
            if len(competitors) != 2:
                continue
            
            # Separate home / away competitors
            home_c = None
            away_c = None
            for c in competitors:
                if c.get("homeAway") == "home":
                    home_c = c
                else:
                    away_c = c
            
            if not home_c or not away_c:
                continue

            home_espn = home_c.get("team", {})
            away_espn = away_c.get("team", {})

            # Check if this is our game via fuzzy match
            if not (
                self._team_matches(home_espn, home_team)
                and self._team_matches(away_espn, away_team)
            ):
                continue
            
            # Parse status
            status = competition.get("status", {})
            status_type = status.get("type", {})
            is_final = status_type.get("completed", False)
            status_name = status_type.get("name", "")
            
            # Parse scores — soccer may return float strings
            def _score(c: Dict) -> Optional[int]:
                v = c.get("score")
                if v is None:
                    return None
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return None

            home_score = _score(home_c)
            away_score = _score(away_c)
            
            return GameResult(
                is_final=is_final,
                home_score=home_score,
                away_score=away_score,
                status=status_name,
            )
        
        return None
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()








