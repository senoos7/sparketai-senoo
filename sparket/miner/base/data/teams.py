"""Team code mappings for various leagues.

Maps short team codes (e.g., "KC") to full names, ESPN IDs, and other identifiers
needed for API lookups.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# NFL Teams - All 32 teams
NFL_TEAMS: Dict[str, Dict[str, Any]] = {
    # AFC East
    "BUF": {"name": "Buffalo Bills", "espn_id": "2", "location": "Buffalo"},
    "MIA": {"name": "Miami Dolphins", "espn_id": "15", "location": "Miami"},
    "NE": {"name": "New England Patriots", "espn_id": "17", "location": "New England"},
    "NYJ": {"name": "New York Jets", "espn_id": "20", "location": "New York"},
    
    # AFC North
    "BAL": {"name": "Baltimore Ravens", "espn_id": "33", "location": "Baltimore"},
    "CIN": {"name": "Cincinnati Bengals", "espn_id": "4", "location": "Cincinnati"},
    "CLE": {"name": "Cleveland Browns", "espn_id": "5", "location": "Cleveland"},
    "PIT": {"name": "Pittsburgh Steelers", "espn_id": "23", "location": "Pittsburgh"},
    
    # AFC South
    "HOU": {"name": "Houston Texans", "espn_id": "34", "location": "Houston"},
    "IND": {"name": "Indianapolis Colts", "espn_id": "11", "location": "Indianapolis"},
    "JAX": {"name": "Jacksonville Jaguars", "espn_id": "30", "location": "Jacksonville"},
    "TEN": {"name": "Tennessee Titans", "espn_id": "10", "location": "Tennessee"},
    
    # AFC West
    "DEN": {"name": "Denver Broncos", "espn_id": "7", "location": "Denver"},
    "KC": {"name": "Kansas City Chiefs", "espn_id": "12", "location": "Kansas City"},
    "LV": {"name": "Las Vegas Raiders", "espn_id": "13", "location": "Las Vegas"},
    "LAC": {"name": "Los Angeles Chargers", "espn_id": "24", "location": "Los Angeles"},
    
    # NFC East
    "DAL": {"name": "Dallas Cowboys", "espn_id": "6", "location": "Dallas"},
    "NYG": {"name": "New York Giants", "espn_id": "19", "location": "New York"},
    "PHI": {"name": "Philadelphia Eagles", "espn_id": "21", "location": "Philadelphia"},
    "WAS": {"name": "Washington Commanders", "espn_id": "28", "location": "Washington"},
    
    # NFC North
    "CHI": {"name": "Chicago Bears", "espn_id": "3", "location": "Chicago"},
    "DET": {"name": "Detroit Lions", "espn_id": "8", "location": "Detroit"},
    "GB": {"name": "Green Bay Packers", "espn_id": "9", "location": "Green Bay"},
    "MIN": {"name": "Minnesota Vikings", "espn_id": "16", "location": "Minnesota"},
    
    # NFC South
    "ATL": {"name": "Atlanta Falcons", "espn_id": "1", "location": "Atlanta"},
    "CAR": {"name": "Carolina Panthers", "espn_id": "29", "location": "Carolina"},
    "NO": {"name": "New Orleans Saints", "espn_id": "18", "location": "New Orleans"},
    "TB": {"name": "Tampa Bay Buccaneers", "espn_id": "27", "location": "Tampa Bay"},
    
    # NFC West
    "ARI": {"name": "Arizona Cardinals", "espn_id": "22", "location": "Arizona"},
    "LA": {"name": "Los Angeles Rams", "espn_id": "14", "location": "Los Angeles"},
    "SF": {"name": "San Francisco 49ers", "espn_id": "25", "location": "San Francisco"},
    "SEA": {"name": "Seattle Seahawks", "espn_id": "26", "location": "Seattle"},
}

# NBA Teams - All 30 teams
NBA_TEAMS: Dict[str, Dict[str, Any]] = {
    # Atlantic Division
    "BOS": {"name": "Boston Celtics", "espn_id": "2", "location": "Boston"},
    "BKN": {"name": "Brooklyn Nets", "espn_id": "17", "location": "Brooklyn"},
    "NYK": {"name": "New York Knicks", "espn_id": "18", "location": "New York"},
    "PHI": {"name": "Philadelphia 76ers", "espn_id": "20", "location": "Philadelphia"},
    "TOR": {"name": "Toronto Raptors", "espn_id": "28", "location": "Toronto"},
    
    # Central Division
    "CHI": {"name": "Chicago Bulls", "espn_id": "4", "location": "Chicago"},
    "CLE": {"name": "Cleveland Cavaliers", "espn_id": "5", "location": "Cleveland"},
    "DET": {"name": "Detroit Pistons", "espn_id": "8", "location": "Detroit"},
    "IND": {"name": "Indiana Pacers", "espn_id": "11", "location": "Indiana"},
    "MIL": {"name": "Milwaukee Bucks", "espn_id": "15", "location": "Milwaukee"},
    
    # Southeast Division
    "ATL": {"name": "Atlanta Hawks", "espn_id": "1", "location": "Atlanta"},
    "CHA": {"name": "Charlotte Hornets", "espn_id": "30", "location": "Charlotte"},
    "MIA": {"name": "Miami Heat", "espn_id": "14", "location": "Miami"},
    "ORL": {"name": "Orlando Magic", "espn_id": "19", "location": "Orlando"},
    "WAS": {"name": "Washington Wizards", "espn_id": "27", "location": "Washington"},
    
    # Northwest Division
    "DEN": {"name": "Denver Nuggets", "espn_id": "7", "location": "Denver"},
    "MIN": {"name": "Minnesota Timberwolves", "espn_id": "16", "location": "Minnesota"},
    "OKC": {"name": "Oklahoma City Thunder", "espn_id": "25", "location": "Oklahoma City"},
    "POR": {"name": "Portland Trail Blazers", "espn_id": "22", "location": "Portland"},
    "UTA": {"name": "Utah Jazz", "espn_id": "26", "location": "Utah"},
    
    # Pacific Division
    "GSW": {"name": "Golden State Warriors", "espn_id": "9", "location": "Golden State"},
    "LAC": {"name": "Los Angeles Clippers", "espn_id": "12", "location": "Los Angeles"},
    "LAL": {"name": "Los Angeles Lakers", "espn_id": "13", "location": "Los Angeles"},
    "PHX": {"name": "Phoenix Suns", "espn_id": "21", "location": "Phoenix"},
    "SAC": {"name": "Sacramento Kings", "espn_id": "23", "location": "Sacramento"},
    
    # Southwest Division
    "DAL": {"name": "Dallas Mavericks", "espn_id": "6", "location": "Dallas"},
    "HOU": {"name": "Houston Rockets", "espn_id": "10", "location": "Houston"},
    "MEM": {"name": "Memphis Grizzlies", "espn_id": "29", "location": "Memphis"},
    "NOP": {"name": "New Orleans Pelicans", "espn_id": "3", "location": "New Orleans"},
    "SAS": {"name": "San Antonio Spurs", "espn_id": "24", "location": "San Antonio"},
}

# League mapping
LEAGUE_TEAMS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "NFL": NFL_TEAMS,
    "NBA": NBA_TEAMS,
}

# ESPN sport paths
ESPN_SPORT_PATHS: Dict[str, str] = {
    # US major sports
    "NFL":   "football/nfl",
    "NBA":   "basketball/nba",
    "MLB":   "baseball/mlb",
    "NHL":   "hockey/nhl",
    "NCAAF": "football/college-football",
    "NCAAB": "basketball/mens-college-basketball",
    # Soccer / football — major leagues with ESPN API coverage
    "MLS":        "soccer/usa.1",
    "EPL":        "soccer/eng.1",
    "ENG":        "soccer/eng.1",
    "LA_LIGA":    "soccer/esp.1",
    "ESP":        "soccer/esp.1",
    "SERIE_A":    "soccer/ita.1",
    "ITA":        "soccer/ita.1",
    "BUNDESLIGA": "soccer/ger.1",
    "GER":        "soccer/ger.1",
    # Additional validator league codes
    "FRL1":       "soccer/fra.1",   # French Ligue 1
    "FRA":        "soccer/fra.1",
    "LIGUE1":     "soccer/fra.1",
    "POR":        "soccer/por.1",   # Primeira Liga (Portugal)
    "NED":        "soccer/ned.1",   # Eredivisie (Netherlands)
    "UOL":        "soccer/eng.1",   # UOL maps to EPL scoreboard as fallback
    # Common aliases
    "PREMIER_LEAGUE": "soccer/eng.1",
    "ENGLISH_PREMIER_LEAGUE": "soccer/eng.1",
    "LALIGA":     "soccer/esp.1",
    "SERIEA":     "soccer/ita.1",
    "SOCCER":     "soccer/eng.1",   # generic fallback
}


def get_team_info(league: str, code: str) -> Optional[Dict[str, Any]]:
    """Get team info by league and code.
    
    Args:
        league: League code (e.g., "NFL", "NBA")
        code: Team code (e.g., "KC", "LAL")
    
    Returns:
        Team info dict with name, espn_id, location, or None if not found.
    """
    teams = LEAGUE_TEAMS.get(league.upper(), {})
    return teams.get(code.upper())


def get_team_by_name(league: str, name: str) -> Optional[str]:
    """Find team code by full or partial name.
    
    Args:
        league: League code
        name: Full or partial team name (case-insensitive)
    
    Returns:
        Team code if found, None otherwise.
    """
    teams = LEAGUE_TEAMS.get(league.upper(), {})
    name_lower = name.lower()
    
    for code, info in teams.items():
        if name_lower in info["name"].lower():
            return code
        if name_lower in info["location"].lower():
            return code
    
    return None


def get_espn_sport_path(league: str) -> Optional[str]:
    """Get ESPN API sport path for a league.
    
    Args:
        league: League code
    
    Returns:
        ESPN sport path (e.g., "football/nfl") or None.
    """
    return ESPN_SPORT_PATHS.get(league.upper())








