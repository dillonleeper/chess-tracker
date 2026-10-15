# chess-tracker

Local chess.com game analysis tool. Fetches games from the chess.com API, applies cleaning rules from your analysis report, and generates a scannable HTML scorecard tracking performance vs baselines.

## Setup

1. Clone the repo:
```bash
git clone https://github.com/dillonleeper/chess-tracker.git
cd chess-tracker
```

2. Run the script:
```bash
python3 chess_tracker.py
```

First run will fetch all games and cache them locally. Subsequent runs fetch only new months (incremental).

## Output

Scorecard is saved to `output/scorecard.html`. Open in any browser.

The scorecard shows:
- Performance per 100 games for each time class (rapid, daily, blitz)
- Points vs expected score
- Habit tracking: 1.c4 usage, Philidor count, ...e6 vs QGD, late-night games (10pm+), abandons

## Data

- `cache/` holds the API data (one JSON file per month, gitignored so each PC caches independently)
- `output/` holds the HTML scorecard

## Cleaning Rules Applied

- Rated games only
- Drop first 25 per time class
- Drop opponents with 5+ games against you
- Drop closed:fair_play accounts
- Abandoned/timeout games: counted if you were down 3+ material, otherwise removed

## Usage on Both PCs

1. On PC 1: Clone, run, commit if you want to track scorecard history
2. On PC 2: Clone the same repo, run, builds its own cache locally

Cache won't sync between PCs (it's gitignored), so each runs independently. That's by design.

## Scheduled Runs (Optional)

Windows Task Scheduler (PC 1):
```
Program: python.exe
Arguments: C:\path\to\chess-tracker\chess_tracker.py
Start in: C:\path\to\chess-tracker
```

Mac/Linux cron:
```bash
52 8 * * 0 cd /path/to/chess-tracker && python3 chess_tracker.py
```

(Sunday 8:52am ET, same as the cloud task)
