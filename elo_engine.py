import json
import math
import os
from datetime import date, timedelta

K   = 4
HFA = 24


def wins_to_elo(wins, games=162):
    """Scale projected wins to Elo (FiveThirtyEight methodology)."""
    rate = max(0.001, min(0.999, wins / games))
    return 1500 + 400 * math.log10(rate / (1 - rate))


def build_preseason_elos():
    """
    FiveThirtyEight preseason methodology:
      - 67% from win projections (FanGraphs depth charts), scaled to Elo
      - 33% from previous season's final Elo, reverted 1/3 toward 1500

    First season of this system: 100% win projections (no prior available).
    Subsequent seasons: blend automatically once prev_season_elo.json exists.
    """
    with open("data/preseason_projections.json") as f:
        proj = json.load(f)
    proj_wins = proj["projections"]

    prev_elo = {}
    if os.path.exists("data/prev_season_elo.json"):
        with open("data/prev_season_elo.json") as f:
            prev_elo = json.load(f)
        print(f"  Blending with previous season Elo (67/33 split)")
    else:
        print(f"  No previous season Elo found — using 100% win projections")

    preseason = {}
    for abbr, wins in proj_wins.items():
        p_elo = wins_to_elo(wins)
        if abbr in prev_elo:
            reverted = prev_elo[abbr] * (2 / 3) + 1500 * (1 / 3)
            preseason[abbr] = 0.67 * p_elo + 0.33 * reverted
        else:
            preseason[abbr] = p_elo

    return preseason


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

    print("Building preseason Elo ratings...")
    preseason = build_preseason_elos()

    # Initialise ratings — fall back to 1500 for any team missing from projections
    elo = {abbr: float(preseason.get(abbr, 1500)) for abbr in teams}
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

    # Save end-of-season Elo for next year's 33% blend
    # (only after the final regular-season game in October)
    season_end = date(date.today().year, 10, 5)
    if date.today() >= season_end:
        prev = {abbr: round(elo[abbr], 1) for abbr in elo}
        with open("data/prev_season_elo.json", "w") as f:
            json.dump(prev, f, indent=2)
        print("Saved data/prev_season_elo.json for next season's preseason blend")

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
