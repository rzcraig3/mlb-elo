import json
import os
import time
from datetime import date, timedelta

import requests

BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
OPENING_DAY = date(2026, 3, 26)
SEASON_END = date(2026, 10, 4)
TODAY = date.today()

os.makedirs("data", exist_ok=True)


def get(url, params=None):
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)
    return resp.json()


def fetch_teams():
    data = get(f"{BASE}/teams", params={"sportId": 1, "season": SEASON})
    teams = {}
    for t in data["teams"]:
        if t.get("sport", {}).get("id") != 1:
            continue
        teams[t["id"]] = {
            "id": t["id"],
            "abbr": t["abbreviation"],
            "name": t["name"],
            "short": t.get("teamName", t["name"]),
            "division": t.get("division", {}).get("name", ""),
            "league": t.get("league", {}).get("name", ""),
        }
    print(f"  Fetched {len(teams)} teams")
    return teams


def fetch_schedule(start: date, end: date):
    completed, remaining = [], []
    current = start
    chunk = timedelta(days=30)

    while current <= end:
        chunk_end = min(current + chunk - timedelta(days=1), end)
        print(f"  Fetching {current} → {chunk_end}...", end=" ", flush=True)

        data = get(
            f"{BASE}/schedule",
            params={
                "sportId": 1,
                "gameType": "R",
                "season": SEASON,
                "startDate": current.isoformat(),
                "endDate": chunk_end.isoformat(),
            },
        )

        chunk_complete = chunk_remaining = 0
        for day in data.get("dates", []):
            for g in day.get("games", []):
                status = g["status"]["abstractGameState"]
                gdate = g["officialDate"]
                home = g["teams"]["home"]["team"]["id"]
                away = g["teams"]["away"]["team"]["id"]

                if status == "Final":
                    home_score = g["teams"]["home"].get("score")
                    away_score = g["teams"]["away"].get("score")
                    if home_score is None or away_score is None:
                        continue
                    completed.append({
                        "date": gdate,
                        "home_id": home,
                        "away_id": away,
                        "home_score": home_score,
                        "away_score": away_score,
                    })
                    chunk_complete += 1
                elif status in ("Preview", "Live"):
                    remaining.append({
                        "date": gdate,
                        "home_id": home,
                        "away_id": away,
                    })
                    chunk_remaining += 1

        print(f"{chunk_complete} final, {chunk_remaining} upcoming")
        current = chunk_end + timedelta(days=1)

    return completed, remaining


def main():
    print("Fetching teams...")
    teams = fetch_teams()

    print(f"\nFetching completed games ({OPENING_DAY} → {TODAY})...")
    completed, _ = fetch_schedule(OPENING_DAY, TODAY)

    print(f"\nFetching remaining schedule ({TODAY} → {SEASON_END})...")
    _, remaining = fetch_schedule(TODAY, SEASON_END)

    # Annotate games with team abbreviations for readability
    for g in completed + remaining:
        g["home"] = teams.get(g["home_id"], {}).get("abbr", str(g["home_id"]))
        g["away"] = teams.get(g["away_id"], {}).get("abbr", str(g["away_id"]))

    completed.sort(key=lambda g: g["date"])
    remaining.sort(key=lambda g: g["date"])

    with open("data/teams.json", "w") as f:
        json.dump(teams, f, indent=2)
    with open("data/completed_games.json", "w") as f:
        json.dump(completed, f, indent=2)
    with open("data/remaining_schedule.json", "w") as f:
        json.dump(remaining, f, indent=2)

    print(f"\n{'─'*50}")
    print(f"  Teams:              {len(teams)}")
    print(f"  Completed games:    {len(completed)}")
    print(f"  Remaining games:    {len(remaining)}")
    if completed:
        print(f"  Date range:         {completed[0]['date']} → {completed[-1]['date']}")
    print(f"{'─'*50}")
    print("Saved: data/teams.json, data/completed_games.json, data/remaining_schedule.json")


if __name__ == "__main__":
    main()
