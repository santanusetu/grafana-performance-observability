"""Generate the Astros+ Spring vs Summer 2026 comparison dashboard (dashboards as code).

Usage:
    python dashboards/build_season_compare.py <datasource-uid>
Writes dashboards/season-compare.json.

Raw numbers move with opponents, grounds and conditions, so the comparison leans on
RELATIVE measures: rank out of the division, and the gap to the league average and
to the top 4 of the same season.
"""
import json
import sys
from pathlib import Path

from build_astros_insights import BLUE, GREEN, GREY, RED, AMBER, DS, target, stat

TEAM = "Astros+"
OLD, NEW = "Spring 2026", "Summer 2026"
OUT = Path(__file__).resolve().parent / "season-compare.json"
INSIGHTS_MD = Path(__file__).resolve().parent / "season-compare-insights.md"
PURPLE = "#a371f7"


def colour(name: str, hex_: str) -> dict:
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": hex_}}]}


def tile(title: str, sql: str, x: int, y: int, description: str) -> dict:
    p = stat(title, sql, x, y, w=6, h=4, description=description, ranked=False)
    p["options"]["colorMode"] = "none"
    p["options"]["textMode"] = "value"
    return p


def rank_shift(metric: str) -> str:
    return f"""
SELECT o.rank_label || '  →  ' || n.rank_label AS v
FROM cricket.team_ranks o JOIN cricket.team_ranks n USING (team, metric)
WHERE team = '{TEAM}' AND metric = '{metric}' AND o.season = '{OLD}' AND n.season = '{NEW}'"""


def phase_compare(title: str, side: str, col: str, x: int, y: int, unit: str, description: str) -> dict:
    sql = f"""
SELECT initcap(p.phase) AS phase,
       max(p.{col}) FILTER (WHERE p.season = '{OLD}' AND p.team = '{TEAM}') AS "{TEAM} {OLD.split()[0]}",
       max(p.{col}) FILTER (WHERE p.season = '{NEW}' AND p.team = '{TEAM}') AS "{TEAM} {NEW.split()[0]}",
       round(avg(p.{col}) FILTER (WHERE p.season = '{NEW}' AND s.top4), 2)  AS "Top 4, {NEW.split()[0]}"
FROM cricket.team_phase p
JOIN cricket.team_summary s ON s.season = p.season AND s.team = p.team
WHERE p.side = '{side}'
GROUP BY p.phase, p.phase_order ORDER BY p.phase_order"""
    return {
        "type": "barchart", "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": 8, "h": 9},
        "targets": [target(sql)],
        "options": {"xField": "phase", "orientation": "vertical", "showValue": "always",
                    "groupWidth": 0.8, "barWidth": 0.9, "stacking": "none", "text": {"valueSize": 12},
                    "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"decimals": 2, "min": 0, "custom": {"fillOpacity": 85, "axisLabel": unit}},
                        "overrides": [colour(f"{TEAM} {OLD.split()[0]}", PURPLE),
                                      colour(f"{TEAM} {NEW.split()[0]}", BLUE),
                                      colour(f"Top 4, {NEW.split()[0]}", GREEN)]},
    }


def build(ds_uid: str) -> dict:
    DS.update({"type": "grafana-postgresql-datasource", "uid": ds_uid})
    panels = []
    y = 0

    panels += [
        tile("Finish", f"""
SELECT max(finish) FILTER (WHERE season = '{OLD}') || '  →  ' || max(finish) FILTER (WHERE season = '{NEW}') AS v
FROM cricket.team_summary WHERE team = '{TEAM}'""", 0, y, f"How far {TEAM} went: {OLD} → {NEW}."),
        tile("Division run rate (conditions)", f"""
SELECT max(league_avg) FILTER (WHERE season = '{OLD}') || '  →  ' || max(league_avg) FILTER (WHERE season = '{NEW}') AS v
FROM cricket.team_ranks WHERE metric = 'Run rate'""", 6, y,
             "Average run rate across the whole division each season. Scoring rose sharply in Summer, "
             "so raw numbers are not comparable; ranks are."),
        tile("Batting run rate rank", rank_shift("Run rate"), 12, y, f"Rank out of the division, {OLD} → {NEW}."),
        tile("Bowling economy rank", rank_shift("Economy"), 18, y, f"Rank out of the division, {OLD} → {NEW}. Rank 1 = lowest."),
    ]
    y += 4

    panels.append({
        "type": "text", "title": "What changed", "gridPos": {"x": 0, "y": y, "w": 9, "h": 18},
        "options": {"mode": "markdown", "content": INSIGHTS_MD.read_text().strip()},
    })
    shift_sql = f"""
SELECT o.category AS "Area", o.metric AS "Metric",
       o.value AS "{OLD.split()[0]}", o.rank AS "{OLD.split()[0]} rank",
       n.value AS "{NEW.split()[0]}", n.rank AS "{NEW.split()[0]} rank",
       o.rank - n.rank AS "Places moved",
       n.top4_avg AS "Top 4 avg, {NEW.split()[0]}"
FROM cricket.team_ranks o JOIN cricket.team_ranks n USING (team, metric)
WHERE team = '{TEAM}' AND o.season = '{OLD}' AND n.season = '{NEW}'
ORDER BY o.sort_order"""
    rank_colours = {"mode": "absolute", "steps": [{"color": GREEN, "value": None}, {"color": AMBER, "value": 6},
                                                  {"color": RED, "value": 12}]}
    panels.append({
        "type": "table", "title": f"{TEAM} rank by metric: {OLD} vs {NEW}",
        "description": "Rank out of the division in each season (1 = best). 'Places moved' is positive when the rank improved.",
        "datasource": DS, "gridPos": {"x": 9, "y": y, "w": 15, "h": 18},
        "targets": [target(shift_sql)],
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                        "overrides": [
                            *[{"matcher": {"id": "byName", "options": f"{s.split()[0]} rank"},
                               "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                                              {"id": "custom.align", "value": "center"}, {"id": "custom.width", "value": 95},
                                              {"id": "thresholds", "value": rank_colours}]} for s in (OLD, NEW)],
                            {"matcher": {"id": "byName", "options": "Places moved"},
                             "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                            {"id": "custom.align", "value": "center"},
                                            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                                {"color": RED, "value": None}, {"color": GREY, "value": 0},
                                                {"color": GREEN, "value": 1}]}}]},
                            {"matcher": {"id": "byName", "options": "Area"}, "properties": [{"id": "custom.width", "value": 75}]},
                            {"matcher": {"id": "byName", "options": "Metric"}, "properties": [{"id": "custom.width", "value": 200}]}]},
    })
    y += 18

    panels += [
        phase_compare("Batting run rate by phase", "batting", "run_rate", 0, y, "runs per over", "Higher is better."),
        phase_compare("Bowling economy by phase", "bowling", "run_rate", 8, y, "runs per over", "Lower is better."),
        phase_compare("Wickets lost per innings, by phase", "batting", "wickets_per_innings", 16, y, "wickets",
                      "Lower is better."),
    ]
    y += 9

    curve_sql = f"""
SELECT over_no AS "Over",
       max(avg_cum_runs) FILTER (WHERE season = '{OLD}' AND team = '{TEAM}') AS "{TEAM} {OLD.split()[0]}",
       max(avg_cum_runs) FILTER (WHERE season = '{NEW}' AND team = '{TEAM}') AS "{TEAM} {NEW.split()[0]}",
       max(avg_cum_runs) FILTER (WHERE season = '{OLD}' AND team = 'League average') AS "League avg {OLD.split()[0]}",
       max(avg_cum_runs) FILTER (WHERE season = '{NEW}' AND team = 'League average') AS "League avg {NEW.split()[0]}"
FROM cricket.over_baseline GROUP BY over_no ORDER BY over_no"""
    panels.append({
        "type": "trend", "title": "Average score at the end of each over",
        "description": "Cumulative runs, averaged over every innings that reached that over. Dashed lines = division average.",
        "datasource": DS, "gridPos": {"x": 0, "y": y, "w": 12, "h": 10},
        "targets": [target(curve_sql)],
        "options": {"xField": "Over", "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"min": 0, "custom": {"lineWidth": 3, "showPoints": "never", "axisLabel": "runs"}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "Over"},
                             "properties": [{"id": "custom.axisLabel", "value": "over"}, {"id": "min", "value": 1},
                                            {"id": "max", "value": 20}]},
                            colour(f"{TEAM} {OLD.split()[0]}", PURPLE), colour(f"{TEAM} {NEW.split()[0]}", BLUE),
                            *[{"matcher": {"id": "byName", "options": f"League avg {s.split()[0]}"},
                               "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}},
                                              {"id": "custom.lineWidth", "value": 1},
                                              {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 8]}}]}
                              for s, c in ((OLD, PURPLE), (NEW, BLUE))]]},
    })
    log_sql = f"""
SELECT to_char(match_date, 'DD Mon') AS "Date", stage AS "Stage", opponent AS "Opponent",
       score_for AS "Our score", score_against AS "Their score", result AS "Result", margin AS "Margin"
FROM cricket.match_log WHERE team = '{TEAM}' AND season = '{OLD}' ORDER BY match_date"""
    panels.append({
        "type": "table", "title": f"{OLD} results", "datasource": DS,
        "gridPos": {"x": 12, "y": y, "w": 12, "h": 10},
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
        "uid": "astros-season-compare",
        "title": f"Astros+ — {OLD} vs {NEW} (Div A)",
        "description": f"How {TEAM} changed from {OLD} to {NEW}, measured against the division each season.",
        "tags": ["cricket", "astros", "nacl"],
        "timezone": "browser", "editable": True, "graphTooltip": 1,
        "time": {"from": "2026-03-01T00:00:00.000Z", "to": "2026-10-10T00:00:00.000Z"},
        "timepicker": {"hidden": True},
        "schemaVersion": 39, "version": 1,
        "links": [{"title": f"{NEW} insights", "type": "link", "url": "/d/astros-insights", "icon": "dashboard"}],
        "panels": [dict(p, id=i + 1) for i, p in enumerate(panels)],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_season_compare.py <datasource-uid>")
    OUT.write_text(json.dumps(build(sys.argv[1]), indent=2))
    print(f"wrote {OUT}")
