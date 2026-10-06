"""Generate the Astros+ performance-analyst dashboard (dashboards as code).

Usage:
    python dashboards/build_story.py <datasource-uid>
Writes dashboards/astros-story.json.

Written the way a team performance analyst presents: verdict first, then the evidence,
then what to fix. Every panel title states its finding. One comparison group throughout:
the semi-finalists ("what the teams that went further do"). Supporting detail sits in
collapsed rows at the bottom. Keeps the uid of the original dashboard so the public
link keeps working.
"""
import json
import sys
from pathlib import Path

import build_astros_insights as summer
import build_season_compare as compare
import build_unified as unified
from build_astros_insights import BLUE, GREEN, GREY, RED, AMBER, DS, target

TEAM, SEASON, OLD = "Astros+", "Summer 2026", "Spring 2026"
OUT = Path(__file__).resolve().parent / "astros-story.json"
DARK_GREEN = "#2ea043"


def text(title, md, x, y, w, h):
    return {"type": "text", "title": title, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": md.strip()}}


def kpi(title, sql, x, y, colour, description):
    return {"type": "stat", "title": title, "description": description, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": 6, "h": 4}, "targets": [target(sql)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False},
                        "textMode": "value", "colorMode": "background", "graphMode": "none",
                        "justifyMode": "center", "wideLayout": True},
            "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": colour}}, "overrides": []}}


def section(title, y):
    return {"type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def colour(name, c):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}


def bars(title, sql, x, y, w, h, x_field, description, overrides=(), horizontal=False,
         by_sign=False, unit=None, decimals=1):
    defaults = {"decimals": decimals, "custom": {"fillOpacity": 85}}
    if unit:
        defaults["unit"] = unit
    if by_sign:   # one series: green when positive (better), red when negative (worse)
        defaults["color"] = {"mode": "thresholds"}
        defaults["thresholds"] = {"mode": "absolute", "steps": [{"color": RED, "value": None},
                                                                 {"color": GREEN, "value": 0}]}
    return {"type": "barchart", "title": title, "description": description, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": [target(sql)],
            "options": {"xField": x_field, "orientation": "horizontal" if horizontal else "vertical",
                        "showValue": "always", "stacking": "none", "groupWidth": 0.75, "barWidth": 0.9,
                        "text": {"valueSize": 12}, "xTickLabelRotation": 0,
                        "legend": {"showLegend": not by_sign, "displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "multi"}},
            "fieldConfig": {"defaults": defaults, "overrides": list(overrides)}}


def semis_vs_us(col, side):
    return f"""
SELECT initcap(p.phase) || CASE p.phase WHEN 'powerplay' THEN ' (1-6)' WHEN 'middle' THEN ' (7-15)' ELSE ' (16-20)' END AS phase,
       p.{col} AS "{TEAM}",
       round(avg(q.{col}) FILTER (WHERE s.top4), 2) AS "Semi-finalists"
FROM cricket.team_phase p
JOIN cricket.team_phase q ON q.season = p.season AND q.side = p.side AND q.phase = p.phase
JOIN cricket.team_summary s ON s.season = q.season AND s.team = q.team
WHERE p.team = '{TEAM}' AND p.side = '{side}' AND p.season = '{SEASON}'
GROUP BY p.phase, p.phase_order, p.{col} ORDER BY p.phase_order"""


VERDICT = """
## Our bowling is semi-final standard. We lose when the batting falls apart between overs 7 and 15.

In our **4 Summer losses** we were **84 for 7 after 15 overs**; in our **5 wins**, **112 for 5**. Every loss included a batting collapse (3+ wickets in 3 overs).
Meanwhile the whole division learned to score faster between Spring and Summer (run rate **+28%**). **Our batting stayed where it was (−1%).**
"""

WHAT_TO_FIX = """
### Possible checkpoints

| Checkpoint | In our wins | In our losses | **Where we want to be** |
|---|---|---|---|
| Score after 6 overs | 44 for 1 | 32 for 2 | **45+ with 1 down or fewer** |
| Wickets down after 15 overs | 5 | 7 | **5 or fewer** — the single biggest difference |
| Total batting first | 158 average | 102 average | **160+** (Div A teams that won batting first scored a median of 172) |

**And keep doing:** bowl the middle overs the way we do (economy 6.73, better than the semi-finalists' 7.33), and take wickets (8.7 a match, 4th of 16).
"""

BETTER_WORSE_MD = """
**Methodology.** Each bar shows Astros+ performance relative to the Division A average, expressed as a percentage. Values are normalised so that a positive figure (green) always indicates above-average performance and a negative figure (red) indicates below-average performance.

**Areas of strength**
- **Bowling effectiveness:** wicket-taking (+8%) and dot-ball percentage (+3%) both exceed the division average.
- **Discipline in the field:** catching (+6%) and control of wides (+5%) are above average.

**Areas for improvement**
- **Squad continuity:** 26 batters were used during the season, against a division average of 21.
- **Run-outs effected:** 0.33 per match, against a division average of 0.61.
- **Batting tempo:** boundary frequency is below average and dot-ball percentage is above average. Six-hitting is the one exception, marginally above average.

**Summary.** Astros+ currently perform in line with an average Division A side. The semi-finalists are differentiated from the division primarily by their batting.
"""

ADAPT_MD = """
**Methodology.** Each pair of bars shows the percentage change in a measure between the Spring and Summer seasons, for the division as a whole (grey) and for Astros+ (blue).

**Division-wide trend**
- Boundary frequency increased by 65% and six-hitting by 61%.
- Scoring rates rose in every phase of the innings, with an overall increase of 28%.

**Astros+ response**
- Run rate and boundary frequency remained broadly unchanged.
- Dot-ball percentage increased by 6%, while the division recorded a 6% reduction.
- Scoring in the death overs declined by 17%.

**Bowling.** Astros+ adapted more effectively than the division with the ball: runs conceded per over rose by 10%, compared with 28% across the division. This underpins the improvement in the economy ranking from 15th to 8th.
"""


def build(ds_uid: str) -> dict:
    DS.update({"type": "grafana-postgresql-datasource", "uid": ds_uid})
    P, y = [], 0

    # Verdict + 4 headline numbers
    P += [
        kpi("Bowling: level with the semi-finalists", f"""
SELECT 'Economy ' || value || '  vs  ' || top4_avg FROM cricket.team_ranks
WHERE team = '{TEAM}' AND season = '{SEASON}' AND metric = 'Economy'""", 0, y, DARK_GREEN,
            "Runs conceded per over: ours vs the average of the 4 semi-finalists."),
        kpi("Batting: well behind others", f"""
SELECT 'Run rate ' || value || '  vs  ' || top4_avg FROM cricket.team_ranks
WHERE team = '{TEAM}' AND season = '{SEASON}' AND metric = 'Run rate'""", 6, y, RED,
            "Runs scored per over: ours vs the average of the 4 semi-finalists."),
        kpi("Losses that included a batting collapse", f"""
SELECT count(c.match_id) || ' of ' || count(*) FROM cricket.match_log l
LEFT JOIN cricket.collapses c ON c.match_id = l.match_id AND c.team = l.team
WHERE l.team = '{TEAM}' AND l.season = '{SEASON}' AND l.result = 'Lost'""", 12, y, RED,
            "Collapse = 3 or more wickets inside 3 overs, before the last 3 overs."),
        kpi("Score that wins batting first", f"""
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY runs)::int || '  ·  we average ' ||
       (SELECT round(avg_score)::int FROM cricket.team_summary WHERE team = '{TEAM}' AND season = '{SEASON}')
FROM cricket.team_innings WHERE season = '{SEASON}' AND batted_first AND won""", 18, y, BLUE,
            "Median first-innings score of Div A teams that batted first and won, vs our average score."),
    ]
    y += 4

    # 1. Wins vs losses
    P.append(section("1 · The game is decided by over 15", y)); y += 1
    worm = f"""
SELECT o.over_no AS "Over",
       round(avg(o.cum_runs) FILTER (WHERE o.team = '{TEAM}' AND o.result = 'Won'), 1)  AS "Our wins",
       round(avg(o.cum_runs) FILTER (WHERE o.team = '{TEAM}' AND o.result = 'Lost'), 1) AS "Our losses",
       round(avg(o.cum_runs) FILTER (WHERE s.top4), 1)                                  AS "Semi-finalists (all games)"
FROM cricket.innings_overs o
JOIN cricket.team_summary s ON s.season = o.season AND s.team = o.team
WHERE o.season = '{SEASON}'
GROUP BY o.over_no ORDER BY o.over_no"""
    P.append({
        "type": "trend", "title": "Our score, over by over: wins vs losses",
        "description": "Average score at the end of each over. The lines split after the powerplay and are "
                       "28 runs apart by over 15.",
        "datasource": DS, "gridPos": {"x": 0, "y": y, "w": 15, "h": 10}, "targets": [target(worm)],
        "options": {"xField": "Over", "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "fieldConfig": {"defaults": {"min": 0, "custom": {"lineWidth": 3, "showPoints": "never", "axisLabel": "runs"}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "Over"},
                             "properties": [{"id": "custom.axisLabel", "value": "over"},
                                            {"id": "min", "value": 1}, {"id": "max", "value": 20}]},
                            colour("Our wins", GREEN), colour("Our losses", RED),
                            {"matcher": {"id": "byName", "options": "Semi-finalists (all games)"},
                             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREY}},
                                            {"id": "custom.lineWidth", "value": 1},
                                            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 8]}}]}]},
    })
    checkpoints = f"""
WITH g AS (
    SELECT result, match_id,
           max(cum_runs) FILTER (WHERE over_no = 6)  AS r6,  max(cum_wickets) FILTER (WHERE over_no = 6)  AS w6,
           max(cum_runs) FILTER (WHERE over_no = 15) AS r15, max(cum_wickets) FILTER (WHERE over_no = 15) AS w15,
           max(final_runs) AS fr, max(dots_faced) * 100.0 / max(legal_balls) AS dots
    FROM cricket.innings_overs WHERE team = '{TEAM}' AND season = '{SEASON}' GROUP BY result, match_id
)
SELECT 'After 6 overs' AS "Checkpoint",
       round(avg(r6) FILTER (WHERE result = 'Won')) || ' for ' || round(avg(w6) FILTER (WHERE result = 'Won')) AS "Our wins",
       round(avg(r6) FILTER (WHERE result = 'Lost')) || ' for ' || round(avg(w6) FILTER (WHERE result = 'Lost')) AS "Our losses", 1 AS o FROM g
UNION ALL
SELECT 'After 15 overs',
       round(avg(r15) FILTER (WHERE result = 'Won')) || ' for ' || round(avg(w15) FILTER (WHERE result = 'Won')),
       round(avg(r15) FILTER (WHERE result = 'Lost')) || ' for ' || round(avg(w15) FILTER (WHERE result = 'Lost')), 2 FROM g
UNION ALL
SELECT 'Final score', round(avg(fr) FILTER (WHERE result = 'Won'))::text, round(avg(fr) FILTER (WHERE result = 'Lost'))::text, 3 FROM g
UNION ALL
SELECT 'Dot balls faced', round(avg(dots) FILTER (WHERE result = 'Won')) || '%', round(avg(dots) FILTER (WHERE result = 'Lost')) || '%', 4 FROM g
UNION ALL
SELECT 'Games', count(*) FILTER (WHERE result = 'Won')::text, count(*) FILTER (WHERE result = 'Lost')::text, 5 FROM g
ORDER BY o"""
    P.append({
        "type": "table", "title": "Checkpoints: wins vs losses (Summer)", "datasource": DS,
        "gridPos": {"x": 15, "y": y, "w": 9, "h": 10}, "targets": [target(checkpoints)],
        "options": {"showHeader": True, "cellHeight": "md", "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"align": "center", "cellOptions": {"type": "auto"}}},
                        "overrides": [
                            {"matcher": {"id": "byName", "options": "o"}, "properties": [{"id": "custom.hidden", "value": True}]},
                            {"matcher": {"id": "byName", "options": "Checkpoint"}, "properties": [{"id": "custom.align", "value": "left"}]},
                            {"matcher": {"id": "byName", "options": "Our wins"},
                             "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                            {"id": "color", "value": {"mode": "fixed", "fixedColor": GREEN}}]},
                            {"matcher": {"id": "byName", "options": "Our losses"},
                             "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                            {"id": "color", "value": {"mode": "fixed", "fixedColor": RED}}]}]},
    })
    y += 10

    # 2. Where the runs go missing
    P.append(section("2 · Where we lose ground to the semi-finalists", y)); y += 1
    gap_sql = f"""
SELECT initcap(p.phase) || CASE p.phase WHEN 'powerplay' THEN ' (6 overs)' WHEN 'middle' THEN ' (9 overs)' ELSE ' (5 overs)' END AS phase,
       round((p.run_rate - avg(q.run_rate) FILTER (WHERE s.top4))
             * CASE p.phase WHEN 'powerplay' THEN 6 WHEN 'middle' THEN 9 ELSE 5 END, 1) AS "Runs vs semi-finalists"
FROM cricket.team_phase p
JOIN cricket.team_phase q ON q.season = p.season AND q.side = p.side AND q.phase = p.phase
JOIN cricket.team_summary s ON s.season = q.season AND s.team = q.team
WHERE p.team = '{TEAM}' AND p.side = 'batting' AND p.season = '{SEASON}'
GROUP BY p.phase, p.phase_order, p.run_rate ORDER BY p.phase_order"""
    P += [
        bars("Batting: runs short of the semi-finalists, per innings", gap_sql, 0, y, 8, 9, "phase",
             "Our run rate minus the semi-finalists' in each phase, times the overs in that phase. "
             "About 26 runs over a full innings.", by_sign=True),
        bars("Batting: wickets lost per innings, by phase", semis_vs_us("wickets_per_innings", "batting"), 8, y, 8, 9,
             "phase", "Lower is better. The middle overs are where we lose wickets faster than the semi-finalists.",
             overrides=[colour(TEAM, BLUE), colour("Semi-finalists", GREEN)], decimals=2),
        bars("Bowling: runs conceded per over, by phase", semis_vs_us("run_rate", "bowling"), 16, y, 8, 9, "phase",
             "Lower is better. Our middle overs are tighter than the semi-finalists'; the powerplay is where we leak.",
             overrides=[colour(TEAM, BLUE), colour("Semi-finalists", GREEN)], decimals=2),
    ]
    y += 9

    # 3. Us vs the division
    P.append(section("3 · Us vs the rest of Div A: where we are better, where we are worse", y)); y += 1
    bw_sql = f"""
SELECT metric AS "Metric",
       round(100.0 * CASE WHEN higher_is_better THEN 1 ELSE -1 END * (value - league_avg) / abs(league_avg), 1)
           AS "Better (+) or worse (−) than the division average"
FROM cricket.team_ranks
WHERE team = '{TEAM}' AND season = '{SEASON}' AND metric NOT IN ('Net run rate', 'Average score')
ORDER BY 2 DESC"""
    P += [
        bars("Summer 2026: how we compare with the division average", bw_sql, 0, y, 14, 14, "Metric",
             "Percentage difference from the Div A average for each measure, flipped so that positive always "
             "means better for us (e.g. fewer dot balls faced counts as positive).",
             horizontal=True, by_sign=True, unit="percent"),
        text("Analysis: performance relative to the division", BETTER_WORSE_MD, 14, y, 10, 14),
    ]
    y += 14

    # 4. League shift and our adaptation
    P.append(section("4 · The league changed between Spring and Summer. Did we?", y)); y += 1
    shift_sql = f"""
WITH r AS (
    SELECT metric AS m, sort_order AS o,
           max(league_avg) FILTER (WHERE season = '{OLD}') AS l0, max(league_avg) FILTER (WHERE season = '{SEASON}') AS l1,
           max(value) FILTER (WHERE season = '{OLD}' AND team = '{TEAM}') AS u0,
           max(value) FILTER (WHERE season = '{SEASON}' AND team = '{TEAM}') AS u1
    FROM cricket.team_ranks
    WHERE metric IN ('Run rate', 'Sixes per innings', 'Dot balls faced %', 'Economy')
    GROUP BY metric, sort_order
    UNION ALL
    SELECT 'Boundaries per over', 3,
           6.0 / max(league_avg) FILTER (WHERE season = '{OLD}'), 6.0 / max(league_avg) FILTER (WHERE season = '{SEASON}'),
           6.0 / max(value) FILTER (WHERE season = '{OLD}' AND team = '{TEAM}'),
           6.0 / max(value) FILTER (WHERE season = '{SEASON}' AND team = '{TEAM}')
    FROM cricket.team_ranks WHERE metric = 'Balls per boundary'
    UNION ALL
    SELECT 'Run rate, ' || phase, 20 + phase_order,
           max(league_avg_run_rate) FILTER (WHERE season = '{OLD}'), max(league_avg_run_rate) FILTER (WHERE season = '{SEASON}'),
           max(run_rate) FILTER (WHERE season = '{OLD}' AND team = '{TEAM}'),
           max(run_rate) FILTER (WHERE season = '{SEASON}' AND team = '{TEAM}')
    FROM cricket.team_phase WHERE side = 'batting' GROUP BY phase, phase_order
)
SELECT replace(replace(m, 'Economy', 'Runs conceded per over (bowling)'), 'Run rate', 'Run rate') AS "Measure",
       round(100 * (l1 - l0) / l0) AS "Division",
       round(100 * (u1 - u0) / u0) AS "{TEAM}"
FROM r ORDER BY o"""
    P += [
        bars("Change from Spring to Summer, %", shift_sql, 0, y, 14, 12, "Measure",
             "How much each measure moved between the two seasons, for the whole division and for us.",
             overrides=[colour("Division", GREY), colour(TEAM, BLUE)], horizontal=True, unit="percent", decimals=0),
        text("Analysis: change between seasons", ADAPT_MD, 14, y, 10, 12),
    ]
    y += 12

    # 5. What to fix
    P.append(section("5 · What to fix", y)); y += 1
    P.append(text("Possible checkpoints for future games", WHAT_TO_FIX, 0, y, 24, 8)); y += 8
    P.append(text("Insights", VERDICT, 0, y, 24, 5)); y += 5

    # Detail, collapsed
    s_panels = summer.build(ds_uid)["panels"]
    c_panels = compare.build(ds_uid)["panels"]
    incidents, _ = unified.incident_panels(0)
    detail = [
        ("Detail · results, both seasons",
         [p for p in s_panels if p["title"] == "Season results"] + [p for p in c_panels if p["title"].endswith("results")]),
        ("Detail · batting collapse log", incidents[:1]),
        ("Detail · full rank table, Summer 2026 vs the semi-finalists", [p for p in s_panels if p["type"] == "table"][:1]),
        ("Detail · rank changes, Spring vs Summer", [p for p in c_panels if p["type"] == "table"][:1]),
    ]
    expanded = {"Detail · full rank table, Summer 2026 vs the semi-finalists",
                "Detail · rank changes, Spring vs Summer"}
    for title, block in detail:
        r = section(title, y)
        inner, bottom = unified.place(block, y + 1)
        x = 0
        for p in inner:                     # lay detail panels side by side at full or half width
            p["gridPos"]["x"] = x if len(inner) > 1 else 0
            p["gridPos"]["w"] = 12 if len(inner) > 1 else 24
            x += 12
        if title.startswith("Detail · full rank table"):
            for p in inner:
                p["gridPos"]["h"] = 19
            bottom = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in inner)
        if title in expanded:               # open by default: panels sit at top level, after the row
            P.append(r)
            P += inner
            y = bottom
        else:                               # collapsed: panels live inside the row
            r["collapsed"] = True
            r["panels"] = inner
            P.append(r)
            y += 1

    # ids: top-level panels and panels nested in collapsed rows must all be unique
    n = 0
    for p in P:
        n += 1
        p["id"] = n
        for q in p.get("panels", []):
            n += 1
            q["id"] = n

    return {
        "uid": "astros-insights",
        "title": "Astros+ 2026 — Signals: Strengths and Opportunities",
        "description": "Performance analysis of Astros+ in NACL Div A, Spring and Summer 2026.",
        "tags": ["cricket", "astros", "nacl", "performance-analysis"],
        "timezone": "browser", "editable": True, "graphTooltip": 1,
        "time": {"from": "2026-03-01T00:00:00.000Z", "to": "2026-10-10T00:00:00.000Z"},
        "timepicker": {"hidden": True},
        "schemaVersion": 39, "version": 31,
        "panels": P,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_story.py <datasource-uid>")
    OUT.write_text(json.dumps(build(sys.argv[1]), indent=2))
    print(f"wrote {OUT}")
