import json
import math
from datetime import date, timedelta

PRESEASON = {
    "LAD": 1590, "NYY": 1560, "ATL": 1550, "PHI": 1540,
    "NYM": 1530, "HOU": 1530, "SD": 1530, "BAL": 1520,
    "AZ": 1520, "CLE": 1520, "MIL": 1520, "MIN": 1510,
    "DET": 1510, "BOS": 1510, "CHC": 1510, "TB":  1505,
    "STL": 1500, "CIN": 1500, "TEX": 1500, "KC":  1500,
    "TOR": 1490, "SEA": 1490, "SF":  1490, "PIT": 1480,
    "WSH": 1470, "LAA": 1470, "ATH": 1460, "MIA": 1440,
    "COL": 1420, "CWS": 1380,
}

K = 4
HFA = 24


def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))


def mov_multiplier(run_diff, elo_diff):
    return math.log(abs(run_diff) + 1) * (2.2 / (elo_diff * 0.001 + 2.2))


def load():
    with open("data/teams.json") as f:
        raw = json.load(f)
    # key by abbreviation
    teams = {v["abbr"]: v for v in raw.values()}

    with open("data/completed_games.json") as f:
        games = json.load(f)

    return teams, games


def run():
    teams, games = load()

    # initialise ratings and record trackers
    elo = {abbr: float(PRESEASON.get(abbr, 1500)) for abbr in teams}
    wins = {abbr: 0 for abbr in teams}
    losses = {abbr: 0 for abbr in teams}
    history = []

    for g in games:
        home, away = g["home"], g["away"]
        if home not in elo or away not in elo:
            continue

        hs, as_ = g["home_score"], g["away_score"]
        run_diff = abs(hs - as_)
        winner, loser = (home, away) if hs > as_ else (away, home)

        pre_home, pre_away = elo[home], elo[away]
        exp_home = expected(pre_home + HFA, pre_away)

        elo_diff = pre_home - pre_away if winner == home else pre_away - pre_home
        mult = mov_multiplier(run_diff, elo_diff)

        outcome_home = 1.0 if hs > as_ else 0.0
        delta = K * mult * (outcome_home - exp_home)

        elo[home] = pre_home + delta
        elo[away] = pre_away - delta

        wins[winner] += 1
        losses[loser] += 1

        history.append({
            "date": g["date"],
            "home": home,
            "away": away,
            "home_score": hs,
            "away_score": as_,
            "home_elo_pre": round(pre_home, 1),
            "away_elo_pre": round(pre_away, 1),
            "home_elo_post": round(elo[home], 1),
            "away_elo_post": round(elo[away], 1),
        })

    # 7-day change
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    delta_7d = {abbr: 0.0 for abbr in elo}
    for g in history:
        if g["date"] < cutoff:
            continue
        delta_7d[g["home"]] += g["home_elo_post"] - g["home_elo_pre"]
        delta_7d[g["away"]] += g["away_elo_post"] - g["away_elo_pre"]

    ratings = {
        abbr: {
            "elo": round(elo[abbr], 1),
            "w": wins[abbr],
            "l": losses[abbr],
            "elo_7d_change": round(delta_7d[abbr], 1),
            "name": teams[abbr]["name"],
            "division": teams[abbr]["division"],
            "league": teams[abbr]["league"],
        }
        for abbr in elo
    }

    output = {
        "ratings": ratings,
        "history": history,
        "updated": date.today().isoformat(),
    }

    with open("data/current_ratings.json", "w") as f:
        json.dump(output, f, indent=2)

    # print table
    ranked = sorted(ratings.items(), key=lambda x: -x[1]["elo"])
    print(f"\n{'#':<3} {'Team':<14} {'W-L':<8} {'Elo':<7} {'Δ7d'}")
    print("─" * 42)
    for i, (abbr, r) in enumerate(ranked, 1):
        wl = f"{r['w']}-{r['l']}"
        d7 = f"{r['elo_7d_change']:+.1f}"
        print(f"{i:<3} {abbr:<6} {r['name'][:12]:<14} {wl:<8} {r['elo']:<7.1f} {d7}")

    print(f"\nSaved data/current_ratings.json  ({len(history)} games processed)")


if __name__ == "__main__":
    run()
