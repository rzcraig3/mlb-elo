import json
import math
import os
from datetime import date, datetime, timedelta

# ── constants ──────────────────────────────────────────────────────────────
HFA        = 24
PITCH_MULT = 4.7   # FiveThirtyEight pitcher adjustment multiplier
TBD_OFFSET = -4.5  # TBD starters assumed this far below team average

# Stadium lat/lng for travel distance calculation
STADIUMS = {
    "LAD": (34.0739, -118.2400), "NYY": (40.8296, -73.9262),
    "ATL": (33.8908, -84.4677),  "SD":  (32.7076, -117.1570),
    "PHI": (39.9061, -75.1665),  "NYM": (40.7571, -73.8458),
    "AZ":  (33.4455, -112.0667), "MIL": (43.0280, -87.9712),
    "CLE": (41.4962, -81.6852),  "BAL": (39.2838, -76.6218),
    "MIN": (44.9817, -93.2776),  "DET": (42.3390, -83.0485),
    "CHC": (41.9484, -87.6553),  "BOS": (42.3467, -71.0972),
    "TB":  (27.7683, -82.6534),  "HOU": (29.7572, -95.3555),
    "STL": (38.6226, -90.1928),  "CIN": (39.0979, -84.5081),
    "TEX": (32.7512, -97.0832),  "KC":  (39.0517, -94.4803),
    "PIT": (40.4469, -80.0057),  "SEA": (47.5915, -122.3325),
    "TOR": (43.6414, -79.3894),  "SF":  (37.7786, -122.3893),
    "LAA": (33.8003, -117.8827), "WSH": (38.8730, -77.0074),
    "ATH": (36.0900, -115.1520), "MIA": (25.7781, -80.2196),
    "COL": (39.7559, -104.9942), "CWS": (41.8299, -87.6338),
}

COLORS = {
    "LAD": "#005A9C", "NYY": "#003087", "ATL": "#CE1141", "SD":  "#2F241D",
    "PHI": "#E81828", "NYM": "#002D72", "AZ":  "#A71930", "MIL": "#13294B",
    "CLE": "#00385D", "BAL": "#DF4601", "MIN": "#002B5C", "DET": "#0C2340",
    "CHC": "#0E3386", "BOS": "#BD3039", "TB":  "#092C5C", "HOU": "#002D62",
    "STL": "#C41E3A", "CIN": "#C6011F", "TEX": "#003278", "KC":  "#004687",
    "PIT": "#FDB827", "SEA": "#0C2C56", "TOR": "#134A8E", "SF":  "#FD5A1E",
    "LAA": "#BA0021", "WSH": "#AB0003", "ATH": "#003831", "MIA": "#00A3E0",
    "COL": "#33006F", "CWS": "#444444",
}

FULL_NAMES = {
    "AL East": ["NYY", "BOS", "TB", "BAL", "TOR"],
    "AL Central": ["CLE", "DET", "MIN", "KC", "CWS"],
    "AL West": ["HOU", "TEX", "SEA", "LAA", "ATH"],
    "NL East": ["ATL", "PHI", "NYM", "MIA", "WSH"],
    "NL Central": ["MIL", "CHC", "STL", "CIN", "PIT"],
    "NL West": ["LAD", "SD", "AZ", "SF", "COL"],
}

DIV_SHORT = {
    "American League East":    "AL East",
    "American League Central": "AL Central",
    "American League West":    "AL West",
    "National League East":    "NL East",
    "National League Central": "NL Central",
    "National League West":    "NL West",
}

DIVISIONS = list(FULL_NAMES.keys())
MONTH_NAMES = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


# ── data helpers ───────────────────────────────────────────────────────────
def load():
    with open("data/simulations.json") as f:
        sim = json.load(f)
    with open("data/current_ratings.json") as f:
        cr = json.load(f)
    with open("data/remaining_schedule.json") as f:
        schedule = json.load(f)
    with open("data/completed_games.json") as f:
        completed = json.load(f)
    pitchers = {}
    if os.path.exists("data/probable_pitchers.json"):
        with open("data/probable_pitchers.json") as f:
            pitchers = json.load(f)
    pitcher_ratings = {"pitchers": {}, "team_avg_rgs": {}}
    if os.path.exists("data/pitcher_ratings.json"):
        with open("data/pitcher_ratings.json") as f:
            pitcher_ratings = json.load(f)
    return sim, cr, schedule, completed, pitchers, pitcher_ratings


def div_short(full):
    return DIV_SHORT.get(full, full)


def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))


# ── travel / rest helpers ──────────────────────────────────────────────────
def haversine(abbr1, abbr2):
    """Great-circle miles between two team stadiums."""
    if abbr1 not in STADIUMS or abbr2 not in STADIUMS:
        return 0
    lat1, lon1 = STADIUMS[abbr1]
    lat2, lon2 = STADIUMS[abbr2]
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 3959 * 2 * math.asin(math.sqrt(a))


def travel_rest_adj(abbr, game, completed_games):
    """Return (travel_adj, rest_adj, rest_days) for abbr in the given upcoming game."""
    recent = [g for g in completed_games if g["home"] == abbr or g["away"] == abbr]
    if not recent:
        return 0.0, 0.0, 0

    last = recent[-1]
    last_loc  = abbr if last["home"] == abbr else last["home"]
    curr_loc  = abbr if game["home"] == abbr else game["home"]

    # Travel
    miles = haversine(last_loc, curr_loc) if last_loc != curr_loc else 0
    t_adj = -(miles ** (1 / 3)) * 0.31 if miles > 0 else 0.0

    # Rest: extra days beyond 1 (baseline is back-to-back)
    last_dt = datetime.strptime(last["date"], "%Y-%m-%d").date()
    game_dt = datetime.strptime(game["date"],  "%Y-%m-%d").date()
    rest_days = max(0, (game_dt - last_dt).days - 1)
    r_adj = min(rest_days, 3) * 2.3

    return round(t_adj, 1), round(r_adj, 1), rest_days


def pitcher_adj(abbr, pitcher_id, pitcher_ratings):
    """Return (adj_elo, rgs, pitcher_rgs, team_avg) for a pitcher."""
    team_avg = pitcher_ratings.get("team_avg_rgs", {}).get(abbr, 47.4)
    if pitcher_id is None:
        # TBD starter: assume below-average
        p_rgs = team_avg + TBD_OFFSET
        adj   = round(PITCH_MULT * TBD_OFFSET, 1)
        return adj, round(p_rgs, 1), round(team_avg, 1)
    p_data = pitcher_ratings.get("pitchers", {}).get(str(pitcher_id), {})
    p_rgs  = p_data.get("rgs")
    if p_rgs is None:
        # Known pitcher but no 2026 starts yet — treat as team average
        return 0.0, round(team_avg, 1), round(team_avg, 1)
    adj = round(PITCH_MULT * (p_rgs - team_avg), 1)
    return adj, round(p_rgs, 1), round(team_avg, 1)


def pct_fmt(p):
    if p < 1:   return "<1%"
    if p > 99:  return ">99%"
    return f"{p:.0f}%"


def prob_td_style(pct):
    opacity = min(0.85, 0.04 + (pct / 100) * 0.81)
    text    = "#ffffff" if opacity > 0.30 else "#111111"
    return f"background:rgba(237,69,62,{opacity:.3f});color:{text};font-weight:700"


# ── SVG helpers ────────────────────────────────────────────────────────────
def circle_svg(abbr, size=36, back=False):
    """Logo img with colored-circle fallback."""
    color    = COLORS.get(abbr, "#888")
    fs       = max(9, size // 4 + 3)
    lbl      = abbr if len(abbr) <= 3 else abbr[:3]
    logo_dir = "../logos" if back else "logos"
    fallback = (
        f'style="background:{color};width:{size}px;height:{size}px;'
        f'font-size:{fs}px;border-radius:50%;display:inline-flex;'
        f'align-items:center;justify-content:center;font-weight:800;'
        f'color:#fff;flex-shrink:0;letter-spacing:-.5px"'
    )
    return (
        f'<span class="team-logo" {fallback}>'
        f'<img src="{logo_dir}/{abbr}.svg" width="{size}" height="{size}" '
        f'alt="{abbr}" style="display:block" '
        f'onerror="this.style.display=\'none\'">'
        f'{lbl}</span>'
    )


def win_dist_svg(win_dist, proj_w):
    proj_l = 162 - int(round(proj_w))
    label  = f"{int(round(proj_w))}–{proj_l}"
    if not win_dist or not win_dist.get("bins"):
        return f'<div class="sim-rec"><span class="proj-wl">{label}</span></div>'

    bins    = win_dist["bins"]
    max_bin = max(bins) if bins else 1
    W, H    = 68, 20
    bar_w   = W / len(bins)

    bars = []
    for i, cnt in enumerate(bins):
        bh = (cnt / max_bin) * H
        x  = i * bar_w
        bars.append(
            f'<rect x="{x:.2f}" y="{H - bh:.2f}" '
            f'width="{max(0.3, bar_w - 0.6):.2f}" height="{bh:.2f}" rx="0.5"/>'
        )
    return (
        f'<div class="sim-rec">'
        f'<svg viewBox="0 0 {W} {H}" style="width:{W}px;height:{H}px" '
        f'class="dist-chart">{"".join(bars)}</svg>'
        f'<span class="proj-wl">{label}</span>'
        f'</div>'
    )


def elo_history_svg(history, abbr, color, w=840, h=160):
    pts = []
    for g in history:
        if g["home"] == abbr:
            pts.append((g["date"], g["home_elo_post"]))
        elif g["away"] == abbr:
            pts.append((g["date"], g["away_elo_post"]))

    if len(pts) < 2:
        return "<p class='chart-empty'>Not enough games yet</p>"

    elos  = [p[1] for p in pts]
    dates = [p[0] for p in pts]
    pl, pr, pt_pad, pb = 46, 12, 14, 28
    cw = w - pl - pr
    ch = h - pt_pad - pb

    lo = min(min(elos) - 12, 1488)
    hi = max(max(elos) + 12, 1512)

    def sx(i): return pl + (i / (len(pts) - 1)) * cw
    def sy(e): return pt_pad + ch - (e - lo) / (hi - lo) * ch

    coords = [(sx(i), sy(e)) for i, e in enumerate(elos)]
    line   = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area   = (line + f" L {coords[-1][0]:.1f},{pt_pad + ch:.1f} "
              f"L {coords[0][0]:.1f},{pt_pad + ch:.1f} Z")

    # y ticks
    rng  = hi - lo
    step = 25 if rng < 120 else 50
    v    = math.ceil(lo / step) * step
    y_ticks = []
    while v <= hi:
        y_ticks.append((v, sy(v)))
        v += step

    # month markers
    month_marks = []
    seen = set()
    for i, d in enumerate(dates):
        m = d[:7]
        if m not in seen:
            seen.add(m)
            month_marks.append((sx(i), MONTH_NAMES[int(d[5:7])]))

    y1500 = sy(1500)

    out = [f'<svg class="elo-chart" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    for _, yp in y_ticks:
        out.append(f'<line x1="{pl}" y1="{yp:.1f}" x2="{pl+cw}" y2="{yp:.1f}" stroke="#f0f0f0" stroke-width="1"/>')
    out.append(f'<path d="{area}" fill="{color}" opacity="0.10"/>')
    out.append(
        f'<line x1="{pl}" y1="{y1500:.1f}" x2="{pl+cw}" y2="{y1500:.1f}" '
        f'stroke="#ED453E" stroke-width="1.5" stroke-dasharray="5,4" opacity="0.55"/>'
    )
    out.append(f'<path d="{line}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>')
    for val, yp in y_ticks:
        out.append(f'<text x="{pl-6}" y="{yp+4:.1f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="10" fill="#bbb">{val:.0f}</text>')
    for xp, mn in month_marks:
        out.append(f'<text x="{xp:.1f}" y="{h-5}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="11" fill="#bbb">{mn}</text>')
    out.append('</svg>')
    return "".join(out)


# ── shared CSS ─────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  background:#f4f4f5;color:#111;font-size:14px;line-height:1.5}
a{color:inherit;text-decoration:none}

.wrap{max-width:1120px;margin:0 auto;padding:0 20px}

/* ── header ── */
header{background:#fff;border-bottom:1px solid #e4e4e7;padding:16px 0;
  position:sticky;top:0;z-index:100;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.header-inner{display:flex;align-items:flex-end;justify-content:space-between}
.hd-label{font-size:10px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;color:#ED453E;margin-bottom:2px}
.hd-title{font-size:20px;font-weight:800;letter-spacing:-.3px}
.hd-meta{font-size:12px;color:#888;margin-top:3px}

/* ── tabs ── */
.tabs{display:flex;border-bottom:2px solid #e4e4e7;margin:20px 0 0;background:#fff;
  border-radius:8px 8px 0 0;overflow:hidden}
.tab{padding:11px 22px;font-size:13px;font-weight:600;cursor:pointer;
  color:#888;border-bottom:2px solid transparent;margin-bottom:-2px;
  transition:color .15s,border-color .15s}
.tab:hover{color:#111}
.tab.active{color:#ED453E;border-bottom-color:#ED453E}

/* ── main table wrapper ── */
.card{background:#fff;border-radius:0 0 10px 10px;
  box-shadow:0 1px 4px rgba(0,0,0,.07);overflow:hidden}
.tbl-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

table{width:100%;border-collapse:collapse}
thead tr th{
  padding:9px 12px;font-size:10px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:#999;border-bottom:2px solid #e8e8e8;
  white-space:nowrap;background:#fafafa;text-align:right}
thead tr th:first-child,thead tr th:nth-child(2){text-align:left}
thead .span-header{text-align:center;color:#ED453E;font-size:9px;
  letter-spacing:.12em;border-bottom:1px solid #e8e8e8;padding:6px 12px}

tbody tr{border-bottom:1px solid #f0f0f0;transition:background .1s}
tbody tr:last-child{border-bottom:none}
tbody tr:hover td{background:#fafafa}
td{padding:10px 12px;text-align:right;vertical-align:middle;background:#fff;
  white-space:nowrap}
td:first-child{text-align:left;color:#999;font-size:12px;font-weight:700;width:36px}
td:nth-child(2){text-align:left}

/* ── team cell ── */
.team-cell{display:flex;align-items:center;gap:10px;min-width:168px}
.team-name{font-size:14px;font-weight:700;line-height:1.2}
.team-rec{font-size:11px;color:#999;margin-top:1px}

/* ── team logo ── */
.team-logo{position:relative;overflow:hidden;flex-shrink:0}
.team-logo img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:2px}

/* ── 7-day badge ── */
.d7{display:inline-block;padding:3px 9px;border-radius:20px;
  font-size:11px;font-weight:700;min-width:46px;text-align:center}
.d7.pos{background:#e6f9e6;color:#1a7f1a}
.d7.neg{background:#fdecea;color:#c0392b}
.d7.neu{background:#f0f0f0;color:#666}

/* ── simulated record cell ── */
.sim-rec{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.dist-chart{fill:#c0c0c0}
.proj-wl{font-size:12px;font-weight:700;color:#444;min-width:52px;text-align:left}

/* ── probability cells ── */
td.prob{padding:0;vertical-align:middle}
td.prob .prob-inner{
  display:flex;align-items:center;justify-content:center;
  height:100%;min-height:44px;padding:10px 12px;
  font-size:13px;font-weight:700}

/* ── standings view ── */
.div-section{margin-bottom:0}
.div-label{padding:10px 16px;font-size:10px;font-weight:800;
  letter-spacing:.12em;text-transform:uppercase;color:#ED453E;
  background:#fafafa;border-bottom:1px solid #e8e8e8;border-top:2px solid #ED453E}
.div-section:first-child .div-label{border-top:none}

/* ── team page ── */
.back-link{display:inline-flex;align-items:center;gap:5px;padding:18px 0 4px;
  font-size:13px;font-weight:600;color:#888}
.back-link:hover{color:#111}
.team-hero{padding:20px 0 24px;text-align:center}
.hero-eyebrow{font-size:11px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:#999;margin-bottom:10px}
.hero-text{font-size:28px;font-weight:800;line-height:1.3;
  font-family:Georgia,"Times New Roman",serif;max-width:660px;margin:0 auto}
.hero-sub{font-size:13px;color:#999;margin-top:8px}

.stat-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}
.stat-card{background:#fff;border:1px solid #e4e4e7;border-radius:10px;
  padding:18px 12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.stat-val{font-size:28px;font-weight:800;line-height:1}
.stat-lbl{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:#999;margin-top:6px}

.section-title{font-size:11px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:#999;margin:28px 0 10px;padding-bottom:6px;
  border-bottom:1px solid #e8e8e8}

/* ── upcoming games ── */
.games-table td:nth-child(2){text-align:left}
.games-table td:nth-child(3){text-align:left}
.pitcher-name{font-size:12px;font-weight:600;color:#444}
.pitcher-tbd{font-size:12px;color:#bbb}
.ha-badge{display:inline-block;padding:1px 7px;border-radius:10px;
  font-size:10px;font-weight:700;letter-spacing:.05em}
.ha-home{background:#e8f3ff;color:#1a5fa8}
.ha-away{background:#f5f5f5;color:#666}
.pwin{font-weight:700;text-align:right}
.pwin.fav{color:#1a7f1a}
.pwin.dog{color:#c0392b}
.pwin.even{color:#888}

/* ── adjustment cells ── */
.num-col{font-size:12px;font-variant-numeric:tabular-nums}
.adj-col{color:#888}
.pre-col{color:#111}
.date-col{color:#bbb;font-size:12px;text-align:left;width:58px;white-space:nowrap}
.opp-col{text-align:left;min-width:180px}
.pit-col{text-align:left;min-width:110px}
.adj-pos{color:#1a7f1a;font-weight:700}
.adj-neg{color:#c0392b;font-weight:700}
.adj-zero{color:#bbb}

/* ── elo chart ── */
.chart-section{margin:28px 0 8px}
.elo-chart{width:100%;height:auto;display:block}
.chart-empty{color:#bbb;text-align:center;padding:24px;font-size:13px}

/* ── responsive ── */
@media(max-width:680px){
  .stat-cards{grid-template-columns:repeat(2,1fr)}
  .hd-title{font-size:16px}
  .hero-text{font-size:20px}
  td,th{padding:8px 8px;font-size:12px}
  .team-name{font-size:13px}
}
"""

# ── shared JS ──────────────────────────────────────────────────────────────
JS = """
(function(){
  document.querySelectorAll('.tab').forEach(function(tab){
    tab.addEventListener('click', function(){
      var view = this.dataset.view;
      document.querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
      this.classList.add('active');
      document.querySelectorAll('.view').forEach(function(v){ v.style.display='none'; });
      var el = document.getElementById(view);
      if(el) el.style.display = '';
    });
  });
})();
"""


# ── page fragments ─────────────────────────────────────────────────────────
def page_top(title, updated="", back=False):
    css_path = "../style.css" if back else "style.css"
    js_path  = "../app.js"   if back else "app.js"
    back_html = '<a class="back-link" href="../index.html">← All Teams</a>' if back else ""
    meta_html = (f'<div class="hd-meta">10,000 simulations · Elo ratings · Updated {updated}</div>'
                 if updated else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{css_path}">
</head>
<body>
<header>
  <div class="wrap header-inner">
    <div>
      <div class="hd-label">Elo Forecast · MLB</div>
      <div class="hd-title">{title}</div>
      {meta_html}
    </div>
  </div>
</header>
<div class="wrap">
{back_html}"""


def page_bot(back=False):
    js = "../app.js" if back else "app.js"
    return f'</div><script src="{js}"></script></body></html>'


def d7_badge(val):
    cls  = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    sign = "+" if val > 0 else ""
    return f'<span class="d7 {cls}">{sign}{val:.1f}</span>'


# ── rankings table ─────────────────────────────────────────────────────────
def rankings_table(ranked):
    rows = []
    for i, (abbr, t) in enumerate(ranked, 1):
        rows.append(f"""  <tr>
    <td>{i}</td>
    <td>
      <div class="team-cell">
        <a href="teams/{abbr}.html">{circle_svg(abbr, 38)}</a>
        <div>
          <div class="team-name"><a href="teams/{abbr}.html">{t['name']}</a></div>
          <div class="team-rec">{t['w']}–{t['l']}</div>
        </div>
      </div>
    </td>
    <td style="color:#888;font-size:12px">{div_short(t['division'])}</td>
    <td style="font-weight:800;font-size:15px">{t['elo']:.0f}</td>
    <td>{d7_badge(t['elo_7d_change'])}</td>
    <td>{win_dist_svg(t.get('win_dist'), t['projected_wins'])}</td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['make_playoffs_pct'])}">{pct_fmt(t['make_playoffs_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['win_division_pct'])}">{pct_fmt(t['win_division_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['win_ws_pct'])}">{pct_fmt(t['win_ws_pct'])}</div></td>
  </tr>""")
    return f"""<div class="card">
<div class="tbl-scroll">
<table>
  <thead>
    <tr>
      <th rowspan="2">#</th>
      <th rowspan="2">Team</th>
      <th rowspan="2">Division</th>
      <th rowspan="2">Rating</th>
      <th rowspan="2">Last&nbsp;7</th>
      <th rowspan="2">Simulated Record</th>
      <th colspan="3" class="span-header">Postseason Chances</th>
    </tr>
    <tr>
      <th>Make Playoffs</th>
      <th>Win Division</th>
      <th>Win World Series</th>
    </tr>
  </thead>
  <tbody>
{"".join(rows)}
  </tbody>
</table>
</div>
</div>"""


# ── standings table ────────────────────────────────────────────────────────
def standings_view(teams):
    blocks = []
    for div in DIVISIONS:
        abbrs = [a for a in teams if div_short(teams[a]["division"]) == div]
        abbrs.sort(key=lambda a: -teams[a]["w"])
        if not abbrs:
            continue
        top = teams[abbrs[0]]
        rows = []
        for abbr in abbrs:
            t  = teams[abbr]
            gb = ((top["w"] - t["w"]) + (t["l"] - top["l"])) / 2
            gb_str = "—" if gb == 0 else f"{gb:.1f}"
            rows.append(f"""  <tr>
    <td style="text-align:left">
      <div class="team-cell">
        {circle_svg(abbr, 30)}
        <div>
          <div class="team-name"><a href="teams/{abbr}.html">{t['name']}</a></div>
          <div class="team-rec">{t['w']}–{t['l']}</div>
        </div>
      </div>
    </td>
    <td style="font-weight:700">{gb_str}</td>
    <td style="font-weight:800">{t['elo']:.0f}</td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['make_playoffs_pct'])}">{pct_fmt(t['make_playoffs_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['win_division_pct'])}">{pct_fmt(t['win_division_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(t['win_ws_pct'])}">{pct_fmt(t['win_ws_pct'])}</div></td>
  </tr>""")
        blocks.append(f"""<div class="div-section">
  <div class="div-label">{div}</div>
  <div class="tbl-scroll">
  <table>
    <thead><tr>
      <th style="text-align:left">Team</th>
      <th>GB</th><th>Rating</th>
      <th>Playoffs</th><th>Win Div</th><th>Win WS</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  </div>
</div>""")
    return f'<div class="card">{"".join(blocks)}</div>'


# ── upcoming games section ─────────────────────────────────────────────────
def upcoming_games_section(abbr, schedule, teams, completed_games, pitchers, pitcher_ratings):
    today = date.today().isoformat()
    games = [g for g in schedule
             if (g["home"] == abbr or g["away"] == abbr) and g["date"] >= today]
    games = games[:9]
    if not games:
        return ""

    def short(n):
        if not n: return None
        p = n.strip().split()
        return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) >= 2 else n

    def adj_cell(val):
        if val == 0:
            return f'<span class="adj-zero">0</span>'
        cls = "adj-pos" if val > 0 else "adj-neg"
        return f'<span class="{cls}">{val:+.0f}</span>'

    rows = []
    prev_date = None
    for g in games:
        is_home  = g["home"] == abbr
        opp      = g["away"] if is_home else g["home"]
        opp_data = teams.get(opp, {})
        base_elo = teams.get(abbr, {}).get("elo", 1500)
        opp_elo  = opp_data.get("elo", 1500)

        pk       = f"{g['date']}|{g['home']}|{g['away']}"
        pit_data = pitchers.get(pk, {})
        our_pid  = pit_data.get("home_pitcher_id" if is_home else "away_pitcher_id")
        opp_pid  = pit_data.get("away_pitcher_id" if is_home else "home_pitcher_id")
        our_name = pit_data.get("home_pitcher" if is_home else "away_pitcher")
        opp_name = pit_data.get("away_pitcher" if is_home else "home_pitcher")

        our_pit_adj, our_rgs, our_team_avg = pitcher_adj(abbr, our_pid, pitcher_ratings)
        opp_pit_adj, opp_rgs, opp_team_avg = pitcher_adj(opp,  opp_pid, pitcher_ratings)

        t_adj, r_adj, rest_d = travel_rest_adj(abbr, g, completed_games)
        tr_adj = round(t_adj + r_adj, 1)

        hfa_adj = HFA if is_home else 0

        pre_elo     = base_elo + our_pit_adj + tr_adj + hfa_adj
        opp_pre_elo = opp_elo  + opp_pit_adj + (HFA if not is_home else 0)

        p_win    = expected(pre_elo, opp_pre_elo)
        pwin_pct = p_win * 100
        pwin_cls = "fav" if pwin_pct > 52 else ("dog" if pwin_pct < 48 else "even")

        ha_badge  = ('<span class="ha-badge ha-home">HOME</span>' if is_home
                     else '<span class="ha-badge ha-away">AWAY</span>')
        our_pit_html = (f'<span class="pitcher-name">{short(our_name)}</span>'
                        if our_name else '<span class="pitcher-tbd">TBD</span>')

        date_cell = ""
        if g["date"] != prev_date:
            mo, dy = int(g["date"][5:7]), int(g["date"][8:10])
            date_cell = f"{MONTH_NAMES[mo]} {dy}"
            prev_date = g["date"]

        rows.append(f"""  <tr>
    <td class="date-col">{date_cell}</td>
    <td class="opp-col">
      {ha_badge}&nbsp;
      <a href="{opp}.html" style="display:inline-flex;align-items:center;gap:8px">
        {circle_svg(opp, 28, back=True)}
        <strong>{opp_data.get('name', opp)}</strong>
      </a>
    </td>
    <td class="pit-col">{our_pit_html}</td>
    <td class="num-col" title="Base Elo">{base_elo:.0f}</td>
    <td class="num-col adj-col">{adj_cell(our_pit_adj)}</td>
    <td class="num-col adj-col">{adj_cell(tr_adj)}</td>
    <td class="num-col pre-col"><strong>{pre_elo:.0f}</strong></td>
    <td class="pwin {pwin_cls}">{pwin_pct:.0f}%</td>
  </tr>""")

    return f"""<div class="section-title">Upcoming Games</div>
<div class="card">
<div class="tbl-scroll">
<table class="games-table">
  <thead>
    <tr>
      <th class="date-col" style="text-align:left" rowspan="2">Date</th>
      <th class="opp-col"  style="text-align:left" rowspan="2">Opponent</th>
      <th class="pit-col"  style="text-align:left" rowspan="2">Starter</th>
      <th colspan="4" class="span-header">Pre-Game Rating</th>
      <th rowspan="2">P(win)</th>
    </tr>
    <tr>
      <th class="num-col">Base</th>
      <th class="num-col adj-col">Pitcher</th>
      <th class="num-col adj-col">Travel/Rest</th>
      <th class="num-col pre-col">Total</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
</div>
</div>"""


# ── division standings on team page ────────────────────────────────────────
def division_section(abbr, div, all_teams):
    div_teams = sorted(
        [(a, t) for a, t in all_teams.items() if div_short(t["division"]) == div],
        key=lambda x: -x[1]["w"],
    )
    top_w = div_teams[0][1]["w"]
    rows = []
    for da, dt in div_teams:
        gb     = ((top_w - dt["w"]) + (dt["l"] - div_teams[0][1]["l"])) / 2
        gb_str = "—" if gb == 0 else f"{gb:.1f}"
        bold   = ' style="font-weight:800"' if da == abbr else ""
        rows.append(f"""  <tr{bold}>
    <td style="text-align:left">
      <div class="team-cell">
        {circle_svg(da, 28, back=True)}
        <div>
          <div class="team-name"><a href="{da}.html">{dt['name']}</a></div>
          <div class="team-rec">{dt['w']}–{dt['l']}</div>
        </div>
      </div>
    </td>
    <td>{gb_str}</td>
    <td style="font-weight:800">{dt['elo']:.0f}</td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(dt['make_playoffs_pct'])}">{pct_fmt(dt['make_playoffs_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(dt['win_division_pct'])}">{pct_fmt(dt['win_division_pct'])}</div></td>
  </tr>""")
    return f"""<div class="section-title">{div} Standings</div>
<div class="card">
<div class="tbl-scroll">
<table>
  <thead><tr>
    <th style="text-align:left">Team</th>
    <th>GB</th><th>Rating</th><th>Playoffs</th><th>Win Div</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
</div>
</div>"""


# ── playoff picture on team page ───────────────────────────────────────────
def playoff_picture_section(abbr, all_teams):
    ranked = sorted(all_teams.items(), key=lambda x: -x[1]["elo"])
    rows = []
    for i, (ra, rt) in enumerate(ranked, 1):
        bold = ' style="font-weight:800"' if ra == abbr else ""
        rows.append(f"""  <tr{bold}>
    <td style="color:#bbb;font-size:11px">#{i}</td>
    <td style="text-align:left">
      <div class="team-cell">
        {circle_svg(ra, 28, back=True)}
        <div>
          <div class="team-name"><a href="{ra}.html">{rt['name']}</a></div>
          <div class="team-rec">{rt['w']}–{rt['l']}</div>
        </div>
      </div>
    </td>
    <td style="font-weight:700">{rt['elo']:.0f}</td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(rt['make_playoffs_pct'])}">{pct_fmt(rt['make_playoffs_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(rt['win_division_pct'])}">{pct_fmt(rt['win_division_pct'])}</div></td>
    <td class="prob"><div class="prob-inner" style="{prob_td_style(rt['win_ws_pct'])}">{pct_fmt(rt['win_ws_pct'])}</div></td>
  </tr>""")
    return f"""<div class="section-title">Playoff Picture</div>
<div class="card">
<div class="tbl-scroll">
<table>
  <thead><tr>
    <th></th>
    <th style="text-align:left">Team</th>
    <th>Rating</th>
    <th>Make Playoffs</th><th>Win Division</th><th>Win WS</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
</div>
</div>"""


# ── team page ──────────────────────────────────────────────────────────────
def build_team_page(abbr, t, all_teams, history, schedule, completed_games,
                    pitchers, pitcher_ratings, updated):
    color     = COLORS.get(abbr, "#888")
    div       = div_short(t["division"])
    ws_pct    = t["win_ws_pct"]
    po_pct    = t["make_playoffs_pct"]
    div_pct   = t["win_division_pct"]
    proj_w    = t["projected_wins"]

    hero = (
        f'<span style="color:{color};font-style:normal">{t["name"]}</span>'
        f' have a <span style="color:{color}">{pct_fmt(ws_pct)}</span>'
        f' chance of winning the World Series.'
    )

    elo_svg  = elo_history_svg(history, abbr, color)
    upcoming = upcoming_games_section(abbr, schedule, all_teams,
                                      completed_games, pitchers, pitcher_ratings)
    div_sec  = division_section(abbr, div, all_teams)
    playoff  = playoff_picture_section(abbr, all_teams)

    return f"""{page_top(t['name'] + ' · 2026 Forecast', updated, back=True)}
<div class="team-hero">
  {circle_svg(abbr, 72, back=True)}
  <div class="hero-eyebrow" style="margin-top:12px">{div} · {t['w']}–{t['l']}</div>
  <div class="hero-text">The {hero}</div>
  <div class="hero-sub">Elo {t['elo']:.0f} · Updated {updated}</div>
</div>

<div class="stat-cards">
  <div class="stat-card">
    <div class="stat-val" style="color:{color}">{proj_w:.0f}</div>
    <div class="stat-lbl">Projected Wins</div>
  </div>
  <div class="stat-card">
    <div class="stat-val" style="color:{color}">{pct_fmt(po_pct)}</div>
    <div class="stat-lbl">Make Playoffs</div>
  </div>
  <div class="stat-card">
    <div class="stat-val" style="color:{color}">{pct_fmt(div_pct)}</div>
    <div class="stat-lbl">Win Division</div>
  </div>
  <div class="stat-card">
    <div class="stat-val" style="color:{color}">{pct_fmt(ws_pct)}</div>
    <div class="stat-lbl">Win World Series</div>
  </div>
</div>

{upcoming}
{div_sec}
{playoff}

<div class="section-title">Team Rating — 2026 Season</div>
<div class="card" style="padding:16px 8px 8px">
  {elo_svg}
</div>
<div style="height:32px"></div>
{page_bot(back=True)}"""


# ── index page ─────────────────────────────────────────────────────────────
def build_index(sim, updated, ranked):
    teams = sim["teams"]
    return f"""{page_top('2026 MLB Elo Forecast', updated)}
<div class="tabs">
  <div class="tab active" data-view="view-rankings">Rankings</div>
  <div class="tab" data-view="view-standings">Standings</div>
</div>
<div id="view-rankings" class="view">
  {rankings_table(ranked)}
</div>
<div id="view-standings" class="view" style="display:none">
  {standings_view(teams)}
</div>
{page_bot()}"""


# ── main ───────────────────────────────────────────────────────────────────
def main():
    sim, cr, schedule, completed, pitchers, pitcher_ratings = load()
    teams   = sim["teams"]
    history = cr["history"]
    updated = sim["updated"]

    os.makedirs("site/teams", exist_ok=True)

    with open("site/style.css", "w") as f:
        f.write(CSS)
    with open("site/app.js", "w") as f:
        f.write(JS)

    ranked = sorted(teams.items(), key=lambda x: -x[1]["elo"])

    with open("site/index.html", "w") as f:
        f.write(build_index(sim, updated, ranked))

    for abbr, t in teams.items():
        html = build_team_page(abbr, t, teams, history, schedule, completed,
                               pitchers, pitcher_ratings, updated)
        with open(f"site/teams/{abbr}.html", "w") as f:
            f.write(html)

    print(f"Built site/index.html + {len(teams)} team pages")
    print("Open with:  open site/index.html")


if __name__ == "__main__":
    main()
