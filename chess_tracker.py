#!/usr/bin/env python3
"""
chess-tracker: Local chess.com game analysis and scorecard generator.
Fetches games from chess.com API, applies cleaning rules, and tracks performance vs baselines.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
import re
from collections import defaultdict

# Configuration
USERNAME = "getdillpickled"
CACHE_DIR = Path(__file__).parent / "cache"
OUTPUT_DIR = Path(__file__).parent / "output"
USER_AGENT = "chess-tracker (github.com/dillonleeper/chess-tracker)"

# Baselines from the report (per 100 games)
BASELINES = {
    "rapid": {"all_time": 0.6, "last_150": -6.7},
    "daily": {"all_time": None},  # Not specified in report
    "blitz": {"all_time": None},
}

# Create directories if they don't exist
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def fetch_archives():
    """Fetch the list of available game archives from chess.com."""
    url = f"https://api.chess.com/pub/player/{USERNAME}/games/archives"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())["archives"]
    except Exception as e:
        print(f"Error fetching archives: {e}")
        return []


def fetch_month(archive_url):
    """Fetch games for a specific month from chess.com."""
    req = urllib.request.Request(archive_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())["games"]
    except Exception as e:
        print(f"Error fetching {archive_url}: {e}")
        return []


def get_cached_months():
    """Return list of (year, month) tuples already cached."""
    cached = []
    for cache_file in CACHE_DIR.glob("*.json"):
        try:
            year, month = cache_file.stem.split("_")
            cached.append((int(year), int(month)))
        except ValueError:
            pass
    return sorted(cached)


def get_latest_remote_months():
    """Fetch the list of available months from chess.com."""
    archives = fetch_archives()
    months = []
    for url in archives:
        # URL format: https://api.chess.com/pub/player/{username}/games/{year}/{month}
        parts = url.rstrip("/").split("/")
        month = int(parts[-1])
        year = int(parts[-2])
        months.append((year, month))
    return sorted(months)


def cache_month(year, month, games):
    """Cache games for a specific month."""
    cache_file = CACHE_DIR / f"{year}_{month:02d}.json"
    with open(cache_file, "w") as f:
        json.dump(games, f)
    print(f"Cached {len(games)} games from {year}-{month:02d}")


def load_cached_month(year, month):
    """Load cached games for a specific month."""
    cache_file = CACHE_DIR / f"{year}_{month:02d}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return []


def parse_pgn_date(pgn_string):
    """Extract UTC datetime from PGN (UTCDate and UTCTime tags)."""
    date_match = re.search(r'\[UTCDate "(\d{4})\.(\d{2})\.(\d{2})"\]', pgn_string)
    time_match = re.search(r'\[UTCTime "(\d{2}):(\d{2}):(\d{2})"\]', pgn_string)
    if date_match and time_match:
        year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        hour, minute, second = int(time_match.group(1)), int(time_match.group(2)), int(time_match.group(3))
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return None


def extract_moves_from_pgn(pgn_string):
    """Extract the moves section from PGN and return as a list of moves."""
    # PGN moves are in the last part after all the metadata
    # Find the position after the last ] which marks end of headers
    last_bracket = pgn_string.rfind("]")
    if last_bracket == -1:
        return []

    moves_section = pgn_string[last_bracket + 1:].strip()
    # Remove result (1-0, 0-1, 1/2-1/2, *)
    moves_section = re.sub(r'\s+[01]-[01]|\s+1/2-1/2|\s+\*\s*$', '', moves_section)
    # Split on whitespace, filter out empty and numbers like "1." "2." etc
    tokens = moves_section.split()
    moves = [t for t in tokens if t and not re.match(r'^\d+\.+$', t)]
    return moves


def extract_first_move(pgn_string, is_white=True):
    """Extract white's first move from PGN."""
    moves = extract_moves_from_pgn(pgn_string)
    if moves:
        return moves[0]
    return None


def extract_defense_vs_qgd(pgn_string, is_black):
    """Check if Black played ...e6 in response to QGD (1.d4 d5 2.c4 e6)."""
    if not is_black:
        return False
    moves = extract_moves_from_pgn(pgn_string)
    # Looking for: 1.d4 d5 2.c4 e6 pattern
    # moves[0]=d4, moves[1]=d5, moves[2]=c4, moves[3]=e6
    if len(moves) >= 4:
        m0 = moves[0].replace('+', '').replace('#', '')
        m1 = moves[1].replace('+', '').replace('#', '')
        m2 = moves[2].replace('+', '').replace('#', '')
        m3 = moves[3].replace('+', '').replace('#', '')
        if m0 == 'd4' and m1 == 'd5' and m2 == 'c4' and m3 == 'e6':
            return True
    return False


def extract_philidor(pgn_string, is_black):
    """Check if Black played the Philidor Defense (1.e4 e5 2.Nf3 d6)."""
    if not is_black:
        return False
    moves = extract_moves_from_pgn(pgn_string)
    # Looking for: 1.e4 e5 2.Nf3 d6
    # moves[0]=e4, moves[1]=e5, moves[2]=Nf3, moves[3]=d6
    if len(moves) >= 4:
        m0 = moves[0].replace('+', '').replace('#', '')
        m1 = moves[1].replace('+', '').replace('#', '')
        m2 = moves[2].replace('+', '').replace('#', '')
        m3 = moves[3].replace('+', '').replace('#', '')
        if m0 == 'e4' and m1 == 'e5' and m2 == 'Nf3' and m3 == 'd6':
            return True
    return False


def get_material_from_fen(fen):
    """Count material from FEN. Returns piece count."""
    # Simplified: count all non-pawn pieces
    board_part = fen.split()[0]
    white_material = sum(1 for c in board_part if c.isupper() and c != 'P')
    black_material = sum(1 for c in board_part if c.islower() and c != 'p')
    return white_material, black_material


def should_remove_abandoned(game, is_player_white):
    """Check if an abandoned/timeout game should be removed (walk-away)."""
    if game["termination"] not in ["abandoned", "timeout"]:
        return False

    final_fen = game.get("fen", "")
    if not final_fen:
        return False

    white_material, black_material = get_material_from_fen(final_fen)
    material_diff = white_material - black_material

    # If the player (leaver) was down 3+ material, it counts; otherwise remove it
    if is_player_white:
        return material_diff > -3  # Keep if white was not down 3+
    else:
        return material_diff < 3  # Keep if black was not down 3+


def expected_score(player_rating, opponent_rating):
    """Compute expected score (0-1) for a game."""
    return 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))


def clean_games(all_games, player_rating):
    """
    Apply cleaning rules:
    - Rated games only
    - Drop first 25 per time class
    - Drop opponents with 5+ games vs them
    - Drop closed:fair_play accounts
    - Handle abandoned/timeout games
    """
    # Filter by time class first
    by_time_class = defaultdict(list)
    for game in all_games:
        if game.get("rules") != "chess":  # Only chess, not variants
            continue
        tc = game.get("time_class")
        if tc in ["rapid", "daily", "blitz"]:
            by_time_class[tc].append(game)

    # Drop first 25 per time class
    cleaned = []
    for tc, games in by_time_class.items():
        cleaned.extend(games[25:])  # Skip first 25

    # Count repeat opponents (excluding custom games)
    opponent_counts = defaultdict(int)
    for game in cleaned:
        opponent = game.get("opponents", {}).get("black" if game.get("white", {}).get("username") == USERNAME else "white", {}).get("username")
        if opponent:
            opponent_counts[opponent] += 1

    # Drop opponents with 5+ games and closed:fair_play accounts
    filtered = []
    for game in cleaned:
        # Get opponent username
        white = game.get("white", {})
        black = game.get("black", {})
        is_player_white = white.get("username") == USERNAME
        opponent = black if is_player_white else white
        opponent_username = opponent.get("username")
        opponent_status = opponent.get("status", "")

        # Skip if repeat opponent (5+ games) or closed:fair_play
        if opponent_username and opponent_counts.get(opponent_username, 0) >= 5:
            continue
        if opponent_status.startswith("closed:fair_play"):
            continue

        # Handle abandoned/timeout
        if game.get("termination") in ["abandoned", "timeout"]:
            if not should_remove_abandoned(game, is_player_white):
                continue

        filtered.append(game)

    return filtered


def compute_metrics(games, player_rating):
    """Compute performance metrics (points vs prediction per 100 games)."""
    if not games:
        return 0, 0, 0

    total_points = 0
    total_expected = 0

    for game in games:
        white = game.get("white", {})
        black = game.get("black", {})
        is_player_white = white.get("username") == USERNAME

        opponent = black if is_player_white else white
        opponent_rating = opponent.get("rating", player_rating)

        result = game.get("pgn", "")
        if is_player_white:
            is_win = "1-0" in result
        else:
            is_win = "0-1" in result

        points = 1.0 if is_win else (0.5 if "1/2" in result else 0.0)
        expected = expected_score(player_rating, opponent_rating)

        total_points += points
        total_expected += expected

    games_count = len(games)
    points_per_100 = (total_points - total_expected) * (100 / games_count) if games_count > 0 else 0

    return points_per_100, total_points, total_expected


def analyze_habits(games):
    """Track habits: openings, Philidor, ...e6 vs QGD, late-night, abandons."""
    habits = {
        "c4": 0,  # 1.c4
        "c4_wins": 0,
        "e4": 0,  # 1.e4
        "e4_wins": 0,
        "d4": 0,  # 1.d4
        "d4_wins": 0,
        "philidor": 0,
        "qgd_e6": 0,
        "late_night_games": 0,  # 10pm+ ET
        "late_night_wins": 0,
        "abandons": 0,
        "total_games": len(games),
    }

    import zoneinfo
    et = zoneinfo.ZoneInfo("America/New_York")

    for game in games:
        pgn = game.get("pgn", "")
        white = game.get("white", {})
        black = game.get("black", {})
        is_player_white = white.get("username") == USERNAME

        # White openings
        if is_player_white:
            first_move = extract_first_move(pgn)
            is_win = "1-0" in pgn
            if first_move == "c4":
                habits["c4"] += 1
                if is_win:
                    habits["c4_wins"] += 1
            elif first_move == "e4":
                habits["e4"] += 1
                if is_win:
                    habits["e4_wins"] += 1
            elif first_move == "d4":
                habits["d4"] += 1
                if is_win:
                    habits["d4_wins"] += 1

        # Philidor (black)
        if not is_player_white and extract_philidor(pgn, True):
            habits["philidor"] += 1

        # ...e6 vs QGD (black)
        if not is_player_white and extract_defense_vs_qgd(pgn, True):
            habits["qgd_e6"] += 1

        # Late-night games (10pm+ ET)
        dt = parse_pgn_date(pgn)
        if dt:
            dt_et = dt.astimezone(et)
            if dt_et.hour >= 22:  # 10pm or later
                habits["late_night_games"] += 1
                is_win = ("1-0" in pgn if is_player_white else "0-1" in pgn)
                if is_win:
                    habits["late_night_wins"] += 1

        # Abandons
        if game.get("termination") in ["abandoned", "timeout"]:
            habits["abandons"] += 1

    return habits


def generate_html(rapid_games, daily_games, blitz_games, player_rating):
    """Generate HTML scorecard."""
    rapid_metrics = compute_metrics(rapid_games, player_rating) if rapid_games else (0, 0, 0)
    daily_metrics = compute_metrics(daily_games, player_rating) if daily_games else (0, 0, 0)
    blitz_metrics = compute_metrics(blitz_games, player_rating) if blitz_games else (0, 0, 0)

    rapid_habits = analyze_habits(rapid_games)
    daily_habits = analyze_habits(daily_games)
    blitz_habits = analyze_habits(blitz_games)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chess Tracker Scorecard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #fff; padding: 20px; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; font-weight: 600; }}
        .timestamp {{ color: #888; font-size: 12px; margin-bottom: 24px; }}
        .section {{ background: #1a1a1a; border-radius: 8px; padding: 20px; margin-bottom: 20px; border-left: 4px solid #4a9eff; }}
        .section h2 {{ font-size: 18px; margin-bottom: 16px; font-weight: 600; color: #4a9eff; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 12px; }}
        .metric {{ background: #252525; padding: 12px; border-radius: 6px; text-align: center; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #4a9eff; }}
        .metric-label {{ font-size: 12px; color: #888; margin-top: 4px; }}
        .metric.positive {{ border-top: 2px solid #4ade80; }}
        .metric.negative {{ border-top: 2px solid #f87171; }}
        .habits-list {{ font-size: 13px; line-height: 1.6; color: #ccc; }}
        .habits-list div {{ margin-bottom: 8px; }}
        .habits-list strong {{ color: #fff; }}
        footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #333; color: #666; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Chess Tracker</h1>
        <div class="timestamp">Generated {timestamp}</div>

        <div class="section">
            <h2>Rapid ({rapid_games.__len__()} games)</h2>
            <div class="metric-grid">
                <div class="metric {'positive' if rapid_metrics[0] >= 0 else 'negative'}">
                    <div class="metric-value">{rapid_metrics[0]:+.1f}</div>
                    <div class="metric-label">per 100</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{rapid_metrics[1]:.1f}</div>
                    <div class="metric-label">points</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{rapid_metrics[2]:.1f}</div>
                    <div class="metric-label">expected</div>
                </div>
            </div>
            <div class="habits-list">
                <div><strong>Openings as White:</strong> 1.c4 {rapid_habits['c4']}W-{rapid_habits['c4_wins']}, 1.e4 {rapid_habits['e4']}W-{rapid_habits['e4_wins']}, 1.d4 {rapid_habits['d4']}W-{rapid_habits['d4_wins']}</div>
                <div><strong>Late-night (10pm+):</strong> {rapid_habits['late_night_games']} games, {rapid_habits['late_night_wins']} wins</div>
                <div><strong>Abandons:</strong> {rapid_habits['abandons']}</div>
            </div>
        </div>

        <div class="section">
            <h2>Daily ({daily_games.__len__()} games)</h2>
            <div class="metric-grid">
                <div class="metric {'positive' if daily_metrics[0] >= 0 else 'negative'}">
                    <div class="metric-value">{daily_metrics[0]:+.1f}</div>
                    <div class="metric-label">per 100</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{daily_metrics[1]:.1f}</div>
                    <div class="metric-label">points</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{daily_metrics[2]:.1f}</div>
                    <div class="metric-label">expected</div>
                </div>
            </div>
            <div class="habits-list">
                <div><strong>As Black:</strong> Philidor {daily_habits['philidor']} games, ...e6 vs QGD {daily_habits['qgd_e6']} games</div>
                <div><strong>Abandons:</strong> {daily_habits['abandons']}</div>
            </div>
        </div>

        <div class="section">
            <h2>Blitz ({blitz_games.__len__()} games)</h2>
            <div class="metric-grid">
                <div class="metric {'positive' if blitz_metrics[0] >= 0 else 'negative'}">
                    <div class="metric-value">{blitz_metrics[0]:+.1f}</div>
                    <div class="metric-label">per 100</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{blitz_metrics[1]:.1f}</div>
                    <div class="metric-label">points</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{blitz_metrics[2]:.1f}</div>
                    <div class="metric-label">expected</div>
                </div>
            </div>
        </div>

        <footer>
            Player: {USERNAME} (Rating ~{player_rating})
        </footer>
    </div>
</body>
</html>"""

    return html


def main():
    """Main entry point."""
    print(f"Chess Tracker for {USERNAME}")
    print("=" * 50)

    # Get player rating
    url = f"https://api.chess.com/pub/player/{USERNAME}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            player_data = json.loads(response.read())
            player_rating = player_data.get("stats", {}).get("chess_rapid", {}).get("last", {}).get("rating", 1200)
    except Exception as e:
        print(f"Error fetching player data: {e}")
        player_rating = 1200

    print(f"Player rating: ~{player_rating}")
    print()

    # Check cache and fetch new months
    cached_months = set(get_cached_months())
    remote_months = set(get_latest_remote_months())
    new_months = sorted(remote_months - cached_months)

    print(f"Cached months: {len(cached_months)}")
    print(f"New months to fetch: {len(new_months)}")

    if new_months:
        print("\nFetching new months...")
        for year, month in new_months:
            url = f"https://api.chess.com/pub/player/{USERNAME}/games/{year}/{month:02d}"
            games = fetch_month(url)
            if games:
                cache_month(year, month, games)

    # Load all games from cache
    print("\nLoading all cached games...")
    all_games = []
    for year, month in sorted(cached_months | set(new_months)):
        games = load_cached_month(year, month)
        all_games.extend(games)

    print(f"Total games loaded: {len(all_games)}")

    # Clean and separate by time class
    print("Cleaning games...")
    cleaned = clean_games(all_games, player_rating)
    print(f"Cleaned games: {len(cleaned)}")

    rapid = [g for g in cleaned if g.get("time_class") == "rapid"]
    daily = [g for g in cleaned if g.get("time_class") == "daily"]
    blitz = [g for g in cleaned if g.get("time_class") == "blitz"]

    print(f"  Rapid: {len(rapid)}")
    print(f"  Daily: {len(daily)}")
    print(f"  Blitz: {len(blitz)}")

    # Generate HTML
    print("\nGenerating scorecard...")
    html = generate_html(rapid, daily, blitz, player_rating)

    output_file = OUTPUT_DIR / "scorecard.html"
    with open(output_file, "w") as f:
        f.write(html)

    print(f"Scorecard saved to: {output_file}")
    print("\nDone!")


if __name__ == "__main__":
    main()
