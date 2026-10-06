# Astros+ Analytics

Performance analysis of the **Astros+** cricket team in **NACL Tennis Ball Cricket, Division A** (Spring and Summer 2026), built as a small data pipeline feeding a Grafana dashboard.

**Live dashboard:** [Astros+ 2026 — Signals: Strengths and Opportunities](https://ardentsailboat1497.grafana.net/public-dashboards/6dfa470ce5304898a50712c39834bd14)

## What it answers

- **What decides our games?** Wins vs losses, compared at checkpoints (after 6 overs, after 15 overs, final score).
- **Where do we lose ground to the semi-finalists?** Run gap, wickets and economy by phase (powerplay, middle, death).
- **How do we compare with the rest of the division?** Every metric as a percentage above or below the division average.
- **How did the league change between seasons, and did we adapt?** Spring → Summer change for the division vs for us.

**Headline findings:**
- Bowling is at semi-final standard (economy 7.36 vs 7.48).
- In the 4 Summer losses the team was 84 for 7 after 15 overs; in the 5 wins, 112 for 5. Every loss included a batting collapse.
- The division's run rate rose 28% between Spring and Summer; ours stayed flat.

## Architecture

```
CricClubs scorecards ──► ingest/extract_cricclubs.js ──► data/*.json ──► ingest/load.py ──► Postgres (Neon)
  (browser, Cloudflare)    (slow, polite extraction)     (git-ignored)    (one transaction)       │
                                                                                                 │  raw.*      player-level, owner only
                                                                                                 │  cricket.*  team-level views
                                                                                                 ▼
                                    dashboards/build_*.py ──► dashboard JSON ──► Grafana Cloud ──► public link
                                    (dashboards as code)                          (read-only role)
```

| Layer | Choice | Why |
|---|---|---|
| Extraction | Browser-side JavaScript | CricClubs is behind Cloudflare; a headless client is blocked |
| Storage | Neon serverless Postgres (free tier) | Scales to zero, never deleted for inactivity |
| Modelling | SQL views in a `cricket` schema | Season-aware ranks, phase splits, collapses, all recomputed on load |
| Access control | `grafana_reader` role, `SELECT` on `cricket` only | Player-level data in `raw` is unreachable from the dashboard |
| Visualisation | Grafana Cloud, built from Python | Reproducible; a dashboard change is a code change |

## Repository layout

```
db/
  01_schema.sql         raw tables: matches, innings, batting, bowling, overs
  02_views.sql          team-level views: team_summary, team_ranks, team_phase, collapses, ...
  DATA-QUALITY.md       reconciliation checks and known source discrepancies
ingest/
  extract_cricclubs.js  browser extraction script
  load.py               full-refresh loader (schema + data + views in one transaction)
dashboards/
  build_story.py        the published dashboard
  build_astros_insights.py, build_season_compare.py, build_unified.py
                        earlier single-purpose dashboards, reused as panel libraries
data/                   raw scorecards (git-ignored: they contain player names)
```

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]"

# .env (git-ignored)
#   DATABASE_URL=postgresql://<owner>:<password>@<host>/neondb?sslmode=require

.venv/bin/python ingest/load.py                                   # loads every data/*.json
cd dashboards && ../.venv/bin/python build_story.py <grafana-datasource-uid>
# then import dashboards/astros-story.json in Grafana (Dashboards → New → Import)
```

## Data and privacy

- Source: public CricClubs scorecards for NACL Division A. Raw files are not committed.
- The dashboard is team-level only. Player names stay in the `raw` schema, which the dashboard's database role cannot read.
- Reconciliation: innings totals match batting + extras in 267 of 268 innings; the exceptions are documented errors in the source scorecards. See [`db/DATA-QUALITY.md`](db/DATA-QUALITY.md).
