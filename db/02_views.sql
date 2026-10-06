-- Astros Analytics: team-level views for Grafana.
-- These are the ONLY objects Grafana's read-only role can see. Player names never
-- leave `raw`: views aggregate to team level, or expose counts only.
-- Views run with the owner's privileges, so grafana_reader needs no access to `raw`.
-- Every view carries a `season` column; ranks and averages are always within a season.

CREATE SCHEMA IF NOT EXISTS cricket;

-- '11' -> '11th' style labels for dashboard text.
CREATE OR REPLACE FUNCTION cricket.ordinal(n bigint) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT n || CASE WHEN n % 100 IN (11, 12, 13) THEN 'th'
                     WHEN n % 10 = 1 THEN 'st' WHEN n % 10 = 2 THEN 'nd' WHEN n % 10 = 3 THEN 'rd'
                     ELSE 'th' END
$$;

DROP VIEW IF EXISTS cricket.innings_overs, cricket.collapses, cricket.innings_timeline, cricket.team_ranks, cricket.team_phase, cricket.team_summary, cricket.team_finish,
    cricket.over_baseline, cricket.chase_progress, cricket.match_log, cricket.team_innings,
    cricket.seasons, cricket.match_season CASCADE;

-- 0. Season of every match. 'Summer 2026 - A' -> 'Summer 2026'.
CREATE VIEW cricket.match_season AS
SELECT m.*, regexp_replace(m.league, '\s*-\s*[A-Z]$', '') AS season
FROM raw.matches m;

CREATE VIEW cricket.seasons AS
SELECT season, min(match_date) AS starts, max(match_date) AS ends, count(*) AS matches,
       rank() OVER (ORDER BY min(match_date)) AS season_order
FROM cricket.match_season GROUP BY season;

-- 1. One row per team per innings batted: the base fact table.
CREATE VIEW cricket.team_innings AS
WITH bat AS (
    SELECT match_id, innings_no,
           sum(fours) AS fours, sum(sixes) AS sixes,
           count(*) FILTER (WHERE runs >= 30) AS scores_30_plus,
           count(*) FILTER (WHERE runs = 0 AND dismissal_type NOT IN ('not_out', 'retired')) AS ducks,
           count(*) FILTER (WHERE dismissal_type = 'caught')  AS out_caught,
           count(*) FILTER (WHERE dismissal_type = 'bowled')  AS out_bowled,
           count(*) FILTER (WHERE dismissal_type = 'run_out') AS out_run_out,
           count(*) FILTER (WHERE dismissal_type = 'stumped') AS out_stumped,
           count(*) FILTER (WHERE dismissal_type = 'lbw')     AS out_lbw,
           sum(runs) AS batter_runs
    FROM raw.batting GROUP BY 1, 2
), bowl AS (
    SELECT match_id, innings_no, sum(dots) AS dots, sum(legal_balls) AS bowled_balls
    FROM raw.bowling GROUP BY 1, 2
)
SELECT m.season,
       m.match_id,
       m.match_date,
       m.match_date::timestamp                      AS "time",       -- Grafana time column
       m.stage,
       i.innings_no,
       i.batting_team                               AS team,
       i.bowling_team                               AS opponent,
       i.innings_no = 1                             AS batted_first,
       m.winner = i.batting_team                    AS won,
       i.runs, i.wickets, i.legal_balls,
       i.wickets = 10                               AS all_out,
       -- Net run rate convention: an all-out side is charged its full 20 overs.
       CASE WHEN i.wickets = 10 THEN 120 ELSE i.legal_balls END AS nrr_balls,
       i.extras_b + i.extras_lb + i.extras_w + i.extras_nb      AS extras,
       i.extras_w AS wides_received, i.extras_nb AS noballs_received,
       b.fours, b.sixes, b.fours * 4 + b.sixes * 6  AS boundary_runs,
       b.batter_runs, b.scores_30_plus, b.ducks,
       b.out_caught, b.out_bowled, b.out_run_out, b.out_stumped, b.out_lbw,
       w.dots                                       AS dots_faced
FROM raw.innings i
JOIN cricket.match_season m USING (match_id)
JOIN bat b USING (match_id, innings_no)
JOIN bowl w USING (match_id, innings_no);

-- 2. Match log: one row per team per match, from that team's point of view.
CREATE VIEW cricket.match_log AS
SELECT f.season, f.match_id, f."time", f.match_date, f.stage, f.team, f.opponent,
       CASE WHEN f.batted_first THEN 'Batted first' ELSE 'Chased' END AS batting_order,
       f.runs || '/' || f.wickets || ' (' || f.legal_balls / 6 || '.' || f.legal_balls % 6 || ')' AS score_for,
       a.runs || '/' || a.wickets || ' (' || a.legal_balls / 6 || '.' || a.legal_balls % 6 || ')' AS score_against,
       CASE WHEN f.won IS NULL THEN 'Tied' WHEN f.won THEN 'Won' ELSE 'Lost' END AS result,
       CASE WHEN m.winner IS NULL THEN 'Tied'
            WHEN m.super_over THEN 'Tied, ' || CASE WHEN f.won THEN 'won' ELSE 'lost' END || ' the Super Over'
            WHEN f.won THEN m.margin_text
            ELSE 'lost ' || replace(m.margin_text, 'won ', '') END AS margin,
       f.runs - a.runs AS run_difference
FROM cricket.team_innings f
JOIN cricket.team_innings a ON a.match_id = f.match_id AND a.team = f.opponent
JOIN raw.matches m ON m.match_id = f.match_id;

-- 3. How far each team went in each season's knockouts.
CREATE VIEW cricket.team_finish AS
WITH ko AS (
    SELECT season, team, stage, result = 'Won' AS won,
           CASE stage WHEN 'Final' THEN 3 WHEN 'Semi Final' THEN 2 WHEN 'Quarter Final' THEN 1 ELSE 0 END AS depth
    FROM cricket.match_log
), best AS (
    SELECT DISTINCT ON (season, team) season, team, depth, won
    FROM ko ORDER BY season, team, depth DESC
)
SELECT season, team,
       CASE WHEN depth = 3 AND won THEN 'Champion'
            WHEN depth = 3          THEN 'Runner-up'
            WHEN depth = 2          THEN 'Semi-finalist'
            WHEN depth = 1 AND won  THEN 'Semi-finalist'      -- won the QF; semi not played yet
            WHEN depth = 1          THEN 'Quarter-finalist'
            ELSE 'League stage' END AS finish,
       depth >= 2 OR (depth = 1 AND won) AS top4
FROM best;

-- 4. Season summary: one row per team per season.
CREATE VIEW cricket.team_summary AS
WITH fr AS (                       -- what the team did with the bat
    SELECT season, team,
           count(*) AS played,
           count(*) FILTER (WHERE won) AS won,
           count(*) FILTER (WHERE NOT won) AS lost,
           count(*) FILTER (WHERE stage = 'League' AND won) AS league_won,
           count(*) FILTER (WHERE stage = 'League' AND NOT won) AS league_lost,
           count(*) FILTER (WHERE batted_first) AS batted_first,
           count(*) FILTER (WHERE batted_first AND won) AS won_batting_first,
           count(*) FILTER (WHERE NOT batted_first) AS chased,
           count(*) FILTER (WHERE NOT batted_first AND won) AS won_chasing,
           sum(runs) AS runs, sum(wickets) AS wickets_lost, sum(legal_balls) AS balls_faced,
           sum(nrr_balls) AS nrr_balls_faced, count(*) FILTER (WHERE all_out) AS times_all_out,
           sum(fours) AS fours, sum(sixes) AS sixes, sum(boundary_runs) AS boundary_runs,
           sum(dots_faced) AS dots_faced, sum(scores_30_plus) AS scores_30_plus,
           sum(ducks) AS ducks, sum(extras) AS extras_received
    FROM cricket.team_innings GROUP BY season, team
), ag AS (                         -- what the team conceded with the ball
    SELECT season, opponent AS team,
           sum(runs) AS runs_conceded, sum(wickets) AS wickets_taken, sum(legal_balls) AS balls_bowled,
           sum(nrr_balls) AS nrr_balls_bowled, count(*) FILTER (WHERE all_out) AS bowled_out_opponent,
           sum(dots_faced) AS dots_bowled, sum(wides_received) AS wides_bowled,
           sum(noballs_received) AS noballs_bowled,
           sum(out_caught) AS catches, sum(out_run_out) AS run_outs, sum(out_stumped) AS stumpings
    FROM cricket.team_innings GROUP BY season, opponent
), squad AS (                      -- counts only; names stay in raw
    SELECT m.season, i.batting_team AS team, count(DISTINCT b.player) AS batters_used
    FROM raw.batting b
    JOIN raw.innings i USING (match_id, innings_no)
    JOIN cricket.match_season m USING (match_id)
    GROUP BY 1, 2
)
SELECT fr.season, fr.team, tf.finish, tf.top4,
       fr.played, fr.won, fr.lost, fr.league_won, fr.league_lost,
       fr.batted_first, fr.won_batting_first, fr.chased, fr.won_chasing,
       -- batting
       round(fr.runs::numeric / fr.played, 1)                          AS avg_score,
       round(fr.runs * 6.0 / fr.balls_faced, 2)                        AS run_rate,
       round(fr.wickets_lost::numeric / fr.played, 1)                  AS wickets_lost_per_innings,
       fr.times_all_out,
       round(100.0 * fr.dots_faced / fr.balls_faced, 1)                AS dot_pct_faced,
       round(fr.balls_faced::numeric / nullif(fr.fours + fr.sixes, 0), 1) AS balls_per_boundary,
       round(100.0 * fr.boundary_runs / fr.runs, 1)                    AS boundary_run_pct,
       round(fr.fours::numeric / fr.played, 1)                         AS fours_per_innings,
       round(fr.sixes::numeric / fr.played, 1)                         AS sixes_per_innings,
       round(fr.scores_30_plus::numeric / fr.played, 2)                AS scores_30_plus_per_innings,
       sq.batters_used,
       -- bowling
       round(ag.runs_conceded::numeric / fr.played, 1)                 AS avg_conceded,
       round(ag.runs_conceded * 6.0 / ag.balls_bowled, 2)              AS economy,
       round(ag.wickets_taken::numeric / fr.played, 1)                 AS wickets_per_match,
       round(100.0 * ag.dots_bowled / ag.balls_bowled, 1)              AS dot_pct_bowled,
       round(ag.wides_bowled::numeric / fr.played, 1)                  AS wides_per_match,
       round(ag.noballs_bowled::numeric / fr.played, 1)                AS noballs_per_match,
       ag.bowled_out_opponent,
       -- fielding
       round(ag.catches::numeric / fr.played, 1)                       AS catches_per_match,
       round(ag.run_outs::numeric / fr.played, 2)                      AS run_outs_per_match,
       ag.stumpings,
       -- overall
       round(fr.runs * 6.0 / fr.nrr_balls_faced - ag.runs_conceded * 6.0 / ag.nrr_balls_bowled, 3) AS net_run_rate
FROM fr
JOIN ag USING (season, team)
JOIN squad sq USING (season, team)
JOIN cricket.team_finish tf USING (season, team);

-- 5. Phase splits: powerplay (1-6), middle (7-15), death (16-20), batting and bowling.
CREATE VIEW cricket.team_phase AS
WITH ob AS (
    SELECT m.season, o.match_id, o.innings_no, o.over_no, o.phase, o.runs, o.wickets,
           i.batting_team, i.bowling_team,
           CASE WHEN o.over_no = max(o.over_no) OVER (PARTITION BY o.match_id, o.innings_no)
                THEN i.legal_balls - 6 * (o.over_no - 1) ELSE 6 END AS balls
    FROM raw.overs o
    JOIN raw.innings i USING (match_id, innings_no)
    JOIN cricket.match_season m USING (match_id)
), sides AS (
    SELECT season, batting_team AS team, 'batting' AS side, phase, runs, wickets, balls FROM ob
    UNION ALL
    SELECT season, bowling_team AS team, 'bowling' AS side, phase, runs, wickets, balls FROM ob
), played AS (
    SELECT season, team, count(*) AS innings FROM cricket.team_innings GROUP BY season, team
), agg AS (
    SELECT s.season, s.team, s.side, s.phase,
           CASE s.phase WHEN 'powerplay' THEN 1 WHEN 'middle' THEN 2 ELSE 3 END AS phase_order,
           sum(s.runs) AS runs, sum(s.wickets) AS wickets, sum(s.balls) AS balls,
           round(sum(s.runs) * 6.0 / sum(s.balls), 2)          AS run_rate,       -- economy on the bowling side
           round(sum(s.wickets)::numeric / p.innings, 2)        AS wickets_per_innings
    FROM sides s JOIN played p USING (season, team)
    GROUP BY s.season, s.team, s.side, s.phase, p.innings
)
SELECT agg.*,
       count(*) OVER w                           AS teams,
       round(avg(run_rate) OVER w, 2)            AS league_avg_run_rate,
       round(avg(wickets_per_innings) OVER w, 2) AS league_avg_wickets,
       -- rank 1 = best: batting wants high run rate, bowling wants low economy
       rank() OVER (PARTITION BY season, side, phase
                    ORDER BY CASE WHEN side = 'batting' THEN -run_rate ELSE run_rate END) AS run_rate_rank,
       -- rank 1 = best: batting wants few wickets lost, bowling wants many taken
       rank() OVER (PARTITION BY season, side, phase
                    ORDER BY CASE WHEN side = 'batting' THEN wickets_per_innings ELSE -wickets_per_innings END) AS wickets_rank
FROM agg
WINDOW w AS (PARTITION BY season, side, phase);

-- 6. Every summary metric as a row, with the team's rank, the league average and the best team.
CREATE VIEW cricket.team_ranks AS
WITH long AS (
    SELECT s.season, s.team, s.top4, v.category, v.metric, v.value, v.higher_is_better, v.sort_order
    FROM cricket.team_summary s,
    LATERAL (VALUES
        ('Batting',  'Run rate',                   s.run_rate,                    true,  1),
        ('Batting',  'Average score',              s.avg_score,                   true,  2),
        ('Batting',  'Balls per boundary',         s.balls_per_boundary,          false, 3),
        ('Batting',  'Dot balls faced %',          s.dot_pct_faced,               false, 4),
        ('Batting',  'Boundary share of runs %',   s.boundary_run_pct,            true,  5),
        ('Batting',  'Wickets lost per innings',   s.wickets_lost_per_innings,    false, 6),
        ('Batting',  '30+ scores per innings',     s.scores_30_plus_per_innings,  true,  7),
        ('Batting',  'Sixes per innings',          s.sixes_per_innings,           true,  8),
        ('Bowling',  'Economy',                    s.economy,                     false, 9),
        ('Bowling',  'Wickets per match',          s.wickets_per_match,           true,  10),
        ('Bowling',  'Dot balls bowled %',         s.dot_pct_bowled,              true,  11),
        ('Bowling',  'Wides per match',            s.wides_per_match,             false, 12),
        ('Fielding', 'Catches per match',          s.catches_per_match,           true,  13),
        ('Fielding', 'Run-outs per match',         s.run_outs_per_match,          true,  14),
        ('Squad',    'Batters used',               s.batters_used::numeric,       false, 15),
        ('Overall',  'Net run rate',               s.net_run_rate,                true,  16)
    ) AS v(category, metric, value, higher_is_better, sort_order)
)
SELECT season, team, top4, category, metric, value, sort_order,
       rank() OVER r                                                 AS rank,
       count(*) OVER m                                               AS teams,
       cricket.ordinal(rank() OVER r) || ' of ' || count(*) OVER m  AS rank_label,
       round(avg(value) OVER m, 2)                                   AS league_avg,
       round(avg(value) FILTER (WHERE top4) OVER m, 2)               AS top4_avg,
       first_value(team)  OVER best                                  AS best_team,
       first_value(value) OVER best                                  AS best_value,
       higher_is_better
FROM long
WINDOW m    AS (PARTITION BY season, metric),
       r    AS (PARTITION BY season, metric ORDER BY CASE WHEN higher_is_better THEN -value ELSE value END),
       best AS (PARTITION BY season, metric ORDER BY CASE WHEN higher_is_better THEN -value ELSE value END
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING);

-- 7. Chase tracker: per over of every second innings, actual vs required run rate.
--    The "SLA" chart: required rate is the threshold, actual rate is the measurement.
CREATE VIEW cricket.chase_progress AS
SELECT m.season, o.match_id, m.match_date, m.match_date::timestamp AS "time", m.stage,
       i.batting_team AS team, i.bowling_team AS opponent,
       f.runs + 1 AS target,
       o.over_no, o.runs AS over_runs, o.cum_runs, o.cum_wickets,
       round(o.cum_runs::numeric / o.over_no, 2) AS run_rate_so_far,
       round((f.runs + 1 - (o.cum_runs - o.runs)) * 1.0 / (21 - o.over_no), 2) AS required_rate_at_start_of_over,
       m.winner = i.batting_team AS won
FROM raw.overs o
JOIN raw.innings i USING (match_id, innings_no)
JOIN raw.innings f ON f.match_id = o.match_id AND f.innings_no = 1
JOIN cricket.match_season m ON m.match_id = o.match_id
WHERE o.innings_no = 2;

-- 8. Scoring curves: average cumulative score and wickets at the end of each over.
CREATE VIEW cricket.over_baseline AS
SELECT m.season, i.batting_team AS team, o.over_no,
       round(avg(o.cum_runs), 1)    AS avg_cum_runs,
       round(avg(o.cum_wickets), 2) AS avg_cum_wickets,
       count(*)                     AS innings_reaching_over
FROM raw.overs o
JOIN raw.innings i USING (match_id, innings_no)
JOIN cricket.match_season m USING (match_id)
GROUP BY m.season, i.batting_team, o.over_no
UNION ALL
SELECT m.season, 'League average', o.over_no, round(avg(o.cum_runs), 1), round(avg(o.cum_wickets), 2), count(*)
FROM raw.overs o JOIN cricket.match_season m USING (match_id)
GROUP BY m.season, o.over_no;

GRANT USAGE ON SCHEMA cricket TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA cricket TO grafana_reader;
GRANT EXECUTE ON FUNCTION cricket.ordinal(bigint) TO grafana_reader;

-- 9. Per-innings timeline across seasons: the time series behind the "Timeline" row.
CREATE VIEW cricket.innings_timeline AS
WITH div AS (
    SELECT season, round(sum(runs) * 6.0 / sum(legal_balls), 2) AS division_run_rate
    FROM cricket.team_innings GROUP BY season
), w15 AS (
    SELECT match_id, innings_no, max(cum_wickets) FILTER (WHERE over_no <= 15) AS wickets_by_over_15
    FROM raw.overs GROUP BY 1, 2
)
SELECT f.season, f."time", f.match_id, f.stage, f.team, f.opponent,
       round(f.runs * 6.0 / f.legal_balls, 2) AS run_rate_scored,
       round(a.runs * 6.0 / a.legal_balls, 2) AS run_rate_conceded,
       d.division_run_rate,
       w.wickets_by_over_15,
       f.runs * 6.0 / f.legal_balls >= d.division_run_rate AS beat_division_rate,
       CASE WHEN f.won IS NULL THEN 'Tied' WHEN f.won THEN 'Won' ELSE 'Lost' END AS result
FROM cricket.team_innings f
JOIN cricket.team_innings a ON a.match_id = f.match_id AND a.team = f.opponent
JOIN div d ON d.season = f.season
JOIN w15 w ON w.match_id = f.match_id AND w.innings_no = f.innings_no;

-- 10. Incident log: batting collapses = 3 or more wickets inside any 3-over window ending by over 17.
CREATE VIEW cricket.collapses AS
WITH win AS (
    SELECT o.match_id, o.innings_no, o.over_no AS end_over,
           sum(o.wickets) OVER w3                         AS wickets_in_window,
           o.cum_runs                                     AS runs_at_end,
           o.cum_wickets                                  AS wickets_at_end,
           lag(o.cum_runs, 3, 0) OVER (PARTITION BY o.match_id, o.innings_no ORDER BY o.over_no) AS runs_before,
           lag(o.cum_wickets, 3, 0) OVER (PARTITION BY o.match_id, o.innings_no ORDER BY o.over_no) AS wickets_before
    FROM raw.overs o
    WINDOW w3 AS (PARTITION BY o.match_id, o.innings_no ORDER BY o.over_no ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
), worst AS (            -- one incident per innings: the worst 3-over window
    SELECT DISTINCT ON (match_id, innings_no) *
    FROM win WHERE wickets_in_window >= 3 AND end_over <= 17    -- overs 18-20 = deliberate slogging, not a collapse
    ORDER BY match_id, innings_no, wickets_in_window DESC, end_over
)
SELECT t.season, t.match_id, t."time", t.match_date, t.stage, t.team, t.opponent,
       greatest(w.end_over - 2, 1) || '-' || w.end_over AS overs,
       w.wickets_in_window,
       w.runs_before || '/' || w.wickets_before || '  →  ' || w.runs_at_end || '/' || w.wickets_at_end AS score_change,
       t.runs || '/' || t.wickets AS final_score,
       CASE WHEN t.won IS NULL THEN 'Tied' WHEN t.won THEN 'Won' ELSE 'Lost' END AS result
FROM worst w
JOIN cricket.team_innings t ON t.match_id = w.match_id AND t.innings_no = w.innings_no;

GRANT SELECT ON ALL TABLES IN SCHEMA cricket TO grafana_reader;

-- 11. Innings shape: cumulative score and wickets at the end of every over, tagged with the result.
--     Feeds the "worm" chart (wins vs losses) and the wins-vs-losses checkpoint table.
CREATE VIEW cricket.innings_overs AS
SELECT t.season, t.match_id, t.team, t.opponent, t.batted_first,
       CASE WHEN t.won IS NULL THEN 'Tied' WHEN t.won THEN 'Won' ELSE 'Lost' END AS result,
       o.over_no, o.runs AS over_runs, o.cum_runs, o.cum_wickets,
       t.runs AS final_runs, t.wickets AS final_wickets, t.legal_balls, t.dots_faced
FROM raw.overs o
JOIN cricket.team_innings t ON t.match_id = o.match_id AND t.innings_no = o.innings_no;

GRANT SELECT ON ALL TABLES IN SCHEMA cricket TO grafana_reader;
