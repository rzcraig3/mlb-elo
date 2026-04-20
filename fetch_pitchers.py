"""
Fetches probable pitchers for next 14 days and calculates rGS pitcher ratings.

rGS (rolling Game Score) — FiveThirtyEight formula:
  game_score = 47.4 + 1.5*outs + K - 2*BB - 2*H - 3*ER - 4*HR
  weighted average over recent starts (decay factor 0.8 per start)

Saves:
  data/probable_pitchers.json  — game key → pitcher names + IDs
  data/pitcher_ratings.json    — per-pitcher rGS + team averages
"""
import json
import time
from collections import defaultdict
from datetime import date, timedelta

import requests

BASE = "https://statsapi.mlb.com/api/v1"
DECAY        = 0.8   # weight decay per start going backward in time
SEASONS      = [2026, 2025, 2024]   # seasons to include in rolling rGS


def get(url, params=None):
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    time.sleep(0.3)
    return r.json()


def ip_to_outs(ip_str):
    parts = str(ip_str).split(".")
    return int(parts[0]) * 3 + (int(parts[1]) if len(parts) > 1 else 0)


def game_score(outs, k, bb, h, er, hr):
    return 47.4 + 1.5 * outs + k - 2 * bb - 2 * h - 3 * er - 4 * hr


def weighted_rgs(rgs_list):
    """Weighted avg rGS. rgs_list is most-recent-first."""
    if not rgs_list:
        return None
    ws = ds = 0.0
    for i, v in enumerate(rgs_list):
        w = DECAY ** i
        ws += w * v
        ds += w
    return round(ws / ds, 1)


def main():
    with open("data/teams.json") as f:
        raw = json.load(f)
    teams_by_id   = {str(v["id"]): v for v in raw.values()}
    teams_by_abbr = {v["abbr"]: v for v in raw.values()}

    today = date.today()
    end   = today + timedelta(days=14)

    # ── 1. Probable pitchers (with IDs) ───────────────────────────────────
    print("Fetching probable pitchers...")
    sched = get(f"{BASE}/schedule", params={
        "sportId":   1, "gameType": "R", "season": 2026,
        "startDate": today.isoformat(), "endDate": end.isoformat(),
        "hydrate":   "probablePitcher",
    })

    probable    = {}
    pitcher_ids = set()

    for day in sched.get("dates", []):
        for g in day.get("games", []):
            home_abbr = teams_by_id.get(str(g["teams"]["home"]["team"]["id"]), {}).get("abbr", "?")
            away_abbr = teams_by_id.get(str(g["teams"]["away"]["team"]["id"]), {}).get("abbr", "?")
            key = f"{g['officialDate']}|{home_abbr}|{away_abbr}"

            hp = g["teams"]["home"].get("probablePitcher")
            ap = g["teams"]["away"].get("probablePitcher")

            probable[key] = {
                "home_pitcher_id": hp["id"] if hp else None,
                "home_pitcher":    hp["fullName"] if hp else None,
                "away_pitcher_id": ap["id"] if ap else None,
                "away_pitcher":    ap["fullName"] if ap else None,
            }
            if hp: pitcher_ids.add(hp["id"])
            if ap: pitcher_ids.add(ap["id"])

    print(f"  {len(probable)} games, {len(pitcher_ids)} unique probable pitchers")

    # ── 2. Team average rGS from season aggregate stats (1 API call) ──────
    print("Fetching 2026 pitcher season stats...")
    stats_data = get(f"{BASE}/stats", params={
        "stats":   "season", "group": "pitching",
        "gameType": "R",     "season": 2026,
        "sportId": 1,        "limit": 1000,
    })

    team_buckets = defaultdict(list)  # abbr → list of (avg_rgs, gs)

    for split in stats_data.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        gs   = stat.get("gamesStarted", 0)
        if gs < 2:
            continue

        outs = ip_to_outs(stat.get("inningsPitched", "0.0"))
        rgs  = game_score(
            outs / gs,
            stat.get("strikeOuts",   0) / gs,
            stat.get("baseOnBalls",  0) / gs,
            stat.get("hits",         0) / gs,
            stat.get("earnedRuns",   0) / gs,
            stat.get("homeRuns",     0) / gs,
        )

        abbr = teams_by_id.get(str(split.get("team", {}).get("id", "")), {}).get("abbr")
        if abbr:
            team_buckets[abbr].append((rgs, gs))

    team_avg_rgs = {}
    for abbr, entries in team_buckets.items():
        total = sum(e[1] for e in entries)
        team_avg_rgs[abbr] = round(sum(e[0] * e[1] for e in entries) / total, 1) if total else 47.4

    # Fill any missing teams
    league_avg = (sum(team_avg_rgs.values()) / len(team_avg_rgs)) if team_avg_rgs else 47.4
    for abbr in teams_by_abbr:
        team_avg_rgs.setdefault(abbr, round(league_avg, 1))

    print(f"  Team avg rGS — min {min(team_avg_rgs.values()):.1f}, "
          f"max {max(team_avg_rgs.values()):.1f}, "
          f"league {league_avg:.1f}")

    # ── 3. Individual pitcher weighted rGS from multi-season game logs ───────
    # Fetch 2024-2026 so established pitchers aren't misrepresented by a small
    # early-season sample. Decay factor 0.8/start means recent starts still
    # dominate; older seasons just prevent wild swings from 3-4 bad outings.
    print(f"Fetching game logs for {len(pitcher_ids)} pitchers "
          f"({', '.join(str(s) for s in SEASONS)})...")
    pitcher_ratings = {}

    for pid in sorted(pitcher_ids):
        try:
            # Collect starts across all seasons, most-recent-first
            all_starts = []
            name = None
            for season in SEASONS:
                log = get(f"{BASE}/people/{pid}/stats", params={
                    "stats":    "gameLog", "group": "pitching",
                    "season":   season,    "gameType": "R",
                })
                splits = log.get("stats", [{}])[0].get("splits", [])
                if not name and splits:
                    name = splits[0].get("player", {}).get("fullName")
                season_starts = [
                    s for s in splits
                    if s.get("stat", {}).get("gamesStarted", 0) > 0
                ]
                season_starts.sort(key=lambda x: x.get("date", ""), reverse=True)
                all_starts.extend(season_starts)

            name = name or str(pid)

            rgs_list = []
            for s in all_starts:
                st = s.get("stat", {})
                rgs_list.append(game_score(
                    ip_to_outs(st.get("inningsPitched", "0.0")),
                    st.get("strikeOuts",  0),
                    st.get("baseOnBalls", 0),
                    st.get("hits",        0),
                    st.get("earnedRuns",  0),
                    st.get("homeRuns",    0),
                ))

            rgs = weighted_rgs(rgs_list)

            pitcher_ratings[str(pid)] = {
                "name":   name,
                "rgs":    rgs,
                "starts": len(rgs_list),
            }
            status = f"rGS={rgs:.1f}" if rgs is not None else "no starts"
            print(f"  {name}: {status} ({len(rgs_list)} starts across "
                  f"{len(SEASONS)} seasons)")

        except Exception as e:
            print(f"  ✗ pitcher {pid}: {e}")

    # ── Save ──────────────────────────────────────────────────────────────
    with open("data/probable_pitchers.json", "w") as f:
        json.dump(probable, f, indent=2)

    with open("data/pitcher_ratings.json", "w") as f:
        json.dump({
            "pitchers":     pitcher_ratings,
            "team_avg_rgs": team_avg_rgs,
            "updated":      today.isoformat(),
        }, f, indent=2)

    known = sum(1 for p in probable.values() if p["home_pitcher"] or p["away_pitcher"])
    print(f"\nSaved {len(probable)} games ({known} with ≥1 probable pitcher)")
    print(f"Saved {len(pitcher_ratings)} pitcher rGS ratings")


if __name__ == "__main__":
    main()
