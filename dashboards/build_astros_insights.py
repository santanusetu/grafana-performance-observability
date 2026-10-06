"""Generate the Astros+ Insights Grafana dashboard as JSON (dashboards as code).

Usage:
    python dashboards/build_astros_insights.py <datasource-uid>
Writes dashboards/astros-insights.json, ready for Grafana's Import screen or the HTTP API.

No template variables are used: Grafana's externally shared (public) dashboards
do not support them, so the team is fixed in each query.
"""
import json
import sys
from pathlib import Path

TEAM = "Astros+"
SEASON = "Summer 2026"
OUT = Path(__file__).resolve().parent / "astros-insights.json"

GREEN, AMBER, RED, BLUE, GREY = "#3fb950", "#d29922", "#f85149", "#4c8fd6", "#8b949e"
DS: dict = {}


def target(sql: str, ref: str = "A") -> dict:
    return {"refId": ref, "datasource": DS, "rawSql": sql.strip(), "format": "table",
            "rawQuery": True, "editorMode": "code"}


def rank_colour_mappings() -> list[dict]:
    """Colour a '... 11th of 16' string by rank: 1-5 green, 12-16 red, otherwise amber."""
    return [
        {"type": "regex", "options": {"pattern": r".*\b([1-5])(st|nd|rd|th) of 16.*",
                                      "result": {"color": GREEN, "index": 0}}},
        {"type": "regex", "options": {"pattern": r".*\b(1[2-6])th of 16.*",
                                      "result": {"color": RED, "index": 1}}},
    ]


def stat(title: str, sql: str, x: int, y: int, w: int = 4, h: int = 4,
         description: str = "", ranked: bool = True) -> dict:
    return {
        "type": "stat", "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql)],
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False},
                    "textMode": "value", "colorMode": "background", "graphMode": "none",
                    "justifyMode": "center", "wideLayout": True},
        "fieldConfig": {"defaults": {
            "color": {"mode": "fixed", "fixedColor": AMBER if ranked else BLUE},
            "mappings": rank_colour_mappings() if ranked else []},
            "overrides": []},
    }


def headline(metric: str) -> str:
    return (f"SELECT value || '  ·  ' || rank_label AS v FROM cricket.team_ranks "
            f"WHERE team = '{TEAM}' AND metric = '{metric}' AND season = '{SEASON}'")


def phase_headline(side: str, phase: str, col: str, rank_col: str) -> str:
    return (f"SELECT {col} || '  ·  ' || cricket.ordinal({rank_col}) || ' of 16' AS v "
            f"FROM cricket.team_phase WHERE team = '{TEAM}' AND side = '{side}' AND phase = '{phase}' AND season = '{SEASON}'")


def phase_bars(title: str, side: str, col: str, x: int, y: int, unit_label: str, description: str) -> dict:
    sql = f"""
SELECT initcap(p.phase) || CASE p.phase WHEN 'powerplay' THEN ' (1-6)' WHEN 'middle' THEN ' (7-15)' ELSE ' (16-20)' END AS phase,
       p.{col} AS "{TEAM}",
       round(avg(q.{col}) FILTER (WHERE s.top4), 2) AS "Semi-finalists",
       round(avg(q.{col}), 2) AS "League average"
FROM cricket.team_phase p
JOIN cricket.team_phase q ON q.season = p.season AND q.side = p.side AND q.phase = p.phase
JOIN cricket.team_summary s ON s.season = q.season AND s.team = q.team
WHERE p.team = '{TEAM}' AND p.side = '{side}' AND p.season = '{SEASON}'
GROUP BY p.phase, p.phase_order, p.{col}
ORDER BY p.phase_order"""
    return {
        "type": "barchart", "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": 8, "h": 9},
        "targets": [target(sql)],
        "options": {"xField": "phase", "orientation": "vertical", "showValue": "always",
                    "groupWidth": 0.8, "barWidth": 0.9, "stacking": "none", "text": {"valueSize": 12},
                    "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"decimals": 2, "min": 0, "custom": {"fillOpacity": 85, "axisLabel": unit_label}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": TEAM},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}}]},
                            {"matcher": {"id": "byName", "options": "Semi-finalists"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREEN}}]},
                            {"matcher": {"id": "byName", "options": "League average"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREY}}]}]},
    }


INSIGHTS_MD = """
### What the season says

**1. Bowling is already semi-final standard.**
Economy 7.36 vs 7.48 for the 4 semi-finalists, and 8.7 wickets a match (4th of 16).
The middle overs are the best phase: economy 6.73, 4th of 16.

**2. The gap is the bat: about 21 runs an innings.**
We average 133; the semi-finalists average 154.
Run rate 7.12 vs 8.37, and a boundary every 6.9 balls vs 5.2.

**3. The runs go missing in all 3 phases.**
Powerplay 6.43 vs 7.77 · middle 7.24 vs 8.39 · death 7.94 vs 9.44.
We protect wickets early (4th fewest lost) but don't cash them in.

**4. Overs 7-15 are where innings break.**
4.2 wickets lost, 11th of 16 (semi-finalists lose 3.6).

**5. Leaking at both ends with the ball.**
Powerplay and death economy are both 12th of 16.

**6. Continuity.**
We used 26 batters across 9 games (13th of 16); the semi-finalists average 20.

**7. Run-outs:** 0.33 a match, 12th of 16 (semi-finalists 0.78).

<small>Source: CricClubs, NACL Summer 2026 Div A, all 68 matches. Ranks are out of 16 teams.</small>
"""


def build(ds_uid: str) -> dict:
    DS.update({"type": "grafana-postgresql-datasource", "uid": ds_uid})
    panels = []
    y = 0

    # Row 1: headline numbers, coloured by rank.
    panels += [
        stat("League record", f"""
SELECT league_won || ' won · ' || league_lost || ' lost  ·  ' || finish AS v
FROM cricket.team_summary WHERE team = '{TEAM}' AND season = '{SEASON}'""", 0, y, ranked=False,
             description="League games only, plus how far the team went in the knockouts."),
        stat("Net run rate", headline("Net run rate"), 4, y,
             description="Runs per over scored minus runs per over conceded. An all-out side is charged 20 overs."),
        stat("Batting run rate", headline("Run rate"), 8, y,
             description="Runs per over across all innings batted."),
        stat("Bowling economy", headline("Economy"), 12, y,
             description="Runs conceded per over. Rank 1 = lowest."),
        stat("Middle-over wickets lost", phase_headline("batting", "middle", "wickets_per_innings", "wickets_rank"), 16, y,
             description="Average wickets lost in the middle overs per innings. Rank 1 = fewest."),
        stat("Balls per 4 or 6", headline("Balls per boundary"), 20, y,
             description="Legal balls faced per 4 or 6. Rank 1 = most frequent boundaries."),
    ]
    y += 4

    # Row 2: written insights + full rank table vs semi-finalists.
    panels.append({
        "type": "text", "title": "Key insights", "gridPos": {"x": 0, "y": y, "w": 9, "h": 17},
        "options": {"mode": "markdown", "content": INSIGHTS_MD.strip()},
    })
    rank_sql = f"""
SELECT r.category AS "Area", r.metric AS "Metric", r.value AS "{TEAM}", r.rank AS "Rank",
       r.top4_avg AS "Semi-finalists avg",
       r.league_avg AS "League avg", r.best_team || ' (' || r.best_value || ')' AS "Best in Div A"
FROM cricket.team_ranks r
WHERE r.team = '{TEAM}' AND r.season = '{SEASON}'
ORDER BY r.sort_order"""
    panels.append({
        "type": "table", "title": f"Where {TEAM} ranks (out of 16) vs the semi-finalists",
        "description": "Rank 1 = best in Div A for that metric. Green = top 5, red = bottom 5.",
        "datasource": DS, "gridPos": {"x": 9, "y": y, "w": 15, "h": 17},
        "targets": [target(rank_sql)],
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "Rank"},
                             "properties": [
                                 {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                                 {"id": "custom.width", "value": 70}, {"id": "custom.align", "value": "center"},
                                 {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                     {"color": GREEN, "value": None}, {"color": AMBER, "value": 6},
                                     {"color": RED, "value": 12}]}}]},
                            {"matcher": {"id": "byName", "options": "Area"},
                             "properties": [{"id": "custom.width", "value": 75}]},
                            {"matcher": {"id": "byName", "options": "Metric"},
                             "properties": [{"id": "custom.width", "value": 200}]},
                            {"matcher": {"id": "byName", "options": TEAM},
                             "properties": [{"id": "custom.width", "value": 80}]}]},
    })
    y += 17

    # Row 3: phase comparisons.
    panels += [
        phase_bars("Batting run rate by phase", "batting", "run_rate", 0, y, "runs per over",
                   "Runs per over in each phase. Higher is better."),
        phase_bars("Bowling economy by phase", "bowling", "run_rate", 8, y, "runs per over",
                   "Runs conceded per over in each phase. Lower is better."),
        phase_bars("Wickets lost per innings, by phase", "batting", "wickets_per_innings", 16, y, "wickets",
                   "Average wickets lost in each phase. Lower is better."),
    ]
    y += 9

    # Row 4: scoring curve vs semi-finalists, and the quarter-final chase.
    curve_sql = f"""
SELECT b.over_no AS "Over",
       max(b.avg_cum_runs) FILTER (WHERE b.team = '{TEAM}') AS "{TEAM}",
       round(avg(b.avg_cum_runs) FILTER (WHERE s.top4), 1) AS "Semi-finalists",
       max(b.avg_cum_runs) FILTER (WHERE b.team = 'League average') AS "League average"
FROM cricket.over_baseline b
LEFT JOIN cricket.team_summary s ON s.season = b.season AND s.team = b.team
WHERE b.season = '{SEASON}'
GROUP BY b.over_no ORDER BY b.over_no"""
    panels.append({
        "type": "trend", "title": "Average score at the end of each over",
        "description": "Cumulative runs, averaged over every innings that reached that over.",
        "datasource": DS, "gridPos": {"x": 0, "y": y, "w": 12, "h": 10},
        "targets": [target(curve_sql)],
        "options": {"xField": "Over", "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"min": 0, "custom": {"lineWidth": 2, "showPoints": "never", "axisLabel": "runs"}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "Over"},
                             "properties": [{"id": "custom.axisLabel", "value": "over"}, {"id": "min", "value": 1}, {"id": "max", "value": 20}]},
                            {"matcher": {"id": "byName", "options": TEAM},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}},
                                            {"id": "custom.lineWidth", "value": 4}]},
                            {"matcher": {"id": "byName", "options": "Semi-finalists"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREEN}}]},
                            {"matcher": {"id": "byName", "options": "League average"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREY}},
                                            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}]},
    })
    qf_sql = f"""
SELECT over_no AS "Over", run_rate_so_far AS "Our run rate",
       required_rate_at_start_of_over AS "Required rate", cum_wickets AS "Wickets down"
FROM cricket.chase_progress
WHERE team = '{TEAM}' AND stage = 'Quarter Final' AND season = '{SEASON}'
ORDER BY over_no"""
    panels.append({
        "type": "trend", "title": "Quarter-final chase vs Money Heist (target 161): our run rate vs required rate",
        "description": "Like an SLA chart: the required rate is the threshold, our run rate is the measurement. "
                       "Bars show wickets down. Axis capped at 16: the required rate passes it in the last 2 overs.",
        "datasource": DS, "gridPos": {"x": 12, "y": y, "w": 12, "h": 10},
        "targets": [target(qf_sql)],
        "options": {"xField": "Over", "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"max": 16, "min": 0, "custom": {"lineWidth": 2, "showPoints": "auto", "axisLabel": "runs per over"}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "Over"},
                             "properties": [{"id": "custom.axisLabel", "value": "over"}, {"id": "min", "value": 1}, {"id": "max", "value": 20}]},
                            {"matcher": {"id": "byName", "options": "Our run rate"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}},
                                            {"id": "custom.lineWidth", "value": 4}]},
                            {"matcher": {"id": "byName", "options": "Required rate"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": RED}},
                                            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]},
                            {"matcher": {"id": "byName", "options": "Wickets down"},
                             "properties": [{"id": "custom.drawStyle", "value": "bars"},
                                            {"id": "custom.fillOpacity", "value": 40},
                                            {"id": "color", "value": {"mode": "fixed", "fixedColor": GREY}},
                                            {"id": "custom.axisPlacement", "value": "right"},
                                            {"id": "custom.axisLabel", "value": "wickets"},
                                            {"id": "max", "value": 10}]}]},
    })
    y += 10

    # Row 5: season match log.
    log_sql = f"""
SELECT to_char(match_date, 'Dy DD Mon') AS "Date", stage AS "Stage", opponent AS "Opponent", batting_order AS "Innings",
       score_for AS "Our score", score_against AS "Their score", result AS "Result", margin AS "Margin"
FROM cricket.match_log WHERE team = '{TEAM}' AND season = '{SEASON}' ORDER BY match_date"""
    panels.append({
        "type": "table", "title": "Season results", "datasource": DS,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 12},
        "targets": [target(log_sql)],
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                        "overrides": [{"matcher": {"id": "byName", "options": "Result"},
                                       "properties": [
                                           {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                           {"id": "mappings", "value": [{"type": "value", "options": {
                                               "Won": {"color": GREEN, "index": 0},
                                               "Lost": {"color": RED, "index": 1}}}]}]}]},
    })

    return {
        "uid": "astros-insights",
        "title": "Astros+ Insights — NACL Summer 2026 Div A",
        "description": "Where Astros+ stand against the semi-finalists and the rest of Div A.",
        "tags": ["cricket", "astros", "nacl"],
        "timezone": "browser", "editable": True, "graphTooltip": 1,
        "time": {"from": "2026-07-01T00:00:00.000Z", "to": "2026-10-10T00:00:00.000Z"},
        "timepicker": {"hidden": True},
        "schemaVersion": 39, "version": 4,
        "panels": [dict(p, id=i + 1) for i, p in enumerate(panels)],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_astros_insights.py <datasource-uid>")
    OUT.write_text(json.dumps(build(sys.argv[1]), indent=2))
    print(f"wrote {OUT}")
