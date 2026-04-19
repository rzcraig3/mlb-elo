import json
import math
import multiprocessing as mp
from datetime import date

NS = 10_000
K = 4
HFA = 24

WIN_BASE = 40   # lowest win total tracked
WIN_BINS = 85   # covers 40–124 wins


def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))


def load():
    with open("data/current_ratings.json") as f:
        cr = json.load(f)
    with open("data/remaining_schedule.json") as f:
        schedule = json.load(f)
    with open("data/teams.json") as f:
        raw = json.load(f)

    teams = {v["abbr"]: v for v in raw.values()}
    ratings = cr["ratings"]
    return ratings, schedule, teams


def make_rng(seed):
    state = [seed | 1]

    def rand():
        x = state[0]
        x ^= x << 13
        x ^= x >> 17
        x ^= x << 5
        x &= 0xFFFFFFFF
        state[0] = x
        return x / 4294967296

    return rand


def sim_series(a, b, games_needed, elo_map, rng):
    aw = bw = 0
    home = a
    while aw < games_needed and bw < games_needed:
        p = expected(elo_map[home] + HFA, elo_map[b if home == a else a])
        if rng() < p:
            aw += 1
        else:
            bw += 1
        home = b if home == a else a
    return a if aw >= games_needed else b


def run_batch(args):
    ratings, schedule, seed_offset, n_sims = args

    abbrs = list(ratings.keys())
    div_of = {a: ratings[a]["division"] for a in abbrs}
    lg_of  = {a: ratings[a]["league"]   for a in abbrs}
    divs_per_lg = {}
    for a in abbrs:
        lg = lg_of[a]
        divs_per_lg.setdefault(lg, set()).add(div_of[a])

    counters = {a: {"po": 0, "dv": 0, "lcs": 0, "pn": 0, "ws": 0, "tw": 0}
                for a in abbrs}
    win_hist = {a: [0] * WIN_BINS for a in abbrs}

    for s in range(n_sims):
        rng = make_rng(seed_offset * 999983 + s * 7919 + 42)

        rc  = {a: {"w": ratings[a]["w"], "l": ratings[a]["l"]} for a in abbrs}
        elo = {a: float(ratings[a]["elo"]) for a in abbrs}

        for g in schedule:
            home, away = g["home"], g["away"]
            if home not in elo or away not in elo:
                continue
            p = expected(elo[home] + HFA, elo[away])
            home_wins = rng() < p
            winner, loser = (home, away) if home_wins else (away, home)
            delta = K * ((1.0 if home_wins else 0.0) - p)
            elo[home] += delta
            elo[away] -= delta
            rc[winner]["w"] += 1
            rc[loser]["l"]  += 1

        for a in abbrs:
            w = rc[a]["w"]
            counters[a]["tw"] += w
            idx = max(0, min(WIN_BINS - 1, w - WIN_BASE))
            win_hist[a][idx] += 1

        pennant_winners = []
        for lg in ("American League", "National League"):
            lt = [a for a in abbrs if lg_of[a] == lg]

            dw = []
            for div in divs_per_lg[lg]:
                dt = sorted([a for a in lt if div_of[a] == div],
                             key=lambda a: rc[a]["w"], reverse=True)
                top_w = rc[dt[0]]["w"]
                tied  = [a for a in dt if rc[a]["w"] == top_w]
                winner = tied[int(rng() * len(tied))]
                dw.append(winner)
                counters[winner]["dv"] += 1

            nw     = sorted([a for a in lt if a not in dw],
                            key=lambda a: rc[a]["w"], reverse=True)
            wc     = nw[:3]
            po     = dw + wc
            for a in po:
                counters[a]["po"] += 1

            seeded = sorted(po, key=lambda a: rc[a]["w"], reverse=True)
            wc1    = sim_series(seeded[2], seeded[5], 2, elo, rng)
            wc2    = sim_series(seeded[3], seeded[4], 2, elo, rng)

            better_wc = wc1 if rc[wc1]["w"] >= rc[wc2]["w"] else wc2
            worse_wc  = wc2 if better_wc == wc1 else wc1
            ds1 = sim_series(seeded[0], worse_wc,  3, elo, rng)
            ds2 = sim_series(seeded[1], better_wc, 3, elo, rng)

            counters[ds1]["lcs"] += 1
            counters[ds2]["lcs"] += 1
            lcs = sim_series(ds1, ds2, 4, elo, rng)
            counters[lcs]["pn"] += 1
            pennant_winners.append(lcs)

        if len(pennant_winners) == 2:
            ws_winner = sim_series(pennant_winners[0], pennant_winners[1], 4, elo, rng)
            counters[ws_winner]["ws"] += 1

    return counters, win_hist


def merge(results):
    totals    = None
    total_dist = None
    for counters, win_hist in results:
        if totals is None:
            totals     = counters
            total_dist = win_hist
        else:
            for a in totals:
                for k in totals[a]:
                    totals[a][k] += counters[a][k]
                for i in range(WIN_BINS):
                    total_dist[a][i] += win_hist[a][i]
    return totals, total_dist


def main():
    ratings, schedule, teams = load()
    abbrs = list(ratings.keys())

    ncpu   = mp.cpu_count() or 4
    chunk  = NS // ncpu
    chunks = [chunk] * ncpu
    chunks[-1] += NS - sum(chunks)

    args = [(ratings, schedule, i, chunks[i]) for i in range(ncpu)]

    print(f"Running {NS:,} simulations across {ncpu} cores...")
    with mp.Pool(ncpu) as pool:
        results = pool.map(run_batch, args)

    totals, total_dist = merge(results)

    sim_teams = {}
    for a in abbrs:
        c = totals[a]
        r = ratings[a]

        # trim leading/trailing zeros from histogram
        bins = total_dist[a]
        start = next((i for i, v in enumerate(bins) if v > 0), 0)
        end   = len(bins) - next((i for i, v in enumerate(reversed(bins)) if v > 0), 0)

        sim_teams[a] = {
            "elo":               r["elo"],
            "w":                 r["w"],
            "l":                 r["l"],
            "elo_7d_change":     r["elo_7d_change"],
            "name":              r["name"],
            "division":          r["division"],
            "league":            r["league"],
            "projected_wins":    round(c["tw"] / NS, 1),
            "make_playoffs_pct": round(c["po"] / NS * 100, 1),
            "win_division_pct":  round(c["dv"] / NS * 100, 1),
            "make_lcs_pct":      round(c["lcs"] / NS * 100, 1),
            "win_pennant_pct":   round(c["pn"] / NS * 100, 1),
            "win_ws_pct":        round(c["ws"] / NS * 100, 1),
            "win_dist": {
                "lo":   WIN_BASE + start,
                "bins": bins[start:end],
            },
        }

    output = {
        "teams":       sim_teams,
        "updated":     date.today().isoformat(),
        "simulations": NS,
    }

    with open("data/simulations.json", "w") as f:
        json.dump(output, f, indent=2)

    ranked = sorted(sim_teams.items(), key=lambda x: -x[1]["elo"])
    header = f"{'#':<3} {'Team':<6} {'W-L':<8} {'Elo':<7} {'Δ7d':<7} {'ProjW':<7} | {'Playoff':>8} {'Div':>7} {'WS':>7}"
    print(f"\n{header}")
    print("─" * len(header))
    for i, (a, t) in enumerate(ranked, 1):
        wl = f"{t['w']}-{t['l']}"
        d7 = f"{t['elo_7d_change']:+.1f}"
        print(
            f"{i:<3} {a:<6} {wl:<8} {t['elo']:<7.1f} {d7:<7} {t['projected_wins']:<7.1f}"
            f" | {t['make_playoffs_pct']:>7.1f}% {t['win_division_pct']:>6.1f}% {t['win_ws_pct']:>6.1f}%"
        )

    print(f"\nSaved data/simulations.json  ({NS:,} simulations)")


if __name__ == "__main__":
    main()
