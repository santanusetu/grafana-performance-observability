"""Generate the unified Astros+ performance dashboard (dashboards as code).

Usage:
    python dashboards/build_unified.py <datasource-uid>
Writes dashboards/astros-unified.json.

Laid out like a service-observability dashboard:
  Health -> Timeline & targets -> Incidents -> Diagnosis (Summer) -> Trend (Spring vs Summer)
It reuses the panels of the two single-purpose builders and adds the timeline,
target (SLO-style) and incident panels. It keeps the uid of the original Summer
dashboard, so its existing public link keeps working.
"""
import json
import sys
from pathlib import Path

import build_astros_insights as summer
import build_season_compare as compare
from build_astros_insights import BLUE, GREEN, GREY, RED, AMBER, DS, target, stat

TEAM = "Astros+"
OUT = Path(__file__).resolve().parent / "astros-unified.json"


def row(title: str, y: int) -> dict:
    return {"type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def place(panels: list[dict], y0: int) -> tuple[list[dict], int]:
    """Shift a block of panels so its top sits at y0; return the panels and the next free y."""
    top = min(p["gridPos"]["y"] for p in panels)
    out = []
    for p in panels:
        q = json.loads(json.dumps(p))
        q["gridPos"]["y"] = q["gridPos"]["y"] - top + y0
        q.pop("id", None)
        out.append(q)
    bottom = max(q["gridPos"]["y"] + q["gridPos"]["h"] for q in out)
    return out, bottom


def target_stat(title: str, sql: str, x: int, y: int, w: int, h: int, description: str) -> dict:
    p = stat(title, sql, x, y, w=w, h=h, description=description, ranked=False)
    p["options"]["colorMode"] = "none"
    return p


def timeline_panels(y: int) -> tuple[list[dict], int]:
    rr_sql = f"""
SELECT "time" + interval '12 hours' AS "time",
       run_rate_scored   AS "Runs per over scored",
       run_rate_conceded AS "Runs per over conceded",
       division_run_rate AS "Division average"
FROM cricket.innings_timeline WHERE team = '{TEAM}' ORDER BY 1"""
    w15_sql = f"""
SELECT t."time" + interval '12 hours' AS "time",
       t.wickets_by_over_15 AS "Wickets down by over 15",
       d.avg_w15 AS "Division average"
FROM cricket.innings_timeline t
JOIN (SELECT season, round(avg(wickets_by_over_15), 2) AS avg_w15
      FROM cricket.innings_timeline GROUP BY season) d USING (season)
WHERE t.team = '{TEAM}' ORDER BY 1"""

    def ts(title, sql, x, w, h, desc, overrides, unit_label):
        return {
            "type": "timeseries", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": [target(sql)],
            "options": {"legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "multi"}},
            "fieldConfig": {"defaults": {"min": 0, "custom": {
                "drawStyle": "line", "lineWidth": 2, "showPoints": "always", "pointSize": 7,
                "spanNulls": True, "axisLabel": unit_label}}, "overrides": overrides},
        }

    def col(name, c, **extra):
        props = [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]
        if extra.get("step"):
            props += [{"id": "custom.lineInterpolation", "value": "stepAfter"},
                      {"id": "custom.showPoints", "value": "never"},
                      {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 8]}}]
        return {"matcher": {"id": "byName", "options": name}, "properties": props}

    panels = [
        ts("Run rate per match, Spring → Summer", rr_sql, 0, 16, 9,
           "Every innings this year. The dashed step is the division's average run rate for that season: "
           "scoring jumped from 5.76 to 7.35 between the seasons.",
           [col("Runs per over scored", BLUE), col("Runs per over conceded", RED),
            col("Division average", GREY, step=True)], "runs per over"),
        target_stat("Target: beat the division run rate", f"""
SELECT max(count_beat) FILTER (WHERE season = 'Spring 2026') || '  →  ' ||
       max(count_beat) FILTER (WHERE season = 'Summer 2026') AS v
FROM (SELECT season, count(*) FILTER (WHERE beat_division_rate) || ' of ' || count(*) || ' innings' AS count_beat
      FROM cricket.innings_timeline WHERE team = '{TEAM}' GROUP BY season) s""",
                    16, y, 8, 4, "Innings where our run rate was at or above that season's division average. "
                                 "Spring → Summer."),
        target_stat("Losses that included a batting collapse", f"""
SELECT max(x) FILTER (WHERE season = 'Spring 2026') || '  →  ' || max(x) FILTER (WHERE season = 'Summer 2026') AS v
FROM (SELECT l.season, count(c.match_id) || ' of ' || count(*) AS x
      FROM cricket.match_log l
      LEFT JOIN cricket.collapses c ON c.match_id = l.match_id AND c.team = l.team
      WHERE l.team = '{TEAM}' AND l.result = 'Lost' GROUP BY l.season) s""",
                    16, y + 4, 8, 5, "Collapse = 3 or more wickets inside 3 overs, before the last 3 overs. "
                                     "Spring → Summer."),
    ]
    y += 9
    panels.append(ts("Wickets down by over 15, per innings", w15_sql, 0, 24, 8,
                     "How many wickets were already gone after 15 overs. Above the dashed line = worse than "
                     "the division average for that season.",
                     [col("Wickets down by over 15", AMBER), col("Division average", GREY, step=True)], "wickets"))
    panels[-1]["fieldConfig"]["defaults"]["max"] = 10
    y += 8
    return panels, y


def incident_panels(y: int) -> tuple[list[dict], int]:
    log_sql = f"""
SELECT to_char(match_date, 'DD Mon') AS "Date", season AS "Season", opponent AS "Opponent",
       overs AS "Overs", wickets_in_window AS "Wickets", score_change AS "Score change",
       final_score AS "Final score", result AS "Result"
FROM cricket.collapses WHERE team = '{TEAM}' ORDER BY match_date DESC"""
    rate_sql = f"""
WITH c AS (SELECT season, team, count(*) AS n FROM cricket.collapses GROUP BY 1, 2),
     i AS (SELECT season, team, count(*) AS inn FROM cricket.team_innings GROUP BY 1, 2)
SELECT i.season AS "Season",
       max(round(coalesce(c.n, 0)::numeric / i.inn, 2)) FILTER (WHERE i.team = '{TEAM}') AS "{TEAM}",
       round(avg(coalesce(c.n, 0)::numeric / i.inn), 2) AS "Division average"
FROM i LEFT JOIN c USING (season, team)
GROUP BY i.season ORDER BY i.season DESC"""
    panels = [
        {"type": "table", "title": "Incident log: batting collapses",
         "description": "3 or more wickets inside any 3-over window, before the last 3 overs (overs 18-20 are "
                        "treated as deliberate slogging). One row per innings: the worst window.",
         "datasource": DS, "gridPos": {"x": 0, "y": y, "w": 16, "h": 11}, "targets": [target(log_sql)],
         "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
         "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                         "overrides": [{"matcher": {"id": "byName", "options": "Result"},
                                        "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                                       {"id": "mappings", "value": [{"type": "value", "options": {
                                                           "Won": {"color": GREEN, "index": 0},
                                                           "Lost": {"color": RED, "index": 1}}}]}]},
                                       {"matcher": {"id": "byName", "options": "Wickets"},
                                        "properties": [{"id": "custom.align", "value": "center"},
                                                       {"id": "custom.width", "value": 75}]}]}},
        {"type": "barchart", "title": "Collapses per innings",
         "description": "How often a collapse happens, against the division average.",
         "datasource": DS, "gridPos": {"x": 16, "y": y, "w": 8, "h": 11}, "targets": [target(rate_sql)],
         "options": {"xField": "Season", "orientation": "vertical", "showValue": "always", "stacking": "none",
                     "groupWidth": 0.7, "barWidth": 0.9, "text": {"valueSize": 12},
                     "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"}},
         "fieldConfig": {"defaults": {"decimals": 2, "min": 0, "custom": {"fillOpacity": 85}},
                         "overrides": [{"matcher": {"id": "byName", "options": TEAM},
                                        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": AMBER}}]},
                                       {"matcher": {"id": "byName", "options": "Division average"},
                                        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREY}}]}]}},
    ]
    return panels, y + 11


def build(ds_uid: str) -> dict:
    s = summer.build(ds_uid)["panels"]
    c = compare.build(ds_uid)["panels"]
    health, diagnosis = s[:6], s[6:]
    panels, y = [], 0

    panels.append(row("Health · Summer 2026 (colour = rank out of 16: green top 5, red bottom 5)", y)); y += 1
    block, y = place(health, y); panels += block

    panels.append(row("Timeline & targets · every innings, Spring and Summer 2026", y)); y += 1
    block, y = timeline_panels(y); panels += block

    panels.append(row("Incidents · batting collapses", y)); y += 1
    block, y = incident_panels(y); panels += block

    panels.append(row("Diagnosis · Summer 2026 vs the semi-finalists", y)); y += 1
    block, y = place(diagnosis, y); panels += block

    panels.append(row("Trend · Spring 2026 vs Summer 2026 (ranks, because scoring conditions changed)", y)); y += 1
    block, y = place(c, y); panels += block

    return {
        "uid": "astros-insights",
        "title": "Astros+ Performance — NACL Div A 2026",
        "description": "Health, timeline, incidents, diagnosis and season trend for Astros+ in NACL Div A.",
        "tags": ["cricket", "astros", "nacl", "observability"],
        "timezone": "browser", "editable": True, "graphTooltip": 1,
        "time": {"from": "2026-03-01T00:00:00.000Z", "to": "2026-10-10T00:00:00.000Z"},
        "timepicker": {"hidden": True},
        "schemaVersion": 39, "version": 10,
        "panels": [dict(p, id=i + 1) for i, p in enumerate(panels)],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_unified.py <datasource-uid>")
    OUT.write_text(json.dumps(build(sys.argv[1]), indent=2))
    print(f"wrote {OUT}")
