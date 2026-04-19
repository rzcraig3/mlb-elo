"""
Downloads official MLB cap logos (SVG) for all 30 teams.
Source: www.mlbstatic.com — team-cap-on-light variant.
Run once; logos don't change during the season.
"""
import json
import os
import time

import requests

BASE = "https://www.mlbstatic.com/team-logos/team-cap-on-light/{team_id}.svg"


def main():
    with open("data/teams.json") as f:
        teams = json.load(f)

    os.makedirs("site/logos", exist_ok=True)

    ok = fail = 0
    for tid, t in teams.items():
        dest = f"site/logos/{t['abbr']}.svg"
        if os.path.exists(dest):
            ok += 1
            continue
        url = BASE.format(team_id=tid)
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(r.content)
            print(f"  ✓ {t['abbr']} ({tid})")
            ok += 1
        except Exception as e:
            print(f"  ✗ {t['abbr']} ({tid}): {e}")
            fail += 1
        time.sleep(0.2)

    print(f"\n{ok} logos saved, {fail} failed → site/logos/")


if __name__ == "__main__":
    main()
